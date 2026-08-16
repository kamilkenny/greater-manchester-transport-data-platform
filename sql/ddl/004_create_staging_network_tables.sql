/*
Creates the GTFS network staging tables for routes, stops and trips.

Source values remain close to their published text form. Data type
conversion and relationship validation occur in later transformations.

Prerequisites:
    001_create_schemas.sql
    002_create_governance_tables.sql
*/

SET NOCOUNT ON;
SET XACT_ABORT ON;

IF OBJECT_ID(N'staging.gtfs_routes', N'U') IS NULL
BEGIN
    CREATE TABLE staging.gtfs_routes (
        snapshot_key BIGINT NOT NULL,
        source_row_number BIGINT NOT NULL,
        route_id NVARCHAR(50) NULL,
        agency_id NVARCHAR(50) NULL,
        route_short_name NVARCHAR(100) NULL,
        route_long_name NVARCHAR(300) NULL,
        route_desc NVARCHAR(1000) NULL,
        route_type VARCHAR(10) NULL,
        route_url NVARCHAR(1000) NULL,
        route_color VARCHAR(20) NULL,
        route_text_color VARCHAR(20) NULL,
        row_hash BINARY(32) NOT NULL,
        ingested_at_utc DATETIME2(3) NOT NULL
            CONSTRAINT DF_staging_routes_ingested
            DEFAULT (SYSUTCDATETIME()),

        CONSTRAINT PK_staging_gtfs_routes
            PRIMARY KEY CLUSTERED (
                snapshot_key,
                source_row_number
            )
    );
END;

IF OBJECT_ID(N'staging.gtfs_stops', N'U') IS NULL
BEGIN
    CREATE TABLE staging.gtfs_stops (
        snapshot_key BIGINT NOT NULL,
        source_row_number BIGINT NOT NULL,
        stop_id NVARCHAR(50) NULL,
        stop_code NVARCHAR(50) NULL,
        stop_name NVARCHAR(300) NULL,
        stop_desc NVARCHAR(1000) NULL,
        stop_lat VARCHAR(50) NULL,
        stop_lon VARCHAR(50) NULL,
        zone_id NVARCHAR(50) NULL,
        stop_url NVARCHAR(1000) NULL,
        location_type VARCHAR(10) NULL,
        parent_station NVARCHAR(50) NULL,
        wheelchair_boarding VARCHAR(10) NULL,
        row_hash BINARY(32) NOT NULL,
        ingested_at_utc DATETIME2(3) NOT NULL
            CONSTRAINT DF_staging_stops_ingested
            DEFAULT (SYSUTCDATETIME()),

        CONSTRAINT PK_staging_gtfs_stops
            PRIMARY KEY CLUSTERED (
                snapshot_key,
                source_row_number
            )
    );
END;

IF OBJECT_ID(N'staging.gtfs_trips', N'U') IS NULL
BEGIN
    CREATE TABLE staging.gtfs_trips (
        snapshot_key BIGINT NOT NULL,
        source_row_number BIGINT NOT NULL,
        route_id NVARCHAR(50) NULL,
        service_id NVARCHAR(50) NULL,
        trip_id NVARCHAR(50) NULL,
        trip_headsign NVARCHAR(300) NULL,
        trip_short_name NVARCHAR(100) NULL,
        direction_id VARCHAR(10) NULL,
        block_id NVARCHAR(100) NULL,
        shape_id NVARCHAR(50) NULL,
        wheelchair_accessible VARCHAR(10) NULL,
        row_hash BINARY(32) NOT NULL,
        ingested_at_utc DATETIME2(3) NOT NULL
            CONSTRAINT DF_staging_trips_ingested
            DEFAULT (SYSUTCDATETIME()),

        CONSTRAINT PK_staging_gtfs_trips
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
        name = N'IX_staging_routes_business_key'
        AND object_id = OBJECT_ID(N'staging.gtfs_routes')
)
BEGIN
    CREATE INDEX IX_staging_routes_business_key
        ON staging.gtfs_routes (
            snapshot_key,
            route_id
        );
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE
        name = N'IX_staging_routes_agency'
        AND object_id = OBJECT_ID(N'staging.gtfs_routes')
)
BEGIN
    CREATE INDEX IX_staging_routes_agency
        ON staging.gtfs_routes (
            snapshot_key,
            agency_id
        );
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE
        name = N'IX_staging_stops_business_key'
        AND object_id = OBJECT_ID(N'staging.gtfs_stops')
)
BEGIN
    CREATE INDEX IX_staging_stops_business_key
        ON staging.gtfs_stops (
            snapshot_key,
            stop_id
        );
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE
        name = N'IX_staging_trips_business_key'
        AND object_id = OBJECT_ID(N'staging.gtfs_trips')
)
BEGIN
    CREATE INDEX IX_staging_trips_business_key
        ON staging.gtfs_trips (
            snapshot_key,
            trip_id
        );
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE
        name = N'IX_staging_trips_relationships'
        AND object_id = OBJECT_ID(N'staging.gtfs_trips')
)
BEGIN
    CREATE INDEX IX_staging_trips_relationships
        ON staging.gtfs_trips (
            snapshot_key,
            route_id,
            service_id
        );
END;

SELECT
    schema_name(schema_id) AS schema_name,
    name AS table_name
FROM sys.tables
WHERE
    schema_name(schema_id) = N'staging'
    AND name IN (
        N'gtfs_routes',
        N'gtfs_stops',
        N'gtfs_trips'
    )
ORDER BY name;
