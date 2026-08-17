from __future__ import annotations

import csv
import io
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from transport_platform.ingestion.load_network_tables import NETWORK_TABLES
from transport_platform.ingestion.load_reference_tables import iter_staging_rows


def _write_stops_archive(path: Path) -> None:
    columns = NETWORK_TABLES[1].source_columns
    text_stream = io.StringIO(newline="")
    writer = csv.writer(text_stream)
    writer.writerow(columns)
    writer.writerow(
        (
            "stop-1",
            "1800SB001",
            "Example Interchange",
            "",
            "53.4808",
            "-2.2426",
            "",
            "",
            "0",
            "",
            "1",
        )
    )

    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("stops.txt", text_stream.getvalue())


def test_network_definitions_match_expected_gtfs_files() -> None:
    assert tuple(definition.source_file for definition in NETWORK_TABLES) == (
        "routes.txt",
        "stops.txt",
        "trips.txt",
    )
    assert tuple(definition.target_table for definition in NETWORK_TABLES) == (
        "staging.gtfs_routes",
        "staging.gtfs_stops",
        "staging.gtfs_trips",
    )


def test_network_rows_preserve_coordinates_and_lineage(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "snapshot.zip"
    _write_stops_archive(snapshot_path)

    with ZipFile(snapshot_path) as archive:
        rows = list(iter_staging_rows(archive, NETWORK_TABLES[1], 7))

    assert len(rows) == 1
    row = rows[0]
    assert row[0] == 7
    assert row[1] == 2
    assert row[2] == "stop-1"
    assert row[4] == "Example Interchange"
    assert row[6] == "53.4808"
    assert row[7] == "-2.2426"
    assert row[5] is None
    assert len(row[-1]) == 32
