/*
Creates the set based loader for the date and operator dimensions.

The procedure validates one fully staged snapshot, extends the shared date
dimension and maintains Type 2 operator history. The Python wrapper records
the execution in governance.pipeline_run.

Prerequisites:
    002_create_governance_tables.sql
    003_create_staging_reference_tables.sql
    006_create_warehouse_core_dimensions.sql
*/

CREATE OR ALTER PROCEDURE warehouse.load_core_dimensions
    @snapshot_key BIGINT
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    DECLARE @snapshot_downloaded_at DATETIME2(3);
    DECLARE @minimum_date DATE;
    DECLARE @maximum_date DATE;
    DECLARE @date_rows_read BIGINT;
    DECLARE @date_rows_inserted BIGINT;
    DECLARE @operator_rows_read BIGINT;
    DECLARE @operator_rows_inserted BIGINT;
    DECLARE @operator_rows_closed BIGINT;

    SELECT
        @snapshot_downloaded_at = downloaded_at_utc
    FROM governance.source_snapshot
    WHERE
        snapshot_key = @snapshot_key
        AND snapshot_status = 'LOADED';

    IF @snapshot_downloaded_at IS NULL
    BEGIN
        THROW 50001, 'The snapshot must exist and have LOADED status.', 1;
    END;

    IF EXISTS (
        SELECT 1
        FROM warehouse.dim_operator AS target
        INNER JOIN governance.source_snapshot AS version_snapshot
            ON version_snapshot.snapshot_key =
                target.valid_from_snapshot_key
        WHERE
            target.is_current = 1
            AND version_snapshot.downloaded_at_utc >
                @snapshot_downloaded_at
    )
    BEGIN
        THROW 50002, 'An older snapshot cannot replace current operator history.', 1;
    END;

    IF NOT EXISTS (
        SELECT 1
        FROM staging.gtfs_agency
        WHERE snapshot_key = @snapshot_key
    )
    BEGIN
        THROW 50003, 'The snapshot has no staged agency records.', 1;
    END;

    IF EXISTS (
        SELECT 1
        FROM staging.gtfs_agency
        WHERE
            snapshot_key = @snapshot_key
            AND (
                NULLIF(LTRIM(RTRIM(agency_id)), '') IS NULL
                OR NULLIF(LTRIM(RTRIM(agency_name)), '') IS NULL
            )
    )
    BEGIN
        THROW 50004, 'Agency identifiers and names are required.', 1;
    END;

    IF EXISTS (
        SELECT 1
        FROM staging.gtfs_agency
        WHERE snapshot_key = @snapshot_key
        GROUP BY LTRIM(RTRIM(agency_id))
        HAVING COUNT_BIG(*) > 1
    )
    BEGIN
        THROW 50005, 'The snapshot contains duplicate agency identifiers.', 1;
    END;

    IF EXISTS (
        SELECT 1
        FROM staging.gtfs_calendar
        WHERE
            snapshot_key = @snapshot_key
            AND (
                (
                    NULLIF(LTRIM(RTRIM(start_date)), '') IS NOT NULL
                    AND TRY_CONVERT(DATE, start_date, 112) IS NULL
                )
                OR (
                    NULLIF(LTRIM(RTRIM(end_date)), '') IS NOT NULL
                    AND TRY_CONVERT(DATE, end_date, 112) IS NULL
                )
            )
    )
    BEGIN
        THROW 50006, 'The calendar table contains an invalid GTFS date.', 1;
    END;

    IF EXISTS (
        SELECT 1
        FROM staging.gtfs_calendar_dates
        WHERE
            snapshot_key = @snapshot_key
            AND NULLIF(LTRIM(RTRIM([date])), '') IS NOT NULL
            AND TRY_CONVERT(DATE, [date], 112) IS NULL
    )
    BEGIN
        THROW 50007, 'The calendar_dates table contains an invalid GTFS date.', 1;
    END;

    SELECT
        @minimum_date = MIN(source_date),
        @maximum_date = MAX(source_date)
    FROM (
        SELECT feed_start_date AS source_date
        FROM governance.source_snapshot
        WHERE snapshot_key = @snapshot_key

        UNION ALL

        SELECT feed_end_date
        FROM governance.source_snapshot
        WHERE snapshot_key = @snapshot_key

        UNION ALL

        SELECT TRY_CONVERT(DATE, start_date, 112)
        FROM staging.gtfs_calendar
        WHERE snapshot_key = @snapshot_key

        UNION ALL

        SELECT TRY_CONVERT(DATE, end_date, 112)
        FROM staging.gtfs_calendar
        WHERE snapshot_key = @snapshot_key

        UNION ALL

        SELECT TRY_CONVERT(DATE, [date], 112)
        FROM staging.gtfs_calendar_dates
        WHERE snapshot_key = @snapshot_key
    ) AS source_boundaries
    WHERE source_date IS NOT NULL;

    IF @minimum_date IS NULL OR @maximum_date IS NULL
    BEGIN
        THROW 50008, 'No service date range could be derived.', 1;
    END;

    IF @maximum_date < @minimum_date
    BEGIN
        THROW 50009, 'The derived service date range is invalid.', 1;
    END;

    IF DATEDIFF(DAY, @minimum_date, @maximum_date) > 7320
    BEGIN
        THROW 50010, 'The derived service date range exceeds twenty years.', 1;
    END;

    SET @date_rows_read = DATEDIFF(DAY, @minimum_date, @maximum_date) + 1;

    ;WITH service_dates AS (
        SELECT @minimum_date AS full_date

        UNION ALL

        SELECT DATEADD(DAY, 1, full_date)
        FROM service_dates
        WHERE full_date < @maximum_date
    ),
    date_attributes AS (
        SELECT
            full_date,
            DATEDIFF(DAY, CONVERT(DATE, '19000101'), full_date) % 7 + 1
                AS day_of_week_iso
        FROM service_dates
    )
    INSERT INTO warehouse.dim_date (
        date_key,
        full_date,
        calendar_year,
        calendar_quarter,
        calendar_month,
        month_name,
        day_of_month,
        day_of_week_iso,
        day_name,
        week_of_year,
        is_weekend
    )
    SELECT
        CONVERT(INT, CONVERT(CHAR(8), attributes.full_date, 112)),
        attributes.full_date,
        DATEPART(YEAR, attributes.full_date),
        DATEPART(QUARTER, attributes.full_date),
        DATEPART(MONTH, attributes.full_date),
        CHOOSE(
            DATEPART(MONTH, attributes.full_date),
            N'January', N'February', N'March', N'April', N'May', N'June',
            N'July', N'August', N'September', N'October', N'November',
            N'December'
        ),
        DATEPART(DAY, attributes.full_date),
        attributes.day_of_week_iso,
        CHOOSE(
            attributes.day_of_week_iso,
            N'Monday', N'Tuesday', N'Wednesday', N'Thursday', N'Friday',
            N'Saturday', N'Sunday'
        ),
        DATEPART(ISO_WEEK, attributes.full_date),
        CASE
            WHEN attributes.day_of_week_iso IN (6, 7) THEN 1
            ELSE 0
        END
    FROM date_attributes AS attributes
    WHERE NOT EXISTS (
        SELECT 1
        FROM warehouse.dim_date AS existing
        WHERE existing.full_date = attributes.full_date
    )
    OPTION (MAXRECURSION 0);

    SET @date_rows_inserted = @@ROWCOUNT;

    CREATE TABLE #source_operator (
        agency_id NVARCHAR(50) NOT NULL,
        agency_noc NVARCHAR(20) NULL,
        operator_name NVARCHAR(200) NOT NULL,
        operator_url NVARCHAR(1000) NULL,
        operator_timezone NVARCHAR(100) NULL,
        operator_language NVARCHAR(20) NULL,
        operator_phone NVARCHAR(100) NULL,
        operator_email NVARCHAR(320) NULL,
        row_hash BINARY(32) NOT NULL,
        PRIMARY KEY CLUSTERED (agency_id)
    );

    INSERT INTO #source_operator (
        agency_id,
        agency_noc,
        operator_name,
        operator_url,
        operator_timezone,
        operator_language,
        operator_phone,
        operator_email,
        row_hash
    )
    SELECT
        LTRIM(RTRIM(agency_id)),
        NULLIF(LTRIM(RTRIM(agency_noc)), ''),
        LTRIM(RTRIM(agency_name)),
        NULLIF(LTRIM(RTRIM(agency_url)), ''),
        NULLIF(LTRIM(RTRIM(agency_timezone)), ''),
        NULLIF(LTRIM(RTRIM(agency_lang)), ''),
        NULLIF(LTRIM(RTRIM(agency_phone)), ''),
        NULLIF(LTRIM(RTRIM(agency_email)), ''),
        row_hash
    FROM staging.gtfs_agency
    WHERE snapshot_key = @snapshot_key;

    SET @operator_rows_read = @@ROWCOUNT;

    UPDATE target
    SET
        valid_to_snapshot_key = @snapshot_key,
        is_current = 0,
        updated_at_utc = SYSUTCDATETIME()
    FROM warehouse.dim_operator AS target
    LEFT JOIN #source_operator AS source
        ON source.agency_id = target.agency_id
    WHERE
        target.is_current = 1
        AND (
            source.agency_id IS NULL
            OR source.row_hash <> target.row_hash
        );

    SET @operator_rows_closed = @@ROWCOUNT;

    INSERT INTO warehouse.dim_operator (
        agency_id,
        agency_noc,
        operator_name,
        operator_url,
        operator_timezone,
        operator_language,
        operator_phone,
        operator_email,
        valid_from_snapshot_key,
        valid_to_snapshot_key,
        is_current,
        row_hash
    )
    SELECT
        source.agency_id,
        source.agency_noc,
        source.operator_name,
        source.operator_url,
        source.operator_timezone,
        source.operator_language,
        source.operator_phone,
        source.operator_email,
        @snapshot_key,
        NULL,
        1,
        source.row_hash
    FROM #source_operator AS source
    LEFT JOIN warehouse.dim_operator AS current_version
        ON current_version.agency_id = source.agency_id
        AND current_version.is_current = 1
    WHERE current_version.operator_key IS NULL;

    SET @operator_rows_inserted = @@ROWCOUNT;

    SELECT
        @date_rows_read AS date_rows_read,
        @date_rows_inserted AS date_rows_inserted,
        @operator_rows_read AS operator_rows_read,
        @operator_rows_inserted AS operator_rows_inserted,
        @operator_rows_closed AS operator_rows_closed;
END;
