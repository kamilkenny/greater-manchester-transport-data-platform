from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

import transport_platform.warehouse.load_daily_service_facts as fact_loader
from transport_platform.warehouse.load_daily_service_facts import (
    DailyServiceFactMetrics,
    _metrics_from_row,
)

DAILY_FACT_DDL = (
    Path(__file__).resolve().parents[1]
    / "sql"
    / "ddl"
    / "020_create_daily_service_fact_loader.sql"
)


class RecordingCursor:
    def __init__(
        self,
        *,
        start_key: int | None = None,
        metrics: tuple[int, ...] | None = None,
        procedure_error: Exception | None = None,
    ) -> None:
        self.start_key = start_key
        self.metrics = metrics
        self.procedure_error = procedure_error
        self.executions: list[tuple[str, tuple[object, ...]]] = []
        self._result: tuple[int, ...] | None = None

    def execute(self, sql: str, *parameters: object) -> RecordingCursor:
        self.executions.append((sql, parameters))

        if "EXEC warehouse.load_daily_service_facts" in sql:
            if self.procedure_error is not None:
                raise self.procedure_error
            self._result = self.metrics
        elif "OUTPUT INSERTED.pipeline_run_key" in sql:
            self._result = (self.start_key,) if self.start_key is not None else None
        else:
            self._result = None

        return self

    def fetchone(self) -> tuple[int, ...] | None:
        return self._result


class RecordingConnection:
    def __init__(self, cursor: RecordingCursor) -> None:
        self.recording_cursor = cursor
        self.commit_count = 0
        self.autocommit = False

    def __enter__(self) -> RecordingConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def cursor(self) -> RecordingCursor:
        return self.recording_cursor

    def commit(self) -> None:
        self.commit_count += 1


def test_metrics_calculate_audited_totals() -> None:
    metrics = _metrics_from_row(
        (
            date(2026, 8, 18),
            date(2027, 8, 18),
            3_447_466,
            80_000,
            250_000,
            250_000,
            8_000_000,
            8_000_000,
            12,
        )
    )

    assert metrics == DailyServiceFactMetrics(
        reporting_start_date=date(2026, 8, 18),
        reporting_end_date=date(2027, 8, 18),
        stop_event_rows_read=3_447_466,
        service_date_rows_read=80_000,
        route_fact_rows_derived=250_000,
        route_fact_rows_inserted=250_000,
        stop_fact_rows_derived=8_000_000,
        stop_fact_rows_inserted=8_000_000,
        batches_completed=12,
    )
    assert metrics.rows_read == 3_527_466
    assert metrics.rows_loaded == 8_250_000


def test_metrics_require_a_procedure_result() -> None:
    with pytest.raises(RuntimeError, match="returned no metrics"):
        _metrics_from_row(None)


def test_daily_fact_load_uses_autocommit_and_is_audited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_cursor = RecordingCursor(start_key=81)
    load_cursor = RecordingCursor(
        metrics=(
            date(2026, 8, 18),
            date(2027, 2, 13),
            3_447_466,
            40_000,
            12,
            12,
            34,
            34,
            13,
        )
    )
    success_cursor = RecordingCursor()
    load_connection = RecordingConnection(load_cursor)
    connections = iter(
        (
            RecordingConnection(start_cursor),
            load_connection,
            RecordingConnection(success_cursor),
        )
    )
    monkeypatch.setattr(fact_loader, "connect", lambda: next(connections))

    metrics = fact_loader.load_daily_service_facts(
        7,
        date_batch_days=14,
        reporting_start_date=date(2026, 8, 18),
        reporting_horizon_days=180,
    )

    assert metrics.route_fact_rows_inserted == 12
    assert metrics.stop_fact_rows_inserted == 34
    assert load_connection.autocommit is True
    assert start_cursor.executions[0][1] == (
        7,
        "build_gtfs_daily_service_facts",
        "Python",
    )
    assert load_cursor.executions[0][1] == (
        7,
        14,
        date(2026, 8, 18),
        180,
    )
    assert success_cursor.executions[0][1] == (3_487_466, 46, 81)


