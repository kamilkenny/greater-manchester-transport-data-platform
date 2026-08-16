from __future__ import annotations

import argparse
import csv
import io
import json
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZipFile

from transport_platform.settings import get_settings
from transport_platform.validation.profile_gtfs import (
    EXPECTED_GTFS_FILES,
)


def profile_table_columns(
    archive: ZipFile,
    file_name: str,
) -> dict[str, object]:
    """Measure maximum lengths and blank values for one GTFS table."""

    with archive.open(file_name) as binary_file:
        with io.TextIOWrapper(
            binary_file,
            encoding="utf-8-sig",
            newline="",
        ) as text_file:
            reader = csv.reader(text_file)
            columns = next(reader, [])

            column_statistics = {
                column: {
                    "max_length": 0,
                    "blank_count": 0,
                }
                for column in columns
            }

            row_count = 0

            for row_number, row in enumerate(reader, start=2):
                if len(row) != len(columns):
                    raise ValueError(
                        f"{file_name} row {row_number} has "
                        f"{len(row)} fields, expected {len(columns)}"
                    )

                row_count += 1

                for column, value in zip(columns, row, strict=True):
                    statistics = column_statistics[column]
                    statistics["max_length"] = max(
                        statistics["max_length"],
                        len(value),
                    )

                    if not value.strip():
                        statistics["blank_count"] += 1

    for statistics in column_statistics.values():
        blank_count = statistics["blank_count"]
        blank_percentage = (
            round((blank_count / row_count) * 100, 4)
            if row_count
            else 0.0
        )
        statistics["blank_percentage"] = blank_percentage

    return {
        "row_count": row_count,
        "columns": column_statistics,
    }


def profile_gtfs_columns(snapshot_path: Path) -> Path:
    """Create a value profile for every table in one GTFS snapshot."""

    if not snapshot_path.exists():
        raise FileNotFoundError(f"Snapshot not found: {snapshot_path}")

    settings = get_settings()
    profile_directory = settings.processed_data_dir / "profiles"
    profile_directory.mkdir(parents=True, exist_ok=True)

    with ZipFile(snapshot_path) as archive:
        archive_names = set(archive.namelist())
        missing_files = sorted(EXPECTED_GTFS_FILES - archive_names)

        if missing_files:
            missing_list = ", ".join(missing_files)
            raise ValueError(f"Required GTFS files missing: {missing_list}")

        table_profiles = {
            file_name: profile_table_columns(archive, file_name)
            for file_name in sorted(EXPECTED_GTFS_FILES)
        }

    report = {
        "snapshot_file": snapshot_path.name,
        "profiled_at_utc": datetime.now(UTC).isoformat(),
        "tables": table_profiles,
    }

    profile_path = (
        profile_directory
        / f"{snapshot_path.stem}_column_profile.json"
    )
    profile_path.write_text(
        json.dumps(report, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"Column profile saved: {profile_path}")

    for table_name, table_profile in table_profiles.items():
        print(f"\n{table_name}")

        columns = table_profile["columns"]

        for column_name, statistics in columns.items():
            print(
                f"  {column_name}: "
                f"max_length={statistics['max_length']}, "
                f"blank={statistics['blank_percentage']}%"
            )

    return profile_path


def main() -> None:
    """Run the GTFS column profiler from the command line."""

    parser = argparse.ArgumentParser(
        description="Profile TfGM GTFS column lengths and blanks."
    )
    parser.add_argument(
        "snapshot",
        type=Path,
        help="Path to the preserved GTFS ZIP file.",
    )
    arguments = parser.parse_args()

    profile_gtfs_columns(arguments.snapshot)


if __name__ == "__main__":
    main()
