#!/usr/bin/env python3
"""Render the auditable Java/FastAPI compatibility matrix from checked-in inventories."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

TARGET_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = TARGET_ROOT.parents[1]
JAVA_ROOT = REPOSITORY_ROOT / "main" / "manager-api"
JAVA_SOURCE_ROOT = JAVA_ROOT / "src" / "main" / "java"
JAVA_RESOURCE_ROOT = JAVA_ROOT / "src" / "main" / "resources"
JAVA_MANIFEST = TARGET_ROOT / "compatibility" / "java-routes.json"
CONSUMER_MANIFEST = TARGET_ROOT / "compatibility" / "consumer-routes.json"
CONTRACT_RESULTS = TARGET_ROOT / "compatibility" / "contract-results.json"
ROUTE_SURFACE_RESULTS = TARGET_ROOT / "compatibility" / "route-surface-results.json"
AUTHENTICATED_ROUTE_RESULTS = TARGET_ROOT / "compatibility" / "authenticated-route-results.json"
PATH_PARAMETER = re.compile(r"\{[^/{}]+\}")


DIFFERENTIAL_CASES: dict[tuple[str, str], str] = {
    ("GET", "/user/pub-config"): "1",
    ("GET", "/user/info"): "9（七语言/过期 Token/Long）",
    ("GET", "/admin/users"): "3（权限/序列化/非法分页）",
    ("GET", "/agent/list"): "1",
    ("GET", "/device/bind/{}"): "1",
    ("GET", "/models/provider"): "1",
    ("GET", "/correct-word/file/list"): "1",
    ("GET", "/correct-word/file/download/{}"): "2（二进制/更新后下载）",
    ("PUT", "/device/update/{}"): "3（上下界/UTF-16 长度）",
    ("POST", "/models/provider"): "1（约束集合）",
    ("POST", "/config/server-base"): "3（缺失/错误/正确 secret）",
    ("GET", "/ota/"): "1（MIME/body）",
    ("POST", "/ota/"): "4（必填/格式/凭证/密码学）",
    ("POST", "/ota/activate"): "3",
    ("POST", "/device/tools/list/{}"): "2（响应/外呼格式）",
    ("POST", "/correct-word/file"): "2（响应/DB）",
    ("PUT", "/correct-word/file/{}"): "2（响应/DB）",
    ("DELETE", "/correct-word/file/{}"): "1（级联副作用）",
    ("POST", "/otaMag/upload"): "2（上传/扩展名错误）",
    ("POST", "/otaMag"): "2（响应/DB）",
    ("GET", "/otaMag/download/{}"): "4（次数限制及二进制）",
}

DOMAIN_TESTS = {
    "AdminController": "sys",
    "SysParamsController": "sys",
    "SysDictDataController": "sys",
    "SysDictTypeController": "sys",
    "ServerSideManageController": "sys",
    "LoginController": "security",
    "ConfigController": "config",
    "AgentController": "agent",
    "AgentChatHistoryController": "agent",
    "AgentMcpAccessPointController": "agent",
    "AgentSnapshotController": "agent",
    "AgentTemplateController": "agent",
    "AgentVoicePrintController": "agent",
    "CorrectWordController": "correctword",
    "DeviceController": "device",
    "KnowledgeBaseController": "knowledge",
    "KnowledgeFilesController": "knowledge",
    "ModelController": "model",
    "ModelProviderController": "model",
    "OTAController": "device",
    "OTAMagController": "device",
    "TimbreController": "timbre",
    "VoiceCloneController": "voiceclone",
    "VoiceResourceController": "voiceclone",
}


def _canonical(path: str) -> str:
    return PATH_PARAMETER.sub("{}", path)


def _declaration(route: dict[str, Any]) -> str:
    source_path = REPOSITORY_ROOT / route["source"]
    lines = source_path.read_text(encoding="utf-8").splitlines()
    excerpt = "\n".join(lines[int(route["line"]) - 1 : int(route["line"]) + 60])
    match = re.search(r"\bpublic\s+", excerpt)
    if match is None:
        raise ValueError(f"public declaration not found for {route['controller']}.{route['handler']}")
    declaration = excerpt[match.start() :]
    depth = 0
    saw_parenthesis = False
    for offset, character in enumerate(declaration):
        if character == "(":
            depth += 1
            saw_parenthesis = True
        elif character == ")":
            depth -= 1
        elif character == "{" and saw_parenthesis and depth == 0:
            return " ".join(declaration[:offset].split())
    raise ValueError(f"unterminated declaration for {route['controller']}.{route['handler']}")


def _parameter_text(declaration: str, handler: str) -> str:
    marker = re.search(rf"\b{re.escape(handler)}\s*\(", declaration)
    if marker is None:
        return ""
    start = marker.end() - 1
    depth = 0
    for offset in range(start, len(declaration)):
        character = declaration[offset]
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return declaration[start + 1 : offset]
    return ""


def _split_parameters(value: str) -> list[str]:
    result: list[str] = []
    start = 0
    round_depth = 0
    angle_depth = 0
    in_quote: str | None = None
    escaped = False
    for offset, character in enumerate(value):
        if escaped:
            escaped = False
            continue
        if character == "\\":
            escaped = True
            continue
        if in_quote is not None:
            if character == in_quote:
                in_quote = None
            continue
        if character in {'"', "'"}:
            in_quote = character
        elif character == "(":
            round_depth += 1
        elif character == ")":
            round_depth -= 1
        elif character == "<":
            angle_depth += 1
        elif character == ">":
            angle_depth -= 1
        elif character == "," and round_depth == 0 and angle_depth == 0:
            result.append(value[start:offset].strip())
            start = offset + 1
    tail = value[start:].strip()
    if tail:
        result.append(tail)
    return result


def _without_annotations(value: str) -> str:
    output: list[str] = []
    offset = 0
    while offset < len(value):
        if value[offset] != "@":
            output.append(value[offset])
            offset += 1
            continue
        offset += 1
        while offset < len(value) and (value[offset].isalnum() or value[offset] in "._$"):
            offset += 1
        while offset < len(value) and value[offset].isspace():
            offset += 1
        if offset < len(value) and value[offset] == "(":
            depth = 1
            offset += 1
            in_quote: str | None = None
            while offset < len(value) and depth:
                character = value[offset]
                if in_quote is not None:
                    if character == in_quote and value[offset - 1] != "\\":
                        in_quote = None
                elif character in {'"', "'"}:
                    in_quote = character
                elif character == "(":
                    depth += 1
                elif character == ")":
                    depth -= 1
                offset += 1
        while offset < len(value) and value[offset].isspace():
            offset += 1
    return " ".join("".join(output).split())


def _type_and_name(parameter: str) -> tuple[str, str]:
    cleaned = _without_annotations(parameter).removeprefix("final ").strip()
    pieces = cleaned.rsplit(" ", 1)
    if len(pieces) != 2:
        return cleaned, cleaned
    return pieces[0], pieces[1]


def _request_surface(route: dict[str, Any], declaration: str) -> str:
    path_names = re.findall(r"\{([^/{}]+)\}", route["path"])
    headers: list[str] = []
    queries: list[str] = []
    bodies: list[str] = []
    multipart: list[str] = []
    for parameter in _split_parameters(_parameter_text(declaration, route["handler"])):
        parameter_type, name = _type_and_name(parameter)
        if "HttpServletResponse" in parameter_type or "HttpServletRequest" in parameter_type:
            continue
        if "@PathVariable" in parameter:
            continue
        if "@RequestHeader" in parameter:
            quoted = re.search(r'@RequestHeader(?:\([^)]*)?["\']([^"\']+)["\']', parameter)
            headers.append(quoted.group(1) if quoted else name)
        elif "MultipartFile" in parameter_type:
            multipart.append(name)
        elif "@RequestBody" in parameter:
            bodies.append(parameter_type)
        elif "@RequestParam" in parameter or "@ParameterObject" in parameter:
            queries.append(f"{name}:{parameter_type}" if parameter_type != name else name)
        elif route["method"] == "GET" or route["controller"] == "ModelProviderController":
            queries.append(f"{name}:{parameter_type}" if parameter_type != name else name)
    parts: list[str] = []
    if path_names:
        parts.append("Path:" + ",".join(path_names))
    if headers:
        parts.append("Header:" + ",".join(headers))
    if queries:
        parts.append("Query:" + ",".join(queries))
    if bodies:
        parts.append("Body:" + ",".join(bodies))
    if multipart:
        parts.append("Multipart:" + ",".join(multipart))
    return "; ".join(parts) if parts else "—"


def _response_type(route: dict[str, Any], declaration: str) -> str:
    path = route["path"]
    if path == "/user/captcha":
        return "image/gif 二进制"
    if path == "/ota/" and route["method"] == "GET":
        return "裸 text/plain"
    if path.startswith("/ota/"):
        return "裸 application/json"
    if path in {
        "/agent/play/{uuid}",
        "/agent/chat-history/download/{uuid}/current",
        "/agent/chat-history/download/{uuid}/previous",
        "/correct-word/file/download/{fileId}",
        "/otaMag/download/{uuid}",
        "/voiceClone/play/{uuid}",
    }:
        return "流式/二进制 + 原下载 headers"
    match = re.search(rf"public\s+(.+?)\s+{re.escape(route['handler'])}\s*\(", declaration)
    return_type = match.group(1) if match else "unknown"
    if return_type.startswith("Result<"):
        return "envelope " + return_type.removeprefix("Result")
    return return_type


def _permission(route: dict[str, Any]) -> str | None:
    source_path = REPOSITORY_ROOT / route["source"]
    lines = source_path.read_text(encoding="utf-8").splitlines()
    excerpt = "\n".join(lines[int(route["line"]) - 1 : int(route["line"]) + 60])
    declaration_offset = excerpt.find("public ")
    decorators = excerpt if declaration_offset < 0 else excerpt[:declaration_offset]
    match = re.search(r'@RequiresPermissions\(\s*"([^"]+)"', decorators)
    return match.group(1) if match else None


def _side_effect(route: dict[str, Any]) -> str:
    method = route["method"]
    path = route["path"]
    handler = route["handler"]
    controller = route["controller"]
    if path == "/user/captcha":
        return "Redis-W(captcha TTL); GIF"
    if path == "/user/login":
        return "DB-R/W(token); Redis-R/DEL(captcha)"
    if path == "/user/smsVerification":
        return "Redis-R/W(TTL/频控); 外部-Aliyun SMS"
    if path in {"/user/register", "/user/retrieve-password", "/user/change-password"}:
        return "DB-W(user/token); Redis-R/DEL(SMS)"
    if path in {"/user/info", "/user/pub-config"}:
        return "DB-R; Redis-R/W(cache)"
    if path.startswith("/admin/server/"):
        return "DB/Redis-R(secret/WS); Redis-W(one-shot); 外部-WebSocket" if method == "POST" else "DB/Redis-R"
    if path.startswith("/admin/params"):
        if method == "GET":
            return "DB-R"
        if method == "PUT":
            return "DB-W; Redis-W; 外部-配置端点探测(按 paramCode)"
        return "DB-W; Redis-W/DEL"
    if path.startswith("/admin/dict"):
        return "DB-R; Redis-R/W(dict cache)" if method == "GET" else "DB-W; Redis-DEL(dict cache)"
    if path == "/admin/device/all" or path == "/admin/users":
        return "DB-R"
    if path == "/admin/users/{id}" and method == "DELETE":
        return "DB-W(用户/token/device/agent 级联)"
    if path.startswith("/admin/users"):
        return "DB-W(user/password/status/token)"
    if path.startswith("/config/"):
        return "DB-R; Redis-R/W(runtime/model/timbre cache)"
    if path.startswith("/agent/mcp/tools"):
        return "DB/Redis-R; 外部-WebSocket MCP"
    if path.startswith("/agent/mcp/address"):
        return "DB/Redis-R; AES token 生成"
    if path.startswith("/agent/voice-print"):
        return "DB-R" if method == "GET" else "DB-W; 外部-voiceprint HTTP"
    if "/chat-summary/" in path or "/chat-title/" in path:
        return "DB-R/W(chat); 外部-OpenAI-compatible LLM"
    if path == "/agent/chat-history/report":
        return "DB-W(chat/session); server-secret"
    if path.startswith("/agent/chat-history/getDownloadUrl/"):
        return "DB-R(chat/session); Redis-W(download token TTL)"
    if "/chat-history/download/" in path or path.startswith("/agent/play/"):
        return "DB/Redis-R(one-shot); 文件-R/流式"
    if path.startswith("/agent/audio/"):
        return "DB-R(audio); Redis-W(one-shot URL)"
    if path.startswith("/agent/") or path == "/agent":
        return "DB-R; Redis-R" if method == "GET" else "DB-W(含快照/映射/标签事务); Redis-DEL"
    if path.startswith("/correct-word/"):
        if "download" in path:
            return "DB-R(content); 二进制"
        return "DB-R" if method == "GET" else "DB-W(file/items/mapping 事务)"
    if path.startswith("/datasets"):
        if path == "/datasets/rag-models":
            return "DB-R(model config)"
        if method == "GET" and not path.endswith("/chunks"):
            return "DB-R"
        return "DB-R/W; 外部-RAGFlow HTTP(upload/dataset/document/chunk/retrieval)"
    if path.startswith("/device/tools/") or (path == "/device/bind/{agentId}" and method == "POST"):
        return "DB/Redis-R; 外部-MQTT gateway HTTP + daily auth"
    if path in {"/device/address-book/call", "/device/address-book/lookup"}:
        return "DB-R; 外部-MQTT gateway HTTP; server-secret"
    if path.startswith("/device/"):
        return "DB-R; Redis-R" if method == "GET" else "DB-W(device/bind/address-book); Redis-R/W"
    if path == "/ota/":
        if method == "GET":
            return "—"
        return "DB/Redis-R(设备/固件/配置); HMAC/Base64/时间戳凭证"
    if path == "/ota/activate":
        return "DB-R/W(device activation); Redis-R/W(TTL)"
    if path.startswith("/otaMag/upload"):
        return "文件-W(MD5/扩展名/大小)"
    if path.startswith("/otaMag/download"):
        return "Redis-R/W(一次性/次数); 文件-R/流式"
    if path.startswith("/otaMag/getDownloadUrl"):
        return "DB-R; Redis-W(download token TTL)"
    if path.startswith("/otaMag"):
        if method == "GET":
            return "DB-R"
        if method == "DELETE":
            return "DB-W(OTA metadata); 文件-DEL"
        return "DB-W(OTA metadata)"
    if path.startswith("/models"):
        return "DB-R; Redis-R/W(model cache)" if method == "GET" else "DB-W; Redis-DEL(model/config cache)"
    if path.startswith("/ttsVoice"):
        return "DB-R; Redis-R/W(timbre cache)" if method == "GET" else "DB-W; Redis-DEL(timbre/config cache)"
    if path.startswith("/voiceClone"):
        if path.startswith("/voiceClone/play"):
            return "Redis-R/DEL(one-shot); 文件/外部音频-R"
        if handler == "getAudioId":
            return "DB-R; Redis-W(one-shot URL)"
        if handler == "updateName":
            return "DB-W(train record name)"
        if method == "GET":
            return "DB-R"
        return "DB-R/W(train state); 文件-W; 外部-火山语音克隆 HTTP"
    if path.startswith("/voiceResource"):
        return "DB-R" if method == "GET" else "DB-W(voice resource)"
    operation = "DB-R" if method == "GET" else "DB-W"
    return f"{operation} ({controller}.{handler})"


def _verification(route: dict[str, Any]) -> str:
    domain = DOMAIN_TESTS.get(route["controller"])
    domain_status = f"领域✓({domain}，域级)" if domain else "领域—"
    diff = DIFFERENTIAL_CASES.get((route["method"], _canonical(route["path"])))
    diff_status = f"差分✓{diff}" if diff else "差分—"
    if route["path"] == "/otaMag/getDownloadUrl/{id}":
        diff_status = "差分间接✓(供下载链路)"
    return f"结构✓；请求面差分✓1；认证业务面差分✓1；{domain_status}；{diff_status}"


def _escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _inventory_section(java_routes: list[dict[str, Any]]) -> str:
    controller_counts = Counter(route["controller"] for route in java_routes)
    mapper_files = sorted((JAVA_RESOURCE_ROOT / "mapper").rglob("*.xml"))
    changelog_root = JAVA_RESOURCE_ROOT / "db" / "changelog"
    sql_files = sorted(changelog_root.rglob("*.sql"))
    master = changelog_root / "db.changelog-master.yaml"
    changeset_refs = master.read_text(encoding="utf-8").count("changeSet:")
    entity_files = list(JAVA_SOURCE_ROOT.rglob("entity/*.java"))
    dto_files = [path for path in JAVA_SOURCE_ROOT.rglob("*.java") if "dto" in path.parts]
    vo_files = list(JAVA_SOURCE_ROOT.rglob("vo/*.java"))
    dao_files = list(JAVA_SOURCE_ROOT.rglob("dao/*.java"))
    service_files = list(JAVA_SOURCE_ROOT.rglob("service/**/*.java"))
    service_impl_files = list(JAVA_SOURCE_ROOT.rglob("service/impl/*.java"))
    assert len(controller_counts) == 24
    assert len(mapper_files) == 20
    assert len(sql_files) == 101
    assert changeset_refs == 101
    assert len(entity_files) == 29
    assert len(dto_files) == 58
    assert len(vo_files) == 14
    assert len(dao_files) == 29
    mapper_names = "、".join(f"`{path.relative_to(JAVA_RESOURCE_ROOT).as_posix()}`" for path in mapper_files)
    controller_names = "、".join(
        f"`{controller}`({controller_counts[controller]})" for controller in sorted(controller_counts)
    )
    return f"""## Java 基线静态盘点

