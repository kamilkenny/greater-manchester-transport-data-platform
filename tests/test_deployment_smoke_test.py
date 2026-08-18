import json
from pathlib import Path

import httpx

from transport_platform.deployment import smoke_test


def successful_response(request: httpx.Request) -> httpx.Response:
    path = request.url.path

    if path == "/health":
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "database_integrity": "ok",
                "database_size_bytes": 38_068_224,
            },
        )
    if path == "/":
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text="Greater Manchester Designed and modelled by Kamil Ridwan",
        )
    if path == "/static/styles.css":
        return httpx.Response(
            200,
            headers={"content-type": "text/css"},
            content=b"a" * 600,
        )
    if path == "/static/app.js":
        return httpx.Response(
            200,
            headers={"content-type": "application/javascript"},
            content=b"a" * 600,
        )
    if path == "/api/overview":
        return httpx.Response(
            200,
            json={
                "kpis": {},
                "platform": {},
                "metadata": {},
                "methodology": "scheduled intelligence",
            },
        )
    if path in {"/api/modes", "/api/routes", "/api/map-stops"}:
        return httpx.Response(200, json=[{"record": 1}])
    if path == "/api/pipelines":
        return httpx.Response(
            200,
            json={"health": [{"status": "HEALTHY"}], "recent_runs": []},
        )
    if path == "/api/data-quality":
        return httpx.Response(
            200,
            json={"counts": {"PASS": 1}, "results": [{"status": "PASS"}]},
        )
    raise AssertionError(f"unexpected smoke test path: {request.url}")


def test_smoke_test_passes_all_governed_endpoints() -> None:
    report = smoke_test.run_smoke_test(
        "https://example.test/",
        transport=httpx.MockTransport(successful_response),
    )

    assert report["status"] == "PASSED"
    assert report["base_url"] == "https://example.test"
    assert report["summary"] == {"total": 10, "passed": 10, "failed": 0}
    assert all(check["passed"] for check in report["checks"])


def test_smoke_test_reports_an_unavailable_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/routes":
            return httpx.Response(503, json={"detail": "unavailable"})
        return successful_response(request)

    report = smoke_test.run_smoke_test(
        transport=httpx.MockTransport(handler),
    )

    assert report["status"] == "FAILED"
    assert report["summary"]["failed"] == 1
    failed = [check for check in report["checks"] if not check["passed"]]
    assert failed[0]["name"] == "routes"
    assert failed[0]["status_code"] == 503


def test_smoke_test_reports_connection_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            raise httpx.ConnectError("site stopped", request=request)
        return successful_response(request)

    report = smoke_test.run_smoke_test(
        transport=httpx.MockTransport(handler),
    )

    assert report["status"] == "FAILED"
    health = report["checks"][0]
    assert health["status_code"] is None
    assert health["detail"] == "request failed: site stopped"


def test_smoke_test_rejects_dashboard_without_creator_credit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                text="Greater Manchester Transport Intelligence",
            )
        return successful_response(request)

    report = smoke_test.run_smoke_test(
        transport=httpx.MockTransport(handler),
    )

    dashboard = next(
        check for check in report["checks"] if check["name"] == "dashboard"
    )
    assert dashboard["passed"] is False
    assert dashboard["detail"] == "missing dashboard marker: Kamil Ridwan"


def test_smoke_report_is_written_atomically(tmp_path: Path) -> None:
    report = {"status": "PASSED", "summary": {"failed": 0}}
    output_path = tmp_path / "reports" / "smoke_test.json"

    smoke_test.write_report(report, output_path)

    assert json.loads(output_path.read_text(encoding="utf-8")) == report
    assert not output_path.with_suffix(".json.tmp").exists()
