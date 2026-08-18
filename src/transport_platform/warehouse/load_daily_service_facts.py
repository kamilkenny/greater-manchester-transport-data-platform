from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
from typing import Any

from transport_platform.database.sql_server import connect

DAILY_FACT_PIPELINE_NAME = "build_gtfs_daily_service_facts"
ORCHESTRATOR = "Python"
DEFAULT_DATE_BATCH_DAYS = 31
DEFAULT_REPORTING_HORIZON_DAYS = 366


@dataclass(frozen=True)
class DailyServiceFactMetrics:
    """Counts produced by the daily service fact transformation."""

    reporting_start_date: date
    reporting_end_date: date
    stop_event_rows_read: int
    service_date_rows_read: int
    route_fact_rows_derived: int
    route_fact_rows_inserted: int
    stop_fact_rows_derived: int
    stop_fact_rows_inserted: int
    batches_completed: int

    @property
    def rows_read(self) -> int:
        """Return the warehouse source rows considered."""

        return self.stop_event_rows_read + self.service_date_rows_read

    @property
    def rows_loaded(self) -> int:
        """Return route and stop daily facts inserted."""

        return self.route_fact_rows_inserted + self.stop_fact_rows_inserted


def _metrics_from_row(row: Any) -> DailyServiceFactMetrics:
    """Convert the stored procedure result into typed metrics."""

    if row is None:
        raise RuntimeError("Daily service fact procedure returned no metrics")

    return DailyServiceFactMetrics(
        reporting_start_date=row[0],
        reporting_end_date=row[1],
        stop_event_rows_read=int(row[2]),
        service_date_rows_read=int(row[3]),
        route_fact_rows_derived=int(row[4]),
        route_fact_rows_inserted=int(row[5]),
        stop_fact_rows_derived=int(row[6]),
        stop_fact_rows_inserted=int(row[7]),
        batches_completed=int(row[8]),
    )


def _start_pipeline_run(snapshot_key: int) -> int:
    """Create and commit an audited daily fact attempt."""

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
                DAILY_FACT_PIPELINE_NAME,
                ORCHESTRATOR,
            )
            .fetchone()
        )
        connection.commit()

    return int(inserted[0])


def _record_pipeline_success(
    pipeline_run_key: int,
    metrics: DailyServiceFactMetrics,
) -> None:
    """Record successful completion independently of fact transactions."""

    with connect() as connection:
        connection.cursor().execute(
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


def _record_pipeline_failure(
    pipeline_run_key: int,
    error: Exception,
) -> None:
    """Record a failed daily fact attempt independently."""

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


def load_daily_service_facts(
    snapshot_key: int,
    *,
    date_batch_days: int = DEFAULT_DATE_BATCH_DAYS,
    reporting_start_date: date | None = None,
    reporting_horizon_days: int = DEFAULT_REPORTING_HORIZON_DAYS,
) -> DailyServiceFactMetrics:
    """Build route and stop service day facts for one snapshot."""

    if snapshot_key <= 0:
        raise ValueError("snapshot_key must be a positive integer")
    if not 1 <= date_batch_days <= 366:
        raise ValueError("date_batch_days must be between 1 and 366")
    if not 1 <= reporting_horizon_days <= 3660:
        raise ValueError("reporting_horizon_days must be between 1 and 3660")

    pipeline_run_key = _start_pipeline_run(snapshot_key)

    try:
        with connect() as connection:
            connection.autocommit = True
            result = (
                connection.cursor()
                .execute(
                    """
                    EXEC warehouse.load_daily_service_facts
                        @snapshot_key = ?,
                        @date_batch_days = ?,
                        @reporting_start_date = ?,
                        @reporting_horizon_days = ?;
                    """,
                    snapshot_key,
                    date_batch_days,
                    reporting_start_date,
                    reporting_horizon_days,
                )
                .fetchone()
            )
            metrics = _metrics_from_row(result)

        _record_pipeline_success(pipeline_run_key, metrics)
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
    print(f"Reporting start date: {metrics.reporting_start_date}")
    print(f"Reporting end date: {metrics.reporting_end_date}")
    print(f"Stop event rows read: {metrics.stop_event_rows_read:,}")
    print(f"Service date rows read: {metrics.service_date_rows_read:,}")
    print(f"Route fact rows derived: {metrics.route_fact_rows_derived:,}")
    print(f"Route fact rows inserted: {metrics.route_fact_rows_inserted:,}")
    print(f"Stop fact rows derived: {metrics.stop_fact_rows_derived:,}")
    print(f"Stop fact rows inserted: {metrics.stop_fact_rows_inserted:,}")
    print(f"Date batches completed: {metrics.batches_completed:,}")
    return metrics


def main() -> None:
    """Build daily service facts for one warehouse snapshot."""

    parser = argparse.ArgumentParser(
        description="Build GTFS route and stop service day facts."
    )
    parser.add_argument(
        "snapshot_key",
        type=int,
        help="Governance snapshot key whose timetable warehouse is loaded.",
    )
    parser.add_argument(
        "--date-batch-days",
        type=int,
        default=DEFAULT_DATE_BATCH_DAYS,
        help="Service dates committed per batch, maximum 366.",
    )
    parser.add_argument(
        "--reporting-start-date",
        type=date.fromisoformat,
        default=None,
        help="First reporting date, defaults to the snapshot download date.",
    )
    parser.add_argument(
        "--reporting-horizon-days",
        type=int,
        default=DEFAULT_REPORTING_HORIZON_DAYS,
        help="Number of reporting dates materialised, defaults to 366.",
    )
    arguments = parser.parse_args()
    load_daily_service_facts(
        arguments.snapshot_key,
        date_batch_days=arguments.date_batch_days,
        reporting_start_date=arguments.reporting_start_date,
        reporting_horizon_days=arguments.reporting_horizon_days,
    )


if __name__ == "__main__":
    main()
