from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from transport_platform.database.sql_server import connect

REFERENCE_PIPELINE_NAME = "load_gtfs_reference_staging"
ORCHESTRATOR = "Python"
BATCH_SIZE = 10_000


@dataclass(frozen=True)
class TableLoadDefinition:
    """Map one GTFS source file to one staging table."""

    source_file: str
    target_table: str
    source_columns: tuple[str, ...]


REFERENCE_TABLES = (
    TableLoadDefinition(
        source_file="agency.txt",
        target_table="staging.gtfs_agency",
        source_columns=(
            "agency_id",
            "agency_name",
            "agency_url",
            "agency_timezone",
            "agency_lang",
            "agency_phone",
            "agency_fare_url",
            "agency_email",
            "agency_noc",
        ),
    ),
    TableLoadDefinition(
        source_file="calendar.txt",
        target_table="staging.gtfs_calendar",
        source_columns=(
            "service_id",
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
            "start_date",
            "end_date",
        ),
    ),
    TableLoadDefinition(
        source_file="calendar_dates.txt",
        target_table="staging.gtfs_calendar_dates",
        source_columns=("service_id", "date", "exception_type"),
    ),
    TableLoadDefinition(
        source_file="feed_info.txt",
        target_table="staging.gtfs_feed_info",
        source_columns=(
            "feed_publisher_name",
            "feed_publisher_url",
            "feed_lang",
            "feed_start_date",
            "feed_end_date",
            "feed_version",
        ),
    ),
)


def _normalise_optional_text(value: str | None) -> str | None:
    """Return source text or None when the GTFS field is blank."""

    if value is None or value == "":
        return None
    return value


def _row_hash(values: Sequence[str]) -> bytes:
    """Create a deterministic SHA256 hash from ordered source values."""

    canonical_row = "\x1f".join(values)
    return hashlib.sha256(canonical_row.encode("utf-8")).digest()


def iter_staging_rows(
    archive: ZipFile,
    definition: TableLoadDefinition,
    snapshot_key: int,
) -> Iterator[tuple[Any, ...]]:
    """Yield validated staging records without loading a file into memory."""

    with archive.open(definition.source_file) as binary_file:
        text_file = io.TextIOWrapper(
            binary_file,
            encoding="utf-8-sig",
            newline="",
        )

        with text_file:
            reader = csv.DictReader(text_file)
            source_headers = set(reader.fieldnames or [])
            missing_columns = set(definition.source_columns) - source_headers

            if missing_columns:
                missing_list = ", ".join(sorted(missing_columns))
                raise ValueError(
                    f"{definition.source_file} is missing columns: {missing_list}"
                )

            for source_row_number, source_row in enumerate(reader, start=2):
                if None in source_row or any(
                    value is None for value in source_row.values()
                ):
                    raise ValueError(
                        f"{definition.source_file} row {source_row_number} "
                        "contains more values than its header"
                    )

                values = [
                    source_row[column] or "" for column in definition.source_columns
                ]
                yield (
                    snapshot_key,
                    source_row_number,
                    *(_normalise_optional_text(value) for value in values),
                    _row_hash(values),
                )


def _batched(
    rows: Iterator[tuple[Any, ...]],
    batch_size: int = BATCH_SIZE,
) -> Iterator[list[tuple[Any, ...]]]:
    """Yield bounded batches from a streaming record iterator."""

    batch: list[tuple[Any, ...]] = []

    for row in rows:
        batch.append(row)
        if len(batch) == batch_size:
            yield batch
            batch = []

    if batch:
        yield batch


def _parse_gtfs_date(value: str | None) -> date | None:
    """Parse an optional GTFS YYYYMMDD date."""

    if not value:
        return None
    return datetime.strptime(value, "%Y%m%d").date()


def _parse_datetime(value: str | None) -> datetime | None:
    """Parse an ISO or HTTP timestamp and return naive UTC for DATETIME2."""

    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        parsed = parsedate_to_datetime(value)

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def _read_metadata(snapshot_path: Path) -> dict[str, Any]:
    """Read and validate metadata written by the snapshot downloader."""

    metadata_path = snapshot_path.with_suffix(".json")
    if not metadata_path.exists():
        raise FileNotFoundError(f"Snapshot metadata not found: {metadata_path}")

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    required_fields = {
        "source_url",
        "downloaded_at_utc",
        "file_name",
        "file_size_bytes",
        "sha256",
    }
    missing_fields = required_fields - metadata.keys()

    if missing_fields:
        missing_list = ", ".join(sorted(missing_fields))
        raise ValueError(f"Snapshot metadata missing fields: {missing_list}")

    return metadata


