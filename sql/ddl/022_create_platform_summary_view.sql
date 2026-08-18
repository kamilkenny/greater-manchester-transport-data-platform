/*
Creates the approved platform summary view used by serving exports.
*/

CREATE OR ALTER VIEW analytics.vw_platform_summary
AS
WITH latest_snapshot AS (
    SELECT TOP (1)
        snapshot_key,
        source_name,
        downloaded_at_utc,
        source_last_modified_utc,
        file_name,
        file_size_bytes,
        sha256,
        feed_start_date,
        feed_end_date,
        feed_version
    FROM governance.source_snapshot
    WHERE snapshot_status = 'LOADED'
    ORDER BY downloaded_at_utc DESC, snapshot_key DESC
),
route_fact_range AS (
    SELECT
        fact.snapshot_key,
        MIN(service_date.full_date) AS reporting_start_date,
        MAX(service_date.full_date) AS reporting_end_date,
        COUNT_BIG(*) AS route_daily_fact_count
    FROM warehouse.fact_route_service_day AS fact
    INNER JOIN warehouse.dim_date AS service_date
        ON service_date.date_key = fact.date_key
    GROUP BY fact.snapshot_key
),
stop_fact_count AS (
    SELECT
        snapshot_key,
        COUNT_BIG(*) AS stop_daily_fact_count
    FROM warehouse.fact_stop_service_day
    GROUP BY snapshot_key
)
SELECT
    snapshot.snapshot_key,
    snapshot.source_name,
    snapshot.downloaded_at_utc,
    snapshot.source_last_modified_utc,
    CAST(
        DATEDIFF_BIG(
            MINUTE,
            snapshot.downloaded_at_utc,
            SYSUTCDATETIME()
        ) / 60.0
        AS DECIMAL(18, 2)
    ) AS data_age_hours,
    CASE
        WHEN DATEDIFF_BIG(
            HOUR,
            snapshot.downloaded_at_utc,
            SYSUTCDATETIME()
        ) <= 36 THEN 'CURRENT'
        WHEN DATEDIFF_BIG(
            HOUR,
            snapshot.downloaded_at_utc,
            SYSUTCDATETIME()
        ) <= 72 THEN 'DELAYED'
        ELSE 'STALE'
    END AS freshness_status,
    snapshot.file_name,
    snapshot.file_size_bytes,
    snapshot.sha256,
    snapshot.feed_start_date,
    snapshot.feed_end_date,
    snapshot.feed_version,
    route_range.reporting_start_date,
    route_range.reporting_end_date,
    (SELECT COUNT_BIG(*)
     FROM warehouse.dim_operator
     WHERE
         valid_from_snapshot_key <= snapshot.snapshot_key
         AND (
             valid_to_snapshot_key IS NULL
             OR valid_to_snapshot_key > snapshot.snapshot_key
         )) AS operator_count,
    (SELECT COUNT_BIG(*)
     FROM warehouse.dim_route
     WHERE
         valid_from_snapshot_key <= snapshot.snapshot_key
         AND (
             valid_to_snapshot_key IS NULL
             OR valid_to_snapshot_key > snapshot.snapshot_key
         )) AS route_count,
    (SELECT COUNT_BIG(*)
     FROM warehouse.dim_stop
     WHERE
         valid_from_snapshot_key <= snapshot.snapshot_key
         AND (
             valid_to_snapshot_key IS NULL
             OR valid_to_snapshot_key > snapshot.snapshot_key
         )) AS stop_count,
    (SELECT COUNT_BIG(*)
     FROM warehouse.dim_service
     WHERE snapshot_key = snapshot.snapshot_key) AS service_count,
    (SELECT COUNT_BIG(*)
     FROM warehouse.dim_trip
     WHERE snapshot_key = snapshot.snapshot_key) AS trip_count,
    (SELECT COUNT_BIG(*)
     FROM warehouse.fact_scheduled_stop_event
     WHERE snapshot_key = snapshot.snapshot_key) AS scheduled_stop_event_count,
    (SELECT COUNT_BIG(*)
     FROM warehouse.shape_point
     WHERE snapshot_key = snapshot.snapshot_key) AS shape_point_count,
    COALESCE(route_range.route_daily_fact_count, 0) AS route_daily_fact_count,
    COALESCE(stop_count.stop_daily_fact_count, 0) AS stop_daily_fact_count,
    (SELECT COUNT_BIG(*)
     FROM warehouse.fact_publication_change
     WHERE current_snapshot_key = snapshot.snapshot_key) AS publication_change_count,
    (SELECT MAX(completed_at_utc)
     FROM governance.pipeline_run
     WHERE
         snapshot_key = snapshot.snapshot_key
         AND run_status = 'SUCCEEDED') AS last_successful_pipeline_at_utc,
    (SELECT COUNT_BIG(*)
     FROM governance.pipeline_run
     WHERE
         snapshot_key = snapshot.snapshot_key
         AND run_status = 'SUCCEEDED') AS successful_pipeline_run_count,
    (SELECT COUNT_BIG(*)
     FROM governance.pipeline_run
     WHERE
         snapshot_key = snapshot.snapshot_key
         AND run_status = 'FAILED') AS failed_pipeline_run_count
FROM latest_snapshot AS snapshot
LEFT JOIN route_fact_range AS route_range
    ON route_range.snapshot_key = snapshot.snapshot_key
LEFT JOIN stop_fact_count AS stop_count
    ON stop_count.snapshot_key = snapshot.snapshot_key;
