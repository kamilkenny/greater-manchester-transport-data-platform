/*
Creates transport mode level scheduled service intelligence.
*/

CREATE OR ALTER VIEW analytics.vw_transport_mode_summary
AS
SELECT
    snapshot_key,
    transport_mode,
    COUNT_BIG(*) AS route_count,
    COUNT_BIG(DISTINCT operator_key) AS operator_count,
    SUM(total_scheduled_trips) AS total_scheduled_trips,
    SUM(total_scheduled_stop_events) AS total_scheduled_stop_events,
    CAST(AVG(average_daily_trips) AS DECIMAL(18, 2))
        AS average_route_daily_trips,
    CAST(AVG(average_daily_unique_stops) AS DECIMAL(18, 2))
        AS average_route_stop_coverage,
    CAST(AVG(average_service_span_minutes) AS DECIMAL(18, 2))
        AS average_service_span_minutes,
    CAST(AVG(average_headway_minutes) AS DECIMAL(18, 2))
        AS average_headway_minutes
FROM analytics.vw_route_summary
GROUP BY
    snapshot_key,
    transport_mode;
