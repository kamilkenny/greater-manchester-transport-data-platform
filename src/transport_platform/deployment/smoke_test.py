from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import httpx

DEFAULT_BASE_URL = "https://gm-transport-intelligence-kamil.azurewebsites.net"


@dataclass(frozen=True)
class EndpointSpec:
    """Describe one public production endpoint acceptance check."""

    name: str
    path: str
    response_kind: Literal[
        "health",
        "html",
        "css",
        "javascript",
        "json_list",
        "overview",
        "pipelines",
        "data_quality",
    ]


@dataclass(frozen=True)
class CheckResult:
    """Record one endpoint check result."""

    name: str
    path: str
    passed: bool
    status_code: int | None
    duration_milliseconds: int
    detail: str


ENDPOINTS = (
    EndpointSpec("health", "/health", "health"),
    EndpointSpec("dashboard", "/", "html"),
    EndpointSpec("stylesheet", "/static/styles.css", "css"),
    EndpointSpec("javascript", "/static/app.js", "javascript"),
    EndpointSpec("overview", "/api/overview", "overview"),
    EndpointSpec("modes", "/api/modes", "json_list"),
    EndpointSpec("routes", "/api/routes?limit=3", "json_list"),
    EndpointSpec("map_stops", "/api/map-stops?limit=100", "json_list"),
    EndpointSpec("pipelines", "/api/pipelines", "pipelines"),
    EndpointSpec(
        "data_quality",
        "/api/data-quality?limit=5",
        "data_quality",
    ),
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _validate_json(response: httpx.Response) -> Any:
    content_type = response.headers.get("content-type", "").lower()
    if "application/json" not in content_type:
        raise ValueError(f"unexpected content type: {content_type or 'missing'}")
    return response.json()


def _validate_response(
    spec: EndpointSpec,
    response: httpx.Response,
) -> tuple[bool, str]:
    if response.status_code != 200:
        return False, f"expected HTTP 200, received {response.status_code}"

    content_type = response.headers.get("content-type", "").lower()

    if spec.response_kind == "html":
        required_markers = ("Greater Manchester", "Kamil Ridwan")
        missing = [marker for marker in required_markers if marker not in response.text]
        if "text/html" not in content_type:
            return False, f"unexpected content type: {content_type or 'missing'}"
        if missing:
            return False, f"missing dashboard marker: {missing[0]}"
        return True, "dashboard HTML and creator credit available"

    if spec.response_kind == "css":
        if "text/css" not in content_type:
            return False, f"unexpected content type: {content_type or 'missing'}"
        if len(response.content) < 500:
            return False, "stylesheet response is unexpectedly small"
        return True, f"stylesheet available, {len(response.content)} bytes"

    if spec.response_kind == "javascript":
        if "javascript" not in content_type:
            return False, f"unexpected content type: {content_type or 'missing'}"
        if len(response.content) < 500:
            return False, "JavaScript response is unexpectedly small"
        return True, f"JavaScript available, {len(response.content)} bytes"

    try:
        payload = _validate_json(response)
    except (ValueError, json.JSONDecodeError) as error:
        return False, str(error)

    if spec.response_kind == "health":
        if not isinstance(payload, dict):
            return False, "health payload is not a JSON object"
        if payload.get("status") != "ok":
            return False, f"health status is {payload.get('status')!r}"
        if payload.get("database_integrity") != "ok":
            return False, "serving database integrity is not ok"
        if int(payload.get("database_size_bytes", 0)) <= 0:
            return False, "serving database size is missing"
        return True, "application and serving database are healthy"

    if spec.response_kind == "json_list":
        if not isinstance(payload, list):
            return False, "payload is not a JSON list"
        if not payload:
            return False, "payload contains no records"
        return True, f"received {len(payload)} governed records"

    if spec.response_kind == "overview":
        required_keys = {"kpis", "platform", "metadata", "methodology"}
        if not isinstance(payload, dict) or not required_keys.issubset(payload):
            return False, "overview payload is missing required sections"
        return True, "executive overview contract available"

    if spec.response_kind == "pipelines":
        required_keys = {"health", "recent_runs"}
        if not isinstance(payload, dict) or not required_keys.issubset(payload):
            return False, "pipeline payload is missing required sections"
        if not isinstance(payload["health"], list) or not payload["health"]:
            return False, "pipeline health contains no governed records"
        return True, f"received {len(payload['health'])} pipeline health records"

    if spec.response_kind == "data_quality":
        required_keys = {"counts", "results"}
        if not isinstance(payload, dict) or not required_keys.issubset(payload):
            return False, "data quality payload is missing required sections"
        if not isinstance(payload["results"], list):
            return False, "data quality results are not a JSON list"
        return True, f"received {len(payload['results'])} quality observations"

    return False, f"unsupported response kind: {spec.response_kind}"


def run_smoke_test(
    base_url: str = DEFAULT_BASE_URL,
    *,
    timeout_seconds: float = 30.0,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    """Run the governed public endpoint acceptance checks."""

    normalised_base_url = base_url.rstrip("/")
    started_at = _utc_now()
    suite_started = time.monotonic()
    results: list[CheckResult] = []

    with httpx.Client(
        base_url=normalised_base_url,
        timeout=timeout_seconds,
        follow_redirects=True,
        transport=transport,
        headers={"User-Agent": "gm-transport-production-smoke-test/1.0"},
    ) as client:
        for spec in ENDPOINTS:
            check_started = time.monotonic()
            try:
                response = client.get(spec.path)
                passed, detail = _validate_response(spec, response)
                status_code = response.status_code
            except httpx.HTTPError as error:
                passed = False
                detail = f"request failed: {error}"
                status_code = None

            duration = round((time.monotonic() - check_started) * 1_000)
            results.append(
                CheckResult(
                    name=spec.name,
                    path=spec.path,
                    passed=passed,
                    status_code=status_code,
                    duration_milliseconds=duration,
                    detail=detail,
                )
            )

    passed_count = sum(result.passed for result in results)
    failed_count = len(results) - passed_count
    return {
        "application": "gm-transport-intelligence-kamil",
        "base_url": normalised_base_url,
        "started_at_utc": started_at,
        "completed_at_utc": _utc_now(),
        "duration_milliseconds": round((time.monotonic() - suite_started) * 1_000),
        "status": "PASSED" if failed_count == 0 else "FAILED",
        "summary": {
            "total": len(results),
            "passed": passed_count,
            "failed": failed_count,
        },
        "checks": [asdict(result) for result in results],
    }


def write_report(report: dict[str, Any], output_path: Path) -> None:
    """Write a smoke test report atomically."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(f"{output_path.suffix}.tmp")
    temporary_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(output_path)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate the public Greater Manchester transport application.",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the command line production acceptance check."""

    parser = _build_parser()
    arguments = parser.parse_args(argv)
    if arguments.timeout <= 0:
        parser.error("--timeout must be greater than zero")

    report = run_smoke_test(
        base_url=arguments.base_url,
        timeout_seconds=arguments.timeout,
    )
    if arguments.output is not None:
        write_report(report, arguments.output)
        print(f"Smoke test report: {arguments.output}")

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
