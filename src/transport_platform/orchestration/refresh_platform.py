from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from typing import Any

from transport_platform.database.initialise import initialise_database
from transport_platform.database.sql_server import connect
from transport_platform.deployment.build_azure_package import build_package
from transport_platform.ingestion.download_gtfs import download_gtfs_snapshot
from transport_platform.ingestion.load_high_volume_tables import (
    load_high_volume_tables,
)
from transport_platform.ingestion.load_network_tables import load_network_tables
from transport_platform.ingestion.load_reference_tables import load_reference_tables
from transport_platform.serving.export_analytics import export_analytics
from transport_platform.settings import get_settings
from transport_platform.validation.profile_gtfs import profile_gtfs_snapshot
from transport_platform.validation.profile_gtfs_columns import profile_gtfs_columns
from transport_platform.warehouse.load_core_dimensions import load_core_dimensions
from transport_platform.warehouse.load_daily_service_facts import (
    load_daily_service_facts,
)
from transport_platform.warehouse.load_network_dimensions import (
    load_network_dimensions,
)
from transport_platform.warehouse.load_publication_changes import (
    load_publication_changes,
)
from transport_platform.warehouse.load_scheduled_stop_events import (
    load_scheduled_stop_events,
)
from transport_platform.warehouse.load_service_calendar import (
    load_service_calendar,
)
from transport_platform.warehouse.load_shape_points import load_shape_points
from transport_platform.warehouse.load_trip_dimension import load_trip_dimension

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PACKAGE_PATH = REPOSITORY_ROOT / "dist/gm_transport_dashboard_azure.zip"


@dataclass(frozen=True)
class StageResult:
    """Serializable outcome for one orchestration stage."""

    name: str
    status: str
    started_at_utc: str
    completed_at_utc: str
    duration_seconds: float
    result: Any = None
    error_type: str | None = None
    error_message: str | None = None


