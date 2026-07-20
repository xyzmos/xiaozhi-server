from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

TARGET_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = TARGET_ROOT.parents[1]
DOCUMENT = REPOSITORY_ROOT / "docs" / "manager-api-fastapi-compatibility.md"
RENDERER = TARGET_ROOT / "scripts" / "render_compatibility_doc.py"
JAVA_MANIFEST = TARGET_ROOT / "compatibility" / "java-routes.json"
ROUTE_SURFACE_RESULTS = TARGET_ROOT / "compatibility" / "route-surface-results.json"
AUTHENTICATED_ROUTE_RESULTS = TARGET_ROOT / "compatibility" / "authenticated-route-results.json"


def test_compatibility_document_is_current() -> None:
    rendered = subprocess.run(  # noqa: S603
        [sys.executable, str(RENDERER)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert DOCUMENT.read_text(encoding="utf-8") == rendered


def test_compatibility_document_has_every_java_route_exactly_once() -> None:
    document = DOCUMENT.read_text(encoding="utf-8")
    routes = json.loads(JAVA_MANIFEST.read_text(encoding="utf-8"))["routes"]
    rows = re.findall(r"^\| J\d{3} \|.*$", document, flags=re.MULTILINE)
    assert len(rows) == 154 == len(routes)
    for route, row in zip(routes, rows, strict=True):
        assert f"`{route['method']} {route['path']}`" in row
        assert f"`{route['controller']}.{route['handler']}`" in row
        assert "结构✓" in row
        assert "请求面差分✓1" in row
        assert "认证业务面差分✓1" in row
        assert "领域✓" in row
        assert "差分" in row


def test_document_separates_structure_domain_and_actual_differential_evidence() -> None:
    document = DOCUMENT.read_text(encoding="utf-8")
    assert "154/154（100%）" in document
    assert "49/49 checks 通过、0 失败、0 跳过" in document
    assert "154/154 通过、0 失败、0 跳过" in document
    assert "authenticated-route-results.json" in document
    assert "21/154" in document
    assert "188" in document and "140" in document
    assert "24 个、154 条映射" in document
    assert "MyBatis XML：20 个" in document
    assert "101 个 `changeSet`" in document
    for orphan in (
        "GET /api/ping",
        "PUT /user/configDevice/{device_id}",
        "GET /device/address-book/lookup",
    ):
        assert orphan in document


def test_document_evidence_requires_two_complete_all_route_differentials() -> None:
    expected = {"total": 154, "passed": 154, "failed": 0, "skipped": 0}
    expected_names = [
        f"{route['method']} {route['path']}"
        for route in json.loads(JAVA_MANIFEST.read_text(encoding="utf-8"))["routes"]
    ]
    route_surface = json.loads(ROUTE_SURFACE_RESULTS.read_text(encoding="utf-8"))
    authenticated_route = json.loads(AUTHENTICATED_ROUTE_RESULTS.read_text(encoding="utf-8"))
    assert route_surface["summary"] == expected
    assert authenticated_route["summary"] == expected
    assert route_surface["coverage"]["request_profile"] == "missing-auth-or-safe-invalid-input"
    assert authenticated_route["coverage"]["request_profile"] == (
        "authenticated-safe-business-or-validation"
    )
    for evidence in (route_surface, authenticated_route):
        assert [result["name"] for result in evidence["results"]] == expected_names
        assert all(
            result["passed"] is True and result["difference"] is None
            for result in evidence["results"]
        )
