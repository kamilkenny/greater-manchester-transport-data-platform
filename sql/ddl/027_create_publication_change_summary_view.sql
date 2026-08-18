/*
Creates the approved publication change summary view.
*/

CREATE OR ALTER VIEW analytics.vw_publication_change_summary
AS
SELECT
    previous_snapshot_key,
    previous_downloaded_at_utc,
    current_snapshot_key,
    current_downloaded_at_utc,
    entity_type,
    change_type,
    COUNT_BIG(*) AS change_count,
    MIN(detected_at_utc) AS first_detected_at_utc,
    MAX(detected_at_utc) AS last_detected_at_utc
FROM analytics.vw_publication_changes
GROUP BY
    previous_snapshot_key,
    previous_downloaded_at_utc,
    current_snapshot_key,
    current_downloaded_at_utc,
    entity_type,
    change_type;
