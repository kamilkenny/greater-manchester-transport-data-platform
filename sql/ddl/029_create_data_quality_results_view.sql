/*
Creates the approved data quality monitoring view.
*/

CREATE OR ALTER VIEW analytics.vw_data_quality_results
AS
SELECT TOP (500)
    result.data_quality_result_key,
    result.pipeline_run_key,
    result.snapshot_key,
    run.pipeline_name,
    result.check_name,
    result.check_category,
    result.table_name,
    result.check_status,
    result.records_checked,
    result.failed_records,
    result.threshold_value,
    result.observed_value,
    result.details,
    result.checked_at_utc
FROM governance.data_quality_result AS result
INNER JOIN governance.pipeline_run AS run
    ON run.pipeline_run_key = result.pipeline_run_key
ORDER BY
    result.checked_at_utc DESC,
    result.data_quality_result_key DESC;
