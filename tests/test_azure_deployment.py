from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path

from transport_platform.deployment.build_azure_package import build_package


def test_azure_package_contains_runtime_and_governed_database(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    source_file = repository_root / "src/transport_platform/api/app.py"
    deployment_directory = repository_root / "deploy/azure"
    database_path = repository_root / "data/serving/transport_dashboard.db"
    output_path = repository_root / "dist/dashboard.zip"

    source_file.parent.mkdir(parents=True)
    source_file.write_text("app = object()\n", encoding="utf-8")
    deployment_directory.mkdir(parents=True)
    (deployment_directory / "requirements.txt").write_text(
        "fastapi>=0.116,<1.0\n"
        "jinja2>=3.1,<4.0\n"
        "pydantic-settings>=2.14,<3.0\n"
        "uvicorn>=0.35,<1.0\n",
        encoding="utf-8",
    )
    (deployment_directory / "startup.sh").write_text(
        "python -m uvicorn transport_platform.api.app:app\n",
        encoding="utf-8",
    )
    database_path.parent.mkdir(parents=True)
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE serving_metadata (
                metadata_key TEXT PRIMARY KEY,
                metadata_value TEXT NOT NULL
            );
            INSERT INTO serving_metadata VALUES ('schema_version', '1');
            """
        )

    manifest = build_package(
        repository_root=repository_root,
        database_path=database_path,
        output_path=output_path,
    )

    assert manifest["database_integrity"] == "ok"
    assert manifest["serving_metadata"] == {"schema_version": "1"}
    assert output_path.is_file()

    with zipfile.ZipFile(output_path) as archive:
        names = set(archive.namelist())
        assert "src/transport_platform/api/app.py" in names
        assert "requirements.txt" in names
        assert "deploy/azure/startup.sh" in names
        assert "data/serving/transport_dashboard.db" in names
        packaged_manifest = json.loads(
            archive.read("deployment_manifest.json")
        )
        assert packaged_manifest["database_integrity"] == "ok"
        packaged_requirements = archive.read("requirements.txt")
        assert b"fastapi" in packaged_requirements
        assert b"jinja2" in packaged_requirements
        assert b"pydantic-settings" in packaged_requirements
        assert b"uvicorn" in packaged_requirements
