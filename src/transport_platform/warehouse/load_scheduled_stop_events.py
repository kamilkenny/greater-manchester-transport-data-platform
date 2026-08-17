from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any

from transport_platform.database.sql_server import connect

STOP_EVENT_PIPELINE_NAME = "load_gtfs_scheduled_stop_event_warehouse"
ORCHESTRATOR = "Python"
STOP_EVENT_BATCH_SIZE = 50_000
PROGRESS_INTERVAL = 500_000


@dataclass(frozen=True)
class StopEventMetrics:
    """Counts produced by the scheduled stop event transformation."""

    stop_event_rows_read: int
    stop_event_rows_inserted: int
    batches_completed: int

    @property
    def rows_read(self) -> int:
        """Return the number of staged stop event rows considered."""

        return self.stop_event_rows_read

    @property
    def rows_loaded(self) -> int:
        """Return the number of warehouse stop events inserted."""

        return self.stop_event_rows_inserted


def _source_count_from_row(row: Any) -> int:
    """Return the validated source count."""

    if row is None:
        raise RuntimeError("Stop event validation returned no metrics")
    return int(row[0])


def _batch_metrics_from_row(row: Any) -> tuple[int, int, int]:
    """Return rows read, rows inserted and the new lineage cursor."""

    if row is None:
        raise RuntimeError("Stop event batch procedure returned no metrics")
    return int(row[0]), int(row[1]), int(row[2])


def _start_pipeline_run(snapshot_key: int) -> int:
    """Create and commit an audited stop event attempt."""

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
                STOP_EVENT_PIPELINE_NAME,
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
    """Record a failed stop event attempt independently."""

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


def load_scheduled_stop_events(
    snapshot_key: int,
    *,
    batch_size: int = STOP_EVENT_BATCH_SIZE,
) -> StopEventMetrics:
    """Validate and load scheduled stop events in resumable batches."""

    if snapshot_key <= 0:
        raise ValueError("snapshot_key must be a positive integer")
    if not 1 <= batch_size <= 100_000:
        raise ValueError("batch_size must be between 1 and 100000")

    pipeline_run_key = _start_pipeline_run(snapshot_key)

    try:
        with connect() as connection:
            cursor = connection.cursor()
            validation_result = cursor.execute(
                """
                EXEC warehouse.validate_scheduled_stop_event_source
                    @snapshot_key = ?;
                """,
                snapshot_key,
            ).fetchone()
            source_rows = _source_count_from_row(validation_result)
            connection.commit()

            after_source_row_number = 0
            stop_event_rows_read = 0
            stop_event_rows_inserted = 0
            batches_completed = 0
            next_progress = PROGRESS_INTERVAL

            while True:
                batch_result = cursor.execute(
                    """
                    EXEC warehouse.load_scheduled_stop_event_batch
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
                    raise RuntimeError("Stop event batch cursor did not advance")

                connection.commit()
                after_source_row_number = last_source_row
                stop_event_rows_read += batch_read
                stop_event_rows_inserted += batch_inserted
                batches_completed += 1

                if stop_event_rows_read >= next_progress:
                    print(
                        f"Stop event progress: {stop_event_rows_read:,} "
                        f"of {source_rows:,} rows"
                    )
                    next_progress += PROGRESS_INTERVAL

            if stop_event_rows_read != source_rows:
                raise RuntimeError(
                    "Stop event batches did not read the validated source count"
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
                stop_event_rows_read,
                stop_event_rows_inserted,
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

    metrics = StopEventMetrics(
        stop_event_rows_read=stop_event_rows_read,
        stop_event_rows_inserted=stop_event_rows_inserted,
        batches_completed=batches_completed,
    )
    print(f"Snapshot key: {snapshot_key}")
    print(f"Pipeline run key: {pipeline_run_key}")
    print(f"Stop event rows read: {metrics.stop_event_rows_read:,}")
    print(f"Stop event rows inserted: {metrics.stop_event_rows_inserted:,}")
    print(f"Batches completed: {metrics.batches_completed:,}")
    return metrics


def main() -> None:
    """Load scheduled stop events for one staged snapshot key."""

    parser = argparse.ArgumentParser(
        description="Load typed GTFS scheduled stop events."
    )
    parser.add_argument(
        "snapshot_key",
        type=int,
        help="Governance snapshot key whose trips and stop times are loaded.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=STOP_EVENT_BATCH_SIZE,
        help="Rows transformed per committed batch, maximum 100000.",
    )
    arguments = parser.parse_args()
    load_scheduled_stop_events(
        arguments.snapshot_key,
        batch_size=arguments.batch_size,
    )


if __name__ == "__main__":
    main()
