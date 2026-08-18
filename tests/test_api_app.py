from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from transport_platform.api.app import create_app


@pytest.fixture
def serving_database(tmp_path: Path) -> Path:
    database_path = tmp_path / "transport_dashboard.db"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE serving_metadata (
                metadata_key TEXT PRIMARY KEY,
                metadata_value TEXT NOT NULL
            );
            INSERT INTO serving_metadata VALUES
                ('exported_at_utc', '2026-08-18T19:45:47.242+00:00'),
                ('schema_version', '1'),
                ('table_count', '17'),
                ('total_rows', '203071');

            CREATE TABLE dashboard_kpis (
                snapshot_key INTEGER,
                operator_count INTEGER,
                route_count INTEGER,
                stop_count INTEGER,
                trip_count INTEGER,
                scheduled_stop_event_count INTEGER,
                high_frequency_route_count INTEGER,
                major_hub_count INTEGER,
                freshness_status TEXT,
                data_age_hours REAL,
                downloaded_at_utc TEXT,
                reporting_start_date TEXT,
                reporting_end_date TEXT,
                healthy_pipeline_count INTEGER,
                recovered_pipeline_count INTEGER,
                service_ready_pipeline_count INTEGER,
                action_required_pipeline_count INTEGER,
                running_pipeline_count INTEGER,
                monitored_pipeline_count INTEGER,
                leading_route TEXT,
                leading_route_score REAL
            );
            INSERT INTO dashboard_kpis VALUES (
                1, 28, 704, 15731, 78970, 3447466, 57, 2476,
                'DELAYED', 42.6, '2026-08-16T22:53:08.553',
                '2026-08-16', '2027-08-16', 6, 5, 11, 0, 0, 11,
                '17', 97.6
            );

            CREATE TABLE platform_summary (
                snapshot_key INTEGER,
                downloaded_at_utc TEXT,
                freshness_status TEXT
            );
            INSERT INTO platform_summary VALUES (
                1, '2026-08-16T22:53:08.553', 'DELAYED'
            );

            CREATE TABLE network_daily_summary (
                service_date TEXT,
                transport_mode TEXT,
                active_route_count INTEGER,
                scheduled_trip_count INTEGER,
                scheduled_stop_event_count INTEGER,
                average_headway_minutes REAL
            );
            INSERT INTO network_daily_summary VALUES
                ('2027-08-15', 'Bus', 658, 16200, 211000, 28.2),
                ('2027-08-15', 'Tram', 17, 1250, 14900, 6.5),
                ('2027-08-16', 'Bus', 660, 16300, 212000, 28.0),
                ('2027-08-16', 'Tram', 17, 1280, 15100, 6.4);

            CREATE TABLE transport_mode_summary (
                transport_mode TEXT,
                route_count INTEGER,
                operator_count INTEGER,
                total_scheduled_trips INTEGER,
                total_scheduled_stop_events INTEGER,
                average_route_daily_trips REAL,
                average_route_stop_coverage REAL,
                average_service_span_minutes REAL,
                average_headway_minutes REAL
            );
            INSERT INTO transport_mode_summary VALUES
                ('Bus', 658, 28, 5939468, 81100000, 28.24, 32.2, 722.0, 240.48),
                ('Tram', 17, 1, 458235, 5500000, 194.1, 25.2, 1130.0, 6.48);

            CREATE TABLE route_service_intelligence (
                network_service_rank INTEGER,
                route_id TEXT,
                route_display_name TEXT,
                operator_name TEXT,
                transport_mode TEXT,
                route_colour TEXT,
                route_text_colour TEXT,
                scheduled_service_score REAL,
                scheduled_service_band TEXT,
                frequency_band TEXT,
                average_daily_trips REAL,
                average_daily_unique_stops REAL,
                average_service_span_minutes REAL,
                average_headway_minutes REAL,
                total_scheduled_trips INTEGER
            );
            INSERT INTO route_service_intelligence VALUES
                (1, '17', '17', 'Bee Network', 'Bus', 'FFD400', '000000',
                 97.6, 'VERY HIGH', 'HIGH FREQUENCY', 194.07, 45.2, 1100, 7.15, 71000),
                (2, 'TRAM-A', 'Altrincham', 'Metrolink', 'Tram', '00A6B2', 'FFFFFF',
                 94.2, 'VERY HIGH', 'HIGH FREQUENCY', 180.2, 20.0, 1080, 6.5, 65000);

            CREATE TABLE stop_service_intelligence (
                network_activity_rank INTEGER,
                stop_id TEXT,
                stop_code TEXT,
                stop_name TEXT,
                stop_latitude REAL,
                stop_longitude REAL,
                zone_id TEXT,
                accessibility_status TEXT,
                scheduled_activity_score REAL,
                scheduled_activity_band TEXT,
                average_daily_trips REAL,
                average_daily_routes REAL,
                average_service_span_minutes REAL,
                average_headway_minutes REAL,
                total_scheduled_trips INTEGER
            );
            INSERT INTO stop_service_intelligence VALUES
                (1, 'STOP-1', 'MAN1', 'Charlotte Street', 53.478, -2.241,
                 NULL, 'Unknown', 100.0, 'MAJOR HUB', 1113.89, 21.69,
                 1150, 2.2, 400000),
                (2, 'STOP-2', 'MAN2', 'Piccadilly Gardens', 53.480, -2.237,
                 NULL, 'Accessible', 99.9, 'MAJOR HUB', 1140.96, 23.53,
                 1180, 2.1, 410000);

            CREATE TABLE operator_summary (
                agency_id TEXT,
                operator_name TEXT,
                route_count INTEGER,
                total_scheduled_trips INTEGER,
                total_scheduled_stop_events INTEGER,
                average_route_daily_trips REAL,
                average_route_stop_coverage REAL,
                average_service_span_minutes REAL,
                average_headway_minutes REAL
            );
            INSERT INTO operator_summary VALUES
                ('BEE', 'Bee Network', 500, 5000000, 70000000, 45.2, 30.1, 730, 18.2),
                ('MET', 'Metrolink', 17, 458235, 5500000, 194.1, 25.2, 1130, 6.48);

            CREATE TABLE location_summary (
                location_group TEXT,
                stop_count INTEGER,
                total_scheduled_trips INTEGER,
                average_stop_daily_trips REAL,
                average_route_choice REAL,
                accessible_stop_count INTEGER,
                inaccessible_stop_count INTEGER,
                unknown_accessibility_count INTEGER,
                centre_latitude REAL,
                centre_longitude REAL
            );
            INSERT INTO location_summary VALUES
                ('UNASSIGNED', 15731, 6397703, 1.1, 2.2, 67, 5, 15659, 53.48, -2.24);

            CREATE TABLE publication_change_summary (
                previous_snapshot_key INTEGER,
                previous_downloaded_at_utc TEXT,
                current_snapshot_key INTEGER,
                current_downloaded_at_utc TEXT,
                entity_type TEXT,
                change_type TEXT,
                change_count INTEGER,
                first_detected_at_utc TEXT,
                last_detected_at_utc TEXT
            );
            CREATE TABLE publication_changes (
                publication_change_key INTEGER,
                current_snapshot_key INTEGER,
                current_downloaded_at_utc TEXT,
                entity_type TEXT,
                entity_id TEXT,
                change_type TEXT,
                changed_fields TEXT,
                detected_at_utc TEXT
            );

            CREATE TABLE pipeline_health (
                pipeline_name TEXT,
                latest_pipeline_run_key INTEGER,
                latest_run_status TEXT,
                latest_started_at_utc TEXT,
                latest_completed_at_utc TEXT,
                latest_duration_milliseconds INTEGER,
                latest_rows_read INTEGER,
                latest_rows_loaded INTEGER,
                latest_rows_rejected INTEGER,
                latest_error_message TEXT,
                recent_run_count INTEGER,
                recent_success_count INTEGER,
                recent_failure_count INTEGER,
                recent_success_rate_pct REAL,
                pipeline_health_status TEXT
            );
            INSERT INTO pipeline_health VALUES
                ('load_gtfs_network_staging', 100, 'SUCCEEDED',
                 '2026-08-18T18:00:00', '2026-08-18T18:01:00', 60000,
                 1000, 1000, 0, NULL, 2, 2, 0, 100.0, 'HEALTHY'),
                ('build_gtfs_daily_service_facts', 101, 'SUCCEEDED',
                 '2026-08-18T18:01:00', '2026-08-18T18:08:00', 420000,
                 3000000, 5000000, 0, NULL, 3, 2, 1, 66.67, 'RECOVERED');

            CREATE TABLE recent_pipeline_runs (
                pipeline_run_key INTEGER,
                pipeline_name TEXT,
                run_status TEXT,
                started_at_utc TEXT,
                completed_at_utc TEXT,
                duration_milliseconds INTEGER,
                rows_read INTEGER,
                rows_loaded INTEGER,
                rows_rejected INTEGER,
                error_message TEXT
            );
            INSERT INTO recent_pipeline_runs VALUES
                (101, 'build_gtfs_daily_service_facts', 'SUCCEEDED',
                 '2026-08-18T18:01:00', '2026-08-18T18:08:00',
                 420000, 3000000, 5000000, 0, NULL);

            CREATE TABLE data_quality_results (
                data_quality_result_key INTEGER,
                pipeline_name TEXT,
                check_name TEXT,
                check_category TEXT,
                table_name TEXT,
                check_status TEXT,
                records_checked INTEGER,
                failed_records INTEGER,
                threshold_value REAL,
                observed_value REAL,
                details TEXT,
                checked_at_utc TEXT
            );
            """
        )
    return database_path


@pytest.fixture
def client(serving_database: Path) -> TestClient:
    return TestClient(create_app(serving_database))


def test_dashboard_health_and_static_assets(client: TestClient) -> None:
    health = client.get("/health")
    dashboard = client.get("/")
    stylesheet = client.get("/static/styles.css")

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["database_integrity"] == "ok"
    assert dashboard.status_code == 200
    assert "Greater Manchester Transport Intelligence" in dashboard.text
    assert '<meta name="author" content="Kamil Ridwan">' in dashboard.text
    assert dashboard.text.count("Designed and modelled by") == 2
    assert 'href="/static/styles.css"' in dashboard.text
    assert 'src="/static/app.js"' in dashboard.text
    assert stylesheet.status_code == 200
    assert "--yellow: #ffd400" in stylesheet.text


def test_overview_exposes_governed_kpis_and_methodology(client: TestClient) -> None:
    response = client.get("/api/overview")

    assert response.status_code == 200
    payload = response.json()
    assert payload["kpis"]["route_count"] == 704
    assert payload["kpis"]["service_ready_pipeline_count"] == 11
    assert payload["metadata"]["table_count"] == "17"
    assert "do not measure live punctuality" in payload["methodology"]


@pytest.mark.parametrize(
    ("path", "expected_key"),
    (
        ("/api/network-trends?days=90", "service_date"),
        ("/api/modes", "transport_mode"),
        ("/api/routes?limit=10", "route_id"),
        ("/api/stops?limit=10", "stop_id"),
        ("/api/map-stops?limit=100", "stop_latitude"),
        ("/api/operators?limit=10", "operator_name"),
        ("/api/locations", "location_group"),
    ),
)
def test_analytical_collection_endpoints(
    client: TestClient,
    path: str,
    expected_key: str,
) -> None:
    response = client.get(path)

    assert response.status_code == 200
    payload = response.json()
    assert payload
    assert expected_key in payload[0]


def test_monitoring_endpoints_handle_baseline_and_empty_quality(
    client: TestClient,
) -> None:
    publications = client.get("/api/publication-changes").json()
    pipelines = client.get("/api/pipelines").json()
    quality = client.get("/api/data-quality").json()

    assert publications == {"summary": [], "changes": []}
    assert len(pipelines["health"]) == 2
    assert pipelines["health"][0]["pipeline_health_status"] == "RECOVERED"
    assert quality == {
        "counts": {"PASS": 0, "WARN": 0, "FAIL": 0},
        "results": [],
    }


def test_route_filters_are_parameterised_and_validated(client: TestClient) -> None:
    tram_response = client.get("/api/routes?mode=Tram&sort_by=frequency")
    invalid_sort = client.get("/api/routes?sort_by=DROP%20TABLE")

    assert tram_response.status_code == 200
    assert [row["transport_mode"] for row in tram_response.json()] == ["Tram"]
    assert invalid_sort.status_code == 422


def test_missing_serving_database_reports_unavailable(tmp_path: Path) -> None:
    unavailable_client = TestClient(create_app(tmp_path / "missing.db"))

    health = unavailable_client.get("/health")
    overview = unavailable_client.get("/api/overview")

    assert health.status_code == 503
    assert health.json()["status"] == "unavailable"
    assert overview.status_code == 503
