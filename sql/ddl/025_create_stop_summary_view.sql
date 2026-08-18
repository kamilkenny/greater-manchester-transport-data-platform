/*
Creates a compact stop summary across the approved reporting window.
*/

CREATE OR ALTER VIEW analytics.vw_stop_summary
AS
WITH latest_snapshot AS (
    SELECT TOP (1) snapshot_key
    FROM governance.source_snapshot
    WHERE snapshot_status = 'LOADED'
    ORDER BY downloaded_at_utc DESC, snapshot_key DESC
)
SELECT
    fact.snapshot_key,
    stop.stop_key,
    stop.stop_id,
    stop.stop_code,
    stop.stop_name,
    stop.stop_latitude,
    stop.stop_longitude,
    stop.zone_id,
    stop.location_type,
    stop.parent_station_id,
    stop.wheelchair_boarding,
    CASE stop.wheelchair_boarding
        WHEN 1 THEN 'Accessible'
        WHEN 2 THEN 'Not accessible'
        ELSE 'Unknown'
    END AS accessibility_status,
    MIN(service_date.full_date) AS first_service_date,
    MAX(service_date.full_date) AS last_service_date,
    COUNT_BIG(*) AS service_day_count,
    SUM(CONVERT(BIGINT, fact.scheduled_trip_count)) AS total_scheduled_trips,
    CAST(AVG(CONVERT(DECIMAL(18, 2), fact.scheduled_trip_count))
        AS DECIMAL(18, 2)) AS average_daily_trips,
    MAX(fact.scheduled_route_count) AS maximum_daily_routes,
    CAST(AVG(CONVERT(DECIMAL(18, 2), fact.scheduled_route_count))
        AS DECIMAL(18, 2)) AS average_daily_routes,
    CAST(AVG(CONVERT(DECIMAL(18, 2), fact.service_span_minutes))
        AS DECIMAL(18, 2)) AS average_service_span_minutes,
    CAST(AVG(CONVERT(DECIMAL(18, 2), fact.average_headway_minutes))
        AS DECIMAL(18, 2)) AS average_headway_minutes
FROM warehouse.fact_stop_service_day AS fact
INNER JOIN latest_snapshot AS snapshot
    ON snapshot.snapshot_key = fact.snapshot_key
INNER JOIN warehouse.dim_date AS service_date
    ON service_date.date_key = fact.date_key
INNER JOIN warehouse.dim_stop AS stop
    ON stop.stop_key = fact.stop_key
GROUP BY
    fact.snapshot_key,
    stop.stop_key,
    stop.stop_id,
    stop.stop_code,
    stop.stop_name,
    stop.stop_latitude,
    stop.stop_longitude,
    stop.zone_id,
    stop.location_type,
    stop.parent_station_id,
    stop.wheelchair_boarding;
