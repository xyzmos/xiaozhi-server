from __future__ import annotations

from tests.compatibility.differential_runner import (
    CapturedResponse,
    _redact_report_value,
    _response_summary,
)


def test_recursive_report_redaction_preserves_non_sensitive_shape() -> None:
    source = {
        "data": {
            "private_key": "generated-private-key",
            "server.secret": "fixture-secret",
            "mqtt_signature_key": "fixture-signature",
            "token": "fixture-token",
            "token_count": 17,
            "public_key": "public-material",
            "params": [
                {"paramCode": "server.secret", "paramValue": "fixture-param-secret"},
                {"paramCode": "server.websocket", "paramValue": "ws://safe.example/ws"},
            ],
        },
        "headers": {"authorization": "Bearer fixture"},
    }

    assert _redact_report_value(source) == {
        "data": {
            "private_key": "<redacted>",
            "server.secret": "<redacted>",
            "mqtt_signature_key": "<redacted>",
            "token": "<redacted>",
            "token_count": 17,
            "public_key": "public-material",
            "params": [
                {"paramCode": "server.secret", "paramValue": "<redacted>"},
                {"paramCode": "server.websocket", "paramValue": "ws://safe.example/ws"},
            ],
        },
        "headers": {"authorization": "<redacted>"},
    }


def test_response_summary_never_embeds_sensitive_values_in_body_or_excerpt() -> None:
    response = CapturedResponse(
        status=200,
        headers={"content-type": "application/json", "content-disposition": None, "content-length": None},
        body={"token": "fixture-token", "password": "fixture-password"},
        body_sha256="raw-response-digest",
    )

    summary = _response_summary(response, response.body)

    assert summary["body"] == {"token": "<redacted>", "password": "<redacted>"}
    assert "fixture-token" not in summary["body_excerpt"]
    assert "fixture-password" not in summary["body_excerpt"]
