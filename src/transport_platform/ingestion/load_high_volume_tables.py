from __future__ import annotations

import argparse
from pathlib import Path

from transport_platform.ingestion.load_reference_tables import (
    TableLoadDefinition,
    load_staging_table_group,
)

HIGH_VOLUME_PIPELINE_NAME = "load_gtfs_high_volume_staging"
HIGH_VOLUME_BATCH_SIZE = 10_000

HIGH_VOLUME_TABLES = (
    TableLoadDefinition(
        source_file="stop_times.txt",
        target_table="staging.gtfs_stop_times",
        source_columns=(
            "trip_id",
            "arrival_time",
            "departure_time",
            "stop_id",
            "stop_sequence",
            "stop_headsign",
            "pickup_type",
            "drop_off_type",
            "shape_dist_traveled",
            "timepoint",
        ),
    ),
    TableLoadDefinition(
        source_file="shapes.txt",
        target_table="staging.gtfs_shapes",
        source_columns=(
            "shape_id",
            "shape_pt_lat",
            "shape_pt_lon",
            "shape_pt_sequence",
            "shape_dist_traveled",
        ),
    ),
)


def load_high_volume_tables(snapshot_path: Path) -> dict[str, int]:
    """Load stop times and shapes from one preserved GTFS snapshot."""

    return load_staging_table_group(
        snapshot_path=snapshot_path,
        definitions=HIGH_VOLUME_TABLES,
        pipeline_name=HIGH_VOLUME_PIPELINE_NAME,
        summary_name="high volume",
        snapshot_status="LOADED",
        batch_size=HIGH_VOLUME_BATCH_SIZE,
        use_native_bulk_copy=True,
    )


def main() -> None:
    """Load high volume staging tables from one GTFS snapshot."""

    parser = argparse.ArgumentParser(
        description="Load high volume TfGM GTFS tables into local SQL Server."
    )
    parser.add_argument(
        "snapshot",
        type=Path,
        help="Path to a preserved TfGM GTFS ZIP file.",
    )
    arguments = parser.parse_args()
    load_high_volume_tables(arguments.snapshot)


if __name__ == "__main__":
    main()
