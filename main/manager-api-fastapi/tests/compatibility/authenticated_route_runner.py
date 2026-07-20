from __future__ import annotations

import argparse
import json
import re
import string
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from tests.compatibility.differential_runner import ContractRunner, _build_report
from tests.compatibility.seed_contract_data import ADMIN_TOKEN, SERVER_SECRET

TARGET_ROOT = Path(__file__).resolve().parents[2]
JAVA_MANIFEST = TARGET_ROOT / "compatibility" / "java-routes.json"
PATH_PARAMETER = re.compile(r"\{([^/{}]+)\}")
MISSING_LONG_ID = "9223372036854775806"
PASSWORD_CHARACTERS = frozenset(string.ascii_letters + string.digits + "!@#$%^&*()")

# These create endpoints accept an object whose fields are largely optional.  An
# empty JSON object could therefore create an isolated row instead of exercising
# validation.  Omitting the body is deterministic on both implementations and
# keeps this runner read-only with respect to intentional business writes.
NO_BODY_ROUTES = {
    ("POST", "/admin/dict/data/save"),
    ("POST", "/admin/dict/type/save"),
    ("POST", "/agent/template"),
    ("POST", "/agent/voice-print"),
    ("POST", "/datasets"),
    ("POST", "/device/manual-add"),
    ("POST", "/device/register"),
}

MULTIPART_ROUTES = {
    ("POST", "/datasets/{dataset_id}/documents"),
    ("POST", "/otaMag/upload"),
    ("POST", "/otaMag/uploadAssetsBin"),
    ("POST", "/voiceClone/upload"),
}

NUMERIC_ID_CONTROLLERS = {
    "AdminController",
    "SysDictDataController",
    "SysDictTypeController",
    "SysParamsController",
}

# Hibernate Validator exposes constraint violations as a Set, so an empty body
# can legitimately select a different first message on two otherwise identical
# processes.  Each payload below leaves exactly one declared constraint invalid;
# the resulting full response remains suitable for an exact comparison and the
# request cannot reach a successful write.
SINGLE_CONSTRAINT_PAYLOADS: dict[tuple[str, str], dict[str, Any]] = {
    ("POST", "/admin/params"): {
        "paramCode": "contract.missing.type",
        "paramValue": "contract-value",
    },
    ("PUT", "/admin/params"): {
        "id": MISSING_LONG_ID,
        "paramCode": "contract.missing.value",
        "valueType": "string",
    },
    ("POST", "/admin/server/emit-action"): {
        "targetWs": "contract-missing-ws",
    },
    ("POST", "/agent/chat-history/report"): {
        "macAddress": "AA:BB:CC:DD:EE:FC",
        "sessionId": "contract-missing-content",
        "chatType": 1,
    },
    ("POST", "/config/agent-models"): {
        "macAddress": "AA:BB:CC:DD:EE:FB",
        "clientId": "contract-missing-selected-module",
    },
    ("POST", "/correct-word/file"): {
        "fileName": "contract-invalid.txt",
    },
    ("PUT", "/correct-word/file/{fileId}"): {
        "fileName": "contract-invalid.txt",
    },
    ("PUT", "/device/address-book/alias"): {
        "targetMac": "AA:BB:CC:DD:EE:FD",
    },
    ("PUT", "/device/address-book/permission"): {
        "macAddress": "AA:BB:CC:DD:EE:FE",
    },
    ("POST", "/models/provider"): {
        "providerCode": "contract-provider-code",
        "name": "Contract Provider",
        "fields": "[]",
        "sort": 0,
    },
    ("POST", "/ttsVoice"): {
        "languages": "zh",
        "name": "Contract Voice",
        "ttsModelId": "contract-missing-model",
    },
    ("PUT", "/ttsVoice/{id}"): {
        "languages": "zh",
        "ttsModelId": "contract-missing-model",
        "ttsVoice": "contract-voice",
    },
}

RANDOM_PASSWORD_ROUTE = ("PUT", "/admin/users/{id}")
OTA_DOWNLOAD_UUID_ROUTE = ("GET", "/otaMag/getDownloadUrl/{id}")


@dataclass(frozen=True, slots=True)
class AuthenticatedRouteCase:
    method: str
    template: str
    path: str
    auth: str
    request_kwargs: dict[str, Any]

    @property
    def key(self) -> tuple[str, str]:
        return self.method, self.template


def _load_routes() -> list[dict[str, Any]]:
    manifest = json.loads(JAVA_MANIFEST.read_text(encoding="utf-8"))
    routes = cast(list[dict[str, Any]], manifest["routes"])
    if manifest["count"] != 154 or len(routes) != 154:
        raise RuntimeError("Java route manifest is not closed at 154 routes")
    return routes


def _path_value(route: dict[str, Any], name: str) -> str:
    controller = str(route["controller"])
    if name == "userId" or (name == "id" and controller in NUMERIC_ID_CONTROLLERS):
        return MISSING_LONG_ID
    if name == "status":
        return "0" if controller in {"AdminController", "ModelController"} else "contract-missing-status"
    if name == "deviceCode":
        return "999999"
    if name == "macAddress":
        return "AA:BB:CC:DD:EE:FE"
    if name == "dictType":
        return "CONTRACT_MISSING_DICT_TYPE"
    if name == "modelType":
        return "CONTRACT_MISSING_MODEL_TYPE"
    if name == "provideCode":
        return "contract-missing-provider"
    return f"contract-missing-{name.lower()}"


