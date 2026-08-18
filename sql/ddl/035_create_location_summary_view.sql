/*
Creates zone level geographic coverage and accessibility intelligence.
*/

CREATE OR ALTER VIEW analytics.vw_location_summary
AS
SELECT
    snapshot_key,
    COALESCE(NULLIF(zone_id, ''), 'UNASSIGNED') AS location_group,
    COUNT_BIG(*) AS stop_count,
    SUM(total_scheduled_trips) AS total_scheduled_trips,
    CAST(AVG(average_daily_trips) AS DECIMAL(18, 2))
        AS average_stop_daily_trips,
    CAST(AVG(average_daily_routes) AS DECIMAL(18, 2))
        AS average_route_choice,
    SUM(CASE WHEN accessibility_status = 'Accessible' THEN 1 ELSE 0 END)
        AS accessible_stop_count,
    SUM(CASE WHEN accessibility_status = 'Not accessible' THEN 1 ELSE 0 END)
        AS inaccessible_stop_count,
    SUM(CASE WHEN accessibility_status = 'Unknown' THEN 1 ELSE 0 END)
        AS unknown_accessibility_count,
    CAST(AVG(CONVERT(DECIMAL(18, 6), stop_latitude))
        AS DECIMAL(9, 6)) AS centre_latitude,
    CAST(AVG(CONVERT(DECIMAL(18, 6), stop_longitude))
        AS DECIMAL(9, 6)) AS centre_longitude
FROM analytics.vw_stop_summary
GROUP BY
    snapshot_key,
    COALESCE(NULLIF(zone_id, ''), 'UNASSIGNED');
