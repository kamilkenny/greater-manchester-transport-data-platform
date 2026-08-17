from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any

from transport_platform.database.sql_server import connect

SHAPE_POINT_PIPELINE_NAME = "load_gtfs_shape_point_warehouse"
ORCHESTRATOR = "Python"
SHAPE_POINT_BATCH_SIZE = 50_000
PROGRESS_INTERVAL = 500_000


@dataclass(frozen=True)
class ShapePointMetrics:
    """Counts produced by the validated shape point transformation."""

    shape_rows_read: int
    shape_rows_inserted: int
    batches_completed: int

    @property
    def rows_read(self) -> int:
        """Return the number of staged shape rows considered."""

        return self.shape_rows_read

    @property
    def rows_loaded(self) -> int:
        """Return the number of warehouse shape points inserted."""

        return self.shape_rows_inserted


def _source_count_from_row(row: Any) -> int:
    """Return the validated source count."""

    if row is None:
        raise RuntimeError("Shape point validation returned no metrics")
    return int(row[0])


def _batch_metrics_from_row(row: Any) -> tuple[int, int, int]:
    """Return rows read, rows inserted and the new lineage cursor."""

    if row is None:
        raise RuntimeError("Shape point batch procedure returned no metrics")
    return int(row[0]), int(row[1]), int(row[2])


def _start_pipeline_run(snapshot_key: int) -> int:
    """Create and commit an audited shape point attempt."""

    with connect() as connection:
        inserted = (
            connection.cursor()
            .execute(
                """
            INSERT INTO governance.pipeline_run (
                snapshot_key,
                pipeline_name,
                orchestrator,
                run_status,
                started_at_utc
            )
            OUTPUT INSERTED.pipeline_run_key
            VALUES (?, ?, ?, 'STARTED', SYSUTCDATETIME());
            """,
                snapshot_key,
                SHAPE_POINT_PIPELINE_NAME,
                ORCHESTRATOR,
            )
            .fetchone()
        )
        connection.commit()

    return int(inserted[0])


def _record_pipeline_failure(
    pipeline_run_key: int,
    error: Exception,
) -> None:
    """Record a failed shape point attempt independently."""

    with connect() as connection:
        connection.cursor().execute(
            """
            UPDATE governance.pipeline_run
            SET
                run_status = 'FAILED',
                completed_at_utc = SYSUTCDATETIME(),
                error_message = ?
            WHERE pipeline_run_key = ?;
            """,
            str(error)[:4000],
            pipeline_run_key,
        )
        connection.commit()


def load_shape_points(
    snapshot_key: int,
    *,
    batch_size: int = SHAPE_POINT_BATCH_SIZE,
) -> ShapePointMetrics:
    """Validate and load geographical shape points in resumable batches."""

    if snapshot_key <= 0:
        raise ValueError("snapshot_key must be a positive integer")
    if not 1 <= batch_size <= 100_000:
        raise ValueError("batch_size must be between 1 and 100000")

    pipeline_run_key = _start_pipeline_run(snapshot_key)

    try:
        with connect() as connection:
            cursor = connection.cursor()
            validation_result = cursor.execute(
                "EXEC warehouse.validate_shape_point_source @snapshot_key = ?;",
                snapshot_key,
            ).fetchone()
            source_rows = _source_count_from_row(validation_result)
            connection.commit()

            after_source_row_number = 0
            shape_rows_read = 0
            shape_rows_inserted = 0
            batches_completed = 0
            next_progress = PROGRESS_INTERVAL

            while True:
                batch_result = cursor.execute(
                    """
                    EXEC warehouse.load_shape_point_batch
                        @snapshot_key = ?,
                        @after_source_row_number = ?,
                        @batch_size = ?;
                    """,
                    snapshot_key,
                    after_source_row_number,
                    batch_size,
                ).fetchone()
                batch_read, batch_inserted, last_source_row = _batch_metrics_from_row(
                    batch_result
                )

                if batch_read == 0:
                    break
                if last_source_row <= after_source_row_number:
                    raise RuntimeError("Shape point batch cursor did not advance")

                connection.commit()
                after_source_row_number = last_source_row
                shape_rows_read += batch_read
                shape_rows_inserted += batch_inserted
                batches_completed += 1

                if shape_rows_read >= next_progress:
                    print(
                        f"Shape point progress: {shape_rows_read:,} "
                        f"of {source_rows:,} rows"
                    )
                    next_progress += PROGRESS_INTERVAL

            if shape_rows_read != source_rows:
                raise RuntimeError(
                    "Shape point batches did not read the validated source count"
                )

            cursor.execute(
                """
                UPDATE governance.pipeline_run
                SET
                    run_status = 'SUCCEEDED',
                    completed_at_utc = SYSUTCDATETIME(),
                    rows_read = ?,
                    rows_loaded = ?
                WHERE pipeline_run_key = ?;
                """,
                shape_rows_read,
                shape_rows_inserted,
                pipeline_run_key,
            )
            connection.commit()
    except Exception as error:
        try:
            _record_pipeline_failure(pipeline_run_key, error)
        except Exception as audit_error:
            error.add_note(
                f"Pipeline failure could not be recorded immediately: {audit_error}"
            )
        raise

    metrics = ShapePointMetrics(
        shape_rows_read=shape_rows_read,
        shape_rows_inserted=shape_rows_inserted,
        batches_completed=batches_completed,
    )
    print(f"Snapshot key: {snapshot_key}")
    print(f"Pipeline run key: {pipeline_run_key}")
    print(f"Shape rows read: {metrics.shape_rows_read:,}")
    print(f"Shape rows inserted: {metrics.shape_rows_inserted:,}")
    print(f"Batches completed: {metrics.batches_completed:,}")
    return metrics


def main() -> None:
    """Load shape points for one staged snapshot key."""

    parser = argparse.ArgumentParser(
        description="Load typed GTFS geographical shape points."
    )
    parser.add_argument(
        "snapshot_key",
        type=int,
        help="Governance snapshot key whose shapes are staged.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=SHAPE_POINT_BATCH_SIZE,
        help="Rows transformed per committed batch, maximum 100000.",
    )
    arguments = parser.parse_args()
    load_shape_points(arguments.snapshot_key, batch_size=arguments.batch_size)


if __name__ == "__main__":
    main()
