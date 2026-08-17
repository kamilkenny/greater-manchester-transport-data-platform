from __future__ import annotations

import csv
import io
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import transport_platform.ingestion.load_high_volume_tables as high_volume_loader
from transport_platform.ingestion.load_reference_tables import (
    _bulk_copy_table,
    _insert_table,
    iter_staging_rows,
)


class RecordingConnection:
    def __init__(self) -> None:
        self.commit_count = 0

    def commit(self) -> None:
        self.commit_count += 1


class RecordingCursor:
    def __init__(self) -> None:
        self.fast_executemany = False
        self.executed_batches: list[list[tuple[object, ...]]] = []

    def execute(self, *_args) -> None:
        return None

    def executemany(self, _sql, batch) -> None:
        self.executed_batches.append(batch)


class RecordingBulkCursor:
    def __init__(self) -> None:
        self.options: dict[str, object] = {}
        self.rows: list[tuple[object, ...]] = []
        self.executed_sql: list[str] = []

    def execute(self, sql, *_args) -> None:
        self.executed_sql.append(sql)
        return None

    def bulkcopy(self, _target, rows, **options):
        self.options = options
        self.rows = list(rows)
        return {
            "rows_copied": len(self.rows),
            "batch_count": 1,
            "elapsed_time": 0.01,
        }


def _write_stop_times_archive(path: Path) -> None:
    columns = high_volume_loader.HIGH_VOLUME_TABLES[0].source_columns
    text_stream = io.StringIO(newline="")
    writer = csv.writer(text_stream)
    writer.writerow(columns)
    writer.writerow(
        (
            "trip-1",
            "27:15:00",
            "27:16:00",
            "stop-1",
            "14",
            "Night service",
            "0",
            "0",
            "12.75",
            "1",
        )
    )

    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("stop_times.txt", text_stream.getvalue())


def test_high_volume_definitions_match_expected_gtfs_files() -> None:
    assert tuple(
        definition.source_file for definition in high_volume_loader.HIGH_VOLUME_TABLES
    ) == (
        "stop_times.txt",
        "shapes.txt",
    )
    assert tuple(
        definition.target_table for definition in high_volume_loader.HIGH_VOLUME_TABLES
    ) == (
        "staging.gtfs_stop_times",
        "staging.gtfs_shapes",
    )


def test_stop_times_preserve_gtfs_times_beyond_midnight(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "snapshot.zip"
    _write_stop_times_archive(snapshot_path)

    with ZipFile(snapshot_path) as archive:
        rows = list(
            iter_staging_rows(
                archive,
                high_volume_loader.HIGH_VOLUME_TABLES[0],
                11,
            )
        )

    assert len(rows) == 1
    row = rows[0]
    assert row[0] == 11
    assert row[1] == 2
    assert row[2] == "trip-1"
    assert row[3] == "27:15:00"
    assert row[4] == "27:16:00"
    assert row[5] == "stop-1"
    assert len(row[-1]) == 32


def test_high_volume_success_marks_snapshot_loaded(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    def fake_load_staging_table_group(**kwargs):
        captured.update(kwargs)
        return {"stop_times.txt": 1, "shapes.txt": 1}

    monkeypatch.setattr(
        high_volume_loader,
        "load_staging_table_group",
        fake_load_staging_table_group,
    )

    result = high_volume_loader.load_high_volume_tables(tmp_path / "snapshot.zip")

    assert result == {"stop_times.txt": 1, "shapes.txt": 1}
    assert captured["snapshot_status"] == "LOADED"
    assert captured["pipeline_name"] == "load_gtfs_high_volume_staging"
    assert captured["batch_size"] == 10_000
    assert captured["use_native_bulk_copy"] is True


def test_high_volume_insert_commits_delete_and_each_batch(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "snapshot.zip"
    _write_stop_times_archive(snapshot_path)
    connection = RecordingConnection()
    cursor = RecordingCursor()

    with ZipFile(snapshot_path) as archive:
        rows_loaded = _insert_table(
            connection,
            cursor,
            archive,
            high_volume_loader.HIGH_VOLUME_TABLES[0],
            snapshot_key=12,
            batch_size=1,
            commit_each_batch=True,
        )

    assert rows_loaded == 1
    assert connection.commit_count == 2
    assert len(cursor.executed_batches) == 1
    assert cursor.fast_executemany is True


def test_high_volume_bulk_copy_uses_native_streaming_options(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "snapshot.zip"
    _write_stop_times_archive(snapshot_path)
    connection = RecordingConnection()
    cursor = RecordingBulkCursor()

    with ZipFile(snapshot_path) as archive:
        rows_loaded = _bulk_copy_table(
            connection,
            cursor,
            archive,
            high_volume_loader.HIGH_VOLUME_TABLES[0],
            snapshot_key=13,
            batch_size=10_000,
        )

    assert rows_loaded == 1
    assert connection.commit_count == 1
    assert cursor.executed_sql == ["TRUNCATE TABLE staging.gtfs_stop_times;"]
    assert cursor.rows[0][0] == 13
    assert cursor.options["batch_size"] == 10_000
    assert cursor.options["table_lock"] is True
    assert cursor.options["use_internal_transaction"] is True
    assert cursor.options["column_mappings"][-1] == "row_hash"
