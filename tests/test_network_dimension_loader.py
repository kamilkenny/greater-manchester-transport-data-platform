from __future__ import annotations

from pathlib import Path

import pytest

import transport_platform.warehouse.load_network_dimensions as network_loader
from transport_platform.warehouse.load_network_dimensions import (
    NetworkDimensionMetrics,
    _metrics_from_row,
)

NETWORK_DIMENSION_DDL = (
    Path(__file__).resolve().parents[1]
    / "sql"
    / "ddl"
    / "013_create_network_dimension_loader.sql"
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

        if "EXEC warehouse.load_network_dimensions" in sql:
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
    metrics = _metrics_from_row((704, 704, 0, 15_731, 15_731, 0))

    assert metrics == NetworkDimensionMetrics(
        route_rows_read=704,
        route_rows_inserted=704,
        route_rows_closed=0,
        stop_rows_read=15_731,
        stop_rows_inserted=15_731,
        stop_rows_closed=0,
    )
    assert metrics.rows_read == 16_435
    assert metrics.rows_loaded == 16_435


def test_metrics_require_a_procedure_result() -> None:
    with pytest.raises(RuntimeError, match="returned no metrics"):
        _metrics_from_row(None)


def test_network_dimension_load_is_audited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_cursor = RecordingCursor(start_key=31)
    load_cursor = RecordingCursor(metrics=(704, 704, 0, 15_731, 15_731, 0))
    connections = iter(
        (
            RecordingConnection(start_cursor),
            RecordingConnection(load_cursor),
        )
    )
    monkeypatch.setattr(network_loader, "connect", lambda: next(connections))

    metrics = network_loader.load_network_dimensions(7)

    assert metrics.route_rows_inserted == 704
    assert metrics.stop_rows_inserted == 15_731
    assert start_cursor.executions[0][1] == (
        7,
        "load_gtfs_network_warehouse",
        "Python",
    )
    assert load_cursor.executions[0][1] == (7,)
    assert load_cursor.executions[1][1] == (16_435, 16_435, 31)


def test_network_dimension_failure_is_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_cursor = RecordingCursor(start_key=32)
    load_cursor = RecordingCursor(procedure_error=ValueError("invalid route"))
    failure_cursor = RecordingCursor()
    connections = iter(
        (
            RecordingConnection(start_cursor),
            RecordingConnection(load_cursor),
            RecordingConnection(failure_cursor),
        )
    )
    monkeypatch.setattr(network_loader, "connect", lambda: next(connections))

    with pytest.raises(ValueError, match="invalid route"):
        network_loader.load_network_dimensions(8)

    failure_sql, failure_parameters = failure_cursor.executions[0]
    assert "run_status = 'FAILED'" in failure_sql
    assert failure_parameters == ("invalid route", 32)


def test_snapshot_key_must_be_positive() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        network_loader.load_network_dimensions(0)


def test_network_procedure_has_validation_and_type_2_logic() -> None:
    sql = NETWORK_DIMENSION_DDL.read_text(encoding="utf-8")

    assert "CREATE OR ALTER PROCEDURE warehouse.load_network_dimensions" in sql
    assert "pipeline_name = 'load_gtfs_core_warehouse'" in sql
    assert "older snapshot cannot replace current network history" in sql
    assert "duplicate route identifiers" in sql
    assert "six hexadecimal characters" in sql
    assert "cannot resolve a current operator" in sql
    assert "valid coordinates" in sql
    assert "duplicate stop identifiers" in sql
    assert "source.operator_key <> target.operator_key" in sql
    assert sql.count("valid_to_snapshot_key = @snapshot_key") == 2
    assert sql.count("target.is_current = 1") == 2
