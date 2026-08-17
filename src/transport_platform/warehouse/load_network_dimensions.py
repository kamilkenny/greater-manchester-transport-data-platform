from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any

from transport_platform.database.sql_server import connect

NETWORK_DIMENSION_PIPELINE_NAME = "load_gtfs_network_warehouse"
ORCHESTRATOR = "Python"


@dataclass(frozen=True)
class NetworkDimensionMetrics:
    """Counts returned by the set based network transformation."""

    route_rows_read: int
    route_rows_inserted: int
    route_rows_closed: int
    stop_rows_read: int
    stop_rows_inserted: int
    stop_rows_closed: int

    @property
    def rows_read(self) -> int:
        """Return the total number of staged network rows considered."""

        return self.route_rows_read + self.stop_rows_read

    @property
    def rows_loaded(self) -> int:
        """Return the number of new route and stop versions inserted."""

        return self.route_rows_inserted + self.stop_rows_inserted


def _metrics_from_row(row: Any) -> NetworkDimensionMetrics:
    """Convert the stored procedure result into typed metrics."""

    if row is None:
        raise RuntimeError("Network dimension procedure returned no metrics")

    return NetworkDimensionMetrics(
        route_rows_read=int(row[0]),
        route_rows_inserted=int(row[1]),
        route_rows_closed=int(row[2]),
        stop_rows_read=int(row[3]),
        stop_rows_inserted=int(row[4]),
        stop_rows_closed=int(row[5]),
    )


def _start_pipeline_run(snapshot_key: int) -> int:
    """Create and commit an audited network warehouse attempt."""

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
                NETWORK_DIMENSION_PIPELINE_NAME,
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
    """Record a failed network warehouse attempt independently."""

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


def load_network_dimensions(snapshot_key: int) -> NetworkDimensionMetrics:
    """Load the Type 2 route and stop dimensions for one snapshot."""

    if snapshot_key <= 0:
        raise ValueError("snapshot_key must be a positive integer")

    pipeline_run_key = _start_pipeline_run(snapshot_key)

    try:
        with connect() as connection:
            cursor = connection.cursor()
            result = cursor.execute(
                "EXEC warehouse.load_network_dimensions @snapshot_key = ?;",
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
    print(f"Route rows read: {metrics.route_rows_read:,}")
    print(f"Route rows inserted: {metrics.route_rows_inserted:,}")
    print(f"Route rows closed: {metrics.route_rows_closed:,}")
    print(f"Stop rows read: {metrics.stop_rows_read:,}")
    print(f"Stop rows inserted: {metrics.stop_rows_inserted:,}")
    print(f"Stop rows closed: {metrics.stop_rows_closed:,}")
    return metrics


def main() -> None:
    """Load network warehouse dimensions for one staged snapshot key."""

    parser = argparse.ArgumentParser(
        description="Load the GTFS route and stop warehouse dimensions."
    )
    parser.add_argument(
        "snapshot_key",
        type=int,
        help="Governance snapshot key whose core dimensions are loaded.",
    )
    arguments = parser.parse_args()
    load_network_dimensions(arguments.snapshot_key)


if __name__ == "__main__":
    main()
