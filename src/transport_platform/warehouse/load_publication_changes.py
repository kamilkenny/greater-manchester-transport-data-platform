from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any

from transport_platform.database.sql_server import connect

PUBLICATION_CHANGE_PIPELINE_NAME = "build_gtfs_publication_changes"
ORCHESTRATOR = "Python"


@dataclass(frozen=True)
class PublicationChangeMetrics:
    """Counts produced by one publication comparison."""

    previous_snapshot_key: int | None
    current_snapshot_key: int
    previous_entity_rows: int
    current_entity_rows: int
    changes_detected: int
    changes_inserted: int
    added_changes: int
    removed_changes: int
    modified_changes: int

    @property
    def rows_read(self) -> int:
        """Return entity versions considered across both publications."""

        return self.previous_entity_rows + self.current_entity_rows

    @property
    def rows_loaded(self) -> int:
        """Return publication change facts inserted."""

        return self.changes_inserted


def _metrics_from_row(row: Any) -> PublicationChangeMetrics:
    """Convert the stored procedure result into typed metrics."""

    if row is None:
        raise RuntimeError("Publication change procedure returned no metrics")

    return PublicationChangeMetrics(
        previous_snapshot_key=None if row[0] is None else int(row[0]),
        current_snapshot_key=int(row[1]),
        previous_entity_rows=int(row[2]),
        current_entity_rows=int(row[3]),
        changes_detected=int(row[4]),
        changes_inserted=int(row[5]),
        added_changes=int(row[6]),
        removed_changes=int(row[7]),
        modified_changes=int(row[8]),
    )


def _start_pipeline_run(snapshot_key: int) -> int:
    """Create and commit an audited comparison attempt."""

    with connect() as connection:
        inserted = (
            connection.cursor()
            .execute(
                """
                INSERT INTO governance.pipeline_run (
                    snapshot_key,
                    pipeline_name,
                    orchestrator,
                    run_status,
                    started_at_utc
                )
                OUTPUT INSERTED.pipeline_run_key
                VALUES (?, ?, ?, 'STARTED', SYSUTCDATETIME());
                """,
                snapshot_key,
                PUBLICATION_CHANGE_PIPELINE_NAME,
                ORCHESTRATOR,
            )
            .fetchone()
        )
        connection.commit()

    return int(inserted[0])


def _record_pipeline_success(
    pipeline_run_key: int,
    metrics: PublicationChangeMetrics,
) -> None:
    """Record successful completion independently of the comparison."""

    with connect() as connection:
        connection.cursor().execute(
            """
            UPDATE governance.pipeline_run
            SET
                run_status = 'SUCCEEDED',
                completed_at_utc = SYSUTCDATETIME(),
                rows_read = ?,
                rows_loaded = ?
            WHERE pipeline_run_key = ?;
            """,
            metrics.rows_read,
            metrics.rows_loaded,
            pipeline_run_key,
        )
        connection.commit()


def _record_pipeline_failure(pipeline_run_key: int, error: Exception) -> None:
    """Record a failed comparison independently."""

    with connect() as connection:
        connection.cursor().execute(
            """
            UPDATE governance.pipeline_run
            SET
                run_status = 'FAILED',
                completed_at_utc = SYSUTCDATETIME(),
                error_message = ?
            WHERE pipeline_run_key = ?;
            """,
            str(error)[:4000],
            pipeline_run_key,
        )
        connection.commit()


def load_publication_changes(
    current_snapshot_key: int,
    *,
    previous_snapshot_key: int | None = None,
) -> PublicationChangeMetrics:
    """Compare one snapshot with its most recent earlier warehouse snapshot."""

    if current_snapshot_key <= 0:
        raise ValueError("current_snapshot_key must be a positive integer")
    if previous_snapshot_key is not None and previous_snapshot_key <= 0:
        raise ValueError("previous_snapshot_key must be a positive integer")
    if (
        previous_snapshot_key is not None
        and previous_snapshot_key >= current_snapshot_key
    ):
        raise ValueError("previous_snapshot_key must be less than current_snapshot_key")

    pipeline_run_key = _start_pipeline_run(current_snapshot_key)

    try:
        with connect() as connection:
            result = (
                connection.cursor()
                .execute(
                    """
                    EXEC warehouse.load_publication_changes
                        @current_snapshot_key = ?,
                        @previous_snapshot_key = ?;
                    """,
                    current_snapshot_key,
                    previous_snapshot_key,
                )
                .fetchone()
            )
            metrics = _metrics_from_row(result)
            connection.commit()

        _record_pipeline_success(pipeline_run_key, metrics)
    except Exception as error:
        try:
            _record_pipeline_failure(pipeline_run_key, error)
        except Exception as audit_error:
            error.add_note(
                f"Pipeline failure could not be recorded immediately: {audit_error}"
            )
        raise

    print(f"Current snapshot key: {metrics.current_snapshot_key}")
    print(f"Previous snapshot key: {metrics.previous_snapshot_key}")
    print(f"Pipeline run key: {pipeline_run_key}")
    print(f"Previous entity rows: {metrics.previous_entity_rows:,}")
    print(f"Current entity rows: {metrics.current_entity_rows:,}")
    print(f"Changes detected: {metrics.changes_detected:,}")
    print(f"Changes inserted: {metrics.changes_inserted:,}")
    print(f"Added entities: {metrics.added_changes:,}")
    print(f"Removed entities: {metrics.removed_changes:,}")
    print(f"Modified entities: {metrics.modified_changes:,}")
    return metrics


def main() -> None:
    """Compare one warehouse snapshot with its predecessor."""

    parser = argparse.ArgumentParser(
        description="Build GTFS publication change facts."
    )
    parser.add_argument(
        "current_snapshot_key",
        type=int,
        help="Current loaded warehouse snapshot key.",
    )
    parser.add_argument(
        "--previous-snapshot-key",
        type=int,
        default=None,
        help="Earlier snapshot key, defaults to the latest eligible predecessor.",
    )
    arguments = parser.parse_args()
    load_publication_changes(
        arguments.current_snapshot_key,
        previous_snapshot_key=arguments.previous_snapshot_key,
    )


if __name__ == "__main__":
    main()
