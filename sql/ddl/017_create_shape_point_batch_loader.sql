/*
Creates the bounded batch procedure for geographical shape points.

Source validation is defined separately because each CREATE OR ALTER
PROCEDURE statement must be executed in its own SQL Server batch.

Prerequisites:
    005_create_staging_high_volume_tables.sql
    009_create_warehouse_schedule_tables.sql
    016_create_shape_point_loader.sql
*/

CREATE OR ALTER PROCEDURE warehouse.load_shape_point_batch
    @snapshot_key BIGINT,
    @after_source_row_number BIGINT,
    @batch_size INT
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    DECLARE @batch_rows_read BIGINT;
    DECLARE @batch_rows_inserted BIGINT;
    DECLARE @last_source_row_number BIGINT;

    IF @after_source_row_number < 0
    BEGIN
        THROW 50406, 'The source row cursor cannot be negative.', 1;
    END;

    IF @batch_size < 1 OR @batch_size > 100000
    BEGIN
        THROW 50407, 'The shape point batch size must be between 1 and 100000.', 1;
    END;

    CREATE TABLE #source_shape_point (
        source_row_number BIGINT NOT NULL,
        shape_id NVARCHAR(50) NOT NULL,
        shape_point_sequence INT NOT NULL,
        shape_point_latitude DECIMAL(9, 6) NOT NULL,
        shape_point_longitude DECIMAL(9, 6) NOT NULL,
        shape_dist_travelled DECIMAL(18, 3) NULL,
        PRIMARY KEY CLUSTERED (
            shape_id,
            shape_point_sequence
        )
    );

    INSERT INTO #source_shape_point (
        source_row_number,
        shape_id,
        shape_point_sequence,
        shape_point_latitude,
        shape_point_longitude,
        shape_dist_travelled
    )
    SELECT TOP (@batch_size)
        source_row_number,
        LTRIM(RTRIM(shape_id)),
        TRY_CONVERT(INT, shape_pt_sequence),
        TRY_CONVERT(DECIMAL(9, 6), shape_pt_lat),
        TRY_CONVERT(DECIMAL(9, 6), shape_pt_lon),
        TRY_CONVERT(
            DECIMAL(18, 3),
            NULLIF(LTRIM(RTRIM(shape_dist_traveled)), '')
        )
    FROM staging.gtfs_shapes
    WHERE
        snapshot_key = @snapshot_key
        AND source_row_number > @after_source_row_number
    ORDER BY source_row_number;

    SET @batch_rows_read = @@ROWCOUNT;

    SELECT
        @last_source_row_number = MAX(source_row_number)
    FROM #source_shape_point;

    IF EXISTS (
        SELECT 1
        FROM #source_shape_point AS source
        INNER JOIN warehouse.shape_point AS target
            ON target.snapshot_key = @snapshot_key
            AND target.shape_id = source.shape_id
            AND target.shape_point_sequence = source.shape_point_sequence
        WHERE
            target.shape_point_latitude <> source.shape_point_latitude
            OR target.shape_point_longitude <> source.shape_point_longitude
            OR (
                target.shape_dist_travelled <> source.shape_dist_travelled
                OR (
                    target.shape_dist_travelled IS NULL
                    AND source.shape_dist_travelled IS NOT NULL
                )
                OR (
                    target.shape_dist_travelled IS NOT NULL
                    AND source.shape_dist_travelled IS NULL
                )
            )
    )
    BEGIN
        THROW 50408, 'Existing shape points conflict with the staged snapshot.', 1;
    END;

    INSERT INTO warehouse.shape_point (
        snapshot_key,
        shape_id,
        shape_point_sequence,
        shape_point_latitude,
        shape_point_longitude,
        shape_dist_travelled
    )
    SELECT
        @snapshot_key,
        source.shape_id,
        source.shape_point_sequence,
        source.shape_point_latitude,
        source.shape_point_longitude,
        source.shape_dist_travelled
    FROM #source_shape_point AS source
    LEFT JOIN warehouse.shape_point AS target
        ON target.snapshot_key = @snapshot_key
        AND target.shape_id = source.shape_id
        AND target.shape_point_sequence = source.shape_point_sequence
    WHERE target.shape_id IS NULL;

    SET @batch_rows_inserted = @@ROWCOUNT;

    SELECT
        @batch_rows_read AS batch_rows_read,
        @batch_rows_inserted AS batch_rows_inserted,
        COALESCE(
            @last_source_row_number,
            @after_source_row_number
        ) AS last_source_row_number;
END;
