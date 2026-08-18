from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from transport_platform.orchestration import refresh_platform


def _settings(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        processed_data_dir=tmp_path / "processed",
        serving_sqlite_path=tmp_path / "serving/transport_dashboard.db",
    )


def _snapshot(tmp_path: Path) -> Path:
    snapshot_path = tmp_path / "snapshot.zip"
    snapshot_path.write_bytes(b"test snapshot")
    snapshot_path.with_suffix(".json").write_text(
        json.dumps({"sha256": "a" * 64}),
        encoding="utf-8",
    )
    return snapshot_path


def test_dry_run_writes_plan_without_executing_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "dry_run.json"
    monkeypatch.setattr(refresh_platform, "get_settings", lambda: _settings(tmp_path))
    monkeypatch.setattr(
        refresh_platform,
        "initialise_database",
        lambda: pytest.fail("dry run executed a pipeline stage"),
    )

    manifest = refresh_platform.run_refresh(
        dry_run=True,
        manifest_path=manifest_path,
    )

    assert manifest["status"] == "DRY_RUN"
    assert manifest["azure_deployment_performed"] is False
    assert "download_snapshot" in manifest["planned_stages"]
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == manifest


def test_registered_publication_is_skipped_without_force(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    snapshot_path = _snapshot(tmp_path)
    manifest_path = tmp_path / "skipped.json"
    monkeypatch.setattr(refresh_platform, "get_settings", lambda: _settings(tmp_path))
    monkeypatch.setattr(refresh_platform, "initialise_database", lambda: None)
    monkeypatch.setattr(
        refresh_platform,
        "_lookup_snapshot",
        lambda _sha256: (17, "WAREHOUSED"),
    )
    monkeypatch.setattr(
        refresh_platform,
        "_snapshot_is_complete",
        lambda _snapshot_key: True,
    )
    monkeypatch.setattr(
        refresh_platform,
        "profile_gtfs_snapshot",
        lambda _path: pytest.fail("unchanged publication was profiled"),
    )

    manifest = refresh_platform.run_refresh(
        snapshot_path=snapshot_path,
        manifest_path=manifest_path,
    )

    assert manifest["status"] == "SKIPPED_UNCHANGED"
    assert manifest["snapshot_key"] == 17
    assert manifest["existing_snapshot_status"] == "WAREHOUSED"
    assert [stage["name"] for stage in manifest["stages"]] == [
        "initialise_database"
    ]


def test_force_runs_complete_pipeline_in_dependency_order(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    snapshot_path = _snapshot(tmp_path)
    manifest_path = tmp_path / "completed.json"
    calls: list[str] = []

    monkeypatch.setattr(refresh_platform, "get_settings", lambda: _settings(tmp_path))
    monkeypatch.setattr(
        refresh_platform,
        "_lookup_snapshot",
        lambda _sha256: (23, "WAREHOUSED"),
    )
    monkeypatch.setattr(
        refresh_platform,
        "_snapshot_is_complete",
        lambda _snapshot_key: pytest.fail(
            "forced refresh queried snapshot completion"
        ),
    )
    monkeypatch.setattr(
        refresh_platform,
        "_resolve_snapshot_key",
        lambda _path: 23,
    )

    def operation(name: str, result: Any = None):
        def execute(*_args: Any, **_kwargs: Any) -> Any:
            calls.append(name)
            return result

        return execute

    monkeypatch.setattr(
        refresh_platform,
        "initialise_database",
        operation("initialise_database"),
    )
    monkeypatch.setattr(
        refresh_platform,
        "profile_gtfs_snapshot",
        operation("profile_gtfs_structure", tmp_path / "structure.json"),
    )
    monkeypatch.setattr(
        refresh_platform,
        "profile_gtfs_columns",
        operation("profile_gtfs_columns", tmp_path / "columns.json"),
    )
    monkeypatch.setattr(
        refresh_platform,
        "load_reference_tables",
        operation("load_reference_staging", {"agency.txt": 1}),
    )
    monkeypatch.setattr(
        refresh_platform,
        "load_network_tables",
        operation("load_network_staging", {"routes.txt": 2}),
    )
    monkeypatch.setattr(
        refresh_platform,
        "load_high_volume_tables",
        operation("load_high_volume_staging", {"stop_times.txt": 3}),
    )
    monkeypatch.setattr(
        refresh_platform,
        "load_core_dimensions",
        operation("load_core_dimensions"),
    )
    monkeypatch.setattr(
        refresh_platform,
        "load_network_dimensions",
        operation("load_network_dimensions"),
    )
    monkeypatch.setattr(
        refresh_platform,
        "load_service_calendar",
        operation("load_service_calendar"),
    )
    monkeypatch.setattr(
        refresh_platform,
        "load_trip_dimension",
        operation("load_trip_dimension"),
    )
    monkeypatch.setattr(
        refresh_platform,
        "load_shape_points",
        operation("load_shape_points"),
    )
    monkeypatch.setattr(
        refresh_platform,
        "load_scheduled_stop_events",
        operation("load_scheduled_stop_events"),
    )
    monkeypatch.setattr(
        refresh_platform,
        "load_daily_service_facts",
        operation("load_daily_service_facts"),
    )
    monkeypatch.setattr(
        refresh_platform,
        "load_publication_changes",
        operation("load_publication_changes"),
    )
    monkeypatch.setattr(
        refresh_platform,
        "export_analytics",
        operation("export_serving_analytics"),
    )
    monkeypatch.setattr(
        refresh_platform,
        "build_package",
        operation("build_azure_package", {"database_integrity": "ok"}),
    )

    manifest = refresh_platform.run_refresh(
        snapshot_path=snapshot_path,
        force=True,
        manifest_path=manifest_path,
    )

    assert manifest["status"] == "SUCCEEDED"
    assert manifest["snapshot_key"] == 23
    assert manifest["azure_deployment_performed"] is False
    assert calls == [
        "initialise_database",
        "profile_gtfs_structure",
        "profile_gtfs_columns",
        "load_reference_staging",
        "load_network_staging",
        "load_high_volume_staging",
        "load_core_dimensions",
        "load_network_dimensions",
        "load_service_calendar",
        "load_trip_dimension",
        "load_shape_points",
        "load_scheduled_stop_events",
        "load_daily_service_facts",
        "load_publication_changes",
        "export_serving_analytics",
        "build_azure_package",
    ]


def test_failed_stage_is_written_to_manifest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "failed.json"
    monkeypatch.setattr(refresh_platform, "get_settings", lambda: _settings(tmp_path))

    def fail_initialisation() -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(
        refresh_platform,
        "initialise_database",
        fail_initialisation,
    )

    with pytest.raises(refresh_platform.PipelineStageError):
        refresh_platform.run_refresh(manifest_path=manifest_path)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "FAILED"
    assert manifest["failed_stage"] == "initialise_database"
    assert manifest["stages"][0]["error_type"] == "RuntimeError"
    assert manifest["stages"][0]["error_message"] == "database unavailable"
