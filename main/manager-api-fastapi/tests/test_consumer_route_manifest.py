from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from app.main import app

TARGET_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = TARGET_ROOT / "compatibility" / "consumer-routes.json"
EXTRACTOR = TARGET_ROOT / "scripts" / "extract_consumer_routes.py"
PATH_PARAMETER = re.compile(r"\{[^/{}]+\}")


def live_manifest() -> dict[str, object]:
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(EXTRACTOR)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _route_matches(declared: str, consumed: str) -> bool:
    declared_parts = declared.strip("/").split("/")
    consumed_parts = consumed.strip("/").split("/")
    if len(declared_parts) != len(consumed_parts):
        return False
    return all(
        PATH_PARAMETER.fullmatch(declared_part) is not None or declared_part == consumed_part
        for declared_part, consumed_part in zip(declared_parts, consumed_parts, strict=True)
    )


def test_checked_in_consumer_route_manifest_is_current() -> None:
    checked_in = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert checked_in == live_manifest()


def test_consumer_inventory_counts_are_closed() -> None:
    manifest = live_manifest()
    assert manifest["count"] == 188
    assert manifest["uniqueRoutes"] == 140
    assert manifest["consumers"] == {
        "manager-web": {
            "callSites": 134,
            "uniqueRoutes": 130,
            "methods": {"DELETE": 12, "GET": 59, "POST": 40, "PUT": 23},
        },
        "manager-mobile": {
            "callSites": 46,
            "uniqueRoutes": 40,
            "methods": {"DELETE": 3, "GET": 26, "POST": 12, "PUT": 5},
        },
        "xiaozhi-server": {
            "callSites": 8,
            "uniqueRoutes": 8,
            "methods": {"GET": 2, "POST": 6},
        },
    }


def test_every_consumer_call_resolves_to_a_fastapi_route() -> None:
    calls = live_manifest()["calls"]
    assert isinstance(calls, list)
    actual = [
        (method, route.path.removeprefix("/xiaozhi"))
        for route in app.routes
        for method in getattr(route, "methods", set())
        if method in {"GET", "POST", "PUT", "DELETE", "PATCH"}
        and route.path.startswith("/xiaozhi")
    ]
    missing = [
        call
        for call in calls
        if not any(
            method == str(call["method"]) and _route_matches(route_path, str(call["path"]))
            for method, route_path in actual
        )
    ]
    assert missing == []