class PipelineStageError(RuntimeError):
    """Identify the exact failed stage while preserving its original error."""

    def __init__(self, stage_result: StageResult) -> None:
        self.stage_result = stage_result
        super().__init__(
            f"Pipeline stage failed: {stage_result.name}: "
            f"{stage_result.error_message}"
        )


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _isoformat(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds")


def _serialise(value: Any) -> Any:
    """Convert stage results into deterministic JSON compatible values."""

    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return _serialise(asdict(value))
    if isinstance(value, dict):
        return {
            str(key): _serialise(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, list | tuple | set):
        return [_serialise(item) for item in value]
    return str(value)


def _execute_stage(
    name: str,
    operation: Callable[[], Any],
) -> StageResult:
    """Execute one stage and capture timing, output and failure context."""

    started_at = _utc_now()
    started_timer = perf_counter()
    print(f"Starting stage: {name}")

    try:
        result = operation()
    except Exception as error:
        completed_at = _utc_now()
        stage_result = StageResult(
            name=name,
            status="FAILED",
            started_at_utc=_isoformat(started_at),
            completed_at_utc=_isoformat(completed_at),
            duration_seconds=round(perf_counter() - started_timer, 3),
            error_type=type(error).__name__,
            error_message=str(error)[:4000],
        )
        print(f"Failed stage: {name}: {error}")
        raise PipelineStageError(stage_result) from error

    completed_at = _utc_now()
    stage_result = StageResult(
        name=name,
        status="SUCCEEDED",
        started_at_utc=_isoformat(started_at),
        completed_at_utc=_isoformat(completed_at),
        duration_seconds=round(perf_counter() - started_timer, 3),
        result=_serialise(result),
    )
    print(
        f"Completed stage: {name} "
        f"({stage_result.duration_seconds:.3f} seconds)"
    )
    return stage_result


def _read_snapshot_metadata(snapshot_path: Path) -> dict[str, Any]:
    metadata_path = snapshot_path.with_suffix(".json")
    if not metadata_path.exists():
        raise FileNotFoundError(f"Snapshot metadata not found: {metadata_path}")

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    sha256 = metadata.get("sha256")
    if not isinstance(sha256, str) or len(sha256) != 64:
        raise ValueError("Snapshot metadata contains an invalid SHA256 value")
    return metadata


def _lookup_snapshot(sha256: str) -> tuple[int, str] | None:
    with connect() as connection:
        row = connection.cursor().execute(
            """
            SELECT snapshot_key, snapshot_status
            FROM governance.source_snapshot
            WHERE sha256 = ?;
            """,
            sha256,
        ).fetchone()

    if row is None:
        return None
    return int(row[0]), str(row[1])


def _snapshot_is_complete(snapshot_key: int) -> bool:
    """Return whether governed serving analytics were exported successfully."""

    with connect() as connection:
        row = connection.cursor().execute(
            """
            SELECT CASE WHEN EXISTS (
                SELECT 1
                FROM governance.pipeline_run
                WHERE snapshot_key = ?
                  AND pipeline_name = 'export_gtfs_analytics_sqlite'
                  AND run_status = 'SUCCEEDED'
            ) THEN 1 ELSE 0 END;
            """,
            snapshot_key,
        ).fetchone()
    return bool(row[0])


def _resolve_snapshot_key(snapshot_path: Path) -> int:
    metadata = _read_snapshot_metadata(snapshot_path)
    registered = _lookup_snapshot(metadata["sha256"])
    if registered is None:
        raise RuntimeError("Snapshot registration was not found after staging load")
    return registered[0]


def _default_manifest_path(started_at: datetime) -> Path:
    settings = get_settings()
    run_id = started_at.strftime("%Y%m%dT%H%M%SZ")
    return settings.processed_data_dir / "orchestration" / f"refresh_{run_id}.json"


def _write_manifest(manifest: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(f"{output_path.suffix}.tmp")
    temporary_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(output_path)
    print(f"Orchestration manifest: {output_path}")


def _planned_stages(build_azure_package: bool) -> list[str]:
    stages = [
        "initialise_database",
        "download_snapshot",
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
    ]
    if build_azure_package:
        stages.append("build_azure_package")
    return stages


def run_refresh(
    snapshot_path: Path | None = None,
    *,
    force: bool = False,
    build_azure: bool = True,
    manifest_path: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run one deterministic source to serving refresh."""

    started_at = _utc_now()
    resolved_manifest_path = manifest_path or _default_manifest_path(started_at)
    settings = get_settings()
    stages: list[StageResult] = []
    manifest: dict[str, Any] = {
        "run_id": started_at.strftime("%Y%m%dT%H%M%SZ"),
        "started_at_utc": _isoformat(started_at),
        "completed_at_utc": None,
        "status": "STARTED",
        "dry_run": dry_run,
        "force": force,
        "source_snapshot": str(snapshot_path) if snapshot_path else None,
        "snapshot_key": None,
        "planned_stages": _planned_stages(build_azure),
        "stages": [],
        "azure_deployment_performed": False,
    }

    if dry_run:
        completed_at = _utc_now()
        manifest.update(
            status="DRY_RUN",
            completed_at_utc=_isoformat(completed_at),
        )
        _write_manifest(manifest, resolved_manifest_path)
        return manifest

    def run(name: str, operation: Callable[[], Any]) -> StageResult:
        stage = _execute_stage(name, operation)
        stages.append(stage)
        manifest["stages"] = [_serialise(item) for item in stages]
        _write_manifest(manifest, resolved_manifest_path)
        return stage

    try:
        run("initialise_database", initialise_database)

        if snapshot_path is None:
            snapshot_stage = run("download_snapshot", download_gtfs_snapshot)
            resolved_snapshot_path = Path(snapshot_stage.result)
        else:
            resolved_snapshot_path = snapshot_path.resolve()
            if not resolved_snapshot_path.exists():
                raise FileNotFoundError(
                    f"Snapshot not found: {resolved_snapshot_path}"
                )

        manifest["source_snapshot"] = str(resolved_snapshot_path)
        metadata = _read_snapshot_metadata(resolved_snapshot_path)
        manifest["source_sha256"] = metadata["sha256"]
        existing_snapshot = _lookup_snapshot(metadata["sha256"])

        existing_is_complete = False
        if existing_snapshot is not None and not force:
            existing_is_complete = _snapshot_is_complete(existing_snapshot[0])

        if existing_snapshot is not None and existing_is_complete:
            completed_at = _utc_now()
            manifest.update(
                status="SKIPPED_UNCHANGED",
                completed_at_utc=_isoformat(completed_at),
                snapshot_key=existing_snapshot[0],
                existing_snapshot_status=existing_snapshot[1],
            )
            _write_manifest(manifest, resolved_manifest_path)
            return manifest

        if existing_snapshot is not None:
            manifest["resuming_snapshot"] = not force and not existing_is_complete

        run(
            "profile_gtfs_structure",
            lambda: profile_gtfs_snapshot(resolved_snapshot_path),
        )
        run(
            "profile_gtfs_columns",
            lambda: profile_gtfs_columns(resolved_snapshot_path),
        )
        run(
            "load_reference_staging",
            lambda: load_reference_tables(resolved_snapshot_path),
        )
        snapshot_key = _resolve_snapshot_key(resolved_snapshot_path)
        manifest["snapshot_key"] = snapshot_key

        run(
            "load_network_staging",
            lambda: load_network_tables(resolved_snapshot_path),
        )
        run(
            "load_high_volume_staging",
            lambda: load_high_volume_tables(resolved_snapshot_path),
        )
        run("load_core_dimensions", lambda: load_core_dimensions(snapshot_key))
        run(
            "load_network_dimensions",
            lambda: load_network_dimensions(snapshot_key),
        )
        run(
            "load_service_calendar",
            lambda: load_service_calendar(snapshot_key),
        )
        run("load_trip_dimension", lambda: load_trip_dimension(snapshot_key))
        run("load_shape_points", lambda: load_shape_points(snapshot_key))
        run(
            "load_scheduled_stop_events",
            lambda: load_scheduled_stop_events(snapshot_key),
        )
        run(
            "load_daily_service_facts",
            lambda: load_daily_service_facts(snapshot_key),
        )
        run(
            "load_publication_changes",
            lambda: load_publication_changes(snapshot_key),
        )
        run(
            "export_serving_analytics",
            lambda: export_analytics(settings.serving_sqlite_path),
        )

        if build_azure:
            run(
                "build_azure_package",
                lambda: build_package(
                    REPOSITORY_ROOT,
                    settings.serving_sqlite_path,
                    DEFAULT_PACKAGE_PATH,
                ),
            )
    except PipelineStageError as error:
        stages.append(error.stage_result)
        completed_at = _utc_now()
        manifest.update(
            status="FAILED",
            completed_at_utc=_isoformat(completed_at),
            failed_stage=error.stage_result.name,
            stages=[_serialise(item) for item in stages],
        )
        _write_manifest(manifest, resolved_manifest_path)
        raise
    except Exception as error:
        completed_at = _utc_now()
        manifest.update(
            status="FAILED",
            completed_at_utc=_isoformat(completed_at),
            failed_stage="orchestration",
            orchestration_error={
                "type": type(error).__name__,
                "message": str(error)[:4000],
            },
            stages=[_serialise(item) for item in stages],
        )
        _write_manifest(manifest, resolved_manifest_path)
        raise

    completed_at = _utc_now()
    manifest.update(
        status="SUCCEEDED",
        completed_at_utc=_isoformat(completed_at),
        stages=[_serialise(item) for item in stages],
    )
    _write_manifest(manifest, resolved_manifest_path)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run one governed TfGM source to serving refresh."
    )
    parser.add_argument(
        "--snapshot",
        type=Path,
        help="Use an existing preserved snapshot instead of downloading one.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reprocess a publication whose SHA256 is already registered.",
    )
    parser.add_argument(
        "--skip-package",
        action="store_true",
        help="Export analytics without building an Azure ZIP package.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        help="Write the orchestration manifest to this path.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Write the planned stages without executing them.",
    )
    arguments = parser.parse_args()

    manifest = run_refresh(
        snapshot_path=arguments.snapshot,
        force=arguments.force,
        build_azure=not arguments.skip_package,
        manifest_path=arguments.manifest,
        dry_run=arguments.dry_run,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