def _safe_path(route: dict[str, Any]) -> str:
    template = str(route["path"])
    return PATH_PARAMETER.sub(lambda match: _path_value(route, match.group(1)), template)


def _headers(auth: str) -> dict[str, str]:
    if auth == "database-token":
        return {"Authorization": f"Bearer {ADMIN_TOKEN}"}
    if auth == "server-secret":
        return {"Authorization": f"Bearer {SERVER_SECRET}"}
    return {}


def build_cases() -> list[AuthenticatedRouteCase]:
    cases: list[AuthenticatedRouteCase] = []
    for route in _load_routes():
        method = str(route["method"])
        template = str(route["path"])
        auth = str(route["auth"])
        kwargs: dict[str, Any] = {}
        headers = _headers(auth)
        if headers:
            kwargs["headers"] = headers
        key = (method, template)
        if key in SINGLE_CONSTRAINT_PAYLOADS:
            kwargs["json"] = SINGLE_CONSTRAINT_PAYLOADS[key]
        elif method in {"POST", "PUT"} and key not in MULTIPART_ROUTES and key not in NO_BODY_ROUTES:
            kwargs["json"] = {}
        cases.append(
            AuthenticatedRouteCase(
                method=method,
                template=template,
                path=_safe_path(route),
                auth=auth,
                request_kwargs=kwargs,
            )
        )
    return cases


def _valid_random_password(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 12
        and set(value) <= PASSWORD_CHARACTERS
        and any(character in string.digits for character in value)
        and any(character in string.ascii_lowercase for character in value)
        and any(character in string.ascii_uppercase for character in value)
        and any(character in "!@#$%^&*()" for character in value)
    )


def _valid_uuid4(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError):
        return False
    return parsed.version == 4 and str(parsed) == value


def _normalize_dynamic_data(
    value: Any,
    *,
    validator: Callable[[Any], bool],
    placeholder: str,
) -> Any:
    if (
        isinstance(value, dict)
        and value.get("code") == 0
        and validator(value.get("data"))
    ):
        return {**value, "data": placeholder}
    return value


def _normalize_random_password(value: Any) -> Any:
    return _normalize_dynamic_data(
        value,
        validator=_valid_random_password,
        placeholder="<valid-random-password>",
    )


def _normalize_ota_download_uuid(value: Any) -> Any:
    return _normalize_dynamic_data(
        value,
        validator=_valid_uuid4,
        placeholder="<valid-uuid-v4>",
    )


DYNAMIC_RESPONSES: dict[
    tuple[str, str], tuple[Callable[[Any], Any], Callable[[Any], bool], str]
] = {
    RANDOM_PASSWORD_ROUTE: (
        _normalize_random_password,
        _valid_random_password,
        "random_password",
    ),
    OTA_DOWNLOAD_UUID_ROUTE: (
        _normalize_ota_download_uuid,
        _valid_uuid4,
        "uuid_v4",
    ),
}


def _validate_dynamic_response(
    runner: ContractRunner,
    *,
    java_body: Any,
    fastapi_body: Any,
    validator: Callable[[Any], bool],
    label: str,
) -> None:
    result = runner.results[-1]
    validity = {
        f"java:{label}": isinstance(java_body, dict)
        and java_body.get("code") == 0
        and validator(java_body.get("data")),
        f"fastapi:{label}": isinstance(fastapi_body, dict)
        and fastapi_body.get("code") == 0
        and validator(fastapi_body.get("data")),
    }
    result.checks.update(validity)
    result.passed = all(result.checks.values())
    failed = [name for name, passed in validity.items() if not passed]
    if failed and result.difference is None:
        result.difference = "invalid dynamic response format: " + ", ".join(failed)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--java-base", default="http://127.0.0.1:18082/xiaozhi")
    parser.add_argument("--fastapi-base", default="http://127.0.0.1:18083/xiaozhi")
    parser.add_argument("--mock-base", default="http://127.0.0.1:18084")
    parser.add_argument("--mysql-port", type=int, default=13316)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("compatibility/authenticated-route-results.json"),
    )
    args = parser.parse_args()
    runner = ContractRunner(args.java_base, args.fastapi_base, args.mock_base, args.mysql_port)
    try:
        for case in build_cases():
            dynamic = DYNAMIC_RESPONSES.get(case.key)
            java, fastapi = runner.request_pair(
                f"{case.method} {case.template}",
                f"authenticated-route:{case.auth}",
                case.method,
                case.path,
                normalize=dynamic[0] if dynamic else None,
                exact_headers=("content-type",),
                **case.request_kwargs,
            )
            if dynamic:
                _validate_dynamic_response(
                    runner,
                    java_body=java.body,
                    fastapi_body=fastapi.body,
                    validator=dynamic[1],
                    label=dynamic[2],
                )
    finally:
        runner.close()

    report = _build_report(runner)
    report["coverage"] = {
        "java_routes": len(runner.results),
        "request_profile": "authenticated-safe-business-or-validation",
        "side_effect_policy": "no intentional successful writes",
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
