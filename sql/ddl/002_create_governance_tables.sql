/*
Creates the governance tables used for source lineage, pipeline
monitoring and data quality auditing.

Prerequisite:
    001_create_schemas.sql
*/

SET NOCOUNT ON;
SET XACT_ABORT ON;

IF OBJECT_ID(N'governance.source_snapshot', N'U') IS NULL
BEGIN
    CREATE TABLE governance.source_snapshot (
        snapshot_key BIGINT IDENTITY(1, 1) NOT NULL,
        source_name NVARCHAR(100) NOT NULL,
        source_url NVARCHAR(1000) NOT NULL,
        downloaded_at_utc DATETIME2(3) NOT NULL,
        source_last_modified_utc DATETIME2(0) NULL,
        source_etag NVARCHAR(200) NULL,
        file_name NVARCHAR(260) NOT NULL,
        file_size_bytes BIGINT NOT NULL,
        sha256 CHAR(64) NOT NULL,
        feed_start_date DATE NULL,
        feed_end_date DATE NULL,
        feed_version NVARCHAR(255) NULL,
        snapshot_status VARCHAR(20) NOT NULL
            CONSTRAINT DF_source_snapshot_status
            DEFAULT ('RECEIVED'),
        created_at_utc DATETIME2(3) NOT NULL
            CONSTRAINT DF_source_snapshot_created
            DEFAULT (SYSUTCDATETIME()),

        CONSTRAINT PK_source_snapshot
            PRIMARY KEY CLUSTERED (snapshot_key),

        CONSTRAINT UQ_source_snapshot_sha256
            UNIQUE (sha256),

        CONSTRAINT CK_source_snapshot_file_size
            CHECK (file_size_bytes > 0),

        CONSTRAINT CK_source_snapshot_status
            CHECK (
                snapshot_status IN (
                    'RECEIVED',
                    'VALIDATED',
                    'LOADED',
                    'REJECTED'
                )
            )
    );
END;

IF OBJECT_ID(N'governance.pipeline_run', N'U') IS NULL
BEGIN
    CREATE TABLE governance.pipeline_run (
        pipeline_run_key BIGINT IDENTITY(1, 1) NOT NULL,
        snapshot_key BIGINT NULL,
        pipeline_name NVARCHAR(200) NOT NULL,
        orchestrator NVARCHAR(100) NOT NULL,
        external_run_id NVARCHAR(255) NULL,
        run_status VARCHAR(20) NOT NULL,
        started_at_utc DATETIME2(3) NOT NULL,
        completed_at_utc DATETIME2(3) NULL,
        rows_read BIGINT NOT NULL
            CONSTRAINT DF_pipeline_run_rows_read
            DEFAULT (0),
        rows_loaded BIGINT NOT NULL
            CONSTRAINT DF_pipeline_run_rows_loaded
            DEFAULT (0),
        rows_rejected BIGINT NOT NULL
            CONSTRAINT DF_pipeline_run_rows_rejected
            DEFAULT (0),
        error_message NVARCHAR(4000) NULL,
        created_at_utc DATETIME2(3) NOT NULL
            CONSTRAINT DF_pipeline_run_created
            DEFAULT (SYSUTCDATETIME()),

        CONSTRAINT PK_pipeline_run
            PRIMARY KEY CLUSTERED (pipeline_run_key),

        CONSTRAINT FK_pipeline_run_snapshot
            FOREIGN KEY (snapshot_key)
            REFERENCES governance.source_snapshot (snapshot_key),

        CONSTRAINT CK_pipeline_run_status
            CHECK (
                run_status IN (
                    'STARTED',
                    'SUCCEEDED',
                    'FAILED',
                    'PARTIAL',
                    'CANCELLED'
                )
            ),

        CONSTRAINT CK_pipeline_run_timestamps
            CHECK (
                completed_at_utc IS NULL
                OR completed_at_utc >= started_at_utc
            ),

        CONSTRAINT CK_pipeline_run_counts
            CHECK (
                rows_read >= 0
                AND rows_loaded >= 0
                AND rows_rejected >= 0
            )
    );
END;

IF OBJECT_ID(N'governance.data_quality_result', N'U') IS NULL
BEGIN
    CREATE TABLE governance.data_quality_result (
        data_quality_result_key BIGINT IDENTITY(1, 1) NOT NULL,
        pipeline_run_key BIGINT NOT NULL,
        snapshot_key BIGINT NOT NULL,
        check_name NVARCHAR(200) NOT NULL,
        check_category NVARCHAR(100) NOT NULL,
        table_name NVARCHAR(128) NULL,
        check_status VARCHAR(10) NOT NULL,
        records_checked BIGINT NOT NULL
            CONSTRAINT DF_data_quality_records_checked
            DEFAULT (0),
        failed_records BIGINT NOT NULL
            CONSTRAINT DF_data_quality_failed_records
            DEFAULT (0),
        threshold_value DECIMAL(18, 6) NULL,
        observed_value DECIMAL(18, 6) NULL,
        details NVARCHAR(4000) NULL,
        checked_at_utc DATETIME2(3) NOT NULL
            CONSTRAINT DF_data_quality_checked
            DEFAULT (SYSUTCDATETIME()),

        CONSTRAINT PK_data_quality_result
            PRIMARY KEY CLUSTERED (data_quality_result_key),

        CONSTRAINT FK_data_quality_pipeline_run
            FOREIGN KEY (pipeline_run_key)
            REFERENCES governance.pipeline_run (pipeline_run_key),

        CONSTRAINT FK_data_quality_snapshot
            FOREIGN KEY (snapshot_key)
            REFERENCES governance.source_snapshot (snapshot_key),

        CONSTRAINT CK_data_quality_status
            CHECK (check_status IN ('PASS', 'WARN', 'FAIL')),

        CONSTRAINT CK_data_quality_counts
            CHECK (
                records_checked >= 0
                AND failed_records >= 0
                AND failed_records <= records_checked
            )
    );
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE
        name = N'IX_source_snapshot_downloaded_at'
        AND object_id = OBJECT_ID(
            N'governance.source_snapshot'
        )
)
BEGIN
    CREATE INDEX IX_source_snapshot_downloaded_at
        ON governance.source_snapshot (downloaded_at_utc DESC);
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE
        name = N'IX_pipeline_run_snapshot'
        AND object_id = OBJECT_ID(N'governance.pipeline_run')
)
BEGIN
    CREATE INDEX IX_pipeline_run_snapshot
        ON governance.pipeline_run (
            snapshot_key,
            started_at_utc DESC
        );
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE
        name = N'IX_pipeline_run_status'
        AND object_id = OBJECT_ID(N'governance.pipeline_run')
)
BEGIN
    CREATE INDEX IX_pipeline_run_status
        ON governance.pipeline_run (
            run_status,
            started_at_utc DESC
        );
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE
        name = N'IX_data_quality_run_status'
        AND object_id = OBJECT_ID(
            N'governance.data_quality_result'
        )
)
BEGIN
    CREATE INDEX IX_data_quality_run_status
        ON governance.data_quality_result (
            pipeline_run_key,
            check_status
        );
END;

SELECT
    schema_name(schema_id) AS schema_name,
    name AS table_name
FROM sys.tables
WHERE schema_name(schema_id) = N'governance'
ORDER BY name;
