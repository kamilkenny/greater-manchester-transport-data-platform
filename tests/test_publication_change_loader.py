from __future__ import annotations

from pathlib import Path

import pytest

import transport_platform.warehouse.load_publication_changes as change_loader
from transport_platform.warehouse.load_publication_changes import (
    PublicationChangeMetrics,
    _metrics_from_row,
)

PUBLICATION_CHANGE_DDL = (
    Path(__file__).resolve().parents[1]
    / "sql"
    / "ddl"
    / "021_create_publication_change_loader.sql"
)


class RecordingCursor:
    def __init__(
        self,
        *,
        start_key: int | None = None,
        metrics: tuple[object, ...] | None = None,
        procedure_error: Exception | None = None,
    ) -> None:
        self.start_key = start_key
        self.metrics = metrics
        self.procedure_error = procedure_error
        self.executions: list[tuple[str, tuple[object, ...]]] = []
        self._result: tuple[object, ...] | None = None

    def execute(self, sql: str, *parameters: object) -> RecordingCursor:
        self.executions.append((sql, parameters))

        if "EXEC warehouse.load_publication_changes" in sql:
            if self.procedure_error is not None:
                raise self.procedure_error
            self._result = self.metrics
        elif "OUTPUT INSERTED.pipeline_run_key" in sql:
            self._result = (self.start_key,) if self.start_key is not None else None
        else:
            self._result = None

        return self

    def fetchone(self) -> tuple[object, ...] | None:
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
    metrics = _metrics_from_row((4, 5, 100, 110, 12, 12, 6, 2, 4))

    assert metrics == PublicationChangeMetrics(
        previous_snapshot_key=4,
        current_snapshot_key=5,
        previous_entity_rows=100,
        current_entity_rows=110,
        changes_detected=12,
        changes_inserted=12,
        added_changes=6,
        removed_changes=2,
        modified_changes=4,
    )
    assert metrics.rows_read == 210
    assert metrics.rows_loaded == 12


def test_metrics_support_first_snapshot_bootstrap() -> None:
    metrics = _metrics_from_row((None, 1, 0, 110, 0, 0, 0, 0, 0))

    assert metrics.previous_snapshot_key is None
    assert metrics.current_snapshot_key == 1
    assert metrics.rows_read == 110
    assert metrics.changes_detected == 0


def test_metrics_require_a_procedure_result() -> None:
    with pytest.raises(RuntimeError, match="returned no metrics"):
        _metrics_from_row(None)


def test_comparison_is_executed_and_audited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_cursor = RecordingCursor(start_key=91)
    load_cursor = RecordingCursor(metrics=(4, 5, 100, 110, 12, 12, 6, 2, 4))
    success_cursor = RecordingCursor()
    load_connection = RecordingConnection(load_cursor)
    connections = iter(
        (
            RecordingConnection(start_cursor),
            load_connection,
            RecordingConnection(success_cursor),
        )
    )
    monkeypatch.setattr(change_loader, "connect", lambda: next(connections))

    metrics = change_loader.load_publication_changes(
        5,
        previous_snapshot_key=4,
    )

    assert metrics.changes_inserted == 12
    assert load_connection.commit_count == 1
    assert start_cursor.executions[0][1] == (
        5,
        "build_gtfs_publication_changes",
        "Python",
    )
    assert load_cursor.executions[0][1] == (5, 4)
    assert success_cursor.executions[0][1] == (210, 12, 91)


def test_comparison_failure_is_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_cursor = RecordingCursor(start_key=92)
    load_cursor = RecordingCursor(procedure_error=ValueError("invalid comparison"))
    failure_cursor = RecordingCursor()
    connections = iter(
        (
            RecordingConnection(start_cursor),
            RecordingConnection(load_cursor),
            RecordingConnection(failure_cursor),
        )
    )
    monkeypatch.setattr(change_loader, "connect", lambda: next(connections))

    with pytest.raises(ValueError, match="invalid comparison"):
        change_loader.load_publication_changes(5)

    failure_sql, failure_parameters = failure_cursor.executions[0]
    assert "run_status = 'FAILED'" in failure_sql
    assert failure_parameters == ("invalid comparison", 92)


@pytest.mark.parametrize(
    ("current_key", "previous_key", "message"),
    (
        (0, None, "current_snapshot_key must be a positive integer"),
        (5, 0, "previous_snapshot_key must be a positive integer"),
        (5, 5, "previous_snapshot_key must be less than current_snapshot_key"),
        (5, 6, "previous_snapshot_key must be less than current_snapshot_key"),
    ),
)
def test_snapshot_arguments_are_validated(
    current_key: int,
    previous_key: int | None,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        change_loader.load_publication_changes(
            current_key,
            previous_snapshot_key=previous_key,
        )


def test_procedure_compares_all_governed_entity_types() -> None:
    sql = PUBLICATION_CHANGE_DDL.read_text(encoding="utf-8")
    procedure_position = sql.index("CREATE OR ALTER PROCEDURE")

    assert sql.count("CREATE OR ALTER PROCEDURE") == 1
    assert "SET NOCOUNT ON" not in sql[:procedure_position]
    assert "SET XACT_ABORT ON" not in sql[:procedure_position]
    assert "CREATE TABLE #previous_entity" in sql
    assert "CREATE TABLE #current_entity" in sql
    assert "CREATE TABLE #detected_change" in sql
    assert "'OPERATOR'" in sql
    assert "'ROUTE'" in sql
    assert "'STOP'" in sql
    assert "'SERVICE'" in sql
    assert "'TRIP'" in sql
    assert "FULL OUTER JOIN #current_entity" in sql


def test_procedure_is_idempotent_and_supports_bootstrap() -> None:
    sql = PUBLICATION_CHANGE_DDL.read_text(encoding="utf-8")

    assert "IF @previous_snapshot_key IS NULL" in sql
    assert "Existing publication changes conflict" in sql
    assert "WHERE existing.publication_change_key IS NULL" in sql
    assert "BEGIN TRANSACTION" in sql
    assert "COMMIT TRANSACTION" in sql
    assert "ROLLBACK TRANSACTION" in sql
