/*
Creates the high volume GTFS staging tables for stop times and shapes.

Source values remain close to their published text form. Conversion
and relationship validation occur in later transformations.

Prerequisites:
    001_create_schemas.sql
    002_create_governance_tables.sql
*/

SET NOCOUNT ON;
SET XACT_ABORT ON;

IF OBJECT_ID(N'staging.gtfs_stop_times', N'U') IS NULL
BEGIN
    CREATE TABLE staging.gtfs_stop_times (
        snapshot_key BIGINT NOT NULL,
        source_row_number BIGINT NOT NULL,
        trip_id NVARCHAR(50) NULL,
        arrival_time VARCHAR(20) NULL,
        departure_time VARCHAR(20) NULL,
        stop_id NVARCHAR(50) NULL,
        stop_sequence VARCHAR(20) NULL,
        stop_headsign NVARCHAR(300) NULL,
        pickup_type VARCHAR(10) NULL,
        drop_off_type VARCHAR(10) NULL,
        shape_dist_traveled VARCHAR(50) NULL,
        timepoint VARCHAR(10) NULL,
        row_hash BINARY(32) NOT NULL,
        ingested_at_utc DATETIME2(3) NOT NULL
            CONSTRAINT DF_staging_stop_times_ingested
            DEFAULT (SYSUTCDATETIME()),

        CONSTRAINT PK_staging_gtfs_stop_times
            PRIMARY KEY CLUSTERED (
                snapshot_key,
                source_row_number
            )
    );
END;

IF OBJECT_ID(N'staging.gtfs_shapes', N'U') IS NULL
BEGIN
    CREATE TABLE staging.gtfs_shapes (
        snapshot_key BIGINT NOT NULL,
        source_row_number BIGINT NOT NULL,
        shape_id NVARCHAR(50) NULL,
        shape_pt_lat VARCHAR(50) NULL,
        shape_pt_lon VARCHAR(50) NULL,
        shape_pt_sequence VARCHAR(20) NULL,
        shape_dist_traveled VARCHAR(50) NULL,
        row_hash BINARY(32) NOT NULL,
        ingested_at_utc DATETIME2(3) NOT NULL
            CONSTRAINT DF_staging_shapes_ingested
            DEFAULT (SYSUTCDATETIME()),

        CONSTRAINT PK_staging_gtfs_shapes
            PRIMARY KEY CLUSTERED (
                snapshot_key,
                source_row_number
            )
    );
END;

/*
High volume staging is loaded sequentially by snapshot and source row.
Keep only the clustered lineage key during ingestion. Secondary indexes
belong on typed warehouse tables, where their analytical benefit justifies
their write and memory cost.
*/
DROP INDEX IF EXISTS IX_staging_stop_times_trip
    ON staging.gtfs_stop_times;

DROP INDEX IF EXISTS IX_staging_stop_times_stop
    ON staging.gtfs_stop_times;

DROP INDEX IF EXISTS IX_staging_shapes_business_key
    ON staging.gtfs_shapes;

SELECT
    schema_name(schema_id) AS schema_name,
    name AS table_name
FROM sys.tables
WHERE
    schema_name(schema_id) = N'staging'
    AND name IN (
        N'gtfs_stop_times',
        N'gtfs_shapes'
    )
ORDER BY name;
