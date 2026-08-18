/*
Creates transparent route strength scores from scheduled service measures.

These are custom comparative indicators and are not measures of actual
punctuality, reliability or passenger demand.
*/

CREATE OR ALTER VIEW analytics.vw_route_service_intelligence
AS
WITH percentiles AS (
    SELECT
        summary.*,
        PERCENT_RANK() OVER (
            PARTITION BY snapshot_key
            ORDER BY average_daily_trips
        ) AS trip_intensity_percentile,
        PERCENT_RANK() OVER (
            PARTITION BY snapshot_key
            ORDER BY average_service_span_minutes
        ) AS span_percentile,
        PERCENT_RANK() OVER (
            PARTITION BY snapshot_key
            ORDER BY average_daily_unique_stops
        ) AS coverage_percentile
    FROM analytics.vw_route_summary AS summary
),
scored AS (
    SELECT
        percentiles.*,
        CAST(ROUND(
            100.0 * (
                0.45 * trip_intensity_percentile
                + 0.30 * span_percentile
                + 0.25 * coverage_percentile
            ),
            1
        ) AS DECIMAL(5, 1)) AS scheduled_service_score
    FROM percentiles
)
SELECT
    scored.snapshot_key,
    scored.operator_key,
    scored.agency_id,
    scored.operator_name,
    scored.route_key,
    scored.route_id,
    scored.route_short_name,
    scored.route_long_name,
    scored.route_display_name,
    scored.route_type,
    scored.transport_mode,
    scored.route_colour,
    scored.route_text_colour,
    scored.first_service_date,
    scored.last_service_date,
    scored.service_day_count,
    scored.total_scheduled_trips,
    scored.total_scheduled_stop_events,
    scored.maximum_daily_trips,
    scored.average_daily_trips,
    scored.average_daily_unique_stops,
    scored.maximum_daily_unique_stops,
    scored.average_service_span_minutes,
    scored.average_headway_minutes,
    scored.trip_intensity_percentile,
    scored.span_percentile,
    scored.coverage_percentile,
    scored.scheduled_service_score,
    DENSE_RANK() OVER (
        PARTITION BY snapshot_key
        ORDER BY scheduled_service_score DESC
    ) AS network_service_rank,
    DENSE_RANK() OVER (
        PARTITION BY snapshot_key, transport_mode
        ORDER BY scheduled_service_score DESC
    ) AS mode_service_rank,
    CASE
        WHEN scheduled_service_score >= 80 THEN 'VERY HIGH'
        WHEN scheduled_service_score >= 60 THEN 'HIGH'
        WHEN scheduled_service_score >= 40 THEN 'MODERATE'
        ELSE 'LIMITED'
    END AS scheduled_service_band,
    CASE
        WHEN average_headway_minutes IS NULL THEN 'SINGLE JOURNEY'
        WHEN average_headway_minutes <= 10 THEN 'HIGH FREQUENCY'
        WHEN average_headway_minutes <= 20 THEN 'FREQUENT'
        WHEN average_headway_minutes <= 30 THEN 'STANDARD'
        ELSE 'LOW FREQUENCY'
    END AS frequency_band
FROM scored;
