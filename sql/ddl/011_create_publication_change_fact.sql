/*
Creates the publication change fact table.

Each record represents an entity added, removed or modified between
two successive TfGM GTFS publication snapshots.

Prerequisites:
    001_create_schemas.sql
    002_create_governance_tables.sql
    006_create_warehouse_core_dimensions.sql
    007_create_warehouse_network_dimensions.sql
    008_create_warehouse_service_dimensions.sql
*/

SET NOCOUNT ON;
SET XACT_ABORT ON;

IF OBJECT_ID(N'warehouse.fact_publication_change', N'U') IS NULL
BEGIN
    CREATE TABLE warehouse.fact_publication_change (
        publication_change_key BIGINT IDENTITY(1, 1) NOT NULL,
        previous_snapshot_key BIGINT NOT NULL,
        current_snapshot_key BIGINT NOT NULL,
        entity_type VARCHAR(20) NOT NULL,
        entity_id NVARCHAR(100) NOT NULL,
        change_type VARCHAR(10) NOT NULL,
        changed_fields NVARCHAR(2000) NULL,
        previous_row_hash BINARY(32) NULL,
        current_row_hash BINARY(32) NULL,
        change_details_json NVARCHAR(MAX) NULL,
        detected_at_utc DATETIME2(3) NOT NULL
            CONSTRAINT DF_publication_change_detected
            DEFAULT (SYSUTCDATETIME()),

        CONSTRAINT PK_fact_publication_change
            PRIMARY KEY CLUSTERED (publication_change_key),

        CONSTRAINT UQ_fact_publication_change
            UNIQUE (
                previous_snapshot_key,
                current_snapshot_key,
                entity_type,
                entity_id
            ),

        CONSTRAINT FK_publication_change_previous_snapshot
            FOREIGN KEY (previous_snapshot_key)
            REFERENCES governance.source_snapshot (snapshot_key),

        CONSTRAINT FK_publication_change_current_snapshot
            FOREIGN KEY (current_snapshot_key)
            REFERENCES governance.source_snapshot (snapshot_key),

        CONSTRAINT CK_publication_change_snapshot_order
            CHECK (current_snapshot_key > previous_snapshot_key),

        CONSTRAINT CK_publication_change_entity
            CHECK (
                entity_type IN (
                    'OPERATOR',
                    'ROUTE',
                    'STOP',
                    'SERVICE',
                    'TRIP'
                )
            ),

        CONSTRAINT CK_publication_change_type
            CHECK (
                change_type IN (
                    'ADDED',
                    'REMOVED',
                    'MODIFIED'
                )
            ),

        CONSTRAINT CK_publication_change_hashes
            CHECK (
                (
                    change_type = 'ADDED'
                    AND previous_row_hash IS NULL
                    AND current_row_hash IS NOT NULL
                )
                OR (
                    change_type = 'REMOVED'
                    AND previous_row_hash IS NOT NULL
                    AND current_row_hash IS NULL
                )
                OR (
                    change_type = 'MODIFIED'
                    AND previous_row_hash IS NOT NULL
                    AND current_row_hash IS NOT NULL
                    AND previous_row_hash <> current_row_hash
                )
            ),

        CONSTRAINT CK_publication_change_json
            CHECK (
                change_details_json IS NULL
                OR ISJSON(change_details_json) = 1
            )
    );
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE
        name = N'IX_publication_change_current'
        AND object_id = OBJECT_ID(
            N'warehouse.fact_publication_change'
        )
)
BEGIN
    CREATE INDEX IX_publication_change_current
        ON warehouse.fact_publication_change (
            current_snapshot_key,
            entity_type,
            change_type
        )
        INCLUDE (
            entity_id,
            previous_snapshot_key,
            changed_fields
        );
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE
        name = N'IX_publication_change_entity'
        AND object_id = OBJECT_ID(
            N'warehouse.fact_publication_change'
        )
)
BEGIN
    CREATE INDEX IX_publication_change_entity
        ON warehouse.fact_publication_change (
            entity_type,
            entity_id,
            current_snapshot_key
        )
        INCLUDE (
            change_type,
            previous_snapshot_key,
            changed_fields
        );
END;

SELECT
    schema_name(schema_id) AS schema_name,
    name AS table_name
FROM sys.tables
WHERE
    schema_name(schema_id) = N'warehouse'
    AND name = N'fact_publication_change';