def test_daily_fact_failure_is_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_cursor = RecordingCursor(start_key=82)
    load_cursor = RecordingCursor(procedure_error=ValueError("invalid daily span"))
    failure_cursor = RecordingCursor()
    connections = iter(
        (
            RecordingConnection(start_cursor),
            RecordingConnection(load_cursor),
            RecordingConnection(failure_cursor),
        )
    )
    monkeypatch.setattr(fact_loader, "connect", lambda: next(connections))

    with pytest.raises(ValueError, match="invalid daily span"):
        fact_loader.load_daily_service_facts(8)

    failure_sql, failure_parameters = failure_cursor.executions[0]
    assert "run_status = 'FAILED'" in failure_sql
    assert failure_parameters == ("invalid daily span", 82)


@pytest.mark.parametrize(
    (
        "snapshot_key",
        "date_batch_days",
        "reporting_horizon_days",
        "message",
    ),
    (
        (0, 31, 366, "snapshot_key must be a positive integer"),
        (1, 0, 366, "date_batch_days must be between 1 and 366"),
        (1, 367, 366, "date_batch_days must be between 1 and 366"),
        (1, 31, 0, "reporting_horizon_days must be between 1 and 3660"),
        (1, 31, 3661, "reporting_horizon_days must be between 1 and 3660"),
    ),
)
def test_daily_fact_arguments_are_bounded(
    snapshot_key: int,
    date_batch_days: int,
    reporting_horizon_days: int,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        fact_loader.load_daily_service_facts(
            snapshot_key,
            date_batch_days=date_batch_days,
            reporting_horizon_days=reporting_horizon_days,
        )


def test_daily_fact_procedure_aggregates_service_patterns_once() -> None:
    sql = DAILY_FACT_DDL.read_text(encoding="utf-8")

    assert sql.count("CREATE OR ALTER PROCEDURE") == 1
    assert "CREATE TABLE #trip_event_metric" in sql
    assert "CREATE TABLE #trip_stop_metric" in sql
    assert "CREATE TABLE #participating_service" in sql
    assert "CREATE TABLE #service_route_metric" in sql
    assert "CREATE TABLE #service_stop_metric" in sql
    assert "COUNT(DISTINCT source.stop_key)" in sql
    assert "COUNT(DISTINCT source.route_key)" in sql
    assert "warehouse.bridge_service_date" in sql
    assert "@reporting_horizon_days INT = 366" in sql
    assert "@snapshot_date" in sql
    assert "@minimum_service_date AND @maximum_service_date" in sql


def test_daily_fact_procedure_is_resumable_and_idempotent() -> None:
    sql = DAILY_FACT_DDL.read_text(encoding="utf-8")

    assert "WHILE @batch_start_date <= @maximum_service_date" in sql
    assert "BEGIN TRANSACTION" in sql
    assert "COMMIT TRANSACTION" in sql
    assert "ROLLBACK TRANSACTION" in sql
    assert "Existing route service day facts conflict" in sql
    assert "Existing stop service day facts conflict" in sql
    assert "WHERE target.route_key IS NULL" in sql
    assert "WHERE target.stop_key IS NULL" in sql
    assert "The route fact target count is incomplete" in sql
    assert "The stop fact target count is incomplete" in sql


def test_daily_fact_procedure_derives_time_measures() -> None:
    sql = DAILY_FACT_DDL.read_text(encoding="utf-8")

    assert "base.last_arrival_seconds - base.first_departure_seconds" in sql
    assert "base.last_departure_seconds" in sql
    assert "base.scheduled_trip_count - 1" in sql
    assert "/ 60.0" in sql
    assert "DECIMAL(12, 2)" in sql
