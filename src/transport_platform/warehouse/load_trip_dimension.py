from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any

from transport_platform.database.sql_server import connect

TRIP_DIMENSION_PIPELINE_NAME = "load_gtfs_trip_warehouse"
ORCHESTRATOR = "Python"


@dataclass(frozen=True)
class TripDimensionMetrics:
    """Counts returned by the set based trip dimension transformation."""

    trip_rows_read: int
    trip_rows_inserted: int

    @property
    def rows_read(self) -> int:
        """Return the number of staged trip rows considered."""

        return self.trip_rows_read

    @property
    def rows_loaded(self) -> int:
        """Return the number of trip dimension rows inserted."""

        return self.trip_rows_inserted


def _metrics_from_row(row: Any) -> TripDimensionMetrics:
    """Convert the stored procedure result into typed metrics."""

    if row is None:
        raise RuntimeError("Trip dimension procedure returned no metrics")

    return TripDimensionMetrics(
        trip_rows_read=int(row[0]),
        trip_rows_inserted=int(row[1]),
    )


def _start_pipeline_run(snapshot_key: int) -> int:
    """Create and commit an audited trip warehouse attempt."""

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
                TRIP_DIMENSION_PIPELINE_NAME,
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
    """Record a failed trip warehouse attempt independently."""

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


def load_trip_dimension(snapshot_key: int) -> TripDimensionMetrics:
    """Load the snapshot specific trip dimension."""

    if snapshot_key <= 0:
        raise ValueError("snapshot_key must be a positive integer")

    pipeline_run_key = _start_pipeline_run(snapshot_key)

    try:
        with connect() as connection:
            cursor = connection.cursor()
            result = cursor.execute(
                "EXEC warehouse.load_trip_dimension @snapshot_key = ?;",
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
    print(f"Trip rows read: {metrics.trip_rows_read:,}")
    print(f"Trip rows inserted: {metrics.trip_rows_inserted:,}")
    return metrics


def main() -> None:
    """Load trip dimensions for one staged snapshot key."""

    parser = argparse.ArgumentParser(
        description="Load the snapshot specific GTFS trip dimension."
    )
    parser.add_argument(
        "snapshot_key",
        type=int,
        help="Governance snapshot key whose route and services are loaded.",
    )
    arguments = parser.parse_args()
    load_trip_dimension(arguments.snapshot_key)


if __name__ == "__main__":
    main()