- Controller：24 个、154 条映射。按 Controller 的路由数为：{controller_names}。
- 数据分层：`entity/` 29 个 Java 文件（28 个 `*Entity.java` 加 `BaseEntity`）、`dto/` 58 个、
  `vo/` 14 个、`dao/` 29 个、`service/` 树 {len(service_files)} 个文件（其中
  `service/impl/` {len(service_impl_files)} 个）。FastAPI 对应落在 `schemas/`、`repositories/`、
  `services/`、`routers/`、`integrations/` 与 `jobs/`，没有把跨表事务放进路由。
- MyBatis XML：20 个，分别是 {mapper_names}。
- Liquibase：`db.changelog-master.yaml` 含 {changeset_refs} 个 `changeSet` 引用，目录中恰有
  {len(sql_files)} 个 SQL；Python 部署继续执行这 101 个原始 SQL，不改写历史。
- 定时工作：`DocumentStatusSyncTask` 每次完成后延迟 30 秒，扫描 RAGFlow RUNNING 文档并
  回写 SUCCESS/FAIL/CANCEL 与统计；当前 Java 源码另有 `AgentSnapshotRedactionRunner`，启动时
  执行一次并在滚动部署期每 15 秒补偿脱敏旧快照。FastAPI 将工作移到独立 jobs 进程，并以
  Redis 分布式锁/watchdog 防止多 worker 重复执行。
