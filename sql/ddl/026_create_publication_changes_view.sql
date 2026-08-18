/*
Creates the approved detailed publication change reporting view.
*/

CREATE OR ALTER VIEW analytics.vw_publication_changes
AS
SELECT
    change.publication_change_key,
    change.previous_snapshot_key,
    previous_snapshot.downloaded_at_utc AS previous_downloaded_at_utc,
    change.current_snapshot_key,
    current_snapshot.downloaded_at_utc AS current_downloaded_at_utc,
    change.entity_type,
    change.entity_id,
    change.change_type,
    change.changed_fields,
    change.change_details_json,
    change.detected_at_utc
FROM warehouse.fact_publication_change AS change
INNER JOIN governance.source_snapshot AS previous_snapshot
    ON previous_snapshot.snapshot_key = change.previous_snapshot_key
INNER JOIN governance.source_snapshot AS current_snapshot
    ON current_snapshot.snapshot_key = change.current_snapshot_key;
