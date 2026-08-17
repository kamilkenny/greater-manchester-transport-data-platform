/*
Creates the set based loader for the snapshot specific trip dimension.

Each trip resolves the route version valid at the snapshot publication time
and the service definition belonging to the same snapshot.

Prerequisites:
    002_create_governance_tables.sql
    004_create_staging_network_tables.sql
    005_create_staging_high_volume_tables.sql
    007_create_warehouse_network_dimensions.sql
    008_create_warehouse_service_dimensions.sql
    013_create_network_dimension_loader.sql
    014_create_service_calendar_loader.sql
*/

CREATE OR ALTER PROCEDURE warehouse.load_trip_dimension
    @snapshot_key BIGINT
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    DECLARE @snapshot_downloaded_at DATETIME2(3);
    DECLARE @trip_rows_read BIGINT;
    DECLARE @trip_rows_inserted BIGINT;

    SELECT
        @snapshot_downloaded_at = downloaded_at_utc
    FROM governance.source_snapshot
    WHERE
        snapshot_key = @snapshot_key
        AND snapshot_status = 'LOADED';

    IF @snapshot_downloaded_at IS NULL
    BEGIN
        THROW 50301, 'The snapshot must exist and have LOADED status.', 1;
    END;

    IF NOT EXISTS (
        SELECT 1
        FROM governance.pipeline_run
        WHERE
            snapshot_key = @snapshot_key
            AND pipeline_name = 'load_gtfs_network_warehouse'
            AND run_status = 'SUCCEEDED'
    )
    BEGIN
        THROW 50302, 'The network warehouse dimensions must load first.', 1;
    END;

    IF NOT EXISTS (
        SELECT 1
        FROM governance.pipeline_run
        WHERE
            snapshot_key = @snapshot_key
            AND pipeline_name = 'load_gtfs_service_warehouse'
            AND run_status = 'SUCCEEDED'
    )
    BEGIN
        THROW 50303, 'The service calendar warehouse must load first.', 1;
    END;

    IF NOT EXISTS (
        SELECT 1
        FROM staging.gtfs_trips
        WHERE snapshot_key = @snapshot_key
    )
    BEGIN
        THROW 50304, 'The snapshot has no staged trip records.', 1;
    END;

    IF EXISTS (
        SELECT 1
        FROM staging.gtfs_trips
        WHERE
            snapshot_key = @snapshot_key
            AND (
                NULLIF(LTRIM(RTRIM(route_id)), '') IS NULL
                OR NULLIF(LTRIM(RTRIM(service_id)), '') IS NULL
                OR NULLIF(LTRIM(RTRIM(trip_id)), '') IS NULL
            )
    )
    BEGIN
        THROW 50305, 'Trips require route, service and trip identifiers.', 1;
    END;

    IF EXISTS (
        SELECT 1
        FROM staging.gtfs_trips
        WHERE snapshot_key = @snapshot_key
        GROUP BY LTRIM(RTRIM(trip_id))
        HAVING COUNT_BIG(*) > 1
    )
    BEGIN
        THROW 50306, 'The snapshot contains duplicate trip identifiers.', 1;
    END;

    IF EXISTS (
        SELECT 1
        FROM staging.gtfs_trips
        WHERE
            snapshot_key = @snapshot_key
            AND (
                (
                    NULLIF(LTRIM(RTRIM(direction_id)), '') IS NOT NULL
                    AND (
                        TRY_CONVERT(TINYINT, direction_id) IS NULL
                        OR TRY_CONVERT(TINYINT, direction_id) NOT BETWEEN 0 AND 1
                    )
                )
                OR (
                    NULLIF(LTRIM(RTRIM(wheelchair_accessible)), '') IS NOT NULL
                    AND (
                        TRY_CONVERT(TINYINT, wheelchair_accessible) IS NULL
                        OR TRY_CONVERT(TINYINT, wheelchair_accessible)
                            NOT BETWEEN 0 AND 2
                    )
                )
            )
    )
    BEGIN
        THROW 50307, 'A trip contains an invalid coded attribute.', 1;
    END;

    CREATE TABLE #route_version (
        route_id NVARCHAR(50) NOT NULL,
        route_key BIGINT NOT NULL,
        PRIMARY KEY CLUSTERED (route_id)
    );

    INSERT INTO #route_version (
        route_id,
        route_key
    )
    SELECT
        route.route_id,
        route.route_key
    FROM warehouse.dim_route AS route
    INNER JOIN governance.source_snapshot AS valid_from_snapshot
        ON valid_from_snapshot.snapshot_key = route.valid_from_snapshot_key
    LEFT JOIN governance.source_snapshot AS valid_to_snapshot
        ON valid_to_snapshot.snapshot_key = route.valid_to_snapshot_key
    WHERE
        valid_from_snapshot.downloaded_at_utc <= @snapshot_downloaded_at
        AND (
            valid_to_snapshot.downloaded_at_utc IS NULL
            OR @snapshot_downloaded_at < valid_to_snapshot.downloaded_at_utc
        );

    IF EXISTS (
        SELECT 1
        FROM staging.gtfs_trips AS source
        LEFT JOIN #route_version AS route
            ON route.route_id = LTRIM(RTRIM(source.route_id))
        WHERE
            source.snapshot_key = @snapshot_key
            AND route.route_key IS NULL
    )
    BEGIN
        THROW 50308, 'One or more trips cannot resolve a route version.', 1;
    END;

    IF EXISTS (
        SELECT 1
        FROM staging.gtfs_trips AS source
        LEFT JOIN warehouse.dim_service AS service
            ON service.snapshot_key = @snapshot_key
            AND service.service_id = LTRIM(RTRIM(source.service_id))
        WHERE
            source.snapshot_key = @snapshot_key
            AND service.service_key IS NULL
    )
    BEGIN
        THROW 50309, 'One or more trips cannot resolve a service.', 1;
    END;

    CREATE TABLE #available_shape (
        shape_id NVARCHAR(50) NOT NULL,
        PRIMARY KEY CLUSTERED (shape_id)
    );

    INSERT INTO #available_shape (shape_id)
    SELECT DISTINCT
        LTRIM(RTRIM(shape_id))
    FROM staging.gtfs_shapes
    WHERE
        snapshot_key = @snapshot_key
        AND NULLIF(LTRIM(RTRIM(shape_id)), '') IS NOT NULL;

    IF EXISTS (
        SELECT 1
        FROM staging.gtfs_trips AS source
        LEFT JOIN #available_shape AS shape
            ON shape.shape_id = LTRIM(RTRIM(source.shape_id))
        WHERE
            source.snapshot_key = @snapshot_key
            AND NULLIF(LTRIM(RTRIM(source.shape_id)), '') IS NOT NULL
            AND shape.shape_id IS NULL
    )
    BEGIN
        THROW 50310, 'One or more trips reference an unknown shape.', 1;
    END;

    CREATE TABLE #source_trip (
        route_key BIGINT NOT NULL,
        service_key BIGINT NOT NULL,
        trip_id NVARCHAR(50) NOT NULL,
        trip_headsign NVARCHAR(300) NULL,
        trip_short_name NVARCHAR(100) NULL,
        direction_id TINYINT NULL,
        block_id NVARCHAR(100) NULL,
        shape_id NVARCHAR(50) NULL,
        wheelchair_accessible TINYINT NULL,
        row_hash BINARY(32) NOT NULL,
        PRIMARY KEY CLUSTERED (trip_id)
    );

    INSERT INTO #source_trip (
        route_key,
        service_key,
        trip_id,
        trip_headsign,
        trip_short_name,
        direction_id,
        block_id,
        shape_id,
        wheelchair_accessible,
        row_hash
    )
    SELECT
        route.route_key,
        service.service_key,
        LTRIM(RTRIM(source.trip_id)),
        NULLIF(LTRIM(RTRIM(source.trip_headsign)), ''),
        NULLIF(LTRIM(RTRIM(source.trip_short_name)), ''),
        TRY_CONVERT(
            TINYINT,
            NULLIF(LTRIM(RTRIM(source.direction_id)), '')
        ),
        NULLIF(LTRIM(RTRIM(source.block_id)), ''),
        NULLIF(LTRIM(RTRIM(source.shape_id)), ''),
        TRY_CONVERT(
            TINYINT,
            NULLIF(LTRIM(RTRIM(source.wheelchair_accessible)), '')
        ),
        source.row_hash
    FROM staging.gtfs_trips AS source
    INNER JOIN #route_version AS route
        ON route.route_id = LTRIM(RTRIM(source.route_id))
    INNER JOIN warehouse.dim_service AS service
        ON service.snapshot_key = @snapshot_key
        AND service.service_id = LTRIM(RTRIM(source.service_id))
    WHERE source.snapshot_key = @snapshot_key;

    SET @trip_rows_read = @@ROWCOUNT;

    IF EXISTS (
        SELECT 1
        FROM warehouse.dim_trip AS target
        LEFT JOIN #source_trip AS source
            ON source.trip_id = target.trip_id
        WHERE
            target.snapshot_key = @snapshot_key
            AND (
                source.trip_id IS NULL
                OR source.row_hash <> target.row_hash
                OR source.route_key <> target.route_key
                OR source.service_key <> target.service_key
            )
    )
    BEGIN
        THROW 50311, 'Existing trip rows conflict with the staged snapshot.', 1;
    END;

    INSERT INTO warehouse.dim_trip (
        snapshot_key,
        route_key,
        service_key,
        trip_id,
        trip_headsign,
        trip_short_name,
        direction_id,
        block_id,
        shape_id,
        wheelchair_accessible,
        row_hash
    )
    SELECT
        @snapshot_key,
        source.route_key,
        source.service_key,
        source.trip_id,
        source.trip_headsign,
        source.trip_short_name,
        source.direction_id,
        source.block_id,
        source.shape_id,
        source.wheelchair_accessible,
        source.row_hash
    FROM #source_trip AS source
    LEFT JOIN warehouse.dim_trip AS target
        ON target.snapshot_key = @snapshot_key
        AND target.trip_id = source.trip_id
    WHERE target.trip_key IS NULL;

    SET @trip_rows_inserted = @@ROWCOUNT;

    SELECT
        @trip_rows_read AS trip_rows_read,
        @trip_rows_inserted AS trip_rows_inserted;
END;
