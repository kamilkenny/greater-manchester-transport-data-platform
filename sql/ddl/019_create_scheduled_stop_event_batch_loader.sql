/*
Creates the bounded batch procedure for scheduled stop events.

Prerequisites:
    005_create_staging_high_volume_tables.sql
    007_create_warehouse_network_dimensions.sql
    008_create_warehouse_service_dimensions.sql
    009_create_warehouse_schedule_tables.sql
    018_validate_scheduled_stop_event_source.sql
*/

CREATE OR ALTER PROCEDURE warehouse.load_scheduled_stop_event_batch
    @snapshot_key BIGINT,
    @after_source_row_number BIGINT,
    @batch_size INT
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    DECLARE @snapshot_downloaded_at DATETIME2(3);
    DECLARE @batch_rows_read BIGINT;
    DECLARE @batch_rows_inserted BIGINT;
    DECLARE @last_source_row_number BIGINT;

    IF @after_source_row_number < 0
    BEGIN
        THROW 50508, 'The source row cursor cannot be negative.', 1;
    END;

    IF @batch_size < 1 OR @batch_size > 100000
    BEGIN
        THROW 50509, 'The stop event batch size must be between 1 and 100000.', 1;
    END;

    SELECT
        @snapshot_downloaded_at = downloaded_at_utc
    FROM governance.source_snapshot
    WHERE snapshot_key = @snapshot_key;

    IF @snapshot_downloaded_at IS NULL
    BEGIN
        THROW 50510, 'The batch snapshot does not exist.', 1;
    END;

    CREATE TABLE #stop_version (
        stop_id NVARCHAR(50) NOT NULL,
        stop_key BIGINT NOT NULL,
        PRIMARY KEY CLUSTERED (stop_id)
    );

    INSERT INTO #stop_version (
        stop_id,
        stop_key
    )
    SELECT
        stop.stop_id,
        stop.stop_key
    FROM warehouse.dim_stop AS stop
    INNER JOIN governance.source_snapshot AS valid_from_snapshot
        ON valid_from_snapshot.snapshot_key = stop.valid_from_snapshot_key
    LEFT JOIN governance.source_snapshot AS valid_to_snapshot
        ON valid_to_snapshot.snapshot_key = stop.valid_to_snapshot_key
    WHERE
        valid_from_snapshot.downloaded_at_utc <= @snapshot_downloaded_at
        AND (
            valid_to_snapshot.downloaded_at_utc IS NULL
            OR @snapshot_downloaded_at < valid_to_snapshot.downloaded_at_utc
        );

    CREATE TABLE #source_stop_event (
        source_row_number BIGINT NOT NULL,
        trip_key BIGINT NOT NULL,
        route_key BIGINT NOT NULL,
        stop_key BIGINT NOT NULL,
        stop_sequence INT NOT NULL,
        arrival_seconds INT NOT NULL,
        departure_seconds INT NOT NULL,
        stop_headsign NVARCHAR(300) NULL,
        pickup_type TINYINT NOT NULL,
        drop_off_type TINYINT NOT NULL,
        shape_dist_travelled DECIMAL(18, 3) NULL,
        is_timepoint BIT NOT NULL,
        row_hash BINARY(32) NOT NULL,
        PRIMARY KEY CLUSTERED (
            trip_key,
            stop_sequence
        )
    );

    INSERT INTO #source_stop_event (
        source_row_number,
        trip_key,
        route_key,
        stop_key,
        stop_sequence,
        arrival_seconds,
        departure_seconds,
        stop_headsign,
        pickup_type,
        drop_off_type,
        shape_dist_travelled,
        is_timepoint,
        row_hash
    )
    SELECT TOP (@batch_size)
        source.source_row_number,
        trip.trip_key,
        trip.route_key,
        stop.stop_key,
        TRY_CONVERT(INT, source.stop_sequence),
        parsed.arrival_hour * 3600 +
            parsed.arrival_minute * 60 + parsed.arrival_second,
        parsed.departure_hour * 3600 +
            parsed.departure_minute * 60 + parsed.departure_second,
        NULLIF(LTRIM(RTRIM(source.stop_headsign)), ''),
        COALESCE(
            TRY_CONVERT(
                TINYINT,
                NULLIF(LTRIM(RTRIM(source.pickup_type)), '')
            ),
            0
        ),
        COALESCE(
            TRY_CONVERT(
                TINYINT,
                NULLIF(LTRIM(RTRIM(source.drop_off_type)), '')
            ),
            0
        ),
        TRY_CONVERT(
            DECIMAL(18, 3),
            NULLIF(LTRIM(RTRIM(source.shape_dist_traveled)), '')
        ),
        COALESCE(
            TRY_CONVERT(
                BIT,
                NULLIF(LTRIM(RTRIM(source.timepoint)), '')
            ),
            1
        ),
        source.row_hash
    FROM staging.gtfs_stop_times AS source
    INNER JOIN warehouse.dim_trip AS trip
        ON trip.snapshot_key = @snapshot_key
        AND trip.trip_id = LTRIM(RTRIM(source.trip_id))
    INNER JOIN #stop_version AS stop
        ON stop.stop_id = LTRIM(RTRIM(source.stop_id))
    CROSS APPLY (
        SELECT
            LTRIM(RTRIM(source.arrival_time)) AS arrival_time,
            LTRIM(RTRIM(source.departure_time)) AS departure_time
    ) AS cleaned
    CROSS APPLY (
        SELECT
            TRY_CONVERT(
                INT,
                PARSENAME(REPLACE(cleaned.arrival_time, ':', '.'), 3)
            ) AS arrival_hour,
            TRY_CONVERT(
                INT,
                PARSENAME(REPLACE(cleaned.arrival_time, ':', '.'), 2)
            ) AS arrival_minute,
            TRY_CONVERT(
                INT,
                PARSENAME(REPLACE(cleaned.arrival_time, ':', '.'), 1)
            ) AS arrival_second,
            TRY_CONVERT(
                INT,
                PARSENAME(REPLACE(cleaned.departure_time, ':', '.'), 3)
            ) AS departure_hour,
            TRY_CONVERT(
                INT,
                PARSENAME(REPLACE(cleaned.departure_time, ':', '.'), 2)
            ) AS departure_minute,
            TRY_CONVERT(
                INT,
                PARSENAME(REPLACE(cleaned.departure_time, ':', '.'), 1)
            ) AS departure_second
    ) AS parsed
    WHERE
        source.snapshot_key = @snapshot_key
        AND source.source_row_number > @after_source_row_number
    ORDER BY source.source_row_number;

    SET @batch_rows_read = @@ROWCOUNT;

    SELECT
        @last_source_row_number = MAX(source_row_number)
    FROM #source_stop_event;

    IF EXISTS (
        SELECT 1
        FROM #source_stop_event AS source
        INNER JOIN warehouse.fact_scheduled_stop_event AS target
            ON target.snapshot_key = @snapshot_key
            AND target.trip_key = source.trip_key
            AND target.stop_sequence = source.stop_sequence
        WHERE
            target.row_hash <> source.row_hash
            OR target.route_key <> source.route_key
            OR target.stop_key <> source.stop_key
    )
    BEGIN
        THROW 50511, 'Existing stop events conflict with the staged snapshot.', 1;
    END;

    INSERT INTO warehouse.fact_scheduled_stop_event (
        snapshot_key,
        trip_key,
        route_key,
        stop_key,
        stop_sequence,
        arrival_seconds,
        departure_seconds,
        stop_headsign,
        pickup_type,
        drop_off_type,
        shape_dist_travelled,
        is_timepoint,
        row_hash
    )
    SELECT
        @snapshot_key,
        source.trip_key,
        source.route_key,
        source.stop_key,
        source.stop_sequence,
        source.arrival_seconds,
        source.departure_seconds,
        source.stop_headsign,
        source.pickup_type,
        source.drop_off_type,
        source.shape_dist_travelled,
        source.is_timepoint,
        source.row_hash
    FROM #source_stop_event AS source
    LEFT JOIN warehouse.fact_scheduled_stop_event AS target
        ON target.snapshot_key = @snapshot_key
        AND target.trip_key = source.trip_key
        AND target.stop_sequence = source.stop_sequence
    WHERE target.trip_key IS NULL;

    SET @batch_rows_inserted = @@ROWCOUNT;

    SELECT
        @batch_rows_read AS batch_rows_read,
        @batch_rows_inserted AS batch_rows_inserted,
        COALESCE(
            @last_source_row_number,
            @after_source_row_number
        ) AS last_source_row_number;
END;
