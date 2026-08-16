/*
Creates the core warehouse dimensions for dates and operators.

The operator dimension uses Type 2 history so changes between TfGM
publications can be preserved.

Prerequisites:
    001_create_schemas.sql
    002_create_governance_tables.sql
*/

SET NOCOUNT ON;
SET XACT_ABORT ON;

IF OBJECT_ID(N'warehouse.dim_date', N'U') IS NULL
BEGIN
    CREATE TABLE warehouse.dim_date (
        date_key INT NOT NULL,
        full_date DATE NOT NULL,
        calendar_year SMALLINT NOT NULL,
        calendar_quarter TINYINT NOT NULL,
        calendar_month TINYINT NOT NULL,
        month_name NVARCHAR(20) NOT NULL,
        day_of_month TINYINT NOT NULL,
        day_of_week_iso TINYINT NOT NULL,
        day_name NVARCHAR(20) NOT NULL,
        week_of_year TINYINT NOT NULL,
        is_weekend BIT NOT NULL,

        CONSTRAINT PK_dim_date
            PRIMARY KEY CLUSTERED (date_key),

        CONSTRAINT UQ_dim_date_full_date
            UNIQUE (full_date),

        CONSTRAINT CK_dim_date_quarter
            CHECK (calendar_quarter BETWEEN 1 AND 4),

        CONSTRAINT CK_dim_date_month
            CHECK (calendar_month BETWEEN 1 AND 12),

        CONSTRAINT CK_dim_date_day_of_month
            CHECK (day_of_month BETWEEN 1 AND 31),

        CONSTRAINT CK_dim_date_day_of_week
            CHECK (day_of_week_iso BETWEEN 1 AND 7),

        CONSTRAINT CK_dim_date_week
            CHECK (week_of_year BETWEEN 1 AND 53)
    );
END;

IF OBJECT_ID(N'warehouse.dim_operator', N'U') IS NULL
BEGIN
    CREATE TABLE warehouse.dim_operator (
        operator_key BIGINT IDENTITY(1, 1) NOT NULL,
        agency_id NVARCHAR(50) NOT NULL,
        agency_noc NVARCHAR(20) NULL,
        operator_name NVARCHAR(200) NOT NULL,
        operator_url NVARCHAR(1000) NULL,
        operator_timezone NVARCHAR(100) NULL,
        operator_language NVARCHAR(20) NULL,
        operator_phone NVARCHAR(100) NULL,
        operator_email NVARCHAR(320) NULL,
        valid_from_snapshot_key BIGINT NOT NULL,
        valid_to_snapshot_key BIGINT NULL,
        is_current BIT NOT NULL
            CONSTRAINT DF_dim_operator_is_current
            DEFAULT (1),
        row_hash BINARY(32) NOT NULL,
        created_at_utc DATETIME2(3) NOT NULL
            CONSTRAINT DF_dim_operator_created
            DEFAULT (SYSUTCDATETIME()),
        updated_at_utc DATETIME2(3) NOT NULL
            CONSTRAINT DF_dim_operator_updated
            DEFAULT (SYSUTCDATETIME()),

        CONSTRAINT PK_dim_operator
            PRIMARY KEY CLUSTERED (operator_key),

        CONSTRAINT FK_dim_operator_valid_from_snapshot
            FOREIGN KEY (valid_from_snapshot_key)
            REFERENCES governance.source_snapshot (snapshot_key),

        CONSTRAINT FK_dim_operator_valid_to_snapshot
            FOREIGN KEY (valid_to_snapshot_key)
            REFERENCES governance.source_snapshot (snapshot_key),

        CONSTRAINT CK_dim_operator_validity
            CHECK (
                valid_to_snapshot_key IS NULL
                OR valid_to_snapshot_key >= valid_from_snapshot_key
            ),

        CONSTRAINT CK_dim_operator_current
            CHECK (
                (
                    is_current = 1
                    AND valid_to_snapshot_key IS NULL
                )
                OR (
                    is_current = 0
                    AND valid_to_snapshot_key IS NOT NULL
                )
            )
    );
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE
        name = N'UX_dim_operator_current'
        AND object_id = OBJECT_ID(N'warehouse.dim_operator')
)
BEGIN
    CREATE UNIQUE INDEX UX_dim_operator_current
        ON warehouse.dim_operator (agency_id)
        WHERE is_current = 1;
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE
        name = N'IX_dim_operator_history'
        AND object_id = OBJECT_ID(N'warehouse.dim_operator')
)
BEGIN
    CREATE INDEX IX_dim_operator_history
        ON warehouse.dim_operator (
            agency_id,
            valid_from_snapshot_key
        )
        INCLUDE (
            valid_to_snapshot_key,
            is_current,
            operator_name
        );
END;

SELECT
    schema_name(schema_id) AS schema_name,
    name AS table_name
FROM sys.tables
WHERE
    schema_name(schema_id) = N'warehouse'
    AND name IN (
        N'dim_date',
        N'dim_operator'
    )
ORDER BY name;
