/*
Creates the smaller GTFS reference staging tables.

Source values remain close to their published text form. Conversion
into dates, integers, Boolean values and warehouse keys occurs later.

Prerequisites:
    001_create_schemas.sql
    002_create_governance_tables.sql
*/

SET NOCOUNT ON;
SET XACT_ABORT ON;

IF OBJECT_ID(N'staging.gtfs_agency', N'U') IS NULL
BEGIN
    CREATE TABLE staging.gtfs_agency (
        snapshot_key BIGINT NOT NULL,
        source_row_number BIGINT NOT NULL,
        agency_id NVARCHAR(50) NULL,
        agency_name NVARCHAR(200) NULL,
        agency_url NVARCHAR(1000) NULL,
        agency_timezone NVARCHAR(100) NULL,
        agency_lang NVARCHAR(20) NULL,
        agency_phone NVARCHAR(100) NULL,
        agency_fare_url NVARCHAR(1000) NULL,
        agency_email NVARCHAR(320) NULL,
        agency_noc NVARCHAR(20) NULL,
        row_hash BINARY(32) NOT NULL,
        ingested_at_utc DATETIME2(3) NOT NULL
            CONSTRAINT DF_staging_agency_ingested
            DEFAULT (SYSUTCDATETIME()),

        CONSTRAINT PK_staging_gtfs_agency
            PRIMARY KEY CLUSTERED (
                snapshot_key,
                source_row_number
            )
    );
END;

IF OBJECT_ID(N'staging.gtfs_calendar', N'U') IS NULL
BEGIN
    CREATE TABLE staging.gtfs_calendar (
        snapshot_key BIGINT NOT NULL,
        source_row_number BIGINT NOT NULL,
        service_id NVARCHAR(50) NULL,
        monday CHAR(1) NULL,
        tuesday CHAR(1) NULL,
        wednesday CHAR(1) NULL,
        thursday CHAR(1) NULL,
        friday CHAR(1) NULL,
        saturday CHAR(1) NULL,
        sunday CHAR(1) NULL,
        start_date CHAR(8) NULL,
        end_date CHAR(8) NULL,
        row_hash BINARY(32) NOT NULL,
        ingested_at_utc DATETIME2(3) NOT NULL
            CONSTRAINT DF_staging_calendar_ingested
            DEFAULT (SYSUTCDATETIME()),

        CONSTRAINT PK_staging_gtfs_calendar
            PRIMARY KEY CLUSTERED (
                snapshot_key,
                source_row_number
            )
    );
END;

IF OBJECT_ID(N'staging.gtfs_calendar_dates', N'U') IS NULL
BEGIN
    CREATE TABLE staging.gtfs_calendar_dates (
        snapshot_key BIGINT NOT NULL,
        source_row_number BIGINT NOT NULL,
        service_id NVARCHAR(50) NULL,
        [date] CHAR(8) NULL,
        exception_type VARCHAR(10) NULL,
        row_hash BINARY(32) NOT NULL,
        ingested_at_utc DATETIME2(3) NOT NULL
            CONSTRAINT DF_staging_calendar_dates_ingested
            DEFAULT (SYSUTCDATETIME()),

        CONSTRAINT PK_staging_gtfs_calendar_dates
            PRIMARY KEY CLUSTERED (
                snapshot_key,
                source_row_number
            )
    );
END;

IF OBJECT_ID(N'staging.gtfs_feed_info', N'U') IS NULL
BEGIN
    CREATE TABLE staging.gtfs_feed_info (
        snapshot_key BIGINT NOT NULL,
        source_row_number BIGINT NOT NULL,
        feed_publisher_name NVARCHAR(200) NULL,
        feed_publisher_url NVARCHAR(1000) NULL,
        feed_lang NVARCHAR(20) NULL,
        feed_start_date CHAR(8) NULL,
        feed_end_date CHAR(8) NULL,
        feed_version NVARCHAR(255) NULL,
        row_hash BINARY(32) NOT NULL,
        ingested_at_utc DATETIME2(3) NOT NULL
            CONSTRAINT DF_staging_feed_info_ingested
            DEFAULT (SYSUTCDATETIME()),

        CONSTRAINT PK_staging_gtfs_feed_info
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
        name = N'IX_staging_agency_business_key'
        AND object_id = OBJECT_ID(N'staging.gtfs_agency')
)
BEGIN
    CREATE INDEX IX_staging_agency_business_key
        ON staging.gtfs_agency (
            snapshot_key,
            agency_id
        );
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE
        name = N'IX_staging_calendar_business_key'
        AND object_id = OBJECT_ID(N'staging.gtfs_calendar')
)
BEGIN
    CREATE INDEX IX_staging_calendar_business_key
        ON staging.gtfs_calendar (
            snapshot_key,
            service_id
        );
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE
        name = N'IX_staging_calendar_dates_business_key'
        AND object_id = OBJECT_ID(
            N'staging.gtfs_calendar_dates'
        )
)
BEGIN
    CREATE INDEX IX_staging_calendar_dates_business_key
        ON staging.gtfs_calendar_dates (
            snapshot_key,
            service_id,
            [date]
        );
END;

SELECT
    schema_name(schema_id) AS schema_name,
    name AS table_name
FROM sys.tables
WHERE
    schema_name(schema_id) = N'staging'
    AND name IN (
        N'gtfs_agency',
        N'gtfs_calendar',
        N'gtfs_calendar_dates',
        N'gtfs_feed_info'
    )
ORDER BY name;
