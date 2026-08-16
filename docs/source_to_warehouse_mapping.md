# TfGM GTFS Source to Warehouse Mapping

## Purpose

This document defines how the TfGM GTFS source files are loaded,
validated, transformed and mapped into the analytical warehouse.

The mapping provides one consistent contract for Python, Microsoft
Fabric Data Factory, Azure SQL, SSIS, SSRS, FastAPI and Power BI.

## Data Layers

| Layer | Responsibility |
|---|---|
| Raw | Preserve the original ZIP and its metadata without modification |
| Staging | Load GTFS fields close to their original published form |
| Warehouse | Apply data types, keys, relationships and dimensional modelling |
| Analytics | Provide efficient facts and approved reporting views |
| Governance | Record snapshots, pipeline runs and data quality results |

## Common Technical Fields

Every staging table will include:

| Field | Purpose |
|---|---|
| snapshot_key | Links every record to its source publication |
| source_row_number | Preserves the original row position |
| row_hash | Identifies duplicate or changed records |
| ingested_at_utc | Records when the row entered the platform |

## Source Table Mapping

### agency.txt

Target table: `warehouse.dim_operator`

Grain: One version of a transport operator.

| Source field | Target field | Transformation |
|---|---|---|
| agency_id | operator_business_id | Preserve as the natural identifier |
| agency_name | operator_name | Trim surrounding spaces |
| agency_url | operator_url | Validate as an optional URL |
| agency_timezone | operator_timezone | Standardise text |
| agency_lang | operator_language | Standardise text |
| agency_phone | operator_phone | Preserve as text |
| agency_fare_url | fare_url | Validate as an optional URL |
| agency_email | operator_email | Standardise case where appropriate |
| agency_noc | national_operator_code | Preserve the TfGM extension |

History method: Type 2 history for changed operator details.

### routes.txt

Target table: `warehouse.dim_route`

Grain: One version of a published route.

| Source field | Target field | Transformation |
|---|---|---|
| route_id | route_business_id | Preserve as the natural identifier |
| agency_id | operator_business_id | Resolve to `dim_operator` |
| route_short_name | route_short_name | Trim spaces |
| route_long_name | route_long_name | Trim spaces |
| route_desc | route_description | Preserve optional description |
| route_type | route_type_code | Convert to an integer |
| route_url | route_url | Validate as an optional URL |
| route_color | route_colour | Validate hexadecimal format |
| route_text_color | route_text_colour | Validate hexadecimal format |

History method: Type 2 history for changed route details.

### stops.txt

Target table: `warehouse.dim_stop`

Grain: One version of a stop, station or parent location.

| Source field | Target field | Transformation |
|---|---|---|
| stop_id | stop_business_id | Preserve as the natural identifier |
| stop_code | stop_code | Preserve as text |
| stop_name | stop_name | Trim spaces |
| stop_desc | stop_description | Preserve optional description |
| stop_lat | latitude | Convert to decimal |
| stop_lon | longitude | Convert to decimal |
| zone_id | zone_id | Preserve as text |
| stop_url | stop_url | Validate as an optional URL |
| location_type | location_type_code | Convert to an integer |
| parent_station | parent_stop_business_id | Resolve the stop hierarchy |
| wheelchair_boarding | wheelchair_boarding_code | Convert to an integer |

History method: Type 2 history for changed stop details.

### calendar.txt

Target table: `warehouse.dim_service`

Grain: One published service calendar pattern.

The weekday fields become Boolean indicators. `start_date` and
`end_date` are converted from `YYYYMMDD` text into SQL dates.

### calendar_dates.txt

Target table: `warehouse.bridge_service_date`

Grain: One service exception on one date.

`exception_type` is converted to an integer:

1 means the service is added.

2 means the service is removed.

The bridge combines normal calendar patterns with these exceptions to
produce the actual dates on which each service operates.

### trips.txt

Target table: `warehouse.dim_trip`

Grain: One published scheduled journey pattern.

| Source field | Target field | Transformation |
|---|---|---|
| trip_id | trip_business_id | Preserve as the natural identifier |
| route_id | route_business_id | Resolve to `dim_route` |
| service_id | service_business_id | Resolve to `dim_service` |
| trip_headsign | trip_headsign | Trim spaces |
| trip_short_name | trip_short_name | Preserve as text |
| direction_id | direction_code | Convert to an integer |
| block_id | block_id | Preserve as text |
| shape_id | shape_business_id | Preserve as text |
| wheelchair_accessible | wheelchair_accessible_code | Convert to an integer |

### stop_times.txt

Target table: `warehouse.fact_scheduled_stop_event`

Grain: One scheduled stop event within one trip publication.

| Source field | Target field | Transformation |
|---|---|---|
| trip_id | trip_key | Resolve to `dim_trip` |
| arrival_time | arrival_time_text | Preserve the original GTFS time |
| arrival_time | arrival_seconds | Derive seconds after midnight |
| departure_time | departure_time_text | Preserve the original GTFS time |
| departure_time | departure_seconds | Derive seconds after midnight |
| stop_id | stop_key | Resolve to `dim_stop` |
| stop_sequence | stop_sequence | Convert to an integer |
| stop_headsign | stop_headsign | Trim spaces |
| pickup_type | pickup_type_code | Convert to an integer |
| drop_off_type | drop_off_type_code | Convert to an integer |
| shape_dist_traveled | shape_distance | Convert to decimal |
| timepoint | timepoint_code | Convert to an integer |

GTFS times may exceed `24:00:00`. The original time is preserved, while
seconds after midnight support sorting and duration calculations.

### shapes.txt

Target table: `warehouse.shape_point`

Grain: One geographic point within a published route shape.

Latitude, longitude, point sequence and travelled distance are converted
to numeric types. This table supports mapping but is kept outside the
main analytical star to control query size.

### feed_info.txt and Download Metadata

Target table: `warehouse.dim_snapshot`

Grain: One preserved TfGM publication.

The table combines feed information with:

* Download timestamp
* Source modification timestamp
* Source URL
* File name
* File size
* ETag
* SHA256 checksum
* Pipeline status

## Analytical Facts

### warehouse.fact_route_service_day

Grain: One route, operator, service date and source snapshot.

Measures include:

* Scheduled trip count
* Scheduled stop event count
* Distinct stop count
* First departure
* Last arrival
* Service span in minutes
* Average scheduled headway

### warehouse.fact_stop_service_day

Grain: One stop, route, service date and source snapshot.

Measures include:

* Scheduled departure count
* Scheduled arrival count
* First scheduled service
* Last scheduled service
* Accessible trip count

### warehouse.fact_publication_change

Grain: One detected entity change between two successive snapshots.

The table records:

* Previous snapshot key
* Current snapshot key
* Entity type
* Entity business identifier
* Change type
* Previous row hash
* Current row hash
* Detected timestamp

Change types are `ADDED`, `REMOVED` and `CHANGED`.

## Storage and History Rules

The detailed stop event and shape tables hold the current validated
publication for efficient operational analysis.

Snapshot metadata and publication change records are append only.

Operator, route and stop dimensions use Type 2 history.

Daily analytical facts are regenerated from the latest validated
publication.

## Load Order

1. Register the snapshot.
2. Load the nine staging tables.
3. Execute structural and relationship checks.
4. Load operator, route, stop, service and trip dimensions.
5. Build actual service dates.
6. Load scheduled stop events and shape points.
7. Calculate route and stop daily facts.
8. Compare the publication with the previous snapshot.
9. Record data quality results and pipeline completion.
10. Refresh approved analytical views.
