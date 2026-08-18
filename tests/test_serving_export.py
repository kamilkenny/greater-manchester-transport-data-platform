from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from transport_platform.serving.export_analytics import (
    APPROVED_EXPORTS,
    ViewExport,
    _build_sqlite_database,
    _normalise_value,
    _quote_identifier,
)


def _source_database() -> sqlite3.Connection:
    source = sqlite3.connect(":memory:")
    source.execute("ATTACH DATABASE ':memory:' AS analytics;")
    source.execute(
        """
        CREATE TABLE analytics.sample_view (
            route_id TEXT,
            service_date TEXT,
            scheduled_trips REAL
        );
        """
    )
    source.executemany(
        "INSERT INTO analytics.sample_view VALUES (?, ?, ?);",
        (
            ("17", "2026-08-16", 194.07),
            ("36", "2026-08-16", 143.58),
            ("17", "2026-08-17", 196.0),
        ),
    )
    return source


def test_approved_export_contract_covers_dashboard_domains() -> None:
    contracts = {item.table_name: item for item in APPROVED_EXPORTS}
    tables = set(contracts)

    assert len(APPROVED_EXPORTS) == 17
    assert "dashboard_kpis" in tables
    assert "network_daily_summary" in tables
    assert "route_service_intelligence" in tables
    assert "stop_service_intelligence" in tables
    assert "location_summary" in tables
    assert "publication_changes" in tables
    assert "pipeline_health" in tables
    assert "data_quality_results" in tables
    assert contracts["operator_summary"].index_columns == (("agency_id",),)
    assert contracts["location_summary"].index_columns == (
        ("location_group",),
    )


def test_build_sqlite_database_is_atomic_indexed_and_self_describing(
    tmp_path: Path,
) -> None:
    source = _source_database()
    output = tmp_path / "transport_dashboard.db"
    specification = ViewExport(
        "sample_routes",
        "analytics.sample_view",
        (("route_id", "service_date"),),
    )

    metrics = _build_sqlite_database(source, output, (specification,))

    assert metrics.output_path == output.resolve()
    assert metrics.table_count == 1
    assert metrics.total_rows == 3
    assert metrics.integrity_status == "ok"
    assert not list(tmp_path.glob("*.tmp"))

    with sqlite3.connect(output) as serving:
        rows = serving.execute(
            """
            SELECT route_id, service_date, scheduled_trips
            FROM sample_routes
            ORDER BY service_date, route_id;
            """
        ).fetchall()
        manifest = serving.execute(
            "SELECT table_name, row_count FROM export_manifest;"
        ).fetchone()
        index_count = serving.execute(
            """
            SELECT COUNT(*)
            FROM sqlite_master
            WHERE type = 'index' AND name = 'ix_sample_routes_1';
            """
        ).fetchone()[0]

    assert rows == [
        ("17", "2026-08-16", "194.07"),
        ("36", "2026-08-16", "143.58"),
        ("17", "2026-08-17", "196.0"),
    ]
    assert manifest == ("sample_routes", 3)
    assert index_count == 1


def test_invalid_index_contract_removes_partial_database(tmp_path: Path) -> None:
    source = _source_database()
    output = tmp_path / "transport_dashboard.db"
    specification = ViewExport(
        "sample_routes",
        "analytics.sample_view",
        (("missing_column",),),
    )

    with pytest.raises(RuntimeError, match="Index columns missing"):
        _build_sqlite_database(source, output, (specification,))

    assert not output.exists()


def test_sqlite_value_normalisation_is_deterministic() -> None:
    moment = datetime(2026, 8, 18, 17, 30, 4, 123456, tzinfo=UTC)

    assert _normalise_value(Decimal("42.60")) == 42.6
    assert _normalise_value(moment) == "2026-08-18T17:30:04.123+00:00"
    assert _normalise_value(date(2026, 8, 18)) == "2026-08-18"
    assert _normalise_value(memoryview(b"bee")) == b"bee"


def test_sqlite_identifiers_are_strictly_validated() -> None:
    assert _quote_identifier("route_summary") == '"route_summary"'

    with pytest.raises(ValueError, match="Unsafe SQLite identifier"):
        _quote_identifier("route_summary; DROP TABLE routes")