def _read_feed_information(snapshot_path: Path) -> dict[str, str]:
    """Read the first feed_info record for snapshot governance metadata."""

    with ZipFile(snapshot_path) as archive:
        with archive.open("feed_info.txt") as binary_file:
            text_file = io.TextIOWrapper(
                binary_file,
                encoding="utf-8-sig",
                newline="",
            )
            with text_file:
                return next(csv.DictReader(text_file), {})


def _register_snapshot(
    cursor: Any,
    metadata: dict[str, Any],
    feed_information: dict[str, str],
) -> int:
    """Return the existing or newly registered immutable snapshot key."""

    existing = cursor.execute(
        "SELECT snapshot_key FROM governance.source_snapshot WHERE sha256 = ?;",
        metadata["sha256"],
    ).fetchone()

    if existing is not None:
        return int(existing[0])

    inserted = cursor.execute(
        """
        INSERT INTO governance.source_snapshot (
            source_name,
            source_url,
            downloaded_at_utc,
            source_last_modified_utc,
            source_etag,
            file_name,
            file_size_bytes,
            sha256,
            feed_start_date,
            feed_end_date,
            feed_version,
            snapshot_status
        )
        OUTPUT INSERTED.snapshot_key
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'RECEIVED');
        """,
        "TfGM GTFS",
        metadata["source_url"],
        _parse_datetime(metadata["downloaded_at_utc"]),
        _parse_datetime(metadata.get("last_modified")),
        _normalise_optional_text(metadata.get("etag")),
        metadata["file_name"],
        int(metadata["file_size_bytes"]),
        metadata["sha256"],
        _parse_gtfs_date(feed_information.get("feed_start_date")),
        _parse_gtfs_date(feed_information.get("feed_end_date")),
        _normalise_optional_text(feed_information.get("feed_version")),
    ).fetchone()
    return int(inserted[0])


def _start_pipeline_run(
    cursor: Any,
    snapshot_key: int,
    pipeline_name: str,
) -> int:
    """Create and return one Python pipeline run record."""

    inserted = cursor.execute(
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
        pipeline_name,
        ORCHESTRATOR,
    ).fetchone()
    return int(inserted[0])


def _insert_table(
    connection: Any,
    cursor: Any,
    archive: ZipFile,
    definition: TableLoadDefinition,
    snapshot_key: int,
    batch_size: int = BATCH_SIZE,
    commit_each_batch: bool = False,
) -> int:
    """Replace one snapshot partition and return its loaded row count."""

    cursor.execute(
        f"DELETE FROM {definition.target_table} WHERE snapshot_key = ?;",
        snapshot_key,
    )
    if commit_each_batch:
        connection.commit()

    target_columns = (
        "snapshot_key",
        "source_row_number",
        *definition.source_columns,
        "row_hash",
    )
    quoted_columns = ", ".join(f"[{column}]" for column in target_columns)
    placeholders = ", ".join("?" for _ in target_columns)
    insert_sql = (
        f"INSERT INTO {definition.target_table} ({quoted_columns}) "
        f"VALUES ({placeholders});"
    )

    rows_loaded = 0
    cursor.fast_executemany = True
    rows = iter_staging_rows(archive, definition, snapshot_key)

    for batch in _batched(rows, batch_size=batch_size):
        cursor.executemany(insert_sql, batch)
        rows_loaded += len(batch)
        if commit_each_batch:
            connection.commit()

    return rows_loaded


def _bulk_copy_table(
    connection: Any,
    cursor: Any,
    archive: ZipFile,
    definition: TableLoadDefinition,
    snapshot_key: int,
    batch_size: int,
) -> int:
    """Replace one rolling staging table through the native TDS protocol."""

    cursor.execute(f"TRUNCATE TABLE {definition.target_table};")
    connection.commit()

    target_columns = [
        "snapshot_key",
        "source_row_number",
        *definition.source_columns,
        "row_hash",
    ]
    result = cursor.bulkcopy(
        definition.target_table,
        iter_staging_rows(archive, definition, snapshot_key),
        batch_size=batch_size,
        timeout=3600,
        column_mappings=target_columns,
        table_lock=True,
        keep_nulls=True,
        use_internal_transaction=True,
    )
    return int(result["rows_copied"])


