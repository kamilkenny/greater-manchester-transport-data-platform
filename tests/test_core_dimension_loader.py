from __future__ import annotations

from pathlib import Path

import pytest

import transport_platform.warehouse.load_core_dimensions as core_loader
from transport_platform.warehouse.load_core_dimensions import (
    CoreDimensionMetrics,
    _metrics_from_row,
)

CORE_DIMENSION_DDL = (
    Path(__file__).resolve().parents[1]
    / "sql"
    / "ddl"
    / "012_create_core_dimension_loader.sql"
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

        if "EXEC warehouse.load_core_dimensions" in sql:
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
    metrics = _metrics_from_row((731, 731, 28, 28, 0))

    assert metrics == CoreDimensionMetrics(
        date_rows_read=731,
        date_rows_inserted=731,
        operator_rows_read=28,
        operator_rows_inserted=28,
        operator_rows_closed=0,
    )
    assert metrics.rows_read == 759
    assert metrics.rows_loaded == 759


def test_metrics_require_a_procedure_result() -> None:
    with pytest.raises(RuntimeError, match="returned no metrics"):
        _metrics_from_row(None)


def test_core_dimension_load_is_audited(monkeypatch: pytest.MonkeyPatch) -> None:
    start_cursor = RecordingCursor(start_key=21)
    load_cursor = RecordingCursor(metrics=(365, 365, 28, 28, 0))
    connections = iter(
        (
            RecordingConnection(start_cursor),
            RecordingConnection(load_cursor),
        )
    )
    monkeypatch.setattr(core_loader, "connect", lambda: next(connections))

    metrics = core_loader.load_core_dimensions(7)

    assert metrics.date_rows_inserted == 365
    assert metrics.operator_rows_inserted == 28
    assert start_cursor.executions[0][1] == (
        7,
        "load_gtfs_core_warehouse",
        "Python",
    )
    assert load_cursor.executions[0][1] == (7,)
    assert load_cursor.executions[1][1] == (393, 393, 21)


def test_core_dimension_failure_is_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_cursor = RecordingCursor(start_key=22)
    load_cursor = RecordingCursor(procedure_error=ValueError("invalid agency"))
    failure_cursor = RecordingCursor()
    connections = iter(
        (
            RecordingConnection(start_cursor),
            RecordingConnection(load_cursor),
            RecordingConnection(failure_cursor),
        )
    )
    monkeypatch.setattr(core_loader, "connect", lambda: next(connections))

    with pytest.raises(ValueError, match="invalid agency"):
        core_loader.load_core_dimensions(8)

    failure_sql, failure_parameters = failure_cursor.executions[0]
    assert "run_status = 'FAILED'" in failure_sql
    assert failure_parameters == ("invalid agency", 22)


def test_snapshot_key_must_be_positive() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        core_loader.load_core_dimensions(0)


def test_core_dimension_procedure_has_validation_and_type_2_logic() -> None:
    sql = CORE_DIMENSION_DDL.read_text(encoding="utf-8")

    assert "CREATE OR ALTER PROCEDURE warehouse.load_core_dimensions" in sql
    assert "snapshot_status = 'LOADED'" in sql
    assert "TRY_CONVERT(DATE, start_date, 112)" in sql
    assert "duplicate agency identifiers" in sql
    assert "valid_to_snapshot_key = @snapshot_key" in sql
    assert "target.is_current = 1" in sql
    assert "DATEDIFF(DAY, @minimum_date, @maximum_date) > 7320" in sql
    assert "exceeds twenty years" in sql
    assert "OPTION (MAXRECURSION 0)" in sql
