/*
Creates a compact route summary across the approved reporting window.
*/

CREATE OR ALTER VIEW analytics.vw_route_summary
AS
SELECT
    snapshot_key,
    operator_key,
    agency_id,
    operator_name,
    route_key,
    route_id,
    route_short_name,
    route_long_name,
    route_display_name,
    route_type,
    transport_mode,
    route_colour,
    route_text_colour,
    MIN(service_date) AS first_service_date,
    MAX(service_date) AS last_service_date,
    COUNT_BIG(*) AS service_day_count,
    SUM(CONVERT(BIGINT, scheduled_trip_count)) AS total_scheduled_trips,
    SUM(CONVERT(BIGINT, scheduled_stop_event_count))
        AS total_scheduled_stop_events,
    MAX(scheduled_trip_count) AS maximum_daily_trips,
    CAST(AVG(CONVERT(DECIMAL(18, 2), scheduled_trip_count))
        AS DECIMAL(18, 2)) AS average_daily_trips,
    CAST(AVG(CONVERT(DECIMAL(18, 2), unique_stop_count))
        AS DECIMAL(18, 2)) AS average_daily_unique_stops,
    MAX(unique_stop_count) AS maximum_daily_unique_stops,
    CAST(AVG(CONVERT(DECIMAL(18, 2), service_span_minutes))
        AS DECIMAL(18, 2)) AS average_service_span_minutes,
    CAST(AVG(CONVERT(DECIMAL(18, 2), average_headway_minutes))
        AS DECIMAL(18, 2)) AS average_headway_minutes
FROM analytics.vw_route_service_daily
GROUP BY
    snapshot_key,
    operator_key,
    agency_id,
    operator_name,
    route_key,
    route_id,
    route_short_name,
    route_long_name,
    route_display_name,
    route_type,
    transport_mode,
    route_colour,
    route_text_colour;
