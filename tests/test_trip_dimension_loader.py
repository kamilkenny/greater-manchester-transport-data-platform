from __future__ import annotations

from pathlib import Path

import pytest

import transport_platform.warehouse.load_trip_dimension as trip_loader
from transport_platform.warehouse.load_trip_dimension import (
    TripDimensionMetrics,
    _metrics_from_row,
)

TRIP_DIMENSION_DDL = (
    Path(__file__).resolve().parents[1]
    / "sql"
    / "ddl"
    / "015_create_trip_dimension_loader.sql"
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

        if "EXEC warehouse.load_trip_dimension" in sql:
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
    metrics = _metrics_from_row((78_970, 78_970))

    assert metrics == TripDimensionMetrics(
        trip_rows_read=78_970,
        trip_rows_inserted=78_970,
    )
    assert metrics.rows_read == 78_970
    assert metrics.rows_loaded == 78_970


def test_metrics_require_a_procedure_result() -> None:
    with pytest.raises(RuntimeError, match="returned no metrics"):
        _metrics_from_row(None)


def test_trip_dimension_load_is_audited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_cursor = RecordingCursor(start_key=51)
    load_cursor = RecordingCursor(metrics=(78_970, 78_970))
    connections = iter(
        (
            RecordingConnection(start_cursor),
            RecordingConnection(load_cursor),
        )
    )
    monkeypatch.setattr(trip_loader, "connect", lambda: next(connections))

    metrics = trip_loader.load_trip_dimension(7)

    assert metrics.trip_rows_inserted == 78_970
    assert start_cursor.executions[0][1] == (
        7,
        "load_gtfs_trip_warehouse",
        "Python",
    )
    assert load_cursor.executions[0][1] == (7,)
    assert load_cursor.executions[1][1] == (78_970, 78_970, 51)


def test_trip_dimension_failure_is_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_cursor = RecordingCursor(start_key=52)
    load_cursor = RecordingCursor(procedure_error=ValueError("unknown route"))
    failure_cursor = RecordingCursor()
    connections = iter(
        (
            RecordingConnection(start_cursor),
            RecordingConnection(load_cursor),
            RecordingConnection(failure_cursor),
        )
    )
    monkeypatch.setattr(trip_loader, "connect", lambda: next(connections))

    with pytest.raises(ValueError, match="unknown route"):
        trip_loader.load_trip_dimension(8)

    failure_sql, failure_parameters = failure_cursor.executions[0]
    assert "run_status = 'FAILED'" in failure_sql
    assert failure_parameters == ("unknown route", 52)


def test_snapshot_key_must_be_positive() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        trip_loader.load_trip_dimension(0)


def test_trip_procedure_validates_and_resolves_relationships() -> None:
    sql = TRIP_DIMENSION_DDL.read_text(encoding="utf-8")

    assert "CREATE OR ALTER PROCEDURE warehouse.load_trip_dimension" in sql
    assert "pipeline_name = 'load_gtfs_network_warehouse'" in sql
    assert "pipeline_name = 'load_gtfs_service_warehouse'" in sql
    assert "duplicate trip identifiers" in sql
    assert "invalid coded attribute" in sql
    assert "@snapshot_downloaded_at < valid_to_snapshot.downloaded_at_utc" in sql
    assert "cannot resolve a route version" in sql
    assert "cannot resolve a service" in sql
    assert "CREATE TABLE #available_shape" in sql
    assert "reference an unknown shape" in sql
    assert "source.route_key <> target.route_key" in sql
    assert "source.service_key <> target.service_key" in sql
