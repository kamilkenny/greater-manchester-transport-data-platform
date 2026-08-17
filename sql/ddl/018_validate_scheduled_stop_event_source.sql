/*
Creates the validation procedure for scheduled stop events.

GTFS times can exceed 24:00:00, so hours, minutes and seconds are validated
separately before the bounded warehouse transformation begins.

Prerequisites:
    002_create_governance_tables.sql
    005_create_staging_high_volume_tables.sql
    007_create_warehouse_network_dimensions.sql
    008_create_warehouse_service_dimensions.sql
    009_create_warehouse_schedule_tables.sql
    015_create_trip_dimension_loader.sql
*/

CREATE OR ALTER PROCEDURE warehouse.validate_scheduled_stop_event_source
    @snapshot_key BIGINT
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    DECLARE @snapshot_downloaded_at DATETIME2(3);
    DECLARE @source_rows BIGINT;

    SELECT
        @snapshot_downloaded_at = downloaded_at_utc
    FROM governance.source_snapshot
    WHERE
        snapshot_key = @snapshot_key
        AND snapshot_status = 'LOADED';

    IF @snapshot_downloaded_at IS NULL
    BEGIN
        THROW 50501, 'The snapshot must exist and have LOADED status.', 1;
    END;

    IF NOT EXISTS (
        SELECT 1
        FROM governance.pipeline_run
        WHERE
            snapshot_key = @snapshot_key
            AND pipeline_name = 'load_gtfs_trip_warehouse'
            AND run_status = 'SUCCEEDED'
    )
    BEGIN
        THROW 50502, 'The trip warehouse dimension must load first.', 1;
    END;

    SELECT
        @source_rows = COUNT_BIG(*)
    FROM staging.gtfs_stop_times
    WHERE snapshot_key = @snapshot_key;

    IF @source_rows = 0
    BEGIN
        THROW 50503, 'The snapshot has no staged stop time records.', 1;
    END;

    IF EXISTS (
        SELECT 1
        FROM staging.gtfs_stop_times AS source
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
            AND (
                NULLIF(LTRIM(RTRIM(source.trip_id)), '') IS NULL
                OR NULLIF(LTRIM(RTRIM(source.stop_id)), '') IS NULL
                OR TRY_CONVERT(INT, source.stop_sequence) IS NULL
                OR TRY_CONVERT(INT, source.stop_sequence) < 0
                OR NULLIF(cleaned.arrival_time, '') IS NULL
                OR LEN(cleaned.arrival_time) -
                    LEN(REPLACE(cleaned.arrival_time, ':', '')) <> 2
                OR parsed.arrival_hour IS NULL
                OR parsed.arrival_hour < 0
                OR parsed.arrival_hour > 596522
                OR parsed.arrival_minute IS NULL
                OR parsed.arrival_minute NOT BETWEEN 0 AND 59
                OR parsed.arrival_second IS NULL
                OR parsed.arrival_second NOT BETWEEN 0 AND 59
                OR NULLIF(cleaned.departure_time, '') IS NULL
                OR LEN(cleaned.departure_time) -
                    LEN(REPLACE(cleaned.departure_time, ':', '')) <> 2
                OR parsed.departure_hour IS NULL
                OR parsed.departure_hour < 0
                OR parsed.departure_hour > 596522
                OR parsed.departure_minute IS NULL
                OR parsed.departure_minute NOT BETWEEN 0 AND 59
                OR parsed.departure_second IS NULL
                OR parsed.departure_second NOT BETWEEN 0 AND 59
                OR (
                    NULLIF(LTRIM(RTRIM(source.pickup_type)), '') IS NOT NULL
                    AND (
                        TRY_CONVERT(TINYINT, source.pickup_type) IS NULL
                        OR TRY_CONVERT(TINYINT, source.pickup_type)
                            NOT BETWEEN 0 AND 3
                    )
                )
                OR (
                    NULLIF(LTRIM(RTRIM(source.drop_off_type)), '') IS NOT NULL
                    AND (
                        TRY_CONVERT(TINYINT, source.drop_off_type) IS NULL
                        OR TRY_CONVERT(TINYINT, source.drop_off_type)
                            NOT BETWEEN 0 AND 3
                    )
                )
                OR (
                    NULLIF(
                        LTRIM(RTRIM(source.shape_dist_traveled)),
                        ''
                    ) IS NOT NULL
                    AND (
                        TRY_CONVERT(
                            DECIMAL(18, 3),
                            source.shape_dist_traveled
                        ) IS NULL
                        OR TRY_CONVERT(
                            DECIMAL(18, 3),
                            source.shape_dist_traveled
                        ) < 0
                    )
                )
                OR (
                    NULLIF(LTRIM(RTRIM(source.timepoint)), '') IS NOT NULL
                    AND (
                        TRY_CONVERT(TINYINT, source.timepoint) IS NULL
                        OR TRY_CONVERT(TINYINT, source.timepoint)
                            NOT BETWEEN 0 AND 1
                    )
                )
            )
    )
    BEGIN
        THROW 50504, 'A scheduled stop event contains an invalid value.', 1;
    END;

    IF EXISTS (
        SELECT 1
        FROM staging.gtfs_stop_times
        WHERE snapshot_key = @snapshot_key
        GROUP BY
            LTRIM(RTRIM(trip_id)),
            TRY_CONVERT(INT, stop_sequence)
        HAVING COUNT_BIG(*) > 1
    )
    BEGIN
        THROW 50505, 'The snapshot contains duplicate trip stop sequences.', 1;
    END;

    IF EXISTS (
        SELECT 1
        FROM staging.gtfs_stop_times AS source
        LEFT JOIN warehouse.dim_trip AS trip
            ON trip.snapshot_key = @snapshot_key
            AND trip.trip_id = LTRIM(RTRIM(source.trip_id))
        WHERE
            source.snapshot_key = @snapshot_key
            AND trip.trip_key IS NULL
    )
    BEGIN
        THROW 50506, 'One or more stop events cannot resolve a trip.', 1;
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

    IF EXISTS (
        SELECT 1
        FROM staging.gtfs_stop_times AS source
        LEFT JOIN #stop_version AS stop
            ON stop.stop_id = LTRIM(RTRIM(source.stop_id))
        WHERE
            source.snapshot_key = @snapshot_key
            AND stop.stop_key IS NULL
    )
    BEGIN
        THROW 50507, 'One or more stop events cannot resolve a stop version.', 1;
    END;

    SELECT @source_rows AS source_rows;
END;
