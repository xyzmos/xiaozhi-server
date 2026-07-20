from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import re
import sys
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import asyncmy  # type: ignore[import-untyped]
import httpx
from asyncmy.cursors import DictCursor  # type: ignore[import-untyped]

from tests.compatibility.seed_contract_data import (
    ADMIN_ID,
    ADMIN_TOKEN,
    EXPIRED_TOKEN,
    MQTT_SIGNATURE_KEY,
    NORMAL_ID,
    NORMAL_TOKEN,
    SERVER_SECRET,
)

JSONValue = dict[str, Any] | list[Any] | str | int | float | bool | None
Normalizer = Callable[[JSONValue], JSONValue]
SENSITIVE_REPORT_KEYS = {
    "accesstoken",
    "authorization",
    "mqttsignaturekey",
    "password",
    "privatekey",
    "refreshtoken",
    "secret",
    "serversecret",
    "token",
    "websockettoken",
}


@dataclass
class ContractResult:
    name: str
    category: str
    passed: bool
    checks: dict[str, bool]
    difference: str | None
    java: dict[str, Any]
    fastapi: dict[str, Any]


@dataclass
class CapturedResponse:
    status: int
    headers: dict[str, str | None]
    body: JSONValue
    body_sha256: str


class ContractRunner:
    def __init__(
        self,
        java_base: str,
        fastapi_base: str,
        mock_base: str,
        mysql_port: int,
    ):
        self.bases = {"java": java_base.rstrip("/"), "fastapi": fastapi_base.rstrip("/")}
        self.mock_base = mock_base.rstrip("/")
        self.mysql_port = mysql_port
        self.client = httpx.Client(timeout=20.0, follow_redirects=False)
        self.results: list[ContractResult] = []

    def close(self) -> None:
        self.client.close()

    @staticmethod
    def _capture(response: httpx.Response) -> CapturedResponse:
        content_type = response.headers.get("content-type")
        try:
            body: JSONValue = response.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            try:
                body = response.content.decode("utf-8")
            except UnicodeDecodeError:
                body = {"base64": base64.b64encode(response.content).decode()}
        return CapturedResponse(
            status=response.status_code,
            headers={
                "content-type": content_type,
                "content-disposition": response.headers.get("content-disposition"),
                "content-length": response.headers.get("content-length"),
            },
            body=body,
            body_sha256=hashlib.sha256(response.content).hexdigest(),
        )

    def request_pair(
        self,
        name: str,
        category: str,
        method: str,
        path: str,
        *,
        normalize: Normalizer | None = None,
        exact_headers: tuple[str, ...] = (),
        **kwargs: Any,
    ) -> tuple[CapturedResponse, CapturedResponse]:
        captured: dict[str, CapturedResponse] = {}
        for side, base in self.bases.items():
            captured[side] = self._capture(self.client.request(method, base + path, **kwargs))
        java, fastapi = captured["java"], captured["fastapi"]
        java_body = normalize(java.body) if normalize else java.body
        fastapi_body = normalize(fastapi.body) if normalize else fastapi.body
        checks = {
            "http_status": java.status == fastapi.status,
            "body": java_body == fastapi_body,
        }
        for header in exact_headers:
            checks[f"header:{header}"] = java.headers.get(header) == fastapi.headers.get(header)
        difference = _first_difference(java_body, fastapi_body)
        if difference is None and not checks["http_status"]:
            difference = f"HTTP status Java={java.status} FastAPI={fastapi.status}"
        if difference is None:
            for check, passed in checks.items():
                if not passed:
                    difference = (
                        f"{check} Java={java.headers.get(check.removeprefix('header:'))!r} "
                        f"FastAPI={fastapi.headers.get(check.removeprefix('header:'))!r}"
                    )
                    break
        self.results.append(
            ContractResult(
                name=name,
                category=category,
                passed=all(checks.values()),
                checks=checks,
                difference=difference,
                java=_response_summary(java, java_body),
                fastapi=_response_summary(fastapi, fastapi_body),
            )
        )
        return java, fastapi

    def add_custom(
        self,
        name: str,
        category: str,
        checks: Mapping[str, bool],
        *,
        difference: str | None = None,
        java: Mapping[str, Any] | None = None,
        fastapi: Mapping[str, Any] | None = None,
    ) -> None:
        failed_checks = [check for check, passed in checks.items() if not passed]
        self.results.append(
            ContractResult(
                name=name,
                category=category,
                passed=not failed_checks,
                checks=dict(checks),
                difference=difference or (", ".join(failed_checks) if failed_checks else None),
                java=dict(java or {}),
                fastapi=dict(fastapi or {}),
            )
        )

    def run_read_only_cases(self) -> None:
        self.request_pair("public configuration", "configuration", "GET", "/user/pub-config")
        languages: list[str | None] = [None, "zh-CN", "zh-TW", "en-US", "de-DE", "vi-VN", "pt-BR"]
        for language in languages:
            headers = {} if language is None else {"Accept-Language": language}
            self.request_pair(
                f"unauthenticated localized response [{language or 'default'}]",
                "authentication-i18n",
                "GET",
                "/user/info",
                headers=headers,
                exact_headers=("content-type",),
            )
        self.request_pair(
            "expired database token",
            "authentication",
            "GET",
            "/user/info",
            headers=_bearer(EXPIRED_TOKEN),
            exact_headers=("content-type",),
        )
        self.request_pair(
            "normal user forbidden from admin endpoint",
            "authorization",
            "GET",
            "/admin/users",
            headers=_bearer(NORMAL_TOKEN),
        )
        self.request_pair(
            "Long user ID and token response",
            "serialization",
            "GET",
            "/user/info",
            headers=_bearer(NORMAL_TOKEN),
        )
        self.request_pair(
            "user page Long/date/null structure",
            "serialization",
            "GET",
            "/admin/users?page=1&limit=10",
            headers=_bearer(ADMIN_TOKEN),
        )
        self.request_pair(
            "agent list null/date fields",
            "agent",
            "GET",
            "/agent/list",
            headers=_bearer(NORMAL_TOKEN),
        )
        self.request_pair(
            "device list UTC display and epoch fields",
            "device",
            "GET",
            "/device/bind/contract-agent-1",
            headers=_bearer(NORMAL_TOKEN),
        )
        self.request_pair(
            "filtered model provider page",
            "model",
            "GET",
            "/models/provider?page=1&limit=10&name=Contract%20Provider",
            headers=_bearer(ADMIN_TOKEN),
        )
        self.request_pair(
            "correct-word page",
            "correct-word",
            "GET",
            "/correct-word/file/list?page=1&limit=10",
            headers=_bearer(NORMAL_TOKEN),
        )
        self.request_pair(
            "correct-word binary download headers and bytes",
            "binary-download",
            "GET",
            "/correct-word/file/download/contract-words",
            headers=_bearer(NORMAL_TOKEN),
            exact_headers=("content-type", "content-disposition", "content-length"),
        )

    def run_validation_cases(self) -> None:
        normal = _bearer(NORMAL_TOKEN)
        admin = _bearer(ADMIN_TOKEN)
        self.request_pair(
            "minimum boundary validation",
            "validation",
            "PUT",
            "/device/update/contract-device-1",
            headers=normal,
            json={"autoUpdate": -1},
        )
        self.request_pair(
            "maximum boundary validation",
            "validation",
            "PUT",
            "/device/update/contract-device-1",
            headers=normal,
            json={"autoUpdate": 2},
        )
        self.request_pair(
            "UTF-16 string-length validation boundary",
            "validation",
            "PUT",
            "/device/update/contract-device-1",
            headers=normal,
            json={"alias": "x" * 65},
        )
        # Hibernate Validator returns a Set of constraint violations, so the
        # first of these five declared annotations is intentionally unstable.
        # Validate the exact declared set and envelope, not one random order.
        declared_messages = {
            "modelType不能为空",
            "providerCode不能为空",
            "name不能为空",
            "fields(JSON格式)不能为空",
            "sort不能为空",
        }
        java_responses = [
            self._capture(
                self.client.post(
                    self.bases["java"] + "/models/provider",
                    headers=admin,
                    json={},
                )
            )
            for _ in range(10)
        ]
        fastapi_response = self._capture(
            self.client.post(
                self.bases["fastapi"] + "/models/provider",
                headers=admin,
                json={},
            )
        )
        java_messages = {
            str(response.body.get("msg"))
            for response in java_responses
            if isinstance(response.body, dict)
        }
        fastapi_message = (
            str(fastapi_response.body.get("msg")) if isinstance(fastapi_response.body, dict) else None
        )
        self.add_custom(
            "required model-provider fields (unordered Java ConstraintViolation Set)",
            "validation",
            {
                "java_http_200": all(response.status == 200 for response in java_responses),
                "java_code_10034": all(
                    isinstance(response.body, dict) and response.body.get("code") == 10034
                    for response in java_responses
                ),
                "java_messages_are_declared_constraints": bool(java_messages)
                and java_messages <= declared_messages,
                "fastapi_http_200": fastapi_response.status == 200,
                "fastapi_code_10034": isinstance(fastapi_response.body, dict)
                and fastapi_response.body.get("code") == 10034,
                "fastapi_message_is_declared_constraint": fastapi_message in declared_messages,
            },
            java={"observed_messages": sorted(java_messages), "declared_messages": sorted(declared_messages)},
            fastapi={"body": fastapi_response.body},
        )
        self.request_pair(
            "invalid pagination number format",
            "validation",
            "GET",
            "/admin/users?page=bad&limit=10",
            headers=admin,
        )

    def run_server_auth_and_config(self) -> None:
        self.request_pair(
            "missing server secret",
            "server-secret",
            "POST",
            "/config/server-base",
            exact_headers=("content-type",),
        )
        self.request_pair(
            "invalid server secret",
            "server-secret",
            "POST",
            "/config/server-base",
            headers=_bearer("invalid-contract-secret"),
            exact_headers=("content-type",),
        )
        self.request_pair(
            "valid server secret runtime configuration",
            "server-secret",
            "POST",
            "/config/server-base",
            headers=_bearer(SERVER_SECRET),
        )

    def run_ota_cases(self) -> None:
        self.request_pair(
            "OTA health MIME and body",
            "ota",
            "GET",
            "/ota/",
            exact_headers=("content-type",),
        )
        self.request_pair(
            "OTA missing required Device-Id",
            "ota-validation",
            "POST",
            "/ota/",
            json={"application": {"version": "1.2.3"}, "board": {"type": "esp32s3"}},
        )
        self.request_pair(
            "OTA invalid Device-Id",
            "ota-validation",
            "POST",
            "/ota/",
            headers={"Device-Id": "not-a-mac"},
            json={"application": {"version": "1.2.3"}, "board": {"type": "esp32s3"}},
            exact_headers=("content-type", "content-length"),
        )
        java, fastapi = self.request_pair(
            "OTA WebSocket/MQTT credentials",
            "ota-signing",
            "POST",
            "/ota/",
            headers={"Device-Id": "AA:BB:CC:DD:EE:01", "Client-Id": "contract-client"},
            json={"application": {"version": "1.2.3"}, "board": {"type": "esp32s3"}},
            normalize=_normalize_ota_dynamic,
            exact_headers=("content-type", "content-length"),
        )
        self.add_custom(
            "OTA HMAC/Base64 cryptographic validity",
            "ota-signing",
            {
                "java_credentials": _valid_ota_credentials(java.body),
                "fastapi_credentials": _valid_ota_credentials(fastapi.body),
            },
            java={"credential_shape": _ota_credential_shape(java.body)},
            fastapi={"credential_shape": _ota_credential_shape(fastapi.body)},
        )
        self.request_pair(
            "activation missing Device-Id",
            "activation",
            "POST",
            "/ota/activate",
        )
        self.request_pair(
            "activation unknown device",
            "activation",
            "POST",
            "/ota/activate",
            headers={"Device-Id": "FF:EE:DD:CC:BB:AA"},
        )
        self.request_pair(
            "activation bound device MIME",
            "activation",
            "POST",
            "/ota/activate",
            headers={"Device-Id": "AA:BB:CC:DD:EE:01"},
            exact_headers=("content-type",),
        )

    def run_external_mock_case(self) -> None:
        self.client.delete(self.mock_base + "/__requests")
        java, fastapi = self.request_pair(
            "MQTT tools external mock response",
            "external-mock",
            "POST",
            "/device/tools/list/contract-device-1",
            headers=_bearer(NORMAL_TOKEN),
        )
        records = self.client.get(self.mock_base + "/__requests").json().get("requests", [])
        recent = [record for record in records if str(record.get("path", "")).startswith("/api/commands/")]
        expected_token = hashlib.sha256(
            f"{datetime.now(tz=timezone.utc).date().isoformat()}{MQTT_SIGNATURE_KEY}".encode()
        ).hexdigest()
        auth_values = [record.get("headers", {}).get("authorization") for record in recent]
        bodies = [record.get("body") for record in recent]
        self.add_custom(
            "MQTT external request format and daily auth",
            "external-mock",
            {
                "both_services_called_mock": len(recent) == 2,
                "request_bodies_equal": len(bodies) == 2 and bodies[0] == bodies[1],
                "daily_tokens_valid": len(auth_values) == 2
                and all(value == f"Bearer {expected_token}" for value in auth_values),
                "responses_compatible": java.body == fastapi.body,
            },
            java={"request": recent[0] if recent else None},
            fastapi={"request": recent[1] if len(recent) > 1 else None},
        )

    def run_correct_word_crud(self) -> None:
        payload = {
            "fileName": "contract-run-created.txt",
            "content": ["xiaozhi|小智", "ESP32|esp32"],
            "fileSize": 31,
        }
        responses: dict[str, CapturedResponse] = {}
        identifiers: dict[str, str] = {}
        for side, base in self.bases.items():
            response = self._capture(
                self.client.post(base + "/correct-word/file", headers=_bearer(NORMAL_TOKEN), json=payload)
            )
            responses[side] = response
            if isinstance(response.body, dict):
                data = response.body.get("data")
                if isinstance(data, dict) and isinstance(data.get("id"), str):
                    identifiers[side] = data["id"]
        java_normalized = _normalize_created_correct_word(responses["java"].body)
        fastapi_normalized = _normalize_created_correct_word(responses["fastapi"].body)
        self.add_custom(
            "correct-word create response",
            "crud",
            {
                "http_status": responses["java"].status == responses["fastapi"].status,
                "body": java_normalized == fastapi_normalized,
                "ids_returned": set(identifiers) == {"java", "fastapi"},
            },
            difference=_first_difference(java_normalized, fastapi_normalized),
            java={"body": java_normalized},
            fastapi={"body": fastapi_normalized},
        )
        if set(identifiers) != {"java", "fastapi"}:
            return
        side_effects = {
            side: _database_row(
                self.mysql_port,
                "manager_java_test" if side == "java" else "manager_fastapi_test",
                "SELECT file_name,word_count,content,creator FROM ai_agent_correct_word_file WHERE id=%s",
                (identifier,),
            )
            for side, identifier in identifiers.items()
        }
        self.add_custom(
            "correct-word create database side effect",
            "database-side-effect",
            {"row_equal": side_effects["java"] == side_effects["fastapi"]},
            difference=_first_difference(side_effects["java"], side_effects["fastapi"]),
            java=side_effects["java"],
            fastapi=side_effects["fastapi"],
        )

        update = {"fileName": "contract-run-updated.txt", "content": ["A|B"], "fileSize": 3}
        update_responses: dict[str, CapturedResponse] = {}
        for side, identifier in identifiers.items():
            update_responses[side] = self._capture(
                self.client.put(
                    self.bases[side] + f"/correct-word/file/{identifier}",
                    headers=_bearer(NORMAL_TOKEN),
                    json=update,
                )
            )
        self.add_custom(
            "correct-word update response",
            "crud",
            {
                "status": update_responses["java"].status == update_responses["fastapi"].status,
                "body": update_responses["java"].body == update_responses["fastapi"].body,
            },
            difference=_first_difference(update_responses["java"].body, update_responses["fastapi"].body),
            java={"body": update_responses["java"].body},
            fastapi={"body": update_responses["fastapi"].body},
        )
        updated_rows = {
            side: _database_row(
                self.mysql_port,
                "manager_java_test" if side == "java" else "manager_fastapi_test",
                "SELECT file_name,word_count,content,creator,updater FROM ai_agent_correct_word_file WHERE id=%s",
                (identifier,),
            )
            for side, identifier in identifiers.items()
        }
        self.add_custom(
            "correct-word update database side effect",
            "database-side-effect",
            {"row_equal": updated_rows["java"] == updated_rows["fastapi"]},
            difference=_first_difference(updated_rows["java"], updated_rows["fastapi"]),
            java=updated_rows["java"],
            fastapi=updated_rows["fastapi"],
        )
        downloads = {
            side: self._capture(
                self.client.get(
                    self.bases[side] + f"/correct-word/file/download/{identifier}",
                    headers=_bearer(NORMAL_TOKEN),
                )
            )
            for side, identifier in identifiers.items()
        }
        self.add_custom(
            "correct-word updated binary download",
            "binary-download",
            {
                "status": downloads["java"].status == downloads["fastapi"].status,
                "bytes": downloads["java"].body_sha256 == downloads["fastapi"].body_sha256,
                "content_type": downloads["java"].headers["content-type"]
                == downloads["fastapi"].headers["content-type"],
                "content_disposition": downloads["java"].headers["content-disposition"]
                == downloads["fastapi"].headers["content-disposition"],
                "content_length": downloads["java"].headers["content-length"]
                == downloads["fastapi"].headers["content-length"],
            },
            java=asdict(downloads["java"]),
            fastapi=asdict(downloads["fastapi"]),
        )
        for side, identifier in identifiers.items():
            self.client.delete(
                self.bases[side] + f"/correct-word/file/{identifier}",
                headers=_bearer(NORMAL_TOKEN),
            )
        counts = {
            side: _database_scalar(
                self.mysql_port,
                "manager_java_test" if side == "java" else "manager_fastapi_test",
                "SELECT COUNT(*) FROM ai_agent_correct_word_file WHERE id=%s",
                (identifier,),
            )
            for side, identifier in identifiers.items()
        }
        self.add_custom(
            "correct-word delete cascade side effect",
            "database-side-effect",
            {"both_deleted": counts == {"java": 0, "fastapi": 0}},
            java={"remaining": counts["java"]},
            fastapi={"remaining": counts["fastapi"]},
        )

    def run_ota_upload_download(self) -> None:
        firmware = b"manager-api-contract-firmware\x00\xff"
        upload_responses: dict[str, CapturedResponse] = {}
        paths: dict[str, str] = {}
        for side, base in self.bases.items():
            response = self._capture(
                self.client.post(
                    base + "/otaMag/upload",
                    headers=_bearer(ADMIN_TOKEN),
                    files={"file": ("contract.bin", firmware, "application/octet-stream")},
                )
            )
            upload_responses[side] = response
            if isinstance(response.body, dict) and isinstance(response.body.get("data"), str):
                paths[side] = response.body["data"]
        self.add_custom(
            "OTA multipart upload response",
            "upload",
            {
                "status": upload_responses["java"].status == upload_responses["fastapi"].status,
                "body": upload_responses["java"].body == upload_responses["fastapi"].body,
                "paths_returned": set(paths) == {"java", "fastapi"},
            },
            difference=_first_difference(upload_responses["java"].body, upload_responses["fastapi"].body),
            java={"body": upload_responses["java"].body},
            fastapi={"body": upload_responses["fastapi"].body},
        )
        self.request_pair(
            "OTA multipart extension validation",
            "upload-validation",
            "POST",
            "/otaMag/upload",
            headers=_bearer(ADMIN_TOKEN),
            files={"file": ("contract.txt", b"invalid", "text/plain")},
        )
        if set(paths) != {"java", "fastapi"}:
            return
        create_responses: dict[str, CapturedResponse] = {}
        for side, base in self.bases.items():
            create_responses[side] = self._capture(
                self.client.post(
                    base + "/otaMag",
                    headers=_bearer(ADMIN_TOKEN),
                    json={
                        "id": "contract-ota-run",
                        "firmwareName": "Contract Firmware",
                        "type": "contract-run",
                        "version": "1.0.0",
                        "size": len(firmware),
                        "remark": None,
                        "firmwarePath": paths[side],
                        "sort": 9,
                    },
                )
            )
        self.add_custom(
            "OTA metadata create response",
            "crud",
            {
                "status": create_responses["java"].status == create_responses["fastapi"].status,
                "body": create_responses["java"].body == create_responses["fastapi"].body,
            },
            difference=_first_difference(create_responses["java"].body, create_responses["fastapi"].body),
            java={"body": create_responses["java"].body},
            fastapi={"body": create_responses["fastapi"].body},
        )
        rows = {
            side: _database_row(
                self.mysql_port,
                "manager_java_test" if side == "java" else "manager_fastapi_test",
                "SELECT id,firmware_name,type,version,size,remark,firmware_path,sort FROM ai_ota WHERE id=%s",
                ("contract-ota-run",),
            )
            for side in self.bases
        }
        self.add_custom(
            "OTA metadata database side effect",
            "database-side-effect",
            {"row_equal": rows["java"] == rows["fastapi"]},
            difference=_first_difference(rows["java"], rows["fastapi"]),
            java=rows["java"],
            fastapi=rows["fastapi"],
        )
        download_ids: dict[str, str] = {}
        for side, base in self.bases.items():
            response = self.client.get(
                base + "/otaMag/getDownloadUrl/contract-ota-run",
                headers=_bearer(ADMIN_TOKEN),
            ).json()
            if isinstance(response.get("data"), str):
                download_ids[side] = response["data"]
        if set(download_ids) != {"java", "fastapi"}:
            self.add_custom(
                "OTA download token generation",
                "binary-download",
                {"tokens_returned": False},
                java={"id": download_ids.get("java")},
                fastapi={"id": download_ids.get("fastapi")},
            )
            return
        for attempt in range(1, 5):
            responses = {
                side: self._capture(self.client.get(self.bases[side] + f"/otaMag/download/{identifier}"))
                for side, identifier in download_ids.items()
            }
            self.add_custom(
                f"OTA binary download attempt {attempt}",
                "binary-download",
                {
                    "status": responses["java"].status == responses["fastapi"].status,
                    "bytes": responses["java"].body_sha256 == responses["fastapi"].body_sha256,
                    "content_type": responses["java"].headers["content-type"]
                    == responses["fastapi"].headers["content-type"],
                    "content_disposition": responses["java"].headers["content-disposition"]
                    == responses["fastapi"].headers["content-disposition"],
                    "content_length": responses["java"].headers["content-length"]
                    == responses["fastapi"].headers["content-length"],
                },
                java=asdict(responses["java"]),
                fastapi=asdict(responses["fastapi"]),
            )


