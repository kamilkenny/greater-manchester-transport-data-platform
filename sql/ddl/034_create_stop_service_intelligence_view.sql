/*
Creates transparent stop activity scores from scheduled service measures.

These are custom comparative indicators and are not passenger demand scores.
*/

CREATE OR ALTER VIEW analytics.vw_stop_service_intelligence
AS
WITH percentiles AS (
    SELECT
        summary.*,
        PERCENT_RANK() OVER (
            PARTITION BY snapshot_key
            ORDER BY average_daily_trips
        ) AS trip_activity_percentile,
        PERCENT_RANK() OVER (
            PARTITION BY snapshot_key
            ORDER BY average_daily_routes
        ) AS route_choice_percentile,
        PERCENT_RANK() OVER (
            PARTITION BY snapshot_key
            ORDER BY average_service_span_minutes
        ) AS span_percentile
    FROM analytics.vw_stop_summary AS summary
),
scored AS (
    SELECT
        percentiles.*,
        CAST(ROUND(
            100.0 * (
                0.50 * trip_activity_percentile
                + 0.30 * route_choice_percentile
                + 0.20 * span_percentile
            ),
            1
        ) AS DECIMAL(5, 1)) AS scheduled_activity_score
    FROM percentiles
)
SELECT
    scored.snapshot_key,
    scored.stop_key,
    scored.stop_id,
    scored.stop_code,
    scored.stop_name,
    scored.stop_latitude,
    scored.stop_longitude,
    scored.zone_id,
    scored.location_type,
    scored.parent_station_id,
    scored.wheelchair_boarding,
    scored.accessibility_status,
    scored.first_service_date,
    scored.last_service_date,
    scored.service_day_count,
    scored.total_scheduled_trips,
    scored.average_daily_trips,
    scored.maximum_daily_routes,
    scored.average_daily_routes,
    scored.average_service_span_minutes,
    scored.average_headway_minutes,
    scored.trip_activity_percentile,
    scored.route_choice_percentile,
    scored.span_percentile,
    scored.scheduled_activity_score,
    DENSE_RANK() OVER (
        PARTITION BY snapshot_key
        ORDER BY scheduled_activity_score DESC
    ) AS network_activity_rank,
    CASE
        WHEN scheduled_activity_score >= 80 THEN 'MAJOR HUB'
        WHEN scheduled_activity_score >= 60 THEN 'HIGH ACTIVITY'
        WHEN scheduled_activity_score >= 40 THEN 'MODERATE ACTIVITY'
        ELSE 'LOCAL ACCESS'
    END AS scheduled_activity_band
FROM scored;
