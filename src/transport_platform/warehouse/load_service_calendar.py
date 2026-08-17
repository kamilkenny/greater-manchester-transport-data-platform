from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any

from transport_platform.database.sql_server import connect

SERVICE_CALENDAR_PIPELINE_NAME = "load_gtfs_service_warehouse"
ORCHESTRATOR = "Python"


@dataclass(frozen=True)
class ServiceCalendarMetrics:
    """Counts returned by the set based service calendar transformation."""

    calendar_rows_read: int
    calendar_date_rows_read: int
    service_rows_inserted: int
    service_date_rows_derived: int
    service_date_rows_inserted: int
    service_date_rows_deleted: int

    @property
    def rows_read(self) -> int:
        """Return the number of staged calendar rows considered."""

        return self.calendar_rows_read + self.calendar_date_rows_read

    @property
    def rows_loaded(self) -> int:
        """Return the number of service and bridge rows inserted."""

        return self.service_rows_inserted + self.service_date_rows_inserted


def _metrics_from_row(row: Any) -> ServiceCalendarMetrics:
    """Convert the stored procedure result into typed metrics."""

    if row is None:
        raise RuntimeError("Service calendar procedure returned no metrics")

    return ServiceCalendarMetrics(
        calendar_rows_read=int(row[0]),
        calendar_date_rows_read=int(row[1]),
        service_rows_inserted=int(row[2]),
        service_date_rows_derived=int(row[3]),
        service_date_rows_inserted=int(row[4]),
        service_date_rows_deleted=int(row[5]),
    )


def _start_pipeline_run(snapshot_key: int) -> int:
    """Create and commit an audited service calendar attempt."""

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
                SERVICE_CALENDAR_PIPELINE_NAME,
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
    """Record a failed service calendar attempt independently."""

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


def load_service_calendar(snapshot_key: int) -> ServiceCalendarMetrics:
    """Load service definitions and active service dates for one snapshot."""

    if snapshot_key <= 0:
        raise ValueError("snapshot_key must be a positive integer")

    pipeline_run_key = _start_pipeline_run(snapshot_key)

    try:
        with connect() as connection:
            cursor = connection.cursor()
            result = cursor.execute(
                "EXEC warehouse.load_service_calendar @snapshot_key = ?;",
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
    print(f"Calendar rows read: {metrics.calendar_rows_read:,}")
    print(f"Calendar date rows read: {metrics.calendar_date_rows_read:,}")
    print(f"Service rows inserted: {metrics.service_rows_inserted:,}")
    print(f"Service date rows derived: {metrics.service_date_rows_derived:,}")
    print(f"Service date rows inserted: {metrics.service_date_rows_inserted:,}")
    print(f"Service date rows deleted: {metrics.service_date_rows_deleted:,}")
    return metrics


def main() -> None:
    """Load service calendars for one staged snapshot key."""

    parser = argparse.ArgumentParser(
        description="Load GTFS service definitions and active service dates."
    )
    parser.add_argument(
        "snapshot_key",
        type=int,
        help="Governance snapshot key whose core dimensions are loaded.",
    )
    arguments = parser.parse_args()
    load_service_calendar(arguments.snapshot_key)


if __name__ == "__main__":
    main()
