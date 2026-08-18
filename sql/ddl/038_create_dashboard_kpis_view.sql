/*
Creates the compact executive KPI contract for the public dashboard.
*/

CREATE OR ALTER VIEW analytics.vw_dashboard_kpis
AS
SELECT
    platform.snapshot_key,
    platform.downloaded_at_utc,
    platform.data_age_hours,
    platform.freshness_status,
    platform.reporting_start_date,
    platform.reporting_end_date,
    platform.operator_count,
    platform.route_count,
    platform.stop_count,
    platform.trip_count,
    platform.scheduled_stop_event_count,
    platform.publication_change_count,
    (SELECT COUNT_BIG(*)
     FROM analytics.vw_route_service_intelligence
     WHERE scheduled_service_band IN ('VERY HIGH', 'HIGH'))
        AS strong_service_route_count,
    (SELECT COUNT_BIG(*)
     FROM analytics.vw_route_service_intelligence
     WHERE frequency_band = 'HIGH FREQUENCY')
        AS high_frequency_route_count,
    (SELECT COUNT_BIG(*)
     FROM analytics.vw_stop_service_intelligence
     WHERE scheduled_activity_band = 'MAJOR HUB') AS major_hub_count,
    (SELECT COUNT_BIG(*)
     FROM analytics.vw_stop_summary
     WHERE accessibility_status = 'Accessible') AS accessible_stop_count,
    (SELECT TOP (1) route_display_name
     FROM analytics.vw_route_service_intelligence
     ORDER BY network_service_rank, route_id) AS leading_route,
    (SELECT TOP (1) scheduled_service_score
     FROM analytics.vw_route_service_intelligence
     ORDER BY network_service_rank, route_id) AS leading_route_score,
    (SELECT TOP (1) stop_name
     FROM analytics.vw_stop_service_intelligence
     ORDER BY network_activity_rank, stop_id) AS leading_stop,
    (SELECT TOP (1) scheduled_activity_score
     FROM analytics.vw_stop_service_intelligence
     ORDER BY network_activity_rank, stop_id) AS leading_stop_score,
    (SELECT COUNT_BIG(*)
     FROM analytics.vw_pipeline_health
     WHERE pipeline_health_status = 'HEALTHY') AS healthy_pipeline_count,
    (SELECT COUNT_BIG(*)
     FROM analytics.vw_pipeline_health) AS monitored_pipeline_count,
    platform.last_successful_pipeline_at_utc
FROM analytics.vw_platform_summary AS platform;
