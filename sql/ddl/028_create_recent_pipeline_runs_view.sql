/*
Creates the approved recent pipeline monitoring view.
*/

CREATE OR ALTER VIEW analytics.vw_recent_pipeline_runs
AS
SELECT TOP (200)
    run.pipeline_run_key,
    run.snapshot_key,
    snapshot.downloaded_at_utc AS snapshot_downloaded_at_utc,
    run.pipeline_name,
    run.orchestrator,
    run.external_run_id,
    run.run_status,
    run.started_at_utc,
    run.completed_at_utc,
    DATEDIFF_BIG(
        MILLISECOND,
        run.started_at_utc,
        COALESCE(run.completed_at_utc, SYSUTCDATETIME())
    ) AS duration_milliseconds,
    run.rows_read,
    run.rows_loaded,
    run.rows_rejected,
    run.error_message
FROM governance.pipeline_run AS run
LEFT JOIN governance.source_snapshot AS snapshot
    ON snapshot.snapshot_key = run.snapshot_key
ORDER BY run.started_at_utc DESC, run.pipeline_run_key DESC;
