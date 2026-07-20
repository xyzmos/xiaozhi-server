from __future__ import annotations

import argparse
import asyncio
import json
import math
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from tests.compatibility.seed_contract_data import ADMIN_TOKEN, NORMAL_TOKEN, SERVER_SECRET


@dataclass(frozen=True)
class Scenario:
    name: str
    method: str
    path: str
    headers: dict[str, str]
    json_body: dict[str, Any] | None = None
    raw_ota: bool = False


@dataclass
class Measurement:
    service: str
    scenario: str
    requests: int
    concurrency: int
    warmup_requests: int
    errors: int
    elapsed_seconds: float
    throughput_requests_per_second: float
    latency_ms_min: float
    latency_ms_p50: float
    latency_ms_p95: float
    latency_ms_max: float


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


SCENARIOS = (
    Scenario("representative-read", "GET", "/user/info", _bearer(ADMIN_TOKEN)),
    Scenario(
        "representative-crud-update",
        "PUT",
        "/device/update/contract-device-1",
        _bearer(NORMAL_TOKEN),
        {"autoUpdate": 1, "alias": None},
    ),
    Scenario("runtime-configuration", "POST", "/config/server-base", _bearer(SERVER_SECRET)),
    Scenario(
        "ota-check-and-signing",
        "POST",
        "/ota/",
        {"Device-Id": "AA:BB:CC:DD:EE:01", "Client-Id": "contract-performance"},
        {"application": {"version": "1.2.3"}, "board": {"type": "esp32s3"}},
        True,
    ),
)


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * percentile
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


async def _request_once(client: httpx.AsyncClient, base: str, scenario: Scenario) -> tuple[float, bool]:
    started = time.perf_counter()
    try:
        response = await client.request(
            scenario.method,
            base + scenario.path,
            headers=scenario.headers,
            json=scenario.json_body,
        )
        valid = response.status_code == 200
        if valid:
            payload = response.json()
            valid = (
                isinstance(payload, dict)
                and ("server_time" in payload if scenario.raw_ota else payload.get("code") == 0)
            )
    except (httpx.HTTPError, json.JSONDecodeError):
        valid = False
    return (time.perf_counter() - started) * 1000, valid


async def measure(
    service: str,
    base: str,
    scenario: Scenario,
    *,
    requests: int,
    concurrency: int,
    warmup: int,
) -> Measurement:
    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    timeout = httpx.Timeout(30.0)
    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
        for _ in range(warmup):
            _, valid = await _request_once(client, base, scenario)
            if not valid:
                raise RuntimeError(f"warmup failed for {service}/{scenario.name}")
        semaphore = asyncio.Semaphore(concurrency)

        async def bounded_request() -> tuple[float, bool]:
            async with semaphore:
                return await _request_once(client, base, scenario)

        started = time.perf_counter()
        values = await asyncio.gather(*(bounded_request() for _ in range(requests)))
        elapsed = time.perf_counter() - started
    latencies = [latency for latency, _ in values]
    errors = sum(not valid for _, valid in values)
    return Measurement(
        service=service,
        scenario=scenario.name,
        requests=requests,
        concurrency=concurrency,
        warmup_requests=warmup,
        errors=errors,
        elapsed_seconds=round(elapsed, 6),
        throughput_requests_per_second=round(requests / elapsed, 3),
        latency_ms_min=round(min(latencies), 3),
        latency_ms_p50=round(_percentile(latencies, 0.50), 3),
        latency_ms_p95=round(_percentile(latencies, 0.95), 3),
        latency_ms_max=round(max(latencies), 3),
    )


async def run(args: argparse.Namespace) -> dict[str, Any]:
    services = {
        "java": args.java_base.rstrip("/"),
        "fastapi": args.fastapi_base.rstrip("/"),
    }
    results: list[Measurement] = []
    for scenario in SCENARIOS:
        for service, base in services.items():
            results.append(
                await measure(
                    service,
                    base,
                    scenario,
                    requests=args.requests,
                    concurrency=args.concurrency,
                    warmup=args.warmup,
                )
            )
    comparisons: list[dict[str, Any]] = []
    for scenario in SCENARIOS:
        java = next(value for value in results if value.service == "java" and value.scenario == scenario.name)
        fastapi = next(value for value in results if value.service == "fastapi" and value.scenario == scenario.name)
        comparisons.append(
            {
                "scenario": scenario.name,
                "p50_ratio_fastapi_over_java": round(fastapi.latency_ms_p50 / java.latency_ms_p50, 3),
                "p95_ratio_fastapi_over_java": round(fastapi.latency_ms_p95 / java.latency_ms_p95, 3),
                "throughput_ratio_fastapi_over_java": round(
                    fastapi.throughput_requests_per_second / java.throughput_requests_per_second,
                    3,
                ),
            }
        )
    return {
        "schema_version": 1,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "parameters": {
            "requests_per_service_per_scenario": args.requests,
            "concurrency": args.concurrency,
            "sequential_warmup_requests": args.warmup,
            "scenario_order": [scenario.name for scenario in SCENARIOS],
            "service_order": ["java", "fastapi"],
        },
        "results": [asdict(result) for result in results],
        "comparisons": comparisons,
        "summary": {
            "measurements": len(results),
            "requests_measured": sum(result.requests for result in results),
            "errors": sum(result.errors for result in results),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--java-base", default="http://127.0.0.1:18082/xiaozhi")
    parser.add_argument("--fastapi-base", default="http://127.0.0.1:18083/xiaozhi")
    parser.add_argument("--requests", type=int, default=60)
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--output", type=Path, default=Path("compatibility/performance-results.json"))
    args = parser.parse_args()
    if args.requests <= 0 or args.concurrency <= 0 or args.warmup < 0:
        parser.error("requests/concurrency must be positive and warmup must be non-negative")
    report = asyncio.run(run(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))
    if report["summary"]["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
