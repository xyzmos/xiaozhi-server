from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, cast

from tests.compatibility.differential_runner import ContractRunner, _build_report

TARGET_ROOT = Path(__file__).resolve().parents[2]
JAVA_MANIFEST = TARGET_ROOT / "compatibility" / "java-routes.json"
PATH_PARAMETER = re.compile(r"\{([^/{}]+)\}")

SAFE_PATH_VALUES = {
    "agentId": "contract-agent-1",
    "audioId": "contract-audio",
    "deviceCode": "000000",
    "deviceId": "contract-device-1",
    "dictType": "FIRMWARE_TYPE",
    "document_id": "contract-document",
    "dataset_id": "contract-dataset",
    "fileId": "contract-words",
    "id": "contract-id",
    "macAddress": "AA:BB:CC:DD:EE:01",
    "modelId": "contract-model",
    "modelType": "LLM",
    "provideCode": "OpenAI",
    "sessionId": "contract-session",
    "snapshotId": "contract-snapshot",
    "status": "1",
    "userId": "contract-user",
    "uuid": "contract-unknown-token",
}


def _safe_path(template: str) -> str:
    return PATH_PARAMETER.sub(lambda match: SAFE_PATH_VALUES.get(match.group(1), "contract-value"), template)


def _load_routes() -> list[dict[str, Any]]:
    manifest = json.loads(JAVA_MANIFEST.read_text(encoding="utf-8"))
    routes = cast(list[dict[str, Any]], manifest["routes"])
    if manifest["count"] != 154 or len(routes) != 154:
        raise RuntimeError("Java route manifest is not closed at 154 routes")
    return routes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--java-base", default="http://127.0.0.1:18082/xiaozhi")
    parser.add_argument("--fastapi-base", default="http://127.0.0.1:18083/xiaozhi")
    parser.add_argument("--mock-base", default="http://127.0.0.1:18084")
    parser.add_argument("--mysql-port", type=int, default=13316)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("compatibility/route-surface-results.json"),
    )
    args = parser.parse_args()
    runner = ContractRunner(args.java_base, args.fastapi_base, args.mock_base, args.mysql_port)
    try:
        for route in _load_routes():
            method = str(route["method"])
            template = str(route["path"])
            runner.request_pair(
                f"{method} {template}",
                f"route-surface:{route['auth']}",
                method,
                _safe_path(template),
                exact_headers=("content-type",),
            )
    finally:
        runner.close()

    report = _build_report(runner)
    report["coverage"] = {
        "java_routes": len(runner.results),
        "request_profile": "missing-auth-or-safe-invalid-input",
        "side_effect_policy": "no successful write request is issued",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    summary = report["summary"]
    print(json.dumps(summary, ensure_ascii=False))
    for result in runner.results:
        if not result.passed:
            print(f"FAIL {result.name}: {result.difference}")
    sys.exit(1 if summary["failed"] else 0)


if __name__ == "__main__":
    main()
