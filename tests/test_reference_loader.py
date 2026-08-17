from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import date, datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from transport_platform.ingestion.load_reference_tables import (
    REFERENCE_TABLES,
    _parse_datetime,
    _parse_gtfs_date,
    _read_metadata,
    _row_hash,
    iter_staging_rows,
)


def _write_agency_archive(path: Path) -> None:
    columns = REFERENCE_TABLES[0].source_columns
    text_stream = io.StringIO(newline="")
    writer = csv.writer(text_stream)
    writer.writerow(columns)
    writer.writerow(
        (
            "agency-1",
            "Example Operator",
            "https://example.test",
            "Europe/London",
            "en",
            "",
            "",
            "contact@example.test",
            "NOC1",
        )
    )

    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("agency.txt", text_stream.getvalue())


def test_row_hash_uses_ordered_source_values() -> None:
    values = ["route-1", "Example", ""]

    result = _row_hash(values)

    expected = hashlib.sha256(b"route-1\x1fExample\x1f").digest()
    assert result == expected
    assert len(result) == 32


def test_iter_staging_rows_preserves_lineage_and_blanks(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "snapshot.zip"
    _write_agency_archive(snapshot_path)

    with ZipFile(snapshot_path) as archive:
        rows = list(iter_staging_rows(archive, REFERENCE_TABLES[0], 42))

    assert len(rows) == 1
    row = rows[0]
    assert row[0] == 42
    assert row[1] == 2
    assert row[2] == "agency-1"
    assert row[3] == "Example Operator"
    assert row[7] is None
    assert row[8] is None
    assert len(row[-1]) == 32


def test_read_metadata_requires_downloader_contract(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "snapshot.zip"
    snapshot_path.touch()
    snapshot_path.with_suffix(".json").write_text(
        json.dumps({"source_url": "https://example.test"}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Snapshot metadata missing fields"):
        _read_metadata(snapshot_path)


def test_parse_source_dates_and_timestamps() -> None:
    assert _parse_gtfs_date("20260817") == date(2026, 8, 17)
    assert _parse_gtfs_date("") is None
    assert _parse_datetime("2026-08-17T01:00:00+00:00") == datetime(
        2026,
        8,
        17,
        1,
        0,
    )
    assert _parse_datetime("Sun, 17 Aug 2026 01:00:00 GMT") == datetime(
        2026,
        8,
        17,
        1,
        0,
    )
