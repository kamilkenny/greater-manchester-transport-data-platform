/*
Creates geographic stop movement intelligence across publications.
*/

CREATE OR ALTER VIEW analytics.vw_stop_location_changes
AS
SELECT
    change.publication_change_key,
    change.previous_snapshot_key,
    change.current_snapshot_key,
    change.entity_id AS stop_id,
    previous_stop.stop_name AS previous_stop_name,
    current_stop.stop_name AS current_stop_name,
    previous_stop.stop_latitude AS previous_latitude,
    previous_stop.stop_longitude AS previous_longitude,
    current_stop.stop_latitude AS current_latitude,
    current_stop.stop_longitude AS current_longitude,
    CAST(
        geography::Point(
            previous_stop.stop_latitude,
            previous_stop.stop_longitude,
            4326
        ).STDistance(
            geography::Point(
                current_stop.stop_latitude,
                current_stop.stop_longitude,
                4326
            )
        )
        AS DECIMAL(18, 2)
    ) AS location_change_metres,
    change.detected_at_utc
FROM warehouse.fact_publication_change AS change
INNER JOIN warehouse.dim_stop AS previous_stop
    ON previous_stop.stop_id = change.entity_id
    AND previous_stop.valid_from_snapshot_key <= change.previous_snapshot_key
    AND (
        previous_stop.valid_to_snapshot_key IS NULL
        OR previous_stop.valid_to_snapshot_key > change.previous_snapshot_key
    )
INNER JOIN warehouse.dim_stop AS current_stop
    ON current_stop.stop_id = change.entity_id
    AND current_stop.valid_from_snapshot_key <= change.current_snapshot_key
    AND (
        current_stop.valid_to_snapshot_key IS NULL
        OR current_stop.valid_to_snapshot_key > change.current_snapshot_key
    )
WHERE
    change.entity_type = 'STOP'
    AND change.change_type = 'MODIFIED'
    AND (
        previous_stop.stop_latitude <> current_stop.stop_latitude
        OR previous_stop.stop_longitude <> current_stop.stop_longitude
    );
