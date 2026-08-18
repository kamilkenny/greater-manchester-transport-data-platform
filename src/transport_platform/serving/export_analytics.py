from __future__ import annotations

import argparse
import os
import re
import sqlite3
import tempfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any

from transport_platform.database.sql_server import connect
from transport_platform.settings import Settings, get_settings

EXPORT_PIPELINE_NAME = "export_gtfs_analytics_sqlite"
ORCHESTRATOR = "Python"
FETCH_BATCH_SIZE = 5_000
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class ViewExport:
    """One governed SQL Server view and its SQLite table contract."""

    table_name: str
    source_view: str
    index_columns: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True)
class ExportMetrics:
    """Summary of one completed serving database export."""

    output_path: Path
    exported_at_utc: datetime
    table_count: int
    total_rows: int
    table_rows: dict[str, int]
    integrity_status: str


APPROVED_EXPORTS: tuple[ViewExport, ...] = (
    ViewExport("dashboard_kpis", "analytics.vw_dashboard_kpis"),
    ViewExport("platform_summary", "analytics.vw_platform_summary"),
    ViewExport(
        "network_daily_summary",
        "analytics.vw_network_daily_summary",
        (("service_date",),),
    ),
    ViewExport(
        "route_service_daily",
        "analytics.vw_route_service_daily",
        (("service_date",), ("route_id", "service_date")),
    ),
    ViewExport(
        "route_summary",
        "analytics.vw_route_summary",
        (("route_id",), ("transport_mode",)),
    ),
    ViewExport(
        "route_service_intelligence",
        "analytics.vw_route_service_intelligence",
        (("network_service_rank",), ("route_id",)),
    ),
    ViewExport(
        "stop_summary",
        "analytics.vw_stop_summary",
        (("stop_id",), ("zone_id",)),
    ),
    ViewExport(
        "stop_service_intelligence",
        "analytics.vw_stop_service_intelligence",
        (("network_activity_rank",), ("stop_id",)),
    ),
    ViewExport(
        "operator_summary",
        "analytics.vw_operator_summary",
        (("agency_id",),),
    ),
    ViewExport(
        "transport_mode_summary",
        "analytics.vw_transport_mode_summary",
        (("transport_mode",),),
    ),
    ViewExport(
        "location_summary",
        "analytics.vw_location_summary",
        (("location_group",),),
    ),
    ViewExport(
        "publication_changes",
        "analytics.vw_publication_changes",
        (("change_type",), ("entity_type",)),
    ),
    ViewExport(
        "publication_change_summary",
        "analytics.vw_publication_change_summary",
        (("current_snapshot_key",),),
    ),
    ViewExport(
        "stop_location_changes",
        "analytics.vw_stop_location_changes",
        (("current_snapshot_key",), ("stop_id",)),
    ),
    ViewExport(
        "pipeline_health",
        "analytics.vw_pipeline_health",
        (("pipeline_name",), ("pipeline_health_status",)),
    ),
    ViewExport(
        "recent_pipeline_runs",
        "analytics.vw_recent_pipeline_runs",
        (("pipeline_name",), ("started_at_utc",)),
    ),
    ViewExport(
        "data_quality_results",
        "analytics.vw_data_quality_results",
        (("check_status",), ("checked_at_utc",)),
    ),
)


def _quote_identifier(identifier: str) -> str:
    """Quote a trusted SQLite identifier after strict validation."""

    if not IDENTIFIER_PATTERN.fullmatch(identifier):
        raise ValueError(f"Unsafe SQLite identifier: {identifier!r}")
    return f'"{identifier}"'


def _sqlite_type(type_code: object) -> str:
    """Map a DB API type descriptor to a practical SQLite affinity."""

    if not isinstance(type_code, type):
        return "TEXT"
    if issubclass(type_code, bool | int):
        return "INTEGER"
    if issubclass(type_code, float | Decimal):
        return "REAL"
    if issubclass(type_code, bytes | bytearray | memoryview):
        return "BLOB"
    return "TEXT"


def _normalise_value(value: object) -> object:
    """Convert SQL Server values into deterministic SQLite values."""

    if value is None or isinstance(value, str | int | float | bytes):
        return value
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat(timespec="milliseconds")
    if isinstance(value, date | time):
        return value.isoformat()
    if isinstance(value, bytearray | memoryview):
        return bytes(value)
    return str(value)


