/*
Creates daily network and transport mode trend measures.
*/

CREATE OR ALTER VIEW analytics.vw_network_daily_summary
AS
SELECT
    snapshot_key,
    service_date,
    day_name,
    is_weekend,
    month_name,
    calendar_year,
    transport_mode,
    COUNT_BIG(*) AS active_route_count,
    COUNT_BIG(DISTINCT operator_key) AS active_operator_count,
    SUM(CONVERT(BIGINT, scheduled_trip_count)) AS scheduled_trip_count,
    SUM(CONVERT(BIGINT, scheduled_stop_event_count))
        AS scheduled_stop_event_count,
    CAST(AVG(CONVERT(DECIMAL(18, 2), unique_stop_count))
        AS DECIMAL(18, 2)) AS average_stops_per_route,
    CAST(AVG(CONVERT(DECIMAL(18, 2), service_span_minutes))
        AS DECIMAL(18, 2)) AS average_service_span_minutes,
    CAST(AVG(CONVERT(DECIMAL(18, 2), average_headway_minutes))
        AS DECIMAL(18, 2)) AS average_headway_minutes
FROM analytics.vw_route_service_daily
GROUP BY
    snapshot_key,
    service_date,
    day_name,
    is_weekend,
    month_name,
    calendar_year,
    transport_mode;