def _bearer(value: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {value}"}


def _response_summary(response: CapturedResponse, normalized_body: JSONValue) -> dict[str, Any]:
    report_body = _redact_report_value(normalized_body)
    body_text = json.dumps(report_body, ensure_ascii=False, sort_keys=True, default=str)
    return {
        "status": response.status,
        "headers": response.headers,
        "body": report_body if len(body_text) <= 8_000 else None,
        "body_sha256": hashlib.sha256(body_text.encode()).hexdigest(),
        "body_excerpt": body_text[:1_000],
    }


def _redact_report_value(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        parameter_code = next(
            (
                item
                for key, item in value.items()
                if re.sub(r"[^a-z0-9]", "", str(key).lower()) == "paramcode"
            ),
            None,
        )
        sensitive_parameter = (
            isinstance(parameter_code, str)
            and re.sub(r"[^a-z0-9]", "", parameter_code.lower()) in SENSITIVE_REPORT_KEYS
        )
        for key, item in value.items():
            normalized_key = re.sub(r"[^a-z0-9]", "", str(key).lower())
            redacted[str(key)] = (
                "<redacted>"
                if normalized_key in SENSITIVE_REPORT_KEYS
                or sensitive_parameter and normalized_key == "paramvalue"
                else _redact_report_value(item)
            )
        return redacted
    if isinstance(value, list):
        return [_redact_report_value(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_report_value(item) for item in value]
    return value


def _first_difference(left: Any, right: Any, path: str = "$") -> str | None:
    if type(left) is not type(right):
        return f"{path}: type Java={type(left).__name__} FastAPI={type(right).__name__}"
    if isinstance(left, dict):
        left_keys, right_keys = set(left), set(right)
        if left_keys != right_keys:
            return (
                f"{path}: keys Java-only={sorted(left_keys - right_keys)} "
                f"FastAPI-only={sorted(right_keys - left_keys)}"
            )
        for key in sorted(left):
            difference = _first_difference(left[key], right[key], f"{path}.{key}")
            if difference:
                return difference
        return None
    if isinstance(left, list):
        if len(left) != len(right):
            return f"{path}: length Java={len(left)} FastAPI={len(right)}"
        for index, (left_item, right_item) in enumerate(zip(left, right, strict=True)):
            difference = _first_difference(left_item, right_item, f"{path}[{index}]")
            if difference:
                return difference
        return None
    if left != right:
        return f"{path}: Java={left!r} FastAPI={right!r}"
    return None


def _normalize_ota_dynamic(value: JSONValue) -> JSONValue:
    copied = json.loads(json.dumps(value, ensure_ascii=False))
    if isinstance(copied, dict):
        server_time = copied.get("server_time")
        if isinstance(server_time, dict) and isinstance(server_time.get("timestamp"), int):
            server_time["timestamp"] = "<millisecond-timestamp>"
        websocket = copied.get("websocket")
        if isinstance(websocket, dict) and isinstance(websocket.get("token"), str):
            websocket["token"] = "<validated-websocket-token>"  # noqa: S105 - redaction marker
    return cast(JSONValue, copied)


def _valid_ota_credentials(value: JSONValue) -> bool:
    if not isinstance(value, dict):
        return False
    websocket, mqtt = value.get("websocket"), value.get("mqtt")
    if not isinstance(websocket, dict) or not isinstance(mqtt, dict):
        return False
    token = websocket.get("token")
    if not isinstance(token, str) or "." not in token:
        return False
    encoded, raw_timestamp = token.rsplit(".", 1)
    if not raw_timestamp.isdigit():
        return False
    expected = base64.urlsafe_b64encode(
        hmac.new(
            SERVER_SECRET.encode(),
            f"contract-client|AA:BB:CC:DD:EE:01|{raw_timestamp}".encode(),
            hashlib.sha256,
        ).digest()
    ).decode().rstrip("=")
    if not hmac.compare_digest(encoded, expected):
        return False
    client_id, username, password = mqtt.get("client_id"), mqtt.get("username"), mqtt.get("password")
    if not all(isinstance(item, str) for item in (client_id, username, password)):
        return False
    expected_password = base64.b64encode(
        hmac.new(
            MQTT_SIGNATURE_KEY.encode(),
            f"{client_id}|{username}".encode(),
            hashlib.sha256,
        ).digest()
    ).decode()
    try:
        user_data = json.loads(base64.b64decode(str(username)).decode())
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    return hmac.compare_digest(str(password), expected_password) and isinstance(user_data.get("ip"), str)


def _ota_credential_shape(value: JSONValue) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"valid": False}
    websocket, mqtt = value.get("websocket"), value.get("mqtt")
    return {
        "websocket_token_pattern": bool(
            isinstance(websocket, dict)
            and re.fullmatch(r"[A-Za-z0-9_-]{43}\.\d{10}", str(websocket.get("token", "")))
        ),
        "mqtt_fields": sorted(mqtt) if isinstance(mqtt, dict) else [],
    }


def _normalize_created_correct_word(value: JSONValue) -> JSONValue:
    copied = json.loads(json.dumps(value, ensure_ascii=False))
    if isinstance(copied, dict) and isinstance(copied.get("data"), dict):
        data = copied["data"]
        if isinstance(data.get("id"), str):
            data["id"] = "<generated-id>"
        for field in ("createdAt", "updatedAt"):
            if data.get(field) is not None:
                data[field] = "<datetime>"
    return cast(JSONValue, copied)


def _database_config(port: int, database: str) -> dict[str, Any]:
    return {
        "host": "127.0.0.1",
        "port": port,
        "user": "xiaozhi_test",
        "password": "isolated-test-only",
        "db": database,
        "charset": "utf8mb4",
        "autocommit": True,
    }


def _database_row(port: int, database: str, sql: str, params: tuple[Any, ...]) -> dict[str, Any]:
    async def query() -> dict[str, Any]:
        connection = await asyncmy.connect(**_database_config(port, database))
        try:
            async with connection.cursor(DictCursor) as cursor:
                await cursor.execute(sql, params)
                row = await cursor.fetchone()
                return {} if row is None else {str(key): value for key, value in row.items()}
        finally:
            connection.close()

    import asyncio

    return asyncio.run(query())


def _database_scalar(port: int, database: str, sql: str, params: tuple[Any, ...]) -> int:
    row = _database_row(port, database, sql, params)
    return int(next(iter(row.values()), 0))


def _build_report(runner: ContractRunner) -> dict[str, Any]:
    passed = sum(result.passed for result in runner.results)
    failed = len(runner.results) - passed
    categories: dict[str, dict[str, int]] = {}
    for result in runner.results:
        category = categories.setdefault(result.category, {"passed": 0, "failed": 0})
        category["passed" if result.passed else "failed"] += 1
    return {
        "schema_version": 1,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "services": runner.bases,
        "fixture_ids": {"admin": str(ADMIN_ID), "normal": str(NORMAL_ID)},
        "summary": {"total": len(runner.results), "passed": passed, "failed": failed, "skipped": 0},
        "categories": categories,
        "results": [_redact_report_value(asdict(result)) for result in runner.results],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--java-base", default="http://127.0.0.1:18082/xiaozhi")
    parser.add_argument("--fastapi-base", default="http://127.0.0.1:18083/xiaozhi")
    parser.add_argument("--mock-base", default="http://127.0.0.1:18084")
    parser.add_argument("--mysql-port", type=int, default=13316)
    parser.add_argument("--output", type=Path, default=Path("compatibility/contract-results.json"))
    args = parser.parse_args()
    runner = ContractRunner(args.java_base, args.fastapi_base, args.mock_base, args.mysql_port)
    try:
        runner.run_read_only_cases()
        runner.run_validation_cases()
        runner.run_server_auth_and_config()
        runner.run_ota_cases()
        runner.run_external_mock_case()
        runner.run_correct_word_crud()
        runner.run_ota_upload_download()
    finally:
        runner.close()
    report = _build_report(runner)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    summary = report["summary"]
    print(json.dumps(summary, ensure_ascii=False))
    for result in runner.results:
        if not result.passed:
            print(f"FAIL {result.name}: {result.difference}")
    sys.exit(1 if summary["failed"] else 0)


if __name__ == "__main__":
    main()