def _create_export_table(
    target: sqlite3.Connection,
    table_name: str,
    description: Sequence[Sequence[Any]],
) -> list[str]:
    """Create one SQLite table from an ODBC cursor description."""

    columns = [str(item[0]) for item in description]
    if not columns:
        raise RuntimeError(f"Source view for {table_name} returned no columns")
    if len(columns) != len(set(columns)):
        raise RuntimeError(f"Source view for {table_name} has duplicate columns")

    definitions = ", ".join(
        f"{_quote_identifier(column)} {_sqlite_type(item[1])}"
        for column, item in zip(columns, description, strict=True)
    )
    target.execute(
        f"CREATE TABLE {_quote_identifier(table_name)} ({definitions});"
    )
    return columns


def _copy_view(
    source: Any,
    target: sqlite3.Connection,
    specification: ViewExport,
    *,
    fetch_batch_size: int = FETCH_BATCH_SIZE,
) -> int:
    """Stream one approved SQL Server view into SQLite."""

    if fetch_batch_size <= 0:
        raise ValueError("fetch_batch_size must be positive")

    source_cursor = source.cursor()
    source_cursor.execute(f"SELECT * FROM {specification.source_view};")
    description = source_cursor.description
    if description is None:
        raise RuntimeError(f"Unable to describe {specification.source_view}")

    columns = _create_export_table(target, specification.table_name, description)
    placeholders = ", ".join("?" for _ in columns)
    insert_sql = (
        f"INSERT INTO {_quote_identifier(specification.table_name)} "
        f"VALUES ({placeholders});"
    )
    row_count = 0

    while batch := source_cursor.fetchmany(fetch_batch_size):
        normalised = [
            tuple(_normalise_value(value) for value in row) for row in batch
        ]
        target.executemany(insert_sql, normalised)
        row_count += len(normalised)

    available_columns = set(columns)
    for index_number, index_columns in enumerate(
        specification.index_columns,
        start=1,
    ):
        if not set(index_columns).issubset(available_columns):
            missing = sorted(set(index_columns) - available_columns)
            raise RuntimeError(
                f"Index columns missing from {specification.table_name}: {missing}"
            )
        index_name = f"ix_{specification.table_name}_{index_number}"
        column_sql = ", ".join(_quote_identifier(item) for item in index_columns)
        target.execute(
            f"CREATE INDEX {_quote_identifier(index_name)} "
            f"ON {_quote_identifier(specification.table_name)} ({column_sql});"
        )

    return row_count


def _write_metadata(
    target: sqlite3.Connection,
    exported_at_utc: datetime,
    table_rows: dict[str, int],
) -> None:
    """Write a small manifest that supports freshness and integrity checks."""

    target.execute(
        """
        CREATE TABLE serving_metadata (
            metadata_key TEXT PRIMARY KEY,
            metadata_value TEXT NOT NULL
        );
        """
    )
    target.executemany(
        "INSERT INTO serving_metadata VALUES (?, ?);",
        (
            ("schema_version", "1"),
            ("exported_at_utc", exported_at_utc.isoformat(timespec="milliseconds")),
            ("table_count", str(len(table_rows))),
            ("total_rows", str(sum(table_rows.values()))),
        ),
    )
    target.execute(
        """
        CREATE TABLE export_manifest (
            table_name TEXT PRIMARY KEY,
            source_view TEXT NOT NULL,
            row_count INTEGER NOT NULL,
            exported_at_utc TEXT NOT NULL
        );
        """
    )
    source_lookup = {item.table_name: item.source_view for item in APPROVED_EXPORTS}
    target.executemany(
        "INSERT INTO export_manifest VALUES (?, ?, ?, ?);",
        (
            (
                table_name,
                source_lookup.get(table_name, "test_source"),
                row_count,
                exported_at_utc.isoformat(timespec="milliseconds"),
            )
            for table_name, row_count in table_rows.items()
        ),
    )


