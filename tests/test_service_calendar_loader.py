from __future__ import annotations

from pathlib import Path

import pytest

import transport_platform.warehouse.load_service_calendar as service_loader
from transport_platform.warehouse.load_service_calendar import (
    ServiceCalendarMetrics,
    _metrics_from_row,
)

SERVICE_CALENDAR_DDL = (
    Path(__file__).resolve().parents[1]
    / "sql"
    / "ddl"
    / "014_create_service_calendar_loader.sql"
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

        if "EXEC warehouse.load_service_calendar" in sql:
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

    def __enter__(self) -> RecordingConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def cursor(self) -> RecordingCursor:
        return self.recording_cursor

    def commit(self) -> None:
        self.commit_count += 1


def test_metrics_calculate_audited_totals() -> None:
    metrics = _metrics_from_row((900, 450, 925, 250_000, 250_000, 0))

    assert metrics == ServiceCalendarMetrics(
        calendar_rows_read=900,
        calendar_date_rows_read=450,
        service_rows_inserted=925,
        service_date_rows_derived=250_000,
        service_date_rows_inserted=250_000,
        service_date_rows_deleted=0,
    )
    assert metrics.rows_read == 1_350
    assert metrics.rows_loaded == 250_925


def test_metrics_require_a_procedure_result() -> None:
    with pytest.raises(RuntimeError, match="returned no metrics"):
        _metrics_from_row(None)


def test_service_calendar_load_is_audited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_cursor = RecordingCursor(start_key=41)
    load_cursor = RecordingCursor(metrics=(900, 450, 925, 250_000, 250_000, 0))
    connections = iter(
        (
            RecordingConnection(start_cursor),
            RecordingConnection(load_cursor),
        )
    )
    monkeypatch.setattr(service_loader, "connect", lambda: next(connections))

    metrics = service_loader.load_service_calendar(7)

    assert metrics.service_rows_inserted == 925
    assert metrics.service_date_rows_inserted == 250_000
    assert start_cursor.executions[0][1] == (
        7,
        "load_gtfs_service_warehouse",
        "Python",
    )
    assert load_cursor.executions[0][1] == (7,)
    assert load_cursor.executions[1][1] == (1_350, 250_925, 41)


def test_service_calendar_failure_is_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_cursor = RecordingCursor(start_key=42)
    load_cursor = RecordingCursor(procedure_error=ValueError("invalid exception"))
    failure_cursor = RecordingCursor()
    connections = iter(
        (
            RecordingConnection(start_cursor),
            RecordingConnection(load_cursor),
            RecordingConnection(failure_cursor),
        )
    )
    monkeypatch.setattr(service_loader, "connect", lambda: next(connections))

    with pytest.raises(ValueError, match="invalid exception"):
        service_loader.load_service_calendar(8)

    failure_sql, failure_parameters = failure_cursor.executions[0]
    assert "run_status = 'FAILED'" in failure_sql
    assert failure_parameters == ("invalid exception", 42)


def test_snapshot_key_must_be_positive() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        service_loader.load_service_calendar(0)


def test_service_procedure_applies_gtfs_calendar_semantics() -> None:
    sql = SERVICE_CALENDAR_DDL.read_text(encoding="utf-8")

    assert "CREATE OR ALTER PROCEDURE warehouse.load_service_calendar" in sql
    assert "pipeline_name = 'load_gtfs_core_warehouse'" in sql
    assert "duplicate calendar service identifiers" in sql
    assert "duplicate service date exceptions" in sql
    assert "exception only service must contain an added date" in sql
    assert "HASHBYTES(" in sql
    assert "CASE service_date.day_of_week_iso" in sql
    assert "exception.exception_type = 1" in sql
    assert "EXCEPTION_ADDED" in sql
    assert "exception.service_date = service_date.full_date" in sql
    assert "desired.activation_source <> target.activation_source" in sql
