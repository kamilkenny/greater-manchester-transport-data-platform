from pathlib import Path

WORKFLOW_PATH = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "quality-gate.yml"
)


def workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def test_quality_gate_is_manual_and_read_only() -> None:
    workflow = workflow_text()

    assert "workflow_dispatch:" in workflow
    assert "schedule:" not in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "cancel-in-progress: true" in workflow


def test_quality_gate_runs_repository_checks() -> None:
    workflow = workflow_text()

    assert "actions/checkout@v7" in workflow
    assert "actions/setup-python@v7" in workflow
    assert "python-version: \"3.12\"" in workflow
    assert "ruff check ." in workflow
    assert "pytest -q" in workflow


def test_quality_gate_only_dry_runs_orchestration() -> None:
    workflow = workflow_text()

    assert "transport_platform.orchestration.refresh_platform" in workflow
    assert "--dry-run" in workflow
    assert "--skip-package" in workflow
    assert 'manifest["azure_deployment_performed"] is False' in workflow


def test_quality_gate_cannot_deploy_to_azure() -> None:
    workflow = workflow_text().lower()

    assert "azure/login" not in workflow
    assert "az webapp" not in workflow
    assert "azure credentials" not in workflow
    assert "actions/upload-artifact@v4" in workflow