def _build_sqlite_database(
    source: Any,
    output_path: Path,
    specifications: Iterable[ViewExport] = APPROVED_EXPORTS,
) -> ExportMetrics:
    """Build and atomically publish one read optimised serving database."""

    resolved_output = output_path.resolve()
    resolved_output.parent.mkdir(parents=True, exist_ok=True)
    exported_at_utc = datetime.now(UTC)
    table_rows: dict[str, int] = {}

    temporary_handle = tempfile.NamedTemporaryFile(
        prefix=f".{resolved_output.name}.",
        suffix=".tmp",
        dir=resolved_output.parent,
        delete=False,
    )
    temporary_path = Path(temporary_handle.name)
    temporary_handle.close()

    try:
        with sqlite3.connect(temporary_path) as target:
            target.execute("PRAGMA journal_mode = DELETE;")
            target.execute("PRAGMA synchronous = FULL;")
            target.execute("PRAGMA foreign_keys = ON;")

            for specification in specifications:
                table_rows[specification.table_name] = _copy_view(
                    source,
                    target,
                    specification,
                )

            _write_metadata(target, exported_at_utc, table_rows)
            target.execute("ANALYZE;")
            target.commit()
            integrity_status = str(
                target.execute("PRAGMA integrity_check;").fetchone()[0]
            )
            if integrity_status.lower() != "ok":
                raise RuntimeError(
                    f"SQLite integrity check failed: {integrity_status}"
                )

        os.replace(temporary_path, resolved_output)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise

    return ExportMetrics(
        output_path=resolved_output,
        exported_at_utc=exported_at_utc,
        table_count=len(table_rows),
        total_rows=sum(table_rows.values()),
        table_rows=table_rows,
        integrity_status=integrity_status,
    )


def _latest_snapshot_key(settings: Settings) -> int | None:
    """Return the snapshot represented by the governed analytics views."""

    with connect(settings=settings) as connection:
        row = (
            connection.cursor()
            .execute(
                """
                SELECT TOP (1) snapshot_key
                FROM analytics.vw_platform_summary;
                """
            )
            .fetchone()
        )
    return None if row is None or row[0] is None else int(row[0])


def _record_export_run(
    settings: Settings,
    *,
    snapshot_key: int | None,
    started_at_utc: datetime,
    metrics: ExportMetrics | None,
    error: Exception | None,
) -> None:
    """Write the final export outcome to the central pipeline audit."""

    run_status = "FAILED" if error is not None else "SUCCEEDED"
    rows = 0 if metrics is None else metrics.total_rows
    error_message = None if error is None else str(error)[:4000]

    with connect(settings=settings) as connection:
        connection.cursor().execute(
            """
            INSERT INTO governance.pipeline_run (
                snapshot_key,
                pipeline_name,
                orchestrator,
                run_status,
                started_at_utc,
                completed_at_utc,
                rows_read,
                rows_loaded,
                error_message
            )
            VALUES (?, ?, ?, ?, ?, SYSUTCDATETIME(), ?, ?, ?);
            """,
            snapshot_key,
            EXPORT_PIPELINE_NAME,
            ORCHESTRATOR,
            run_status,
            started_at_utc,
            rows,
            rows,
            error_message,
        )
        connection.commit()


def export_analytics(
    output_path: Path | None = None,
    *,
    settings: Settings | None = None,
) -> ExportMetrics:
    """Export approved analytics views into an atomic SQLite artefact."""

    resolved_settings = settings or get_settings()
    resolved_output = output_path or resolved_settings.serving_sqlite_path
    started_at_utc = datetime.now(UTC)
    snapshot_key = _latest_snapshot_key(resolved_settings)
    metrics: ExportMetrics | None = None

    try:
        with connect(settings=resolved_settings) as source:
            metrics = _build_sqlite_database(source, resolved_output)
    except Exception as error:
        try:
            _record_export_run(
                resolved_settings,
                snapshot_key=snapshot_key,
                started_at_utc=started_at_utc,
                metrics=None,
                error=error,
            )
        except Exception as audit_error:
            error.add_note(f"Export failure could not be audited: {audit_error}")
        raise

    _record_export_run(
        resolved_settings,
        snapshot_key=snapshot_key,
        started_at_utc=started_at_utc,
        metrics=metrics,
        error=None,
    )

    print(f"Serving database: {metrics.output_path}")
    print(f"Tables exported: {metrics.table_count:,}")
    print(f"Rows exported: {metrics.total_rows:,}")
    print(f"Integrity check: {metrics.integrity_status}")
    for table_name, row_count in metrics.table_rows.items():
        print(f"  {table_name}: {row_count:,}")
    return metrics


def main() -> None:
    """Export the current governed analytics contract for public serving."""

    parser = argparse.ArgumentParser(
        description="Export governed transport analytics to SQLite."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output path, defaults to SERVING_SQLITE_PATH.",
    )
    arguments = parser.parse_args()
    export_analytics(arguments.output)


if __name__ == "__main__":
    main()
