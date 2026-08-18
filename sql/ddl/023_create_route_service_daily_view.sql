/*
Creates the approved route service day reporting view.
*/

CREATE OR ALTER VIEW analytics.vw_route_service_daily
AS
WITH latest_snapshot AS (
    SELECT TOP (1) snapshot_key
    FROM governance.source_snapshot
    WHERE snapshot_status = 'LOADED'
    ORDER BY downloaded_at_utc DESC, snapshot_key DESC
)
SELECT
    fact.snapshot_key,
    service_date.full_date AS service_date,
    service_date.day_name,
    service_date.is_weekend,
    service_date.month_name,
    service_date.calendar_year,
    operator.operator_key,
    operator.agency_id,
    operator.operator_name,
    route.route_key,
    route.route_id,
    route.route_short_name,
    route.route_long_name,
    COALESCE(
        NULLIF(route.route_short_name, ''),
        NULLIF(route.route_long_name, ''),
        route.route_id
    ) AS route_display_name,
    route.route_type,
    CASE route.route_type
        WHEN 0 THEN 'Tram'
        WHEN 1 THEN 'Underground'
        WHEN 2 THEN 'Rail'
        WHEN 3 THEN 'Bus'
        ELSE 'Other'
    END AS transport_mode,
    route.route_colour,
    route.route_text_colour,
    fact.scheduled_trip_count,
    fact.scheduled_stop_event_count,
    fact.unique_stop_count,
    fact.first_departure_seconds,
    fact.last_arrival_seconds,
    fact.service_span_minutes,
    fact.average_headway_minutes
FROM warehouse.fact_route_service_day AS fact
INNER JOIN latest_snapshot AS snapshot
    ON snapshot.snapshot_key = fact.snapshot_key
INNER JOIN warehouse.dim_date AS service_date
    ON service_date.date_key = fact.date_key
INNER JOIN warehouse.dim_route AS route
    ON route.route_key = fact.route_key
INNER JOIN warehouse.dim_operator AS operator
    ON operator.operator_key = fact.operator_key;
