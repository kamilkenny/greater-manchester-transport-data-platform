from __future__ import annotations

from pathlib import Path

import pytest

import transport_platform.warehouse.load_shape_points as shape_loader
from transport_platform.warehouse.load_shape_points import (
    ShapePointMetrics,
    _batch_metrics_from_row,
    _source_count_from_row,
)

DDL_DIRECTORY = Path(__file__).resolve().parents[1] / "sql" / "ddl"
SHAPE_POINT_DDLS = (
    DDL_DIRECTORY / "016_create_shape_point_loader.sql",
    DDL_DIRECTORY / "017_create_shape_point_batch_loader.sql",
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

        if "validate_shape_point_source" in sql:
            if self.validation_error is not None:
                raise self.validation_error
            self._result = (
                (self.source_count,) if self.source_count is not None else None
            )
        elif "load_shape_point_batch" in sql:
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
    assert _source_count_from_row((2_217_210,)) == 2_217_210
    assert _batch_metrics_from_row((50_000, 49_000, 50_001)) == (
        50_000,
        49_000,
        50_001,
    )

    with pytest.raises(RuntimeError, match="validation returned no metrics"):
        _source_count_from_row(None)
    with pytest.raises(RuntimeError, match="batch procedure returned no metrics"):
        _batch_metrics_from_row(None)


def test_shape_point_load_commits_resumable_batches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_cursor = RecordingCursor(start_key=61)
    load_cursor = RecordingCursor(
        source_count=3,
        batches=[
            (2, 2, 3),
            (1, 1, 4),
            (0, 0, 4),
        ],
    )
    start_connection = RecordingConnection(start_cursor)
    load_connection = RecordingConnection(load_cursor)
    connections = iter((start_connection, load_connection))
    monkeypatch.setattr(shape_loader, "connect", lambda: next(connections))

    metrics = shape_loader.load_shape_points(7, batch_size=2)

    assert metrics == ShapePointMetrics(
        shape_rows_read=3,
        shape_rows_inserted=3,
        batches_completed=2,
    )
    assert metrics.rows_read == 3
    assert metrics.rows_loaded == 3
    assert start_cursor.executions[0][1] == (
        7,
        "load_gtfs_shape_point_warehouse",
        "Python",
    )
    assert load_cursor.executions[0][1] == (7,)
    assert load_cursor.executions[1][1] == (7, 0, 2)
    assert load_cursor.executions[2][1] == (7, 3, 2)
    assert load_cursor.executions[3][1] == (7, 4, 2)
    assert load_cursor.executions[4][1] == (3, 3, 61)
    assert load_connection.commit_count == 4


def test_shape_point_validation_failure_is_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_cursor = RecordingCursor(start_key=62)
    load_cursor = RecordingCursor(validation_error=ValueError("invalid coordinate"))
    failure_cursor = RecordingCursor()
    connections = iter(
        (
            RecordingConnection(start_cursor),
            RecordingConnection(load_cursor),
            RecordingConnection(failure_cursor),
        )
    )
    monkeypatch.setattr(shape_loader, "connect", lambda: next(connections))

    with pytest.raises(ValueError, match="invalid coordinate"):
        shape_loader.load_shape_points(8)

    failure_sql, failure_parameters = failure_cursor.executions[0]
    assert "run_status = 'FAILED'" in failure_sql
    assert failure_parameters == ("invalid coordinate", 62)


@pytest.mark.parametrize(
    ("snapshot_key", "batch_size", "message"),
    (
        (0, 50_000, "snapshot_key must be a positive integer"),
        (1, 0, "batch_size must be between 1 and 100000"),
        (1, 100_001, "batch_size must be between 1 and 100000"),
    ),
)
def test_shape_point_arguments_are_bounded(
    snapshot_key: int,
    batch_size: int,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        shape_loader.load_shape_points(snapshot_key, batch_size=batch_size)


def test_shape_point_procedures_validate_and_batch_source() -> None:
    sql = "\n".join(path.read_text(encoding="utf-8") for path in SHAPE_POINT_DDLS)

    assert "CREATE OR ALTER PROCEDURE warehouse.validate_shape_point_source" in sql
    assert "CREATE OR ALTER PROCEDURE warehouse.load_shape_point_batch" in sql
    assert all(
        path.read_text(encoding="utf-8").count("CREATE OR ALTER PROCEDURE") == 1
        for path in SHAPE_POINT_DDLS
    )
    assert "pipeline_name = 'load_gtfs_high_volume_staging'" in sql
    assert "duplicate shape point keys" in sql
    assert "shape_pt_lat" in sql
    assert "NOT BETWEEN -90 AND 90" in sql
    assert "NOT BETWEEN -180 AND 180" in sql
    assert "@batch_size > 100000" in sql
    assert "SELECT TOP (@batch_size)" in sql
    assert "source_row_number > @after_source_row_number" in sql
    assert "Existing shape points conflict" in sql
