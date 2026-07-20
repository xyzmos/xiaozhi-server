#!/usr/bin/env python3
"""Extract the Spring MVC contract without starting the Java application."""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

MAPPING_RE = re.compile(r"@(Get|Post|Put|Delete|Patch)Mapping(?:\((.*)\))?")
CLASS_MAPPING_RE = re.compile(r"@RequestMapping\(\s*(?:value\s*=\s*)?[\"']([^\"']*)[\"']")
PATH_RE = re.compile(r"[\"']([^\"']*)[\"']")
METHOD_RE = re.compile(r"\bpublic\s+(?:<[^>]+>\s+)?[^=(;]+?\s+(\w+)\s*\(")
PERMISSION_RE = re.compile(r'@RequiresPermissions\(\s*"([^"]+)"')

PUBLIC_PATTERNS = (
    "/ota/**",
    "/otaMag/download/**",
    "/webjars/**",
    "/druid/**",
    "/v3/api-docs/**",
    "/doc.html",
    "/favicon.ico",
    "/user/captcha",
    "/user/smsVerification",
    "/user/login",
    "/user/pub-config",
    "/user/register",
    "/user/retrieve-password",
    "/agent/chat-history/download/**",
    "/agent/play/**",
    "/voiceClone/play/**",
)
SERVER_PATTERNS = (
    "/config/**",
    "/device/address-book/call",
    "/agent/chat-history/report",
    "/agent/chat-summary/**",
    "/agent/chat-title/**",
)


@dataclass(frozen=True, slots=True)
class Route:
    method: str
    path: str
    controller: str
    handler: str
    auth: str
    permission: str | None
    source: str
    line: int
    java_signature: str


def _spring_match(path: str, pattern: str) -> bool:
    return fnmatch.fnmatchcase(path, pattern.replace("**", "*"))


def classify_auth(path: str) -> str:
    if any(_spring_match(path, pattern) for pattern in PUBLIC_PATTERNS):
        return "anonymous"
    if any(_spring_match(path, pattern) for pattern in SERVER_PATTERNS):
        return "server-secret"
    return "database-token"


def join_paths(base: str, child: str) -> str:
    if not base:
        base = "/"
    if not base.startswith("/"):
        base = "/" + base
    if not child:
        return base
    if not child.startswith("/"):
        child = "/" + child
    if base == "/":
        return child
    return base.rstrip("/") + child


def extract_controller(path: Path, root: Path) -> list[Route]:
    source = path.read_text(encoding="utf-8")
    class_position = source.find(" class ")
    class_header = source[:class_position] if class_position >= 0 else source
    class_match = list(CLASS_MAPPING_RE.finditer(class_header))
    base = class_match[-1].group(1) if class_match else ""
    controller_match = re.search(r"public\s+class\s+(\w+)", source)
    controller = controller_match.group(1) if controller_match else path.stem
    lines = source.splitlines()
    routes: list[Route] = []
    for index, line in enumerate(lines):
        mapping = MAPPING_RE.search(line)
        if not mapping:
            continue
        method = mapping.group(1).upper()
        arguments = mapping.group(2) or ""
        path_match = PATH_RE.search(arguments)
        child = path_match.group(1) if path_match else ""
        decorator_block: list[str] = [line]
        signature_lines: list[str] = []
        handler = "unknown"
        for cursor in range(index + 1, min(index + 40, len(lines))):
            candidate = lines[cursor]
            if not signature_lines and candidate.lstrip().startswith("@"):
                decorator_block.append(candidate)
                continue
            signature_lines.append(candidate.strip())
            signature = " ".join(signature_lines)
            handler_match = METHOD_RE.search(signature)
            if handler_match:
                handler = handler_match.group(1)
                break
            if "{" in candidate and "public " not in signature:
                break
        permission_match = PERMISSION_RE.search("\n".join(decorator_block))
        route_path = join_paths(base, child)
        routes.append(
            Route(
                method=method,
                path=route_path,
                controller=controller,
                handler=handler,
                auth=classify_auth(route_path),
                permission=permission_match.group(1) if permission_match else None,
                source=str(path.relative_to(root)),
                line=index + 1,
                java_signature=" ".join(signature_lines),
            )
        )
    return routes


def extract_routes(java_root: Path, repository_root: Path) -> list[Route]:
    routes: list[Route] = []
    for controller in sorted(java_root.rglob("*Controller.java")):
        routes.extend(extract_controller(controller, repository_root))
    return sorted(routes, key=lambda route: (route.path, route.method, route.controller, route.handler))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    repository_root = args.repository_root.resolve()
    java_root = repository_root / "main" / "manager-api" / "src" / "main" / "java"
    routes = extract_routes(java_root, repository_root)
    payload = {
        "source": "main/manager-api",
        "contextPath": "/xiaozhi",
        "count": len(routes),
        "routes": [asdict(route) for route in routes],
    }
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    else:
        print(serialized, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