- 外部集成：RAGFlow dataset/document/chunk/retrieval/upload；阿里云短信；火山语音克隆训练与
  音频；声纹 HTTP；OpenAI-compatible LLM 摘要/标题；MQTT gateway HTTP；MCP/管理动作
  WebSocket；OTA/WS/MQTT 的 HMAC、Base64、时间戳与下载文件存储。自动测试只访问可重复 mock，
  未使用真实付费凭证。
"""


def _require_complete_route_report(
    report: dict[str, Any],
    routes: list[dict[str, Any]],
    *,
    request_profile: str,
    side_effect_policy: str,
) -> None:
    expected_summary = {"total": 154, "passed": 154, "failed": 0, "skipped": 0}
    expected_names = [f"{route['method']} {route['path']}" for route in routes]
    assert report["summary"] == expected_summary
    assert report["coverage"] == {
        "java_routes": 154,
        "request_profile": request_profile,
        "side_effect_policy": side_effect_policy,
    }
    assert [result["name"] for result in report["results"]] == expected_names
    assert all(result["passed"] is True and result["difference"] is None for result in report["results"])


def render() -> str:
    java_manifest = json.loads(JAVA_MANIFEST.read_text(encoding="utf-8"))
    consumer_manifest = json.loads(CONSUMER_MANIFEST.read_text(encoding="utf-8"))
    contract = json.loads(CONTRACT_RESULTS.read_text(encoding="utf-8"))
    route_surface = json.loads(ROUTE_SURFACE_RESULTS.read_text(encoding="utf-8"))
    authenticated_route = json.loads(AUTHENTICATED_ROUTE_RESULTS.read_text(encoding="utf-8"))
    routes: list[dict[str, Any]] = java_manifest["routes"]
    assert len(routes) == 154
    assert contract["summary"] == {"total": 49, "passed": 49, "failed": 0, "skipped": 0}
    _require_complete_route_report(
        route_surface,
        routes,
        request_profile="missing-auth-or-safe-invalid-input",
        side_effect_policy="no successful write request is issued",
    )
    _require_complete_route_report(
        authenticated_route,
        routes,
        request_profile="authenticated-safe-business-or-validation",
        side_effect_policy="no intentional successful writes",
    )
    assert len(DIFFERENTIAL_CASES) == 21

    lines = [
        "# manager-api FastAPI 兼容性矩阵",
        "",
        "> 生成依据：`main/manager-api-fastapi/compatibility/java-routes.json`、",
        "> `main/manager-api-fastapi/compatibility/consumer-routes.json`、`route-surface-results.json`、",
        "> `authenticated-route-results.json`、`contract-results.json` 和当前 Java 源码。接口路径均省略",
        "> 共同前缀 `/xiaozhi`。",
        "",
        "## 结论与状态口径",
        "",
        "Java 基线共有 **154** 条 Spring MVC 路由；FastAPI 已注册 **154/154（100%）**，并由",
        "`tests/test_java_route_manifest.py` 对源码清单 freshness、数量和 method/path 注册闭合进行检查。",
        "此外实现 3 条仅由仓库消费者使用、Java Controller 中不存在的兼容路由，因此这 3 条不计入",
        "154 条 Java 覆盖率。三端 188 个调用点均能解析到 FastAPI 路由。",
        "",
        "矩阵状态必须按下列含义阅读：",
        "",
        "- `结构✓`：method/path 已注册且清单闭合；它不等于业务行为逐接口实测。",
        "- `请求面差分✓1`：本行已向隔离 Java/FastAPI 各发送一次缺少鉴权或安全非法输入，精确比较",
        "  HTTP status、body 与 Content-Type；最终为 **154/154 通过、0 失败、0 跳过**，且不发送成功写请求。",
        "- `认证业务面差分✓1`：本行已使用有效 DB Token、server-secret 或匿名身份，再向隔离",
        "  Java/FastAPI 各发送一次安全业务/校验请求，精确比较 HTTP status、body 与 Content-Type；",
        "  最终为 **154/154 通过、0 失败、0 跳过**，且不主动发送成功写请求。该状态不等于每条路由的",
        "  完整成功生命周期均已差分，完整副作用证据仍以 `差分✓N` 为准。",
        "- `领域✓(x，域级)`：该领域有 service/repository/协议自动测试，但不保证本行每条成功与错误路径",
        "  都被直接请求。`领域—` 表示除结构测试外没有可归属的域级直接测试证据。",
        "- `差分✓N`：本行除安全请求面外，还参与了成功、主要错误、协议或数据库副作用的深度对照；",
        "  括号说明覆盖面。深度结果为 **49/49 checks 通过、0 失败、0 跳过**，覆盖 **21/154** 条路由。",
        "  `差分间接✓` 表示 J125 作为下载链路的 URL 生成步骤被间接覆盖；`差分—` 表示没有深度对照，",
        "  不能把 154/154 请求面差分误读成 154 条全部成功路径与副作用都已逐接口对照。",
        "- 所有 `Result<T>` 均表示 `{code,msg,data}` envelope；原 Java 为 HTTP 200 的认证、权限、业务和",
        "  参数错误由全局兼容层维持 HTTP 200。二进制/OTA 裸响应在“响应类型”列单独标明。",
        "",
        "## 三端消费者闭合",
        "",
        "| 消费者 | 调用点 | 唯一结构路由 | 方法分布 |",
        "|---|---:|---:|---|",
    ]
    for consumer in ("manager-web", "manager-mobile", "xiaozhi-server"):
        item = consumer_manifest["consumers"][consumer]
        methods = "、".join(f"{method} {count}" for method, count in item["methods"].items())
        lines.append(f"| `{consumer}` | {item['callSites']} | {item['uniqueRoutes']} | {methods} |")
    lines.extend(
        [
            f"| **合计** | **{consumer_manifest['count']}** | **{consumer_manifest['uniqueRoutes']}** | — |",
            "",
            "### 3 条消费者孤儿兼容路由",
            "",
            "| Method/path | 来源 | FastAPI 语义 | 鉴权 | 状态 |",
            "|---|---|---|---|---|",
            (
                "| `GET /api/ping` | manager-mobile 环境设置探活 | "
                "`{code:0,msg:\"success\",data:\"pong\"}` | 匿名 | 实现✓；consumer resolve✓ |"
            ),
            (
                "| `PUT /user/configDevice/{device_id}` | manager-web 遗留设备配置调用 | "
                "按现有设备更新契约处理 body | DB Token | 实现✓；consumer resolve✓ |"
            ),
            (
                "| `GET /device/address-book/lookup` | xiaozhi-server 管理客户端 | "
                "`callerMac/nickname/answer` 地址簿查询/呼叫兼容别名 | server-secret | "
                "实现✓；consumer resolve✓；device 域测试✓ |"
            ),
            "",
            "`GET /admin/dict/data/type/FIRMWARE_TYPE` 是动态 Java 路由",
            "`GET /admin/dict/data/type/{dictType}` 的一个字面调用，不是第四条孤儿路由。",
            "",
            _inventory_section(routes).rstrip(),
            "",
            "## 154 条 Java→FastAPI 逐接口矩阵",
            "",
            "副作用缩写：`DB-R/W`=数据库读/写，`Redis-R/W/DEL`=缓存读/写/失效，`文件-R/W`=文件",
            "读取/写入；外部调用均在 service/integration 层。权限为空时表示只需对应鉴权身份。",
            "",
            (
                "| # | Method/path | Java Controller.handler | 请求面 | 响应类型 | 鉴权 / 权限 | "
                "DB/Redis/文件/外部副作用 | 实现与测试状态 |"
            ),
            "|---:|---|---|---|---|---|---|---|",
        ]
    )
    for index, route in enumerate(routes, start=1):
        declaration = _declaration(route)
        permission = _permission(route) or "—"
        auth = {
            "anonymous": "匿名",
            "database-token": "DB Token",
            "server-secret": "server-secret",
        }[route["auth"]]
        values = [
            f"J{index:03d}",
            f"`{route['method']} {route['path']}`",
            f"`{route['controller']}.{route['handler']}`",
            _request_surface(route, declaration),
            _response_type(route, declaration),
            f"{auth} / `{permission}`" if permission != "—" else f"{auth} / —",
            _side_effect(route),
            _verification(route),
        ]
        lines.append("| " + " | ".join(_escape(value) for value in values) + " |")

    lines.extend(
        [
            "",
            "## 已观测差异与未覆盖面",
            "",
            "- 154 条安全请求面差分最终全部一致。首轮曾发现 5 个空 Body 映射差异；修复 FastAPI 对",
            "  Spring `HttpMessageNotReadableException` 的 code-500 语义后，重新从零执行才得到 154/154。",
            "- 154 条认证业务面差分最终全部一致；该轮使用有效鉴权与安全业务/校验输入，在不主动成功",
            "  写入的前提下逐路由对照。证据是 `authenticated-route-results.json`，渲染器会在结果不是",
            "  154/154、存在失败或跳过时硬失败。",
            "- 2026-07-20 的隔离差分报告未在 49 个 checks 中观测到响应/所选 headers/数据库副作用",
            "  不一致；证据是 `main/manager-api-fastapi/compatibility/contract-results.json`，不是人工推断。",
            "- Hibernate Validator 的 `ConstraintViolation Set` 首条消息无稳定顺序；模型 provider 必填",
            "  用例比较“消息属于 Java 声明约束集合”与相同错误码，而不伪造一个固定顺序。",
            "- OTA 时间戳/token 是动态值，差分先比较归一化结构，再分别校验两端 HMAC/Base64 密码学",
            "  有效性；这属于有意的测试归一化，不是声称字节恒等。",
            "- 深度差分未直接命中的 133 条中，J125 是下载链路间接覆盖，另 132 条标为 `差分—`；",
            "  它们有请求面、认证业务面与所属领域测试，但尚无逐路由成功+主要错误+副作用深度对照，不能据此宣称",
            "  每一种业务状态均已逐接口行为等价。",
            "- FastAPI 额外提供上述 3 条消费者兼容路由与 live/ready 健康检查；它们没有 Java",
            "  Controller 基线，属于明确、可回退的加法差异。",
            "- Java 把定时任务放在 Spring 进程；FastAPI 使用独立 jobs 进程和 Redis 分布式锁。这是",
            "  部署拓扑差异，业务状态和幂等目标保持一致。",
            "- RAGFlow、阿里云短信、火山语音克隆、真实声纹、真实 LLM、真实 MQTT/MCP/WS 均未用",
            "  生产凭证联调；自动化只证明 mock 请求格式、超时/错误映射/重试中的已覆盖场景。",
            "",
            "## 可复现检查",
            "",
            "```bash",
            "cd main/manager-api-fastapi",
            ".venv/bin/python scripts/extract_java_routes.py --output compatibility/java-routes.json",
            ".venv/bin/python scripts/extract_consumer_routes.py > /tmp/consumer-routes.json",
            (
                ".venv/bin/pytest -q tests/test_java_route_manifest.py "
                "tests/test_consumer_route_manifest.py tests/test_compatibility_document.py"
            ),
            "```",
            "",
            "逐接口差分的启动、隔离库、mock 与执行命令见 `docs/manager-api-fastapi-test-report.md`；",
            "本文件只陈述已落盘的结果，不把缺少真实密钥的外部联调列为通过。",
        ]
    )
    rendered = "\n".join(lines) + "\n"
    if len(re.findall(r"^\| J\d{3} \|", rendered, flags=re.MULTILINE)) != 154:
        raise AssertionError("rendered route matrix is not closed")
    return rendered


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rendered = render()
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