def load_staging_table_group(
    snapshot_path: Path,
    definitions: Sequence[TableLoadDefinition],
    pipeline_name: str,
    summary_name: str,
    snapshot_status: str = "VALIDATED",
    batch_size: int = BATCH_SIZE,
    commit_each_batch: bool = False,
    use_native_bulk_copy: bool = False,
) -> dict[str, int]:
    """Register one snapshot and transactionally load a staging table group."""

    if not snapshot_path.exists():
        raise FileNotFoundError(f"Snapshot not found: {snapshot_path}")

    metadata = _read_metadata(snapshot_path)
    feed_information = _read_feed_information(snapshot_path)

    with connect() as connection:
        cursor = connection.cursor()
        snapshot_key = _register_snapshot(cursor, metadata, feed_information)
        pipeline_run_key = _start_pipeline_run(
            cursor,
            snapshot_key,
            pipeline_name,
        )
        connection.commit()

    row_counts: dict[str, int] = {}

    try:
        if use_native_bulk_copy:
            from transport_platform.database.sql_server import connect_bulk

            connection_context = connect_bulk()
        else:
            connection_context = connect()

        with connection_context as connection:
            cursor = connection.cursor()

            with ZipFile(snapshot_path) as archive:
                archive_names = set(archive.namelist())
                missing_files = {
                    definition.source_file for definition in definitions
                } - archive_names
                if missing_files:
                    missing_list = ", ".join(sorted(missing_files))
                    raise ValueError(f"Snapshot missing files: {missing_list}")

                for definition in definitions:
                    if use_native_bulk_copy:
                        rows_loaded = _bulk_copy_table(
                            connection,
                            cursor,
                            archive,
                            definition,
                            snapshot_key,
                            batch_size=batch_size,
                        )
                    else:
                        rows_loaded = _insert_table(
                            connection,
                            cursor,
                            archive,
                            definition,
                            snapshot_key,
                            batch_size=batch_size,
                            commit_each_batch=commit_each_batch,
                        )
                    row_counts[definition.source_file] = rows_loaded
                    print(f"Loaded {definition.source_file}: {rows_loaded:,} rows")

            total_rows = sum(row_counts.values())
            cursor.execute(
                """
                UPDATE governance.source_snapshot
                SET snapshot_status = ?
                WHERE snapshot_key = ?;

                UPDATE governance.pipeline_run
                SET
                    run_status = 'SUCCEEDED',
                    completed_at_utc = SYSUTCDATETIME(),
                    rows_read = ?,
                    rows_loaded = ?
                WHERE pipeline_run_key = ?;
                """,
                snapshot_status,
                snapshot_key,
                total_rows,
                total_rows,
                pipeline_run_key,
            )
            connection.commit()
    except Exception as error:
        try:
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
        except Exception as audit_error:
            error.add_note(
                "Pipeline failure could not be recorded immediately: "
                f"{audit_error}"
            )
        raise

    print(f"Snapshot key: {snapshot_key}")
    print(f"Pipeline run key: {pipeline_run_key}")
    print(f"Total {summary_name} rows loaded: {sum(row_counts.values()):,}")
    return row_counts


def load_reference_tables(snapshot_path: Path) -> dict[str, int]:
    """Register one snapshot and transactionally load reference staging."""

    return load_staging_table_group(
        snapshot_path=snapshot_path,
        definitions=REFERENCE_TABLES,
        pipeline_name=REFERENCE_PIPELINE_NAME,
        summary_name="reference",
    )


def main() -> None:
    """Load reference staging tables from one preserved GTFS snapshot."""

    parser = argparse.ArgumentParser(
        description="Load TfGM GTFS reference tables into local SQL Server."
    )
    parser.add_argument(
        "snapshot",
        type=Path,
        help="Path to a preserved TfGM GTFS ZIP file.",
    )
    arguments = parser.parse_args()
    load_reference_tables(arguments.snapshot)


if __name__ == "__main__":
    main()
