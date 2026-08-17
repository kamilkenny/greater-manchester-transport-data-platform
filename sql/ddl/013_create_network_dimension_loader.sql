/*
Creates the set based loader for the route and stop dimensions.

Both dimensions preserve Type 2 publication history. Routes resolve the
current operator version created by the core warehouse transformation.

Prerequisites:
    002_create_governance_tables.sql
    004_create_staging_network_tables.sql
    006_create_warehouse_core_dimensions.sql
    007_create_warehouse_network_dimensions.sql
    012_create_core_dimension_loader.sql
*/

CREATE OR ALTER PROCEDURE warehouse.load_network_dimensions
    @snapshot_key BIGINT
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    DECLARE @snapshot_downloaded_at DATETIME2(3);
    DECLARE @route_rows_read BIGINT;
    DECLARE @route_rows_inserted BIGINT;
    DECLARE @route_rows_closed BIGINT;
    DECLARE @stop_rows_read BIGINT;
    DECLARE @stop_rows_inserted BIGINT;
    DECLARE @stop_rows_closed BIGINT;

    SELECT
        @snapshot_downloaded_at = downloaded_at_utc
    FROM governance.source_snapshot
    WHERE
        snapshot_key = @snapshot_key
        AND snapshot_status = 'LOADED';

    IF @snapshot_downloaded_at IS NULL
    BEGIN
        THROW 50101, 'The snapshot must exist and have LOADED status.', 1;
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
        THROW 50102, 'The core warehouse dimensions must load first.', 1;
    END;

    IF EXISTS (
        SELECT 1
        FROM (
            SELECT valid_from_snapshot_key
            FROM warehouse.dim_route
            WHERE is_current = 1

            UNION ALL

            SELECT valid_from_snapshot_key
            FROM warehouse.dim_stop
            WHERE is_current = 1
        ) AS current_versions
        INNER JOIN governance.source_snapshot AS version_snapshot
            ON version_snapshot.snapshot_key =
                current_versions.valid_from_snapshot_key
        WHERE version_snapshot.downloaded_at_utc > @snapshot_downloaded_at
    )
    BEGIN
        THROW 50103, 'An older snapshot cannot replace current network history.', 1;
    END;

    IF NOT EXISTS (
        SELECT 1
        FROM staging.gtfs_routes
        WHERE snapshot_key = @snapshot_key
    )
    BEGIN
        THROW 50104, 'The snapshot has no staged route records.', 1;
    END;

    IF NOT EXISTS (
        SELECT 1
        FROM staging.gtfs_stops
        WHERE snapshot_key = @snapshot_key
    )
    BEGIN
        THROW 50105, 'The snapshot has no staged stop records.', 1;
    END;

    IF EXISTS (
        SELECT 1
        FROM staging.gtfs_routes
        WHERE
            snapshot_key = @snapshot_key
            AND (
                NULLIF(LTRIM(RTRIM(route_id)), '') IS NULL
                OR NULLIF(LTRIM(RTRIM(agency_id)), '') IS NULL
                OR TRY_CONVERT(SMALLINT, route_type) IS NULL
                OR TRY_CONVERT(SMALLINT, route_type) < 0
            )
    )
    BEGIN
        THROW 50106, 'Routes require identifiers, operators and valid types.', 1;
    END;

    IF EXISTS (
        SELECT 1
        FROM staging.gtfs_routes
        WHERE snapshot_key = @snapshot_key
        GROUP BY LTRIM(RTRIM(route_id))
        HAVING COUNT_BIG(*) > 1
    )
    BEGIN
        THROW 50107, 'The snapshot contains duplicate route identifiers.', 1;
    END;

    IF EXISTS (
        SELECT 1
        FROM staging.gtfs_routes
        WHERE
            snapshot_key = @snapshot_key
            AND (
                (
                    NULLIF(LTRIM(RTRIM(route_color)), '') IS NOT NULL
                    AND (
                        LEN(LTRIM(RTRIM(route_color))) <> 6
                        OR LTRIM(RTRIM(route_color))
                            COLLATE Latin1_General_100_BIN2
                            LIKE '%[^0-9A-Fa-f]%'
                    )
                )
                OR (
                    NULLIF(LTRIM(RTRIM(route_text_color)), '') IS NOT NULL
                    AND (
                        LEN(LTRIM(RTRIM(route_text_color))) <> 6
                        OR LTRIM(RTRIM(route_text_color))
                            COLLATE Latin1_General_100_BIN2
                            LIKE '%[^0-9A-Fa-f]%'
                    )
                )
            )
    )
    BEGIN
        THROW 50108, 'Route colours must contain six hexadecimal characters.', 1;
    END;

    IF EXISTS (
        SELECT 1
        FROM staging.gtfs_routes AS source
        LEFT JOIN warehouse.dim_operator AS operator
            ON operator.agency_id = LTRIM(RTRIM(source.agency_id))
            AND operator.is_current = 1
        WHERE
            source.snapshot_key = @snapshot_key
            AND operator.operator_key IS NULL
    )
    BEGIN
        THROW 50109, 'One or more routes cannot resolve a current operator.', 1;
    END;

    IF EXISTS (
        SELECT 1
        FROM staging.gtfs_stops
        WHERE
            snapshot_key = @snapshot_key
            AND (
                NULLIF(LTRIM(RTRIM(stop_id)), '') IS NULL
                OR NULLIF(LTRIM(RTRIM(stop_name)), '') IS NULL
                OR TRY_CONVERT(DECIMAL(9, 6), stop_lat) IS NULL
                OR TRY_CONVERT(DECIMAL(9, 6), stop_lon) IS NULL
                OR TRY_CONVERT(DECIMAL(9, 6), stop_lat)
                    NOT BETWEEN -90 AND 90
                OR TRY_CONVERT(DECIMAL(9, 6), stop_lon)
                    NOT BETWEEN -180 AND 180
            )
    )
    BEGIN
        THROW 50110, 'Stops require identifiers, names and valid coordinates.', 1;
    END;

    IF EXISTS (
        SELECT 1
        FROM staging.gtfs_stops
        WHERE snapshot_key = @snapshot_key
        GROUP BY LTRIM(RTRIM(stop_id))
        HAVING COUNT_BIG(*) > 1
    )
    BEGIN
        THROW 50111, 'The snapshot contains duplicate stop identifiers.', 1;
    END;

    IF EXISTS (
        SELECT 1
        FROM staging.gtfs_stops
        WHERE
            snapshot_key = @snapshot_key
            AND (
                (
                    NULLIF(LTRIM(RTRIM(location_type)), '') IS NOT NULL
                    AND (
                        TRY_CONVERT(TINYINT, location_type) IS NULL
                        OR TRY_CONVERT(TINYINT, location_type)
                            NOT BETWEEN 0 AND 4
                    )
                )
                OR (
                    NULLIF(LTRIM(RTRIM(wheelchair_boarding)), '') IS NOT NULL
                    AND (
                        TRY_CONVERT(TINYINT, wheelchair_boarding) IS NULL
                        OR TRY_CONVERT(TINYINT, wheelchair_boarding)
                            NOT BETWEEN 0 AND 2
                    )
                )
            )
    )
    BEGIN
        THROW 50112, 'A stop contains an invalid coded attribute.', 1;
    END;

    CREATE TABLE #source_route (
        route_id NVARCHAR(50) NOT NULL,
        operator_key BIGINT NOT NULL,
        route_short_name NVARCHAR(100) NULL,
        route_long_name NVARCHAR(300) NULL,
        route_description NVARCHAR(1000) NULL,
        route_type SMALLINT NOT NULL,
        route_url NVARCHAR(1000) NULL,
        route_colour CHAR(6) NULL,
        route_text_colour CHAR(6) NULL,
        row_hash BINARY(32) NOT NULL,
        PRIMARY KEY CLUSTERED (route_id)
    );

    INSERT INTO #source_route (
        route_id,
        operator_key,
        route_short_name,
        route_long_name,
        route_description,
        route_type,
        route_url,
        route_colour,
        route_text_colour,
        row_hash
    )
    SELECT
        LTRIM(RTRIM(source.route_id)),
        operator.operator_key,
        NULLIF(LTRIM(RTRIM(source.route_short_name)), ''),
        NULLIF(LTRIM(RTRIM(source.route_long_name)), ''),
        NULLIF(LTRIM(RTRIM(source.route_desc)), ''),
        TRY_CONVERT(SMALLINT, source.route_type),
        NULLIF(LTRIM(RTRIM(source.route_url)), ''),
        UPPER(NULLIF(LTRIM(RTRIM(source.route_color)), '')),
        UPPER(NULLIF(LTRIM(RTRIM(source.route_text_color)), '')),
        source.row_hash
    FROM staging.gtfs_routes AS source
    INNER JOIN warehouse.dim_operator AS operator
        ON operator.agency_id = LTRIM(RTRIM(source.agency_id))
        AND operator.is_current = 1
    WHERE source.snapshot_key = @snapshot_key;

    SET @route_rows_read = @@ROWCOUNT;

    UPDATE target
    SET
        valid_to_snapshot_key = @snapshot_key,
        is_current = 0,
        updated_at_utc = SYSUTCDATETIME()
    FROM warehouse.dim_route AS target
    LEFT JOIN #source_route AS source
        ON source.route_id = target.route_id
    WHERE
        target.is_current = 1
        AND (
            source.route_id IS NULL
            OR source.row_hash <> target.row_hash
            OR source.operator_key <> target.operator_key
        );

    SET @route_rows_closed = @@ROWCOUNT;

    INSERT INTO warehouse.dim_route (
        route_id,
        operator_key,
        route_short_name,
        route_long_name,
        route_description,
        route_type,
        route_url,
        route_colour,
        route_text_colour,
        valid_from_snapshot_key,
        valid_to_snapshot_key,
        is_current,
        row_hash
    )
    SELECT
        source.route_id,
        source.operator_key,
        source.route_short_name,
        source.route_long_name,
        source.route_description,
        source.route_type,
        source.route_url,
        source.route_colour,
        source.route_text_colour,
        @snapshot_key,
        NULL,
        1,
        source.row_hash
    FROM #source_route AS source
    LEFT JOIN warehouse.dim_route AS current_version
        ON current_version.route_id = source.route_id
        AND current_version.is_current = 1
    WHERE current_version.route_key IS NULL;

    SET @route_rows_inserted = @@ROWCOUNT;

    CREATE TABLE #source_stop (
        stop_id NVARCHAR(50) NOT NULL,
        stop_code NVARCHAR(50) NULL,
        stop_name NVARCHAR(300) NOT NULL,
        stop_description NVARCHAR(1000) NULL,
        stop_latitude DECIMAL(9, 6) NOT NULL,
        stop_longitude DECIMAL(9, 6) NOT NULL,
        zone_id NVARCHAR(50) NULL,
        stop_url NVARCHAR(1000) NULL,
        location_type TINYINT NULL,
        parent_station_id NVARCHAR(50) NULL,
        wheelchair_boarding TINYINT NULL,
        row_hash BINARY(32) NOT NULL,
        PRIMARY KEY CLUSTERED (stop_id)
    );

    INSERT INTO #source_stop (
        stop_id,
        stop_code,
        stop_name,
        stop_description,
        stop_latitude,
        stop_longitude,
        zone_id,
        stop_url,
        location_type,
        parent_station_id,
        wheelchair_boarding,
        row_hash
    )
    SELECT
        LTRIM(RTRIM(stop_id)),
        NULLIF(LTRIM(RTRIM(stop_code)), ''),
        LTRIM(RTRIM(stop_name)),
        NULLIF(LTRIM(RTRIM(stop_desc)), ''),
        TRY_CONVERT(DECIMAL(9, 6), stop_lat),
        TRY_CONVERT(DECIMAL(9, 6), stop_lon),
        NULLIF(LTRIM(RTRIM(zone_id)), ''),
        NULLIF(LTRIM(RTRIM(stop_url)), ''),
        TRY_CONVERT(TINYINT, NULLIF(LTRIM(RTRIM(location_type)), '')),
        NULLIF(LTRIM(RTRIM(parent_station)), ''),
        TRY_CONVERT(
            TINYINT,
            NULLIF(LTRIM(RTRIM(wheelchair_boarding)), '')
        ),
        row_hash
    FROM staging.gtfs_stops
    WHERE snapshot_key = @snapshot_key;

    SET @stop_rows_read = @@ROWCOUNT;

    UPDATE target
    SET
        valid_to_snapshot_key = @snapshot_key,
        is_current = 0,
        updated_at_utc = SYSUTCDATETIME()
    FROM warehouse.dim_stop AS target
    LEFT JOIN #source_stop AS source
        ON source.stop_id = target.stop_id
    WHERE
        target.is_current = 1
        AND (
            source.stop_id IS NULL
            OR source.row_hash <> target.row_hash
        );

    SET @stop_rows_closed = @@ROWCOUNT;

    INSERT INTO warehouse.dim_stop (
        stop_id,
        stop_code,
        stop_name,
        stop_description,
        stop_latitude,
        stop_longitude,
        zone_id,
        stop_url,
        location_type,
        parent_station_id,
        wheelchair_boarding,
        valid_from_snapshot_key,
        valid_to_snapshot_key,
        is_current,
        row_hash
    )
    SELECT
        source.stop_id,
        source.stop_code,
        source.stop_name,
        source.stop_description,
        source.stop_latitude,
        source.stop_longitude,
        source.zone_id,
        source.stop_url,
        source.location_type,
        source.parent_station_id,
        source.wheelchair_boarding,
        @snapshot_key,
        NULL,
        1,
        source.row_hash
    FROM #source_stop AS source
    LEFT JOIN warehouse.dim_stop AS current_version
        ON current_version.stop_id = source.stop_id
        AND current_version.is_current = 1
    WHERE current_version.stop_key IS NULL;

    SET @stop_rows_inserted = @@ROWCOUNT;

    SELECT
        @route_rows_read AS route_rows_read,
        @route_rows_inserted AS route_rows_inserted,
        @route_rows_closed AS route_rows_closed,
        @stop_rows_read AS stop_rows_read,
        @stop_rows_inserted AS stop_rows_inserted,
        @stop_rows_closed AS stop_rows_closed;
END;
