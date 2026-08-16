/*
Creates the warehouse route and stop dimensions.

Both dimensions use Type 2 history so changes between TfGM
publications remain available for comparison.

Prerequisites:
    001_create_schemas.sql
    002_create_governance_tables.sql
    006_create_warehouse_core_dimensions.sql
*/

SET NOCOUNT ON;
SET XACT_ABORT ON;

IF OBJECT_ID(N'warehouse.dim_route', N'U') IS NULL
BEGIN
    CREATE TABLE warehouse.dim_route (
        route_key BIGINT IDENTITY(1, 1) NOT NULL,
        route_id NVARCHAR(50) NOT NULL,
        operator_key BIGINT NOT NULL,
        route_short_name NVARCHAR(100) NULL,
        route_long_name NVARCHAR(300) NULL,
        route_description NVARCHAR(1000) NULL,
        route_type SMALLINT NOT NULL,
        route_url NVARCHAR(1000) NULL,
        route_colour CHAR(6) NULL,
        route_text_colour CHAR(6) NULL,
        valid_from_snapshot_key BIGINT NOT NULL,
        valid_to_snapshot_key BIGINT NULL,
        is_current BIT NOT NULL
            CONSTRAINT DF_dim_route_is_current
            DEFAULT (1),
        row_hash BINARY(32) NOT NULL,
        created_at_utc DATETIME2(3) NOT NULL
            CONSTRAINT DF_dim_route_created
            DEFAULT (SYSUTCDATETIME()),
        updated_at_utc DATETIME2(3) NOT NULL
            CONSTRAINT DF_dim_route_updated
            DEFAULT (SYSUTCDATETIME()),

        CONSTRAINT PK_dim_route
            PRIMARY KEY CLUSTERED (route_key),

        CONSTRAINT FK_dim_route_operator
            FOREIGN KEY (operator_key)
            REFERENCES warehouse.dim_operator (operator_key),

        CONSTRAINT FK_dim_route_valid_from_snapshot
            FOREIGN KEY (valid_from_snapshot_key)
            REFERENCES governance.source_snapshot (snapshot_key),

        CONSTRAINT FK_dim_route_valid_to_snapshot
            FOREIGN KEY (valid_to_snapshot_key)
            REFERENCES governance.source_snapshot (snapshot_key),

        CONSTRAINT CK_dim_route_type
            CHECK (route_type >= 0),

        CONSTRAINT CK_dim_route_validity
            CHECK (
                valid_to_snapshot_key IS NULL
                OR valid_to_snapshot_key >= valid_from_snapshot_key
            ),

        CONSTRAINT CK_dim_route_current
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

IF OBJECT_ID(N'warehouse.dim_stop', N'U') IS NULL
BEGIN
    CREATE TABLE warehouse.dim_stop (
        stop_key BIGINT IDENTITY(1, 1) NOT NULL,
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
        valid_from_snapshot_key BIGINT NOT NULL,
        valid_to_snapshot_key BIGINT NULL,
        is_current BIT NOT NULL
            CONSTRAINT DF_dim_stop_is_current
            DEFAULT (1),
        row_hash BINARY(32) NOT NULL,
        created_at_utc DATETIME2(3) NOT NULL
            CONSTRAINT DF_dim_stop_created
            DEFAULT (SYSUTCDATETIME()),
        updated_at_utc DATETIME2(3) NOT NULL
            CONSTRAINT DF_dim_stop_updated
            DEFAULT (SYSUTCDATETIME()),

        CONSTRAINT PK_dim_stop
            PRIMARY KEY CLUSTERED (stop_key),

        CONSTRAINT FK_dim_stop_valid_from_snapshot
            FOREIGN KEY (valid_from_snapshot_key)
            REFERENCES governance.source_snapshot (snapshot_key),

        CONSTRAINT FK_dim_stop_valid_to_snapshot
            FOREIGN KEY (valid_to_snapshot_key)
            REFERENCES governance.source_snapshot (snapshot_key),

        CONSTRAINT CK_dim_stop_latitude
            CHECK (stop_latitude BETWEEN -90 AND 90),

        CONSTRAINT CK_dim_stop_longitude
            CHECK (stop_longitude BETWEEN -180 AND 180),

        CONSTRAINT CK_dim_stop_location_type
            CHECK (
                location_type IS NULL
                OR location_type BETWEEN 0 AND 4
            ),

        CONSTRAINT CK_dim_stop_wheelchair
            CHECK (
                wheelchair_boarding IS NULL
                OR wheelchair_boarding BETWEEN 0 AND 2
            ),

        CONSTRAINT CK_dim_stop_validity
            CHECK (
                valid_to_snapshot_key IS NULL
                OR valid_to_snapshot_key >= valid_from_snapshot_key
            ),

        CONSTRAINT CK_dim_stop_current
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
        name = N'UX_dim_route_current'
        AND object_id = OBJECT_ID(N'warehouse.dim_route')
)
BEGIN
    CREATE UNIQUE INDEX UX_dim_route_current
        ON warehouse.dim_route (route_id)
        WHERE is_current = 1;
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE
        name = N'IX_dim_route_operator'
        AND object_id = OBJECT_ID(N'warehouse.dim_route')
)
BEGIN
    CREATE INDEX IX_dim_route_operator
        ON warehouse.dim_route (
            operator_key,
            is_current
        )
        INCLUDE (
            route_id,
            route_short_name,
            route_long_name,
            route_type
        );
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE
        name = N'IX_dim_route_history'
        AND object_id = OBJECT_ID(N'warehouse.dim_route')
)
BEGIN
    CREATE INDEX IX_dim_route_history
        ON warehouse.dim_route (
            route_id,
            valid_from_snapshot_key
        )
        INCLUDE (
            valid_to_snapshot_key,
            is_current
        );
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE
        name = N'UX_dim_stop_current'
        AND object_id = OBJECT_ID(N'warehouse.dim_stop')
)
BEGIN
    CREATE UNIQUE INDEX UX_dim_stop_current
        ON warehouse.dim_stop (stop_id)
        WHERE is_current = 1;
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE
        name = N'IX_dim_stop_code_current'
        AND object_id = OBJECT_ID(N'warehouse.dim_stop')
)
BEGIN
    CREATE INDEX IX_dim_stop_code_current
        ON warehouse.dim_stop (
            stop_code,
            is_current
        )
        INCLUDE (
            stop_id,
            stop_name,
            stop_latitude,
            stop_longitude
        );
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE
        name = N'IX_dim_stop_history'
        AND object_id = OBJECT_ID(N'warehouse.dim_stop')
)
BEGIN
    CREATE INDEX IX_dim_stop_history
        ON warehouse.dim_stop (
            stop_id,
            valid_from_snapshot_key
        )
        INCLUDE (
            valid_to_snapshot_key,
            is_current,
            stop_name
        );
END;

SELECT
    schema_name(schema_id) AS schema_name,
    name AS table_name
FROM sys.tables
WHERE
    schema_name(schema_id) = N'warehouse'
    AND name IN (
        N'dim_route',
        N'dim_stop'
    )
ORDER BY name;
