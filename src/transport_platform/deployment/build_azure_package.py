from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_DATABASE = Path("data/serving/transport_dashboard.db")
DEFAULT_OUTPUT = Path("dist/gm_transport_dashboard_azure.zip")


def _database_metadata(database_path: Path) -> dict[str, str]:
    connection_uri = f"file:{database_path.resolve()}?mode=ro"
    with sqlite3.connect(connection_uri, uri=True) as connection:
        integrity = str(connection.execute("PRAGMA quick_check;").fetchone()[0])
        metadata_rows = connection.execute(
            "SELECT metadata_key, metadata_value FROM serving_metadata;"
        ).fetchall()
    if integrity != "ok":
        raise ValueError(f"Serving database integrity check failed: {integrity}")
    return {str(key): str(value) for key, value in metadata_rows}


def _git_commit(repository_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"
    return result.stdout.strip()


def _source_files(source_root: Path) -> list[Path]:
    return sorted(
        path
        for path in source_root.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix not in {".pyc", ".pyo"}
    )


def build_package(
    repository_root: Path,
    database_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Build a validated, self-contained Azure App Service ZIP package."""

    repository_root = repository_root.resolve()
    database_path = database_path.resolve()
    output_path = output_path.resolve()
    source_root = repository_root / "src"
    deployment_requirements = repository_root / "deploy/azure/requirements.txt"
    startup_script = repository_root / "deploy/azure/startup.sh"

    required_paths = (
        database_path,
        source_root,
        deployment_requirements,
        startup_script,
    )
    missing_paths = [path for path in required_paths if not path.exists()]
    if missing_paths:
        missing = ", ".join(str(path) for path in missing_paths)
        raise FileNotFoundError(f"Azure package inputs are unavailable: {missing}")

    database_metadata = _database_metadata(database_path)
    source_files = _source_files(source_root)
    manifest = {
        "application": "gm-transport-intelligence-kamil",
        "built_at_utc": datetime.now(UTC).isoformat(timespec="milliseconds"),
        "git_commit": _git_commit(repository_root),
        "database_file": database_path.name,
        "database_size_bytes": database_path.stat().st_size,
        "database_integrity": "ok",
        "serving_metadata": database_metadata,
        "source_file_count": len(source_files),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output_path.with_suffix(f"{output_path.suffix}.tmp")
    temporary_output.unlink(missing_ok=True)

    try:
        with zipfile.ZipFile(
            temporary_output,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
        ) as archive:
            for source_file in source_files:
                archive.write(
                    source_file,
                    source_file.relative_to(repository_root).as_posix(),
                )
            archive.write(deployment_requirements, "requirements.txt")
            archive.write(startup_script, "deploy/azure/startup.sh")
            archive.write(
                database_path,
                "data/serving/transport_dashboard.db",
            )
            archive.writestr(
                "deployment_manifest.json",
                json.dumps(manifest, indent=2, sort_keys=True),
            )
        temporary_output.replace(output_path)
    except Exception:
        temporary_output.unlink(missing_ok=True)
        raise

    manifest["package_path"] = str(output_path)
    manifest["package_size_bytes"] = output_path.stat().st_size
    return manifest


def main() -> None:
    repository_root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(
        description="Build the Azure App Service dashboard deployment package.",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=repository_root / DEFAULT_DATABASE,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=repository_root / DEFAULT_OUTPUT,
    )
    arguments = parser.parse_args()

    manifest = build_package(
        repository_root=repository_root,
        database_path=arguments.database,
        output_path=arguments.output,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
