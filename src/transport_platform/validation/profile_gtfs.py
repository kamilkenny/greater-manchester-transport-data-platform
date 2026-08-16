from __future__ import annotations

import argparse
import csv
import io
import json
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZipFile

from transport_platform.settings import get_settings

EXPECTED_GTFS_FILES = {
    "agency.txt",
    "calendar.txt",
    "calendar_dates.txt",
    "feed_info.txt",
    "routes.txt",
    "shapes.txt",
    "stops.txt",
    "stop_times.txt",
    "trips.txt",
}


def profile_table(archive: ZipFile, file_name: str) -> dict[str, object]:
    """Profile one GTFS table without loading it fully into memory."""

    file_information = archive.getinfo(file_name)

    with archive.open(file_information) as binary_file:
        with io.TextIOWrapper(
            binary_file,
            encoding="utf-8-sig",
            newline="",
        ) as text_file:
            reader = csv.reader(text_file)
            columns = next(reader, [])

            row_count = 0
            malformed_row_count = 0

            for row in reader:
                row_count += 1

                if len(row) != len(columns):
                    malformed_row_count += 1

    return {
        "columns": columns,
        "column_count": len(columns),
        "row_count": row_count,
        "malformed_row_count": malformed_row_count,
        "compressed_bytes": file_information.compress_size,
        "uncompressed_bytes": file_information.file_size,
    }


def profile_gtfs_snapshot(snapshot_path: Path) -> Path:
    """Create a structural profile for one preserved GTFS snapshot."""

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

        table_names = sorted(
            name
            for name in archive_names
            if name.endswith(".txt") and "/" not in name
        )

        table_profiles = {
            name: profile_table(archive, name)
            for name in table_names
        }

    report = {
        "snapshot_file": snapshot_path.name,
        "profiled_at_utc": datetime.now(UTC).isoformat(),
        "table_count": len(table_profiles),
        "missing_required_files": missing_files,
        "tables": table_profiles,
    }

    profile_path = (
        profile_directory / f"{snapshot_path.stem}_profile.json"
    )
    profile_path.write_text(
        json.dumps(report, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"Profile saved: {profile_path}")

    for table_name, table_profile in table_profiles.items():
        row_count = table_profile["row_count"]
        malformed_count = table_profile["malformed_row_count"]

        print(
            f"{table_name}: {row_count:,} rows, "
            f"{malformed_count:,} malformed"
        )

    return profile_path


def main() -> None:
    """Run the GTFS profiler from the command line."""

    parser = argparse.ArgumentParser(
        description="Profile a preserved TfGM GTFS snapshot."
    )
    parser.add_argument(
        "snapshot",
        type=Path,
        help="Path to the preserved GTFS ZIP file.",
    )
    arguments = parser.parse_args()

    profile_gtfs_snapshot(arguments.snapshot)


if __name__ == "__main__":
    main()

