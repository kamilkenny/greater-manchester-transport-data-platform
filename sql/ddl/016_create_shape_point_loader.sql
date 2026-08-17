/*
Creates validation and bounded batch procedures for geographical shape points.

The source is validated once, then transformed in resumable transactions to
control memory and transaction log pressure on local SQL Server.

Prerequisites:
    002_create_governance_tables.sql
    005_create_staging_high_volume_tables.sql
    009_create_warehouse_schedule_tables.sql
*/

CREATE OR ALTER PROCEDURE warehouse.validate_shape_point_source
    @snapshot_key BIGINT
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    DECLARE @source_rows BIGINT;

    IF NOT EXISTS (
        SELECT 1
        FROM governance.source_snapshot
        WHERE
            snapshot_key = @snapshot_key
            AND snapshot_status = 'LOADED'
    )
    BEGIN
        THROW 50401, 'The snapshot must exist and have LOADED status.', 1;
    END;

    IF NOT EXISTS (
        SELECT 1
        FROM governance.pipeline_run
        WHERE
            snapshot_key = @snapshot_key
            AND pipeline_name = 'load_gtfs_high_volume_staging'
            AND run_status = 'SUCCEEDED'
    )
    BEGIN
        THROW 50402, 'The high volume staging load must succeed first.', 1;
    END;

    SELECT
        @source_rows = COUNT_BIG(*)
    FROM staging.gtfs_shapes
    WHERE snapshot_key = @snapshot_key;

    IF @source_rows = 0
    BEGIN
        THROW 50403, 'The snapshot has no staged shape point records.', 1;
    END;

    IF EXISTS (
        SELECT 1
        FROM staging.gtfs_shapes
        WHERE
            snapshot_key = @snapshot_key
            AND (
                NULLIF(LTRIM(RTRIM(shape_id)), '') IS NULL
                OR TRY_CONVERT(DECIMAL(9, 6), shape_pt_lat) IS NULL
                OR TRY_CONVERT(DECIMAL(9, 6), shape_pt_lon) IS NULL
                OR TRY_CONVERT(INT, shape_pt_sequence) IS NULL
                OR TRY_CONVERT(INT, shape_pt_sequence) < 0
                OR TRY_CONVERT(DECIMAL(9, 6), shape_pt_lat)
                    NOT BETWEEN -90 AND 90
                OR TRY_CONVERT(DECIMAL(9, 6), shape_pt_lon)
                    NOT BETWEEN -180 AND 180
                OR (
                    NULLIF(LTRIM(RTRIM(shape_dist_traveled)), '') IS NOT NULL
                    AND (
                        TRY_CONVERT(
                            DECIMAL(18, 3),
                            shape_dist_traveled
                        ) IS NULL
                        OR TRY_CONVERT(
                            DECIMAL(18, 3),
                            shape_dist_traveled
                        ) < 0
                    )
                )
            )
    )
    BEGIN
        THROW 50404, 'A shape point contains an invalid required value.', 1;
    END;

    IF EXISTS (
        SELECT 1
        FROM staging.gtfs_shapes
        WHERE snapshot_key = @snapshot_key
        GROUP BY
            LTRIM(RTRIM(shape_id)),
            TRY_CONVERT(INT, shape_pt_sequence)
        HAVING COUNT_BIG(*) > 1
    )
    BEGIN
        THROW 50405, 'The snapshot contains duplicate shape point keys.', 1;
    END;

    SELECT @source_rows AS source_rows;
END;
