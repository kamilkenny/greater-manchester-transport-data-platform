/*
Creates daily route and stop service fact tables.

These aggregates support reporting without repeatedly scanning every
scheduled stop event.

Prerequisites:
    001_create_schemas.sql
    002_create_governance_tables.sql
    006_create_warehouse_core_dimensions.sql
    007_create_warehouse_network_dimensions.sql
    009_create_warehouse_schedule_tables.sql
*/

SET NOCOUNT ON;
SET XACT_ABORT ON;

IF OBJECT_ID(N'warehouse.fact_route_service_day', N'U') IS NULL
BEGIN
    CREATE TABLE warehouse.fact_route_service_day (
        snapshot_key BIGINT NOT NULL,
        date_key INT NOT NULL,
        route_key BIGINT NOT NULL,
        operator_key BIGINT NOT NULL,
        scheduled_trip_count INT NOT NULL,
        scheduled_stop_event_count INT NOT NULL,
        unique_stop_count INT NOT NULL,
        first_departure_seconds INT NOT NULL,
        last_arrival_seconds INT NOT NULL,
        service_span_minutes DECIMAL(12, 2) NOT NULL,
        average_headway_minutes DECIMAL(12, 2) NULL,
        created_at_utc DATETIME2(3) NOT NULL
            CONSTRAINT DF_fact_route_day_created
            DEFAULT (SYSUTCDATETIME()),

        CONSTRAINT PK_fact_route_service_day
            PRIMARY KEY CLUSTERED (
                snapshot_key,
                date_key,
                route_key
            ),

        CONSTRAINT FK_fact_route_day_snapshot
            FOREIGN KEY (snapshot_key)
            REFERENCES governance.source_snapshot (snapshot_key),

        CONSTRAINT FK_fact_route_day_date
            FOREIGN KEY (date_key)
            REFERENCES warehouse.dim_date (date_key),

        CONSTRAINT FK_fact_route_day_route
            FOREIGN KEY (route_key)
            REFERENCES warehouse.dim_route (route_key),

        CONSTRAINT FK_fact_route_day_operator
            FOREIGN KEY (operator_key)
            REFERENCES warehouse.dim_operator (operator_key),

        CONSTRAINT CK_fact_route_day_counts
            CHECK (
                scheduled_trip_count > 0
                AND scheduled_stop_event_count > 0
                AND unique_stop_count > 0
            ),

        CONSTRAINT CK_fact_route_day_times
            CHECK (
                first_departure_seconds >= 0
                AND last_arrival_seconds >= first_departure_seconds
            ),

        CONSTRAINT CK_fact_route_day_span
            CHECK (service_span_minutes >= 0),

        CONSTRAINT CK_fact_route_day_headway
            CHECK (
                average_headway_minutes IS NULL
                OR average_headway_minutes >= 0
            )
    );
END;

IF OBJECT_ID(N'warehouse.fact_stop_service_day', N'U') IS NULL
BEGIN
    CREATE TABLE warehouse.fact_stop_service_day (
        snapshot_key BIGINT NOT NULL,
        date_key INT NOT NULL,
        stop_key BIGINT NOT NULL,
        scheduled_trip_count INT NOT NULL,
        scheduled_route_count INT NOT NULL,
        first_departure_seconds INT NOT NULL,
        last_departure_seconds INT NOT NULL,
        service_span_minutes DECIMAL(12, 2) NOT NULL,
        average_headway_minutes DECIMAL(12, 2) NULL,
        created_at_utc DATETIME2(3) NOT NULL
            CONSTRAINT DF_fact_stop_day_created
            DEFAULT (SYSUTCDATETIME()),

        CONSTRAINT PK_fact_stop_service_day
            PRIMARY KEY CLUSTERED (
                snapshot_key,
                date_key,
                stop_key
            ),

        CONSTRAINT FK_fact_stop_day_snapshot
            FOREIGN KEY (snapshot_key)
            REFERENCES governance.source_snapshot (snapshot_key),

        CONSTRAINT FK_fact_stop_day_date
            FOREIGN KEY (date_key)
            REFERENCES warehouse.dim_date (date_key),

        CONSTRAINT FK_fact_stop_day_stop
            FOREIGN KEY (stop_key)
            REFERENCES warehouse.dim_stop (stop_key),

        CONSTRAINT CK_fact_stop_day_counts
            CHECK (
                scheduled_trip_count > 0
                AND scheduled_route_count > 0
            ),

        CONSTRAINT CK_fact_stop_day_times
            CHECK (
                first_departure_seconds >= 0
                AND last_departure_seconds >= first_departure_seconds
            ),

        CONSTRAINT CK_fact_stop_day_span
            CHECK (service_span_minutes >= 0),

        CONSTRAINT CK_fact_stop_day_headway
            CHECK (
                average_headway_minutes IS NULL
                OR average_headway_minutes >= 0
            )
    );
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE
        name = N'IX_fact_route_day_date'
        AND object_id = OBJECT_ID(
            N'warehouse.fact_route_service_day'
        )
)
BEGIN
    CREATE INDEX IX_fact_route_day_date
        ON warehouse.fact_route_service_day (
            snapshot_key,
            date_key
        )
        INCLUDE (
            route_key,
            operator_key,
            scheduled_trip_count,
            unique_stop_count,
            service_span_minutes,
            average_headway_minutes
        );
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE
        name = N'IX_fact_route_day_operator'
        AND object_id = OBJECT_ID(
            N'warehouse.fact_route_service_day'
        )
)
BEGIN
    CREATE INDEX IX_fact_route_day_operator
        ON warehouse.fact_route_service_day (
            snapshot_key,
            operator_key,
            date_key
        )
        INCLUDE (
            route_key,
            scheduled_trip_count,
            scheduled_stop_event_count
        );
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE
        name = N'IX_fact_stop_day_date'
        AND object_id = OBJECT_ID(
            N'warehouse.fact_stop_service_day'
        )
)
BEGIN
    CREATE INDEX IX_fact_stop_day_date
        ON warehouse.fact_stop_service_day (
            snapshot_key,
            date_key
        )
        INCLUDE (
            stop_key,
            scheduled_trip_count,
            scheduled_route_count,
            service_span_minutes,
            average_headway_minutes
        );
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE
        name = N'IX_fact_stop_day_stop'
        AND object_id = OBJECT_ID(
            N'warehouse.fact_stop_service_day'
        )
)
BEGIN
    CREATE INDEX IX_fact_stop_day_stop
        ON warehouse.fact_stop_service_day (
            snapshot_key,
            stop_key,
            date_key
        )
        INCLUDE (
            scheduled_trip_count,
            scheduled_route_count,
            first_departure_seconds,
            last_departure_seconds
        );
END;

SELECT
    schema_name(schema_id) AS schema_name,
    name AS table_name
FROM sys.tables
WHERE
    schema_name(schema_id) = N'warehouse'
    AND name IN (
        N'fact_route_service_day',
        N'fact_stop_service_day'
    )
ORDER BY name;
