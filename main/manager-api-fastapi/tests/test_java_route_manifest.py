from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

from app.main import app

TARGET_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = TARGET_ROOT / "compatibility" / "java-routes.json"
EXTRACTOR = TARGET_ROOT / "scripts" / "extract_java_routes.py"
PATH_PARAMETER = re.compile(r"\{[^/{}]+\}")


def live_manifest() -> dict[str, object]:
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(EXTRACTOR)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_checked_in_java_route_manifest_is_current() -> None:
    checked_in = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert checked_in == live_manifest()


def test_java_route_inventory_counts_are_closed() -> None:
    payload = live_manifest()
    routes = payload["routes"]
    assert isinstance(routes, list)
    assert payload["count"] == 154
    assert len({(route["method"], route["path"]) for route in routes}) == 154
    assert Counter(route["method"] for route in routes) == {"GET": 65, "POST": 52, "PUT": 23, "DELETE": 14}
    assert Counter(route["auth"] for route in routes) == {
        "database-token": 133,
        "anonymous": 14,
        "server-secret": 7,
    }


def test_every_java_route_is_registered_by_fastapi() -> None:
    routes = live_manifest()["routes"]
    assert isinstance(routes, list)
    expected = {
        (str(route["method"]), PATH_PARAMETER.sub("{}", f"/xiaozhi{route['path']}"))
        for route in routes
    }
    actual = {
        (method, PATH_PARAMETER.sub("{}", route.path))
        for route in app.routes
        for method in getattr(route, "methods", set())
        if method in {"GET", "POST", "PUT", "DELETE"}
        and route.path.startswith("/xiaozhi")
        and not route.path.startswith("/xiaozhi/health")
        and route.path not in {"/xiaozhi/doc.html", "/xiaozhi/v3/api-docs"}
    }
    consumer_only = {
        ("GET", "/xiaozhi/api/ping"),
        ("GET", "/xiaozhi/device/address-book/lookup"),
        ("PUT", "/xiaozhi/user/configDevice/{}"),
    }
    assert expected <= actual
    assert actual - expected == consumer_only
