from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any

from transport_platform.database.sql_server import connect

CORE_DIMENSION_PIPELINE_NAME = "load_gtfs_core_warehouse"
ORCHESTRATOR = "Python"


@dataclass(frozen=True)
class CoreDimensionMetrics:
    """Counts returned by the set based core dimension transformation."""

    date_rows_read: int
    date_rows_inserted: int
    operator_rows_read: int
    operator_rows_inserted: int
    operator_rows_closed: int

    @property
    def rows_read(self) -> int:
        """Return the total number of source and derived rows considered."""

        return self.date_rows_read + self.operator_rows_read

    @property
    def rows_loaded(self) -> int:
        """Return the number of new warehouse rows inserted."""

        return self.date_rows_inserted + self.operator_rows_inserted


def _metrics_from_row(row: Any) -> CoreDimensionMetrics:
    """Convert the stored procedure result into typed metrics."""

    if row is None:
        raise RuntimeError("Core dimension procedure returned no metrics")

    return CoreDimensionMetrics(
        date_rows_read=int(row[0]),
        date_rows_inserted=int(row[1]),
        operator_rows_read=int(row[2]),
        operator_rows_inserted=int(row[3]),
        operator_rows_closed=int(row[4]),
    )


def _start_pipeline_run(snapshot_key: int) -> int:
    """Create and commit an audited warehouse pipeline attempt."""

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
                CORE_DIMENSION_PIPELINE_NAME,
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
    """Record a failed warehouse attempt using an independent connection."""

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


def load_core_dimensions(snapshot_key: int) -> CoreDimensionMetrics:
    """Load the date and Type 2 operator dimensions for one snapshot."""

    if snapshot_key <= 0:
        raise ValueError("snapshot_key must be a positive integer")

    pipeline_run_key = _start_pipeline_run(snapshot_key)

    try:
        with connect() as connection:
            cursor = connection.cursor()
            result = cursor.execute(
                "EXEC warehouse.load_core_dimensions @snapshot_key = ?;",
                snapshot_key,
            ).fetchone()
            metrics = _metrics_from_row(result)

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
                metrics.rows_read,
                metrics.rows_loaded,
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

    print(f"Snapshot key: {snapshot_key}")
    print(f"Pipeline run key: {pipeline_run_key}")
    print(f"Date rows considered: {metrics.date_rows_read:,}")
    print(f"Date rows inserted: {metrics.date_rows_inserted:,}")
    print(f"Operator rows read: {metrics.operator_rows_read:,}")
    print(f"Operator rows inserted: {metrics.operator_rows_inserted:,}")
    print(f"Operator rows closed: {metrics.operator_rows_closed:,}")
    return metrics


def main() -> None:
    """Load core warehouse dimensions for one staged snapshot key."""

    parser = argparse.ArgumentParser(
        description="Load the GTFS date and operator warehouse dimensions."
    )
    parser.add_argument(
        "snapshot_key",
        type=int,
        help="Governance snapshot key whose staging rows are already loaded.",
    )
    arguments = parser.parse_args()
    load_core_dimensions(arguments.snapshot_key)


if __name__ == "__main__":
    main()
