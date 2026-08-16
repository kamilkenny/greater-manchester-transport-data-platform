/*
Creates the service date bridge, scheduled stop event fact and
geographical shape point table.

Times are stored as seconds after the start of the service day because
GTFS times can extend beyond 24:00:00.

Prerequisites:
    001_create_schemas.sql
    002_create_governance_tables.sql
    006_create_warehouse_core_dimensions.sql
    007_create_warehouse_network_dimensions.sql
    008_create_warehouse_service_dimensions.sql
*/

SET NOCOUNT ON;
SET XACT_ABORT ON;

IF OBJECT_ID(N'warehouse.bridge_service_date', N'U') IS NULL
BEGIN
    CREATE TABLE warehouse.bridge_service_date (
        snapshot_key BIGINT NOT NULL,
        service_key BIGINT NOT NULL,
        date_key INT NOT NULL,
        activation_source VARCHAR(20) NOT NULL,
        created_at_utc DATETIME2(3) NOT NULL
            CONSTRAINT DF_bridge_service_date_created
            DEFAULT (SYSUTCDATETIME()),

        CONSTRAINT PK_bridge_service_date
            PRIMARY KEY CLUSTERED (
                service_key,
                date_key
            ),

        CONSTRAINT FK_bridge_service_date_snapshot
            FOREIGN KEY (snapshot_key)
            REFERENCES governance.source_snapshot (snapshot_key),

        CONSTRAINT FK_bridge_service_date_service
            FOREIGN KEY (service_key)
            REFERENCES warehouse.dim_service (service_key),

        CONSTRAINT FK_bridge_service_date_date
            FOREIGN KEY (date_key)
            REFERENCES warehouse.dim_date (date_key),

        CONSTRAINT CK_bridge_service_date_source
            CHECK (
                activation_source IN (
                    'CALENDAR',
                    'EXCEPTION_ADDED'
                )
            )
    );
END;

IF OBJECT_ID(N'warehouse.fact_scheduled_stop_event', N'U') IS NULL
BEGIN
    CREATE TABLE warehouse.fact_scheduled_stop_event (
        snapshot_key BIGINT NOT NULL,
        trip_key BIGINT NOT NULL,
        route_key BIGINT NOT NULL,
        stop_key BIGINT NOT NULL,
        stop_sequence INT NOT NULL,
        arrival_seconds INT NOT NULL,
        departure_seconds INT NOT NULL,
        stop_headsign NVARCHAR(300) NULL,
        pickup_type TINYINT NOT NULL,
        drop_off_type TINYINT NOT NULL,
        shape_dist_travelled DECIMAL(18, 3) NULL,
        is_timepoint BIT NOT NULL,
        row_hash BINARY(32) NOT NULL,
        created_at_utc DATETIME2(3) NOT NULL
            CONSTRAINT DF_fact_stop_event_created
            DEFAULT (SYSUTCDATETIME()),

        CONSTRAINT PK_fact_scheduled_stop_event
            PRIMARY KEY CLUSTERED (
                snapshot_key,
                trip_key,
                stop_sequence
            ),

        CONSTRAINT FK_fact_stop_event_snapshot
            FOREIGN KEY (snapshot_key)
            REFERENCES governance.source_snapshot (snapshot_key),

        CONSTRAINT FK_fact_stop_event_trip
            FOREIGN KEY (trip_key)
            REFERENCES warehouse.dim_trip (trip_key),

        CONSTRAINT FK_fact_stop_event_route
            FOREIGN KEY (route_key)
            REFERENCES warehouse.dim_route (route_key),

        CONSTRAINT FK_fact_stop_event_stop
            FOREIGN KEY (stop_key)
            REFERENCES warehouse.dim_stop (stop_key),

        CONSTRAINT CK_fact_stop_event_sequence
            CHECK (stop_sequence >= 0),

        CONSTRAINT CK_fact_stop_event_arrival
            CHECK (arrival_seconds >= 0),

        CONSTRAINT CK_fact_stop_event_departure
            CHECK (departure_seconds >= 0),

        CONSTRAINT CK_fact_stop_event_pickup
            CHECK (pickup_type BETWEEN 0 AND 3),

        CONSTRAINT CK_fact_stop_event_drop_off
            CHECK (drop_off_type BETWEEN 0 AND 3),

        CONSTRAINT CK_fact_stop_event_distance
            CHECK (
                shape_dist_travelled IS NULL
                OR shape_dist_travelled >= 0
            )
    );
END;

IF OBJECT_ID(N'warehouse.shape_point', N'U') IS NULL
BEGIN
    CREATE TABLE warehouse.shape_point (
        snapshot_key BIGINT NOT NULL,
        shape_id NVARCHAR(50) NOT NULL,
        shape_point_sequence INT NOT NULL,
        shape_point_latitude DECIMAL(9, 6) NOT NULL,
        shape_point_longitude DECIMAL(9, 6) NOT NULL,
        shape_dist_travelled DECIMAL(18, 3) NULL,
        created_at_utc DATETIME2(3) NOT NULL
            CONSTRAINT DF_shape_point_created
            DEFAULT (SYSUTCDATETIME()),

        CONSTRAINT PK_shape_point
            PRIMARY KEY CLUSTERED (
                snapshot_key,
                shape_id,
                shape_point_sequence
            ),

        CONSTRAINT FK_shape_point_snapshot
            FOREIGN KEY (snapshot_key)
            REFERENCES governance.source_snapshot (snapshot_key),

        CONSTRAINT CK_shape_point_sequence
            CHECK (shape_point_sequence >= 0),

        CONSTRAINT CK_shape_point_latitude
            CHECK (shape_point_latitude BETWEEN -90 AND 90),

        CONSTRAINT CK_shape_point_longitude
            CHECK (shape_point_longitude BETWEEN -180 AND 180),

        CONSTRAINT CK_shape_point_distance
            CHECK (
                shape_dist_travelled IS NULL
                OR shape_dist_travelled >= 0
            )
    );
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE
        name = N'IX_bridge_service_date_date'
        AND object_id = OBJECT_ID(
            N'warehouse.bridge_service_date'
        )
)
BEGIN
    CREATE INDEX IX_bridge_service_date_date
        ON warehouse.bridge_service_date (
            snapshot_key,
            date_key
        )
        INCLUDE (service_key);
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE
        name = N'IX_fact_stop_event_stop'
        AND object_id = OBJECT_ID(
            N'warehouse.fact_scheduled_stop_event'
        )
)
BEGIN
    CREATE INDEX IX_fact_stop_event_stop
        ON warehouse.fact_scheduled_stop_event (
            snapshot_key,
            stop_key
        )
        INCLUDE (
            route_key,
            trip_key,
            arrival_seconds,
            departure_seconds
        );
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE
        name = N'IX_fact_stop_event_route'
        AND object_id = OBJECT_ID(
            N'warehouse.fact_scheduled_stop_event'
        )
)
BEGIN
    CREATE INDEX IX_fact_stop_event_route
        ON warehouse.fact_scheduled_stop_event (
            snapshot_key,
            route_key
        )
        INCLUDE (
            trip_key,
            stop_key,
            arrival_seconds,
            departure_seconds
        );
END;

SELECT
    schema_name(schema_id) AS schema_name,
    name AS table_name
FROM sys.tables
WHERE
    schema_name(schema_id) = N'warehouse'
    AND name IN (
        N'bridge_service_date',
        N'fact_scheduled_stop_event',
        N'shape_point'
    )
ORDER BY name;
