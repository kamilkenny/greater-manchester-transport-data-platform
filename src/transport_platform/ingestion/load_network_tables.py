from __future__ import annotations

import argparse
from pathlib import Path

from transport_platform.ingestion.load_reference_tables import (
    TableLoadDefinition,
    load_staging_table_group,
)

NETWORK_PIPELINE_NAME = "load_gtfs_network_staging"

NETWORK_TABLES = (
    TableLoadDefinition(
        source_file="routes.txt",
        target_table="staging.gtfs_routes",
        source_columns=(
            "route_id",
            "agency_id",
            "route_short_name",
            "route_long_name",
            "route_desc",
            "route_type",
            "route_url",
            "route_color",
            "route_text_color",
        ),
    ),
    TableLoadDefinition(
        source_file="stops.txt",
        target_table="staging.gtfs_stops",
        source_columns=(
            "stop_id",
            "stop_code",
            "stop_name",
            "stop_desc",
            "stop_lat",
            "stop_lon",
            "zone_id",
            "stop_url",
            "location_type",
            "parent_station",
            "wheelchair_boarding",
        ),
    ),
    TableLoadDefinition(
        source_file="trips.txt",
        target_table="staging.gtfs_trips",
        source_columns=(
            "route_id",
            "service_id",
            "trip_id",
            "trip_headsign",
            "trip_short_name",
            "direction_id",
            "block_id",
            "shape_id",
            "wheelchair_accessible",
        ),
    ),
)


def load_network_tables(snapshot_path: Path) -> dict[str, int]:
    """Load routes, stops and trips from one preserved GTFS snapshot."""

    return load_staging_table_group(
        snapshot_path=snapshot_path,
        definitions=NETWORK_TABLES,
        pipeline_name=NETWORK_PIPELINE_NAME,
        summary_name="network",
    )


def main() -> None:
    """Load network staging tables from one preserved GTFS snapshot."""

    parser = argparse.ArgumentParser(
        description="Load TfGM GTFS network tables into local SQL Server."
    )
    parser.add_argument(
        "snapshot",
        type=Path,
        help="Path to a preserved TfGM GTFS ZIP file.",
    )
    arguments = parser.parse_args()
    load_network_tables(arguments.snapshot)


if __name__ == "__main__":
    main()
