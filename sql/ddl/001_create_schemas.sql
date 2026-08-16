/*
Creates the logical database schemas used by the Greater Manchester
Transport Data Platform.

The script is idempotent and can be executed repeatedly.
*/

SET NOCOUNT ON;
SET XACT_ABORT ON;

IF NOT EXISTS (
    SELECT 1
    FROM sys.schemas
    WHERE name = N'staging'
)
BEGIN
    EXEC(N'CREATE SCHEMA [staging] AUTHORIZATION [dbo];');
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.schemas
    WHERE name = N'warehouse'
)
BEGIN
    EXEC(N'CREATE SCHEMA [warehouse] AUTHORIZATION [dbo];');
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.schemas
    WHERE name = N'analytics'
)
BEGIN
    EXEC(N'CREATE SCHEMA [analytics] AUTHORIZATION [dbo];');
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.schemas
    WHERE name = N'governance'
)
BEGIN
    EXEC(N'CREATE SCHEMA [governance] AUTHORIZATION [dbo];');
END;

SELECT
    name AS schema_name
FROM sys.schemas
WHERE name IN (
    N'staging',
    N'warehouse',
    N'analytics',
    N'governance'
)
ORDER BY name;
