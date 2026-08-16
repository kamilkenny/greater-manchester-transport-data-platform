/*
Creates the warehouse service and trip dimensions.

These dimensions are snapshot specific because timetable services
and trips can be regenerated with each TfGM publication.

Prerequisites:
    001_create_schemas.sql
    002_create_governance_tables.sql
    006_create_warehouse_core_dimensions.sql
    007_create_warehouse_network_dimensions.sql
*/

SET NOCOUNT ON;
SET XACT_ABORT ON;

IF OBJECT_ID(N'warehouse.dim_service', N'U') IS NULL
BEGIN
    CREATE TABLE warehouse.dim_service (
        service_key BIGINT IDENTITY(1, 1) NOT NULL,
        snapshot_key BIGINT NOT NULL,
        service_id NVARCHAR(50) NOT NULL,
        monday BIT NOT NULL,
        tuesday BIT NOT NULL,
        wednesday BIT NOT NULL,
        thursday BIT NOT NULL,
        friday BIT NOT NULL,
        saturday BIT NOT NULL,
        sunday BIT NOT NULL,
        start_date DATE NOT NULL,
        end_date DATE NOT NULL,
        row_hash BINARY(32) NOT NULL,
        created_at_utc DATETIME2(3) NOT NULL
            CONSTRAINT DF_dim_service_created
            DEFAULT (SYSUTCDATETIME()),

        CONSTRAINT PK_dim_service
            PRIMARY KEY CLUSTERED (service_key),

        CONSTRAINT UQ_dim_service_snapshot
            UNIQUE (
                snapshot_key,
                service_id
            ),

        CONSTRAINT FK_dim_service_snapshot
            FOREIGN KEY (snapshot_key)
            REFERENCES governance.source_snapshot (snapshot_key),

        CONSTRAINT CK_dim_service_dates
            CHECK (end_date >= start_date)
    );
END;

IF OBJECT_ID(N'warehouse.dim_trip', N'U') IS NULL
BEGIN
    CREATE TABLE warehouse.dim_trip (
        trip_key BIGINT IDENTITY(1, 1) NOT NULL,
        snapshot_key BIGINT NOT NULL,
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
        created_at_utc DATETIME2(3) NOT NULL
            CONSTRAINT DF_dim_trip_created
            DEFAULT (SYSUTCDATETIME()),

        CONSTRAINT PK_dim_trip
            PRIMARY KEY CLUSTERED (trip_key),

        CONSTRAINT UQ_dim_trip_snapshot
            UNIQUE (
                snapshot_key,
                trip_id
            ),

        CONSTRAINT FK_dim_trip_snapshot
            FOREIGN KEY (snapshot_key)
            REFERENCES governance.source_snapshot (snapshot_key),

        CONSTRAINT FK_dim_trip_route
            FOREIGN KEY (route_key)
            REFERENCES warehouse.dim_route (route_key),

        CONSTRAINT FK_dim_trip_service
            FOREIGN KEY (service_key)
            REFERENCES warehouse.dim_service (service_key),

        CONSTRAINT CK_dim_trip_direction
            CHECK (
                direction_id IS NULL
                OR direction_id BETWEEN 0 AND 1
            ),

        CONSTRAINT CK_dim_trip_wheelchair
            CHECK (
                wheelchair_accessible IS NULL
                OR wheelchair_accessible BETWEEN 0 AND 2
            )
    );
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE
        name = N'IX_dim_service_business_key'
        AND object_id = OBJECT_ID(N'warehouse.dim_service')
)
BEGIN
    CREATE INDEX IX_dim_service_business_key
        ON warehouse.dim_service (
            service_id,
            snapshot_key
        )
        INCLUDE (
            start_date,
            end_date
        );
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE
        name = N'IX_dim_service_date_range'
        AND object_id = OBJECT_ID(N'warehouse.dim_service')
)
BEGIN
    CREATE INDEX IX_dim_service_date_range
        ON warehouse.dim_service (
            snapshot_key,
            start_date,
            end_date
        )
        INCLUDE (service_id);
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE
        name = N'IX_dim_trip_route_service'
        AND object_id = OBJECT_ID(N'warehouse.dim_trip')
)
BEGIN
    CREATE INDEX IX_dim_trip_route_service
        ON warehouse.dim_trip (
            snapshot_key,
            route_key,
            service_key
        )
        INCLUDE (
            trip_id,
            direction_id,
            shape_id
        );
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE
        name = N'IX_dim_trip_shape'
        AND object_id = OBJECT_ID(N'warehouse.dim_trip')
)
BEGIN
    CREATE INDEX IX_dim_trip_shape
        ON warehouse.dim_trip (
            snapshot_key,
            shape_id
        )
        INCLUDE (
            trip_id,
            route_key
        );
END;

SELECT
    schema_name(schema_id) AS schema_name,
    name AS table_name
FROM sys.tables
WHERE
    schema_name(schema_id) = N'warehouse'
    AND name IN (
        N'dim_service',
        N'dim_trip'
    )
ORDER BY name;
