from __future__ import annotations

from pathlib import Path

DDL_DIRECTORY = Path(__file__).resolve().parents[1] / "sql" / "ddl"

VIEW_FILES = {
    "022_create_platform_summary_view.sql": "analytics.vw_platform_summary",
    "023_create_route_service_daily_view.sql": (
        "analytics.vw_route_service_daily"
    ),
    "024_create_route_summary_view.sql": "analytics.vw_route_summary",
    "025_create_stop_summary_view.sql": "analytics.vw_stop_summary",
    "026_create_publication_changes_view.sql": (
        "analytics.vw_publication_changes"
    ),
    "027_create_publication_change_summary_view.sql": (
        "analytics.vw_publication_change_summary"
    ),
    "028_create_recent_pipeline_runs_view.sql": (
        "analytics.vw_recent_pipeline_runs"
    ),
    "029_create_data_quality_results_view.sql": (
        "analytics.vw_data_quality_results"
    ),
    "030_create_network_daily_summary_view.sql": (
        "analytics.vw_network_daily_summary"
    ),
    "031_create_operator_summary_view.sql": "analytics.vw_operator_summary",
    "032_create_transport_mode_summary_view.sql": (
        "analytics.vw_transport_mode_summary"
    ),
    "033_create_route_service_intelligence_view.sql": (
        "analytics.vw_route_service_intelligence"
    ),
    "034_create_stop_service_intelligence_view.sql": (
        "analytics.vw_stop_service_intelligence"
    ),
    "035_create_location_summary_view.sql": "analytics.vw_location_summary",
    "036_create_stop_location_changes_view.sql": (
        "analytics.vw_stop_location_changes"
    ),
    "037_create_pipeline_health_view.sql": "analytics.vw_pipeline_health",
    "038_create_dashboard_kpis_view.sql": "analytics.vw_dashboard_kpis",
}


def test_each_approved_view_has_an_independent_sql_server_batch() -> None:
    for file_name, view_name in VIEW_FILES.items():
        sql = (DDL_DIRECTORY / file_name).read_text(encoding="utf-8")
        view_position = sql.index("CREATE OR ALTER VIEW")

        assert sql.count("CREATE OR ALTER VIEW") == 1
        assert f"CREATE OR ALTER VIEW {view_name}" in sql
        assert "SET NOCOUNT ON" not in sql[:view_position]
        assert "SET XACT_ABORT ON" not in sql[:view_position]


def test_views_expose_only_explicit_governed_columns() -> None:
    for file_name in VIEW_FILES:
        sql = (DDL_DIRECTORY / file_name).read_text(encoding="utf-8")

        assert "SELECT *" not in sql.upper()
        assert "staging." not in sql.lower()


def test_route_and_stop_views_use_latest_loaded_snapshot() -> None:
    route_sql = (
        DDL_DIRECTORY / "023_create_route_service_daily_view.sql"
    ).read_text(encoding="utf-8")
    stop_sql = (DDL_DIRECTORY / "025_create_stop_summary_view.sql").read_text(
        encoding="utf-8"
    )

    for sql in (route_sql, stop_sql):
        assert "snapshot_status = 'LOADED'" in sql
        assert "downloaded_at_utc DESC" in sql

    assert "warehouse.fact_route_service_day" in route_sql
    assert "warehouse.fact_stop_service_day" in stop_sql


def test_monitoring_views_are_bounded_for_public_serving() -> None:
    pipeline_sql = (
        DDL_DIRECTORY / "028_create_recent_pipeline_runs_view.sql"
    ).read_text(encoding="utf-8")
    quality_sql = (
        DDL_DIRECTORY / "029_create_data_quality_results_view.sql"
    ).read_text(encoding="utf-8")

    assert "SELECT TOP (200)" in pipeline_sql
    assert "SELECT TOP (500)" in quality_sql


def test_service_intelligence_is_ranked_and_transparently_scheduled() -> None:
    route_sql = (
        DDL_DIRECTORY / "033_create_route_service_intelligence_view.sql"
    ).read_text(encoding="utf-8")
    stop_sql = (
        DDL_DIRECTORY / "034_create_stop_service_intelligence_view.sql"
    ).read_text(encoding="utf-8")

    assert "scheduled_service_score" in route_sql
    assert "network_service_rank" in route_sql
    assert "frequency_band" in route_sql
    assert "not measures of actual" in route_sql
    assert "scheduled_activity_score" in stop_sql
    assert "network_activity_rank" in stop_sql
    assert "not passenger demand" in stop_sql


def test_dashboard_contract_includes_freshness_location_and_health() -> None:
    summary_sql = (
        DDL_DIRECTORY / "022_create_platform_summary_view.sql"
    ).read_text(encoding="utf-8")
    location_sql = (
        DDL_DIRECTORY / "036_create_stop_location_changes_view.sql"
    ).read_text(encoding="utf-8")
    health_sql = (
        DDL_DIRECTORY / "037_create_pipeline_health_view.sql"
    ).read_text(encoding="utf-8")
    dashboard_sql = (
        DDL_DIRECTORY / "038_create_dashboard_kpis_view.sql"
    ).read_text(encoding="utf-8")

    assert "freshness_status" in summary_sql
    assert "location_change_metres" in location_sql
    assert "recent_success_rate_pct" in health_sql
    assert "pipeline_health_status" in health_sql
    assert "recent_failure_count > 0" in health_sql
    assert "THEN 'RECOVERED'" in health_sql
    assert "ELSE 'UNSTABLE'" not in health_sql
    assert "leading_route" in dashboard_sql
    assert "leading_stop" in dashboard_sql
    assert "recovered_pipeline_count" in dashboard_sql
    assert "service_ready_pipeline_count" in dashboard_sql
    assert "action_required_pipeline_count" in dashboard_sql
