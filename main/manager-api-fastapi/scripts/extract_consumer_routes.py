#!/usr/bin/env python3
"""Extract manager-api HTTP call sites from all three in-repository consumers."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import NamedTuple

TARGET_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = TARGET_ROOT.parents[1]
MAIN_ROOT = REPO_ROOT / "main"

WEB_ROOT = MAIN_ROOT / "manager-web" / "src"
MOBILE_ROOT = MAIN_ROOT / "manager-mobile" / "src"
SERVER_ROOT = MAIN_ROOT / "xiaozhi-server"

WEB_CHAIN = re.compile(
    r"\.url\(\s*(?P<quote>[`'\"])(?P<url>.*?)(?P=quote)\s*\)"
    r"(?:\s*//[^\n]*)?\s*\.method\(\s*['\"](?P<method>[A-Za-z]+)['\"]\s*\)",
    re.DOTALL,
)
WEB_CONFIG = re.compile(
    r"\burl\s*:\s*(?P<quote>[`'\"])(?P<url>.*?)(?P=quote)\s*,"
    r"\s*method\s*:\s*['\"](?P<method>[A-Za-z]+)['\"]",
    re.DOTALL,
)
WEB_TEMPLATE_URL = re.compile(
    r"(?P<quote>`)(?P<url>\$\{(?:(?:Api|api)\.)?getServiceUrl\(\)\}/.*?)"
    r"(?P=quote)"
)
WEB_CONCAT_URL = re.compile(
    r"(?:(?:Api|api)\.)?getServiceUrl\(\)\s*\+\s*(?P<quote>`)(?P<url>/.*?)(?P=quote)"
)
MOBILE_HTTP = re.compile(
    r"http\.(?P<method>Get|Post|Put|Delete|Patch)(?:<[^\n(]*>)?\(\s*"
    r"(?P<quote>[`'\"])(?P<url>.*?)(?P=quote)"
)
MOBILE_UNI = re.compile(
    r"uni\.request\(\s*\{(?:(?!\}\s*\)).)*?\burl\s*:\s*"
    r"(?P<quote>[`'\"])(?P<url>.*?)(?P=quote)\s*,\s*"
    r"method\s*:\s*['\"](?P<method>[A-Za-z]+)['\"]",
    re.DOTALL,
)
SERVER_CLIENT = re.compile(
    r"\._execute_async_request\(\s*['\"](?P<method>[A-Za-z]+)['\"]\s*,\s*"
    r"f?(?P<quote>[`'\"])(?P<url>/.*?)(?P=quote)",
    re.DOTALL,
)
SERVER_DIRECT = re.compile(
    r"f(?P<quote>[`'\"])\{api_url\}(?P<url>/device/address-book/call)(?P=quote)"
)
JS_EXPRESSION = re.compile(r"\$\{([^{}]+)\}")
PYTHON_EXPRESSION = re.compile(r"\{([^{}]+)\}")
PATH_PARAMETER = re.compile(r"\{[^/{}]+\}")


class CallSite(NamedTuple):
    consumer: str
    method: str
    path: str
    source: str


def _source(path: Path, text: str, offset: int) -> str:
    line = text.count("\n", 0, offset) + 1
    return f"{path.relative_to(REPO_ROOT).as_posix()}:{line}"


def _parameter_name(expression: str) -> str:
    identifiers = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expression)
    ignored = {"getServiceUrl", "encodeURIComponent", "toString", "value"}
    useful = [item for item in identifiers if item not in ignored]
    return useful[-1] if useful else "value"


def normalize_path(raw: str) -> str:
    value = raw.strip()
    for marker in (
        "${getServiceUrl()}",
        "${Api.getServiceUrl()}",
        "${api.getServiceUrl()}",
        "${baseUrlInput.value}",
        "${getEnvBaseUrl()}",
        "{api_url}",
    ):
        if value.startswith(marker):
            value = value[len(marker) :]
            break
    value = value.split("?", 1)[0].split("#", 1)[0]
    value = JS_EXPRESSION.sub(lambda match: "{" + _parameter_name(match.group(1)) + "}", value)
    value = PYTHON_EXPRESSION.sub(lambda match: "{" + _parameter_name(match.group(1)) + "}", value)
    if not value.startswith("/"):
        raise ValueError(f"consumer URL does not resolve to a manager-api path: {raw!r}")
    return re.sub(r"/{2,}", "/", value).rstrip("/") or "/"


def _iter_source_files(root: Path, suffixes: set[str]) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix in suffixes
        and "node_modules" not in path.parts
        and "dist" not in path.parts
    )


def extract_web() -> list[CallSite]:
    calls: list[CallSite] = []
    for path in _iter_source_files(WEB_ROOT, {".js", ".mjs", ".vue"}):
        text = path.read_text(encoding="utf-8")
        covered: list[tuple[int, int]] = []
        for pattern in (WEB_CHAIN, WEB_CONFIG):
            for match in pattern.finditer(text):
                raw_url = match.group("url")
                if "getServiceUrl()" not in raw_url:
                    continue
                calls.append(
                    CallSite(
                        "manager-web",
                        match.group("method").upper(),
                        normalize_path(raw_url),
                        _source(path, text, match.start("url")),
                    )
                )
                covered.append(match.span("url"))

        def already_covered(offset: int, spans: list[tuple[int, int]] = covered) -> bool:
            return any(start <= offset < end for start, end in spans)

        for pattern in (WEB_TEMPLATE_URL, WEB_CONCAT_URL):
            for match in pattern.finditer(text):
                if already_covered(match.start("url")):
                    continue
                line_start = text.rfind("\n", 0, match.start()) + 1
                line_end = text.find("\n", match.end())
                line = text[line_start : len(text) if line_end < 0 else line_end]
                if "console.log" in line:
                    continue
                calls.append(
                    CallSite(
                        "manager-web",
                        "GET",
                        normalize_path(match.group("url")),
                        _source(path, text, match.start("url")),
                    )
                )

        literal_builders = len(
            re.findall(r"\.url\(\s*[`'\"]\$\{getServiceUrl\(\)\}", text)
        )
        parsed_builders = sum(
            1
            for match in WEB_CHAIN.finditer(text)
            if "getServiceUrl()" in match.group("url")
        )
        if literal_builders != parsed_builders:
            raise RuntimeError(
                f"unparsed manager-web request builder(s) in {path}: "
                f"found={literal_builders}, parsed={parsed_builders}"
            )
    return calls


def extract_mobile() -> list[CallSite]:
    calls: list[CallSite] = []
    for path in _iter_source_files(MOBILE_ROOT, {".ts", ".vue"}):
        text = path.read_text(encoding="utf-8")
        parsed_http = list(MOBILE_HTTP.finditer(text))
        raw_http_count = len(re.findall(r"\bhttp\.(?:Get|Post|Put|Delete|Patch)(?:<|\()", text))
        if raw_http_count != len(parsed_http):
            raise RuntimeError(
                f"unparsed manager-mobile http call(s) in {path}: "
                f"found={raw_http_count}, parsed={len(parsed_http)}"
            )
        for match in parsed_http:
            calls.append(
                CallSite(
                    "manager-mobile",
                    match.group("method").upper(),
                    normalize_path(match.group("url")),
                    _source(path, text, match.start("url")),
                )
            )
        for match in MOBILE_UNI.finditer(text):
            raw_url = match.group("url")
            if not raw_url.startswith(("${baseUrlInput.value}", "${getEnvBaseUrl()}")):
                continue
            calls.append(
                CallSite(
                    "manager-mobile",
                    match.group("method").upper(),
                    normalize_path(raw_url),
                    _source(path, text, match.start("url")),
                )
            )
    return calls


def extract_server() -> list[CallSite]:
    calls: list[CallSite] = []
    path = SERVER_ROOT / "config" / "manage_api_client.py"
    text = path.read_text(encoding="utf-8")
    matches = list(SERVER_CLIENT.finditer(text))
    raw_count = len(re.findall(r"\._execute_async_request\(", text))
    if raw_count != len(matches):
        raise RuntimeError(
            f"unparsed xiaozhi-server manager client call(s): found={raw_count}, parsed={len(matches)}"
        )
    for match in matches:
        calls.append(
            CallSite(
                "xiaozhi-server",
                match.group("method").upper(),
                normalize_path(match.group("url")),
                _source(path, text, match.start("url")),
            )
        )

    direct_path = SERVER_ROOT / "plugins_func" / "functions" / "call_device.py"
    direct_text = direct_path.read_text(encoding="utf-8")
    direct_matches = list(SERVER_DIRECT.finditer(direct_text))
    if len(direct_matches) != 1:
        raise RuntimeError(f"expected one direct manager-api call in {direct_path}, found {len(direct_matches)}")
    match = direct_matches[0]
    calls.append(
        CallSite(
            "xiaozhi-server",
            "GET",
            normalize_path(match.group("url")),
            _source(direct_path, direct_text, match.start("url")),
        )
    )
    return calls


def canonical_route(method: str, path: str) -> tuple[str, str]:
    return method, PATH_PARAMETER.sub("{}", path)


def build_manifest() -> dict[str, object]:
    calls = sorted(
        extract_web() + extract_mobile() + extract_server(),
        key=lambda item: (item.consumer, item.source, item.method, item.path),
    )
    consumers: dict[str, dict[str, object]] = {}
    for consumer in ("manager-web", "manager-mobile", "xiaozhi-server"):
        selected = [item for item in calls if item.consumer == consumer]
        consumers[consumer] = {
            "callSites": len(selected),
            "uniqueRoutes": len({canonical_route(item.method, item.path) for item in selected}),
            "methods": dict(sorted(Counter(item.method for item in selected).items())),
        }
    all_routes = {canonical_route(item.method, item.path) for item in calls}
    return {
        "count": len(calls),
        "uniqueRoutes": len(all_routes),
        "consumers": consumers,
        "calls": [item._asdict() for item in calls],
    }


if __name__ == "__main__":
    print(json.dumps(build_manifest(), ensure_ascii=False, indent=2, sort_keys=False))
