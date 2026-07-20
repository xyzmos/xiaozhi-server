from __future__ import annotations

import json

from tests.compatibility.authenticated_route_runner import (
    DYNAMIC_RESPONSES,
    JAVA_MANIFEST,
    MULTIPART_ROUTES,
    NO_BODY_ROUTES,
    OTA_DOWNLOAD_UUID_ROUTE,
    RANDOM_PASSWORD_ROUTE,
    SINGLE_CONSTRAINT_PAYLOADS,
    _normalize_ota_download_uuid,
    _normalize_random_password,
    _valid_random_password,
    _valid_uuid4,
    _validate_dynamic_response,
    build_cases,
)
from tests.compatibility.differential_runner import ContractRunner
from tests.compatibility.seed_contract_data import (
    ADMIN_TOKEN,
    MIGRATION_TIMESTAMP_TABLES,
    SERVER_SECRET,
)


def test_authenticated_route_cases_are_fresh_and_close_all_java_routes() -> None:
    manifest = json.loads(JAVA_MANIFEST.read_text(encoding="utf-8"))
    expected = {(str(route["method"]), str(route["path"])) for route in manifest["routes"]}
    cases = build_cases()

    assert manifest["count"] == len(expected) == len(cases) == 154
    assert {case.key for case in cases} == expected
    assert len({(case.method, case.path) for case in cases}) == 154


def test_authenticated_route_cases_use_safe_auth_and_body_profiles() -> None:
    for case in build_cases():
        headers = case.request_kwargs.get("headers", {})
        if case.auth == "database-token":
            assert headers == {"Authorization": f"Bearer {ADMIN_TOKEN}"}
        elif case.auth == "server-secret":
            assert headers == {"Authorization": f"Bearer {SERVER_SECRET}"}
        else:
            assert headers == {}

        if case.method in {"GET", "DELETE"}:
            assert "json" not in case.request_kwargs
        elif case.key in MULTIPART_ROUTES | NO_BODY_ROUTES:
            assert "json" not in case.request_kwargs
        elif case.key in SINGLE_CONSTRAINT_PAYLOADS:
            assert case.request_kwargs.get("json") == SINGLE_CONSTRAINT_PAYLOADS[case.key]
        else:
            assert case.request_kwargs.get("json") == {}


def test_array_body_validation_routes_are_not_hidden_by_safe_case_overrides() -> None:
    cases = {case.key: case for case in build_cases()}
    object_sent_to_array_routes = {
        ("POST", "/admin/dict/data/delete"),
        ("POST", "/admin/dict/type/delete"),
        ("POST", "/admin/params/delete"),
        ("PUT", "/admin/users/changeStatus/{status}"),
        ("POST", "/agent/template/batch-remove"),
        ("POST", "/correct-word/file/batch-delete"),
        ("POST", "/models/provider/delete"),
        ("POST", "/ttsVoice/delete"),
    }
    for key in object_sent_to_array_routes:
        assert cases[key].request_kwargs.get("json") == {}
    assert "json" not in cases[("DELETE", "/datasets/batch")].request_kwargs


def test_dynamic_response_normalizers_require_the_full_java_formats() -> None:
    valid_password = "aA1!bcDEF234"  # noqa: S105 - format-only fixture value
    assert _valid_random_password(valid_password)
    assert not _valid_random_password("aA1!short")
    assert not _valid_random_password("aA1_bcDEF234")
    assert not _valid_random_password("abcdefghijkl")

    valid_uuid = "123e4567-e89b-42d3-a456-426614174000"
    assert _valid_uuid4(valid_uuid)
    assert not _valid_uuid4("123e4567-e89b-12d3-a456-426614174000")
    assert not _valid_uuid4(valid_uuid.upper())

    password_body = {"code": 0, "msg": "success", "data": valid_password}
    uuid_body = {"code": 0, "msg": "success", "data": valid_uuid}
    assert _normalize_random_password(password_body) == {
        "code": 0,
        "msg": "success",
        "data": "<valid-random-password>",
    }
    assert _normalize_ota_download_uuid(uuid_body) == {
        "code": 0,
        "msg": "success",
        "data": "<valid-uuid-v4>",
    }
    invalid = {"code": 0, "msg": "success", "data": "not-dynamic"}
    assert _normalize_random_password(invalid) is invalid
    assert _normalize_ota_download_uuid(invalid) is invalid
    assert set(DYNAMIC_RESPONSES) == {RANDOM_PASSWORD_ROUTE, OTA_DOWNLOAD_UUID_ROUTE}


def test_identical_invalid_dynamic_values_fail_both_independent_format_checks() -> None:
    runner = ContractRunner("http://java.invalid", "http://fastapi.invalid", "http://mock.invalid", 0)
    try:
        runner.add_custom("dynamic", "test", {"body": True})
        invalid = {"code": 0, "msg": "success", "data": "same-invalid-value"}
        _validate_dynamic_response(
            runner,
            java_body=invalid,
            fastapi_body=invalid,
            validator=_valid_uuid4,
            label="uuid_v4",
        )
        result = runner.results[-1]
        assert not result.passed
        assert result.checks["body"]
        assert not result.checks["java:uuid_v4"]
        assert not result.checks["fastapi:uuid_v4"]
        assert result.difference == (
            "invalid dynamic response format: java:uuid_v4, fastapi:uuid_v4"
        )
    finally:
        runner.close()


def test_migration_timestamp_fixture_is_limited_to_generated_seed_rows() -> None:
    assert MIGRATION_TIMESTAMP_TABLES == (
        "ai_model_provider",
        "sys_dict_data",
        "sys_dict_type",
    )
