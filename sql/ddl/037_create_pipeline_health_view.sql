/*
Creates latest state and recent execution health for every pipeline.
*/

CREATE OR ALTER VIEW analytics.vw_pipeline_health
AS
WITH ranked_runs AS (
    SELECT
        run.*,
        ROW_NUMBER() OVER (
            PARTITION BY run.pipeline_name
            ORDER BY run.started_at_utc DESC, run.pipeline_run_key DESC
        ) AS recency_rank
    FROM governance.pipeline_run AS run
),
recent_history AS (
    SELECT
        pipeline_name,
        COUNT_BIG(*) AS recent_run_count,
        SUM(CASE WHEN run_status = 'SUCCEEDED' THEN 1 ELSE 0 END)
            AS recent_success_count,
        SUM(CASE WHEN run_status = 'FAILED' THEN 1 ELSE 0 END)
            AS recent_failure_count,
        CAST(
            100.0 * SUM(
                CASE WHEN run_status = 'SUCCEEDED' THEN 1 ELSE 0 END
            ) / NULLIF(COUNT_BIG(*), 0)
            AS DECIMAL(5, 2)
        ) AS recent_success_rate_pct
    FROM ranked_runs
    WHERE recency_rank <= 20
    GROUP BY pipeline_name
)
SELECT
    latest.pipeline_name,
    latest.pipeline_run_key AS latest_pipeline_run_key,
    latest.snapshot_key AS latest_snapshot_key,
    latest.orchestrator,
    latest.run_status AS latest_run_status,
    latest.started_at_utc AS latest_started_at_utc,
    latest.completed_at_utc AS latest_completed_at_utc,
    DATEDIFF_BIG(
        MILLISECOND,
        latest.started_at_utc,
        COALESCE(latest.completed_at_utc, SYSUTCDATETIME())
    ) AS latest_duration_milliseconds,
    latest.rows_read AS latest_rows_read,
    latest.rows_loaded AS latest_rows_loaded,
    latest.rows_rejected AS latest_rows_rejected,
    latest.error_message AS latest_error_message,
    history.recent_run_count,
    history.recent_success_count,
    history.recent_failure_count,
    history.recent_success_rate_pct,
    CASE
        WHEN latest.run_status = 'STARTED' THEN 'RUNNING'
        WHEN latest.run_status = 'FAILED' THEN 'ACTION REQUIRED'
        WHEN
            latest.run_status = 'SUCCEEDED'
            AND history.recent_failure_count > 0
            THEN 'RECOVERED'
        WHEN history.recent_success_rate_pct >= 95 THEN 'HEALTHY'
        WHEN history.recent_success_rate_pct >= 80 THEN 'WATCH'
        ELSE 'WATCH'
    END AS pipeline_health_status
FROM ranked_runs AS latest
INNER JOIN recent_history AS history
    ON history.pipeline_name = latest.pipeline_name
WHERE latest.recency_rank = 1;
