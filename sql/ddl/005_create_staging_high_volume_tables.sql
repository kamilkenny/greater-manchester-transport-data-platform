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

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE
        name = N'IX_staging_stop_times_trip'
        AND object_id = OBJECT_ID(N'staging.gtfs_stop_times')
)
BEGIN
    CREATE INDEX IX_staging_stop_times_trip
        ON staging.gtfs_stop_times (
            snapshot_key,
            trip_id,
            stop_sequence
        )
        INCLUDE (
            stop_id,
            arrival_time,
            departure_time
        );
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE
        name = N'IX_staging_stop_times_stop'
        AND object_id = OBJECT_ID(N'staging.gtfs_stop_times')
)
BEGIN
    CREATE INDEX IX_staging_stop_times_stop
        ON staging.gtfs_stop_times (
            snapshot_key,
            stop_id
        )
        INCLUDE (
            trip_id,
            stop_sequence
        );
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE
        name = N'IX_staging_shapes_business_key'
        AND object_id = OBJECT_ID(N'staging.gtfs_shapes')
)
BEGIN
    CREATE INDEX IX_staging_shapes_business_key
        ON staging.gtfs_shapes (
            snapshot_key,
            shape_id,
            shape_pt_sequence
        )
        INCLUDE (
            shape_pt_lat,
            shape_pt_lon,
            shape_dist_traveled
        );
END;

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
