from __future__ import annotations

from pathlib import Path

import pytest

import transport_platform.warehouse.load_scheduled_stop_events as event_loader
from transport_platform.warehouse.load_scheduled_stop_events import (
    StopEventMetrics,
    _batch_metrics_from_row,
    _source_count_from_row,
)

DDL_DIRECTORY = Path(__file__).resolve().parents[1] / "sql" / "ddl"
STOP_EVENT_DDLS = (
    DDL_DIRECTORY / "018_validate_scheduled_stop_event_source.sql",
    DDL_DIRECTORY / "019_create_scheduled_stop_event_batch_loader.sql",
)


class RecordingCursor:
    def __init__(
        self,
        *,
        start_key: int | None = None,
        source_count: int | None = None,
        batches: list[tuple[int, int, int]] | None = None,
        validation_error: Exception | None = None,
    ) -> None:
        self.start_key = start_key
        self.source_count = source_count
        self.batches = list(batches or [])
        self.validation_error = validation_error
        self.executions: list[tuple[str, tuple[object, ...]]] = []
        self._result: tuple[int, ...] | None = None

    def execute(self, sql: str, *parameters: object) -> RecordingCursor:
        self.executions.append((sql, parameters))

        if "validate_scheduled_stop_event_source" in sql:
            if self.validation_error is not None:
                raise self.validation_error
            self._result = (
                (self.source_count,) if self.source_count is not None else None
            )
        elif "load_scheduled_stop_event_batch" in sql:
            self._result = self.batches.pop(0)
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


def test_metric_rows_require_procedure_results() -> None:
    assert _source_count_from_row((3_447_466,)) == 3_447_466
    assert _batch_metrics_from_row((50_000, 49_000, 50_001)) == (
        50_000,
        49_000,
        50_001,
    )

    with pytest.raises(RuntimeError, match="validation returned no metrics"):
        _source_count_from_row(None)
    with pytest.raises(RuntimeError, match="batch procedure returned no metrics"):
        _batch_metrics_from_row(None)


def test_stop_event_load_commits_resumable_batches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_cursor = RecordingCursor(start_key=71)
    load_cursor = RecordingCursor(
        source_count=3,
        batches=[
            (2, 2, 3),
            (1, 1, 4),
            (0, 0, 4),
        ],
    )
    load_connection = RecordingConnection(load_cursor)
    connections = iter((RecordingConnection(start_cursor), load_connection))
    monkeypatch.setattr(event_loader, "connect", lambda: next(connections))

    metrics = event_loader.load_scheduled_stop_events(7, batch_size=2)

    assert metrics == StopEventMetrics(
        stop_event_rows_read=3,
        stop_event_rows_inserted=3,
        batches_completed=2,
    )
    assert metrics.rows_read == 3
    assert metrics.rows_loaded == 3
    assert start_cursor.executions[0][1] == (
        7,
        "load_gtfs_scheduled_stop_event_warehouse",
        "Python",
    )
    assert load_cursor.executions[0][1] == (7,)
    assert load_cursor.executions[1][1] == (7, 0, 2)
    assert load_cursor.executions[2][1] == (7, 3, 2)
    assert load_cursor.executions[3][1] == (7, 4, 2)
    assert load_cursor.executions[4][1] == (3, 3, 71)
    assert load_connection.commit_count == 4


def test_stop_event_validation_failure_is_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_cursor = RecordingCursor(start_key=72)
    load_cursor = RecordingCursor(validation_error=ValueError("invalid service time"))
    failure_cursor = RecordingCursor()
    connections = iter(
        (
            RecordingConnection(start_cursor),
            RecordingConnection(load_cursor),
            RecordingConnection(failure_cursor),
        )
    )
    monkeypatch.setattr(event_loader, "connect", lambda: next(connections))

    with pytest.raises(ValueError, match="invalid service time"):
        event_loader.load_scheduled_stop_events(8)

    failure_sql, failure_parameters = failure_cursor.executions[0]
    assert "run_status = 'FAILED'" in failure_sql
    assert failure_parameters == ("invalid service time", 72)


@pytest.mark.parametrize(
    ("snapshot_key", "batch_size", "message"),
    (
        (0, 50_000, "snapshot_key must be a positive integer"),
        (1, 0, "batch_size must be between 1 and 100000"),
        (1, 100_001, "batch_size must be between 1 and 100000"),
    ),
)
def test_stop_event_arguments_are_bounded(
    snapshot_key: int,
    batch_size: int,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        event_loader.load_scheduled_stop_events(
            snapshot_key,
            batch_size=batch_size,
        )


def test_stop_event_procedures_validate_time_and_relationships() -> None:
    sql = "\n".join(path.read_text(encoding="utf-8") for path in STOP_EVENT_DDLS)

    assert all(
        path.read_text(encoding="utf-8").count("CREATE OR ALTER PROCEDURE") == 1
        for path in STOP_EVENT_DDLS
    )
    assert "pipeline_name = 'load_gtfs_trip_warehouse'" in sql
    assert "duplicate trip stop sequences" in sql
    assert "cannot resolve a trip" in sql
    assert "cannot resolve a stop version" in sql
    assert "PARSENAME(REPLACE(cleaned.arrival_time, ':', '.'), 3)" in sql
    assert "parsed.arrival_hour * 3600" in sql
    assert "parsed.departure_hour * 3600" in sql
    assert "COALESCE(" in sql
    assert "SELECT TOP (@batch_size)" in sql
    assert "Existing stop events conflict" in sql
