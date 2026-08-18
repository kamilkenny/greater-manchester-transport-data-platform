/*
Detects entity changes between successive loaded GTFS publications.

The first warehouse snapshot is a valid bootstrap case and produces no
change rows. Later snapshots are compared with the most recent earlier
snapshot whose entity dimensions completed successfully.

Prerequisites:
    001_create_schemas.sql
    002_create_governance_tables.sql
    006_create_warehouse_core_dimensions.sql
    007_create_warehouse_network_dimensions.sql
    008_create_warehouse_service_dimensions.sql
    011_create_publication_change_fact.sql
    012_create_core_dimension_loader.sql
    013_create_network_dimension_loader.sql
    014_create_service_calendar_loader.sql
    015_create_trip_dimension_loader.sql
*/

CREATE OR ALTER PROCEDURE warehouse.load_publication_changes
    @current_snapshot_key BIGINT,
    @previous_snapshot_key BIGINT = NULL
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    DECLARE @previous_entity_rows BIGINT = 0;
    DECLARE @current_entity_rows BIGINT = 0;
    DECLARE @changes_detected BIGINT = 0;
    DECLARE @changes_inserted BIGINT = 0;
    DECLARE @added_changes BIGINT = 0;
    DECLARE @removed_changes BIGINT = 0;
    DECLARE @modified_changes BIGINT = 0;

    IF NOT EXISTS (
        SELECT 1
        FROM governance.source_snapshot
        WHERE
            snapshot_key = @current_snapshot_key
            AND snapshot_status = 'LOADED'
    )
    BEGIN
        THROW 50701, 'The current snapshot must exist and have LOADED status.', 1;
    END;

    IF (
        SELECT COUNT(DISTINCT pipeline_name)
        FROM governance.pipeline_run
        WHERE
            snapshot_key = @current_snapshot_key
            AND run_status = 'SUCCEEDED'
            AND pipeline_name IN (
                'load_gtfs_core_warehouse',
                'load_gtfs_network_warehouse',
                'load_gtfs_service_warehouse',
                'load_gtfs_trip_warehouse'
            )
    ) < 4
    BEGIN
        THROW 50702, 'The current snapshot entity warehouse is incomplete.', 1;
    END;

    IF @previous_snapshot_key IS NULL
    BEGIN
        SELECT TOP (1)
            @previous_snapshot_key = candidate.snapshot_key
        FROM governance.source_snapshot AS candidate
        WHERE
            candidate.snapshot_key < @current_snapshot_key
            AND candidate.snapshot_status = 'LOADED'
            AND (
                SELECT COUNT(DISTINCT run.pipeline_name)
                FROM governance.pipeline_run AS run
                WHERE
                    run.snapshot_key = candidate.snapshot_key
                    AND run.run_status = 'SUCCEEDED'
                    AND run.pipeline_name IN (
                        'load_gtfs_core_warehouse',
                        'load_gtfs_network_warehouse',
                        'load_gtfs_service_warehouse',
                        'load_gtfs_trip_warehouse'
                    )
            ) = 4
        ORDER BY
            candidate.downloaded_at_utc DESC,
            candidate.snapshot_key DESC;
    END;

    IF @previous_snapshot_key IS NULL
    BEGIN
        SELECT
            @current_entity_rows =
                (SELECT COUNT_BIG(*)
                 FROM warehouse.dim_operator
                 WHERE
                     valid_from_snapshot_key <= @current_snapshot_key
                     AND (
                         valid_to_snapshot_key IS NULL
                         OR valid_to_snapshot_key > @current_snapshot_key
                     ))
                + (SELECT COUNT_BIG(*)
                   FROM warehouse.dim_route
                   WHERE
                       valid_from_snapshot_key <= @current_snapshot_key
                       AND (
                           valid_to_snapshot_key IS NULL
                           OR valid_to_snapshot_key > @current_snapshot_key
                       ))
                + (SELECT COUNT_BIG(*)
                   FROM warehouse.dim_stop
                   WHERE
                       valid_from_snapshot_key <= @current_snapshot_key
                       AND (
                           valid_to_snapshot_key IS NULL
                           OR valid_to_snapshot_key > @current_snapshot_key
                       ))
                + (SELECT COUNT_BIG(*)
                   FROM warehouse.dim_service
                   WHERE snapshot_key = @current_snapshot_key)
                + (SELECT COUNT_BIG(*)
                   FROM warehouse.dim_trip
                   WHERE snapshot_key = @current_snapshot_key);

        SELECT
            CAST(NULL AS BIGINT) AS previous_snapshot_key,
            @current_snapshot_key AS current_snapshot_key,
            @previous_entity_rows AS previous_entity_rows,
            @current_entity_rows AS current_entity_rows,
            @changes_detected AS changes_detected,
            @changes_inserted AS changes_inserted,
            @added_changes AS added_changes,
            @removed_changes AS removed_changes,
            @modified_changes AS modified_changes;
        RETURN;
    END;

    IF
        @previous_snapshot_key >= @current_snapshot_key
        OR NOT EXISTS (
            SELECT 1
            FROM governance.source_snapshot
            WHERE
                snapshot_key = @previous_snapshot_key
                AND snapshot_status = 'LOADED'
        )
    BEGIN
        THROW 50703, 'The previous snapshot must be an earlier LOADED snapshot.', 1;
    END;

    IF (
        SELECT COUNT(DISTINCT pipeline_name)
        FROM governance.pipeline_run
        WHERE
            snapshot_key = @previous_snapshot_key
            AND run_status = 'SUCCEEDED'
            AND pipeline_name IN (
                'load_gtfs_core_warehouse',
                'load_gtfs_network_warehouse',
                'load_gtfs_service_warehouse',
                'load_gtfs_trip_warehouse'
            )
    ) < 4
    BEGIN
        THROW 50704, 'The previous snapshot entity warehouse is incomplete.', 1;
    END;

    CREATE TABLE #previous_entity (
        entity_type VARCHAR(20) NOT NULL,
        entity_id NVARCHAR(100) NOT NULL,
        row_hash BINARY(32) NOT NULL,
        PRIMARY KEY CLUSTERED (entity_type, entity_id)
    );

    CREATE TABLE #current_entity (
        entity_type VARCHAR(20) NOT NULL,
        entity_id NVARCHAR(100) NOT NULL,
        row_hash BINARY(32) NOT NULL,
        PRIMARY KEY CLUSTERED (entity_type, entity_id)
    );

    INSERT INTO #previous_entity (entity_type, entity_id, row_hash)
    SELECT 'OPERATOR', agency_id, row_hash
    FROM warehouse.dim_operator
    WHERE
        valid_from_snapshot_key <= @previous_snapshot_key
        AND (
            valid_to_snapshot_key IS NULL
            OR valid_to_snapshot_key > @previous_snapshot_key
        )
    UNION ALL
    SELECT 'ROUTE', route_id, row_hash
    FROM warehouse.dim_route
    WHERE
        valid_from_snapshot_key <= @previous_snapshot_key
        AND (
            valid_to_snapshot_key IS NULL
            OR valid_to_snapshot_key > @previous_snapshot_key
        )
    UNION ALL
    SELECT 'STOP', stop_id, row_hash
    FROM warehouse.dim_stop
    WHERE
        valid_from_snapshot_key <= @previous_snapshot_key
        AND (
            valid_to_snapshot_key IS NULL
            OR valid_to_snapshot_key > @previous_snapshot_key
        )
    UNION ALL
    SELECT 'SERVICE', service_id, row_hash
    FROM warehouse.dim_service
    WHERE snapshot_key = @previous_snapshot_key
    UNION ALL
    SELECT 'TRIP', trip_id, row_hash
    FROM warehouse.dim_trip
    WHERE snapshot_key = @previous_snapshot_key;

    SET @previous_entity_rows = @@ROWCOUNT;

    INSERT INTO #current_entity (entity_type, entity_id, row_hash)
    SELECT 'OPERATOR', agency_id, row_hash
    FROM warehouse.dim_operator
    WHERE
        valid_from_snapshot_key <= @current_snapshot_key
        AND (
            valid_to_snapshot_key IS NULL
            OR valid_to_snapshot_key > @current_snapshot_key
        )
    UNION ALL
    SELECT 'ROUTE', route_id, row_hash
    FROM warehouse.dim_route
    WHERE
        valid_from_snapshot_key <= @current_snapshot_key
        AND (
            valid_to_snapshot_key IS NULL
            OR valid_to_snapshot_key > @current_snapshot_key
        )
    UNION ALL
    SELECT 'STOP', stop_id, row_hash
    FROM warehouse.dim_stop
    WHERE
        valid_from_snapshot_key <= @current_snapshot_key
        AND (
            valid_to_snapshot_key IS NULL
            OR valid_to_snapshot_key > @current_snapshot_key
        )
    UNION ALL
    SELECT 'SERVICE', service_id, row_hash
    FROM warehouse.dim_service
    WHERE snapshot_key = @current_snapshot_key
    UNION ALL
    SELECT 'TRIP', trip_id, row_hash
    FROM warehouse.dim_trip
    WHERE snapshot_key = @current_snapshot_key;

    SET @current_entity_rows = @@ROWCOUNT;

    CREATE TABLE #detected_change (
        entity_type VARCHAR(20) NOT NULL,
        entity_id NVARCHAR(100) NOT NULL,
        change_type VARCHAR(10) NOT NULL,
        previous_row_hash BINARY(32) NULL,
        current_row_hash BINARY(32) NULL,
        PRIMARY KEY CLUSTERED (entity_type, entity_id)
    );

    INSERT INTO #detected_change (
        entity_type,
        entity_id,
        change_type,
        previous_row_hash,
        current_row_hash
    )
    SELECT
        COALESCE(current_entity.entity_type, previous_entity.entity_type),
        COALESCE(current_entity.entity_id, previous_entity.entity_id),
        CASE
            WHEN previous_entity.entity_id IS NULL THEN 'ADDED'
            WHEN current_entity.entity_id IS NULL THEN 'REMOVED'
            ELSE 'MODIFIED'
        END,
        previous_entity.row_hash,
        current_entity.row_hash
    FROM #previous_entity AS previous_entity
    FULL OUTER JOIN #current_entity AS current_entity
        ON current_entity.entity_type = previous_entity.entity_type
        AND current_entity.entity_id = previous_entity.entity_id
    WHERE
        previous_entity.entity_id IS NULL
        OR current_entity.entity_id IS NULL
        OR previous_entity.row_hash <> current_entity.row_hash;

    SET @changes_detected = @@ROWCOUNT;

    SELECT
        @added_changes = COALESCE(SUM(
            CASE WHEN change_type = 'ADDED' THEN 1 ELSE 0 END
        ), 0),
        @removed_changes = COALESCE(SUM(
            CASE WHEN change_type = 'REMOVED' THEN 1 ELSE 0 END
        ), 0),
        @modified_changes = COALESCE(SUM(
            CASE WHEN change_type = 'MODIFIED' THEN 1 ELSE 0 END
        ), 0)
    FROM #detected_change;

    BEGIN TRY
        BEGIN TRANSACTION;

        IF EXISTS (
            SELECT 1
            FROM warehouse.fact_publication_change AS existing
            LEFT JOIN #detected_change AS detected
                ON detected.entity_type = existing.entity_type
                AND detected.entity_id = existing.entity_id
            WHERE
                existing.previous_snapshot_key = @previous_snapshot_key
                AND existing.current_snapshot_key = @current_snapshot_key
                AND (
                    detected.entity_id IS NULL
                    OR detected.change_type <> existing.change_type
                    OR ISNULL(detected.previous_row_hash, 0x)
                        <> ISNULL(existing.previous_row_hash, 0x)
                    OR ISNULL(detected.current_row_hash, 0x)
                        <> ISNULL(existing.current_row_hash, 0x)
                )
        )
        BEGIN
            THROW 50705, 'Existing publication changes conflict with the warehouse.', 1;
        END;

        INSERT INTO warehouse.fact_publication_change (
            previous_snapshot_key,
            current_snapshot_key,
            entity_type,
            entity_id,
            change_type,
            changed_fields,
            previous_row_hash,
            current_row_hash,
            change_details_json
        )
        SELECT
            @previous_snapshot_key,
            @current_snapshot_key,
            detected.entity_type,
            detected.entity_id,
            detected.change_type,
            CASE
                WHEN detected.change_type = 'MODIFIED'
                THEN 'published_attributes'
                ELSE NULL
            END,
            detected.previous_row_hash,
            detected.current_row_hash,
            NULL
        FROM #detected_change AS detected
        LEFT JOIN warehouse.fact_publication_change AS existing
            ON existing.previous_snapshot_key = @previous_snapshot_key
            AND existing.current_snapshot_key = @current_snapshot_key
            AND existing.entity_type = detected.entity_type
            AND existing.entity_id = detected.entity_id
        WHERE existing.publication_change_key IS NULL;

        SET @changes_inserted = @@ROWCOUNT;

        COMMIT TRANSACTION;
    END TRY
    BEGIN CATCH
        IF XACT_STATE() <> 0
        BEGIN
            ROLLBACK TRANSACTION;
        END;
        THROW;
    END CATCH;

    SELECT
        @previous_snapshot_key AS previous_snapshot_key,
        @current_snapshot_key AS current_snapshot_key,
        @previous_entity_rows AS previous_entity_rows,
        @current_entity_rows AS current_entity_rows,
        @changes_detected AS changes_detected,
        @changes_inserted AS changes_inserted,
        @added_changes AS added_changes,
        @removed_changes AS removed_changes,
        @modified_changes AS modified_changes;
END;
