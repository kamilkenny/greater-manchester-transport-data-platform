/*
Creates the set based loader for service calendars and active service dates.

The loader materialises snapshot specific service definitions, expands normal
weekday operation and applies calendar date additions and removals.

Prerequisites:
    002_create_governance_tables.sql
    003_create_staging_reference_tables.sql
    006_create_warehouse_core_dimensions.sql
    008_create_warehouse_service_dimensions.sql
    009_create_warehouse_schedule_tables.sql
    012_create_core_dimension_loader.sql
*/

CREATE OR ALTER PROCEDURE warehouse.load_service_calendar
    @snapshot_key BIGINT
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    DECLARE @calendar_rows_read BIGINT;
    DECLARE @calendar_date_rows_read BIGINT;
    DECLARE @service_rows_inserted BIGINT;
    DECLARE @service_date_rows_derived BIGINT;
    DECLARE @service_date_rows_inserted BIGINT;
    DECLARE @service_date_rows_deleted BIGINT;

    IF NOT EXISTS (
        SELECT 1
        FROM governance.source_snapshot
        WHERE
            snapshot_key = @snapshot_key
            AND snapshot_status = 'LOADED'
    )
    BEGIN
        THROW 50201, 'The snapshot must exist and have LOADED status.', 1;
    END;

    IF NOT EXISTS (
        SELECT 1
        FROM governance.pipeline_run
        WHERE
            snapshot_key = @snapshot_key
            AND pipeline_name = 'load_gtfs_core_warehouse'
            AND run_status = 'SUCCEEDED'
    )
    BEGIN
        THROW 50202, 'The core warehouse dimensions must load first.', 1;
    END;

    SELECT
        @calendar_rows_read = COUNT_BIG(*)
    FROM staging.gtfs_calendar
    WHERE snapshot_key = @snapshot_key;

    SELECT
        @calendar_date_rows_read = COUNT_BIG(*)
    FROM staging.gtfs_calendar_dates
    WHERE snapshot_key = @snapshot_key;

    IF @calendar_rows_read = 0 AND @calendar_date_rows_read = 0
    BEGIN
        THROW 50203, 'The snapshot has no staged service calendar records.', 1;
    END;

    IF EXISTS (
        SELECT 1
        FROM staging.gtfs_calendar
        WHERE
            snapshot_key = @snapshot_key
            AND (
                NULLIF(LTRIM(RTRIM(service_id)), '') IS NULL
                OR NULLIF(LTRIM(RTRIM(monday)), '') IS NULL
                OR LTRIM(RTRIM(monday)) NOT IN ('0', '1')
                OR NULLIF(LTRIM(RTRIM(tuesday)), '') IS NULL
                OR LTRIM(RTRIM(tuesday)) NOT IN ('0', '1')
                OR NULLIF(LTRIM(RTRIM(wednesday)), '') IS NULL
                OR LTRIM(RTRIM(wednesday)) NOT IN ('0', '1')
                OR NULLIF(LTRIM(RTRIM(thursday)), '') IS NULL
                OR LTRIM(RTRIM(thursday)) NOT IN ('0', '1')
                OR NULLIF(LTRIM(RTRIM(friday)), '') IS NULL
                OR LTRIM(RTRIM(friday)) NOT IN ('0', '1')
                OR NULLIF(LTRIM(RTRIM(saturday)), '') IS NULL
                OR LTRIM(RTRIM(saturday)) NOT IN ('0', '1')
                OR NULLIF(LTRIM(RTRIM(sunday)), '') IS NULL
                OR LTRIM(RTRIM(sunday)) NOT IN ('0', '1')
                OR TRY_CONVERT(DATE, start_date, 112) IS NULL
                OR TRY_CONVERT(DATE, end_date, 112) IS NULL
                OR TRY_CONVERT(DATE, end_date, 112) <
                    TRY_CONVERT(DATE, start_date, 112)
            )
    )
    BEGIN
        THROW 50204, 'A calendar row contains an invalid required value.', 1;
    END;

    IF EXISTS (
        SELECT 1
        FROM staging.gtfs_calendar
        WHERE snapshot_key = @snapshot_key
        GROUP BY LTRIM(RTRIM(service_id))
        HAVING COUNT_BIG(*) > 1
    )
    BEGIN
        THROW 50205, 'The snapshot contains duplicate calendar service identifiers.', 1;
    END;

    IF EXISTS (
        SELECT 1
        FROM staging.gtfs_calendar_dates
        WHERE
            snapshot_key = @snapshot_key
            AND (
                NULLIF(LTRIM(RTRIM(service_id)), '') IS NULL
                OR TRY_CONVERT(DATE, [date], 112) IS NULL
                OR TRY_CONVERT(TINYINT, exception_type) IS NULL
                OR TRY_CONVERT(TINYINT, exception_type) NOT IN (1, 2)
            )
    )
    BEGIN
        THROW 50206, 'A calendar date row contains an invalid required value.', 1;
    END;

    IF EXISTS (
        SELECT 1
        FROM staging.gtfs_calendar_dates
        WHERE snapshot_key = @snapshot_key
        GROUP BY
            LTRIM(RTRIM(service_id)),
            TRY_CONVERT(DATE, [date], 112)
        HAVING COUNT_BIG(*) > 1
    )
    BEGIN
        THROW 50207, 'The snapshot contains duplicate service date exceptions.', 1;
    END;

    IF EXISTS (
        SELECT 1
        FROM staging.gtfs_calendar_dates AS exception
        WHERE
            exception.snapshot_key = @snapshot_key
            AND NOT EXISTS (
                SELECT 1
                FROM staging.gtfs_calendar AS calendar
                WHERE
                    calendar.snapshot_key = @snapshot_key
                    AND LTRIM(RTRIM(calendar.service_id)) =
                        LTRIM(RTRIM(exception.service_id))
            )
            AND NOT EXISTS (
                SELECT 1
                FROM staging.gtfs_calendar_dates AS addition
                WHERE
                    addition.snapshot_key = @snapshot_key
                    AND LTRIM(RTRIM(addition.service_id)) =
                        LTRIM(RTRIM(exception.service_id))
                    AND TRY_CONVERT(TINYINT, addition.exception_type) = 1
            )
    )
    BEGIN
        THROW 50208, 'An exception only service must contain an added date.', 1;
    END;

    CREATE TABLE #source_exception (
        service_id NVARCHAR(50) NOT NULL,
        service_date DATE NOT NULL,
        exception_type TINYINT NOT NULL,
        PRIMARY KEY CLUSTERED (
            service_id,
            service_date
        )
    );

    INSERT INTO #source_exception (
        service_id,
        service_date,
        exception_type
    )
    SELECT
        LTRIM(RTRIM(service_id)),
        TRY_CONVERT(DATE, [date], 112),
        TRY_CONVERT(TINYINT, exception_type)
    FROM staging.gtfs_calendar_dates
    WHERE snapshot_key = @snapshot_key;

    CREATE TABLE #source_service (
        service_id NVARCHAR(50) NOT NULL,
        monday BIT NOT NULL,
        tuesday BIT NOT NULL,
        wednesday BIT NOT NULL,
        thursday BIT NOT NULL,
        friday BIT NOT NULL,
        saturday BIT NOT NULL,
        sunday BIT NOT NULL,
        start_date DATE NOT NULL,
        end_date DATE NOT NULL,
        row_hash BINARY(32) NOT NULL,
        PRIMARY KEY CLUSTERED (service_id)
    );

    INSERT INTO #source_service (
        service_id,
        monday,
        tuesday,
        wednesday,
        thursday,
        friday,
        saturday,
        sunday,
        start_date,
        end_date,
        row_hash
    )
    SELECT
        LTRIM(RTRIM(service_id)),
        TRY_CONVERT(BIT, monday),
        TRY_CONVERT(BIT, tuesday),
        TRY_CONVERT(BIT, wednesday),
        TRY_CONVERT(BIT, thursday),
        TRY_CONVERT(BIT, friday),
        TRY_CONVERT(BIT, saturday),
        TRY_CONVERT(BIT, sunday),
        TRY_CONVERT(DATE, start_date, 112),
        TRY_CONVERT(DATE, end_date, 112),
        row_hash
    FROM staging.gtfs_calendar
    WHERE snapshot_key = @snapshot_key;

    INSERT INTO #source_service (
        service_id,
        monday,
        tuesday,
        wednesday,
        thursday,
        friday,
        saturday,
        sunday,
        start_date,
        end_date,
        row_hash
    )
    SELECT
        exception.service_id,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        MIN(exception.service_date),
        MAX(exception.service_date),
        HASHBYTES(
            'SHA2_256',
            CONCAT(
                exception.service_id,
                N'|EXCEPTION_ONLY|',
                CONVERT(CHAR(8), MIN(exception.service_date), 112),
                N'|',
                CONVERT(CHAR(8), MAX(exception.service_date), 112)
            )
        )
    FROM #source_exception AS exception
    WHERE
        exception.exception_type = 1
        AND NOT EXISTS (
            SELECT 1
            FROM #source_service AS calendar
            WHERE calendar.service_id = exception.service_id
        )
    GROUP BY exception.service_id;

    IF EXISTS (
        SELECT 1
        FROM warehouse.dim_service AS target
        LEFT JOIN #source_service AS source
            ON source.service_id = target.service_id
        WHERE
            target.snapshot_key = @snapshot_key
            AND (
                source.service_id IS NULL
                OR source.row_hash <> target.row_hash
            )
    )
    BEGIN
        THROW 50209, 'Existing service rows conflict with the staged snapshot.', 1;
    END;

    INSERT INTO warehouse.dim_service (
        snapshot_key,
        service_id,
        monday,
        tuesday,
        wednesday,
        thursday,
        friday,
        saturday,
        sunday,
        start_date,
        end_date,
        row_hash
    )
    SELECT
        @snapshot_key,
        source.service_id,
        source.monday,
        source.tuesday,
        source.wednesday,
        source.thursday,
        source.friday,
        source.saturday,
        source.sunday,
        source.start_date,
        source.end_date,
        source.row_hash
    FROM #source_service AS source
    LEFT JOIN warehouse.dim_service AS target
        ON target.snapshot_key = @snapshot_key
        AND target.service_id = source.service_id
    WHERE target.service_key IS NULL;

    SET @service_rows_inserted = @@ROWCOUNT;

    IF EXISTS (
        SELECT 1
        FROM #source_exception AS exception
        LEFT JOIN warehouse.dim_date AS service_date
            ON service_date.full_date = exception.service_date
        WHERE service_date.date_key IS NULL
    )
    BEGIN
        THROW 50210, 'The date dimension does not cover every service exception.', 1;
    END;

    CREATE TABLE #desired_service_date (
        service_key BIGINT NOT NULL,
        date_key INT NOT NULL,
        activation_source VARCHAR(20) NOT NULL,
        PRIMARY KEY CLUSTERED (
            service_key,
            date_key
        )
    );

    INSERT INTO #desired_service_date (
        service_key,
        date_key,
        activation_source
    )
    SELECT
        target.service_key,
        service_date.date_key,
        'CALENDAR'
    FROM #source_service AS source
    INNER JOIN warehouse.dim_service AS target
        ON target.snapshot_key = @snapshot_key
        AND target.service_id = source.service_id
    INNER JOIN warehouse.dim_date AS service_date
        ON service_date.full_date BETWEEN source.start_date AND source.end_date
    WHERE
        CASE service_date.day_of_week_iso
            WHEN 1 THEN source.monday
            WHEN 2 THEN source.tuesday
            WHEN 3 THEN source.wednesday
            WHEN 4 THEN source.thursday
            WHEN 5 THEN source.friday
            WHEN 6 THEN source.saturday
            WHEN 7 THEN source.sunday
        END = 1
        AND NOT EXISTS (
            SELECT 1
            FROM #source_exception AS exception
            WHERE
                exception.service_id = source.service_id
                AND exception.service_date = service_date.full_date
        );

    INSERT INTO #desired_service_date (
        service_key,
        date_key,
        activation_source
    )
    SELECT
        target.service_key,
        service_date.date_key,
        'EXCEPTION_ADDED'
    FROM #source_exception AS exception
    INNER JOIN warehouse.dim_service AS target
        ON target.snapshot_key = @snapshot_key
        AND target.service_id = exception.service_id
    INNER JOIN warehouse.dim_date AS service_date
        ON service_date.full_date = exception.service_date
    WHERE exception.exception_type = 1;

    SELECT
        @service_date_rows_derived = COUNT_BIG(*)
    FROM #desired_service_date;

    DELETE target
    FROM warehouse.bridge_service_date AS target
    LEFT JOIN #desired_service_date AS desired
        ON desired.service_key = target.service_key
        AND desired.date_key = target.date_key
    WHERE
        target.snapshot_key = @snapshot_key
        AND (
            desired.service_key IS NULL
            OR desired.activation_source <> target.activation_source
        );

    SET @service_date_rows_deleted = @@ROWCOUNT;

    INSERT INTO warehouse.bridge_service_date (
        snapshot_key,
        service_key,
        date_key,
        activation_source
    )
    SELECT
        @snapshot_key,
        desired.service_key,
        desired.date_key,
        desired.activation_source
    FROM #desired_service_date AS desired
    LEFT JOIN warehouse.bridge_service_date AS target
        ON target.service_key = desired.service_key
        AND target.date_key = desired.date_key
    WHERE target.service_key IS NULL;

    SET @service_date_rows_inserted = @@ROWCOUNT;

    SELECT
        @calendar_rows_read AS calendar_rows_read,
        @calendar_date_rows_read AS calendar_date_rows_read,
        @service_rows_inserted AS service_rows_inserted,
        @service_date_rows_derived AS service_date_rows_derived,
        @service_date_rows_inserted AS service_date_rows_inserted,
        @service_date_rows_deleted AS service_date_rows_deleted;
END;
