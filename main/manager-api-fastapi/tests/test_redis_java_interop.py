from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.core.redis import JavaRedisCodec

TARGET_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = TARGET_ROOT.parents[1]
JAVA_PROJECT = REPOSITORY_ROOT / "main" / "manager-api"
MAVEN = REPOSITORY_ROOT / ".runtime" / "maven" / "bin" / "mvn"
MAVEN_REPOSITORY = REPOSITORY_ROOT / ".runtime" / "m2"
JAVA = REPOSITORY_ROOT / ".runtime" / "jdk" / "bin"


@pytest.fixture(scope="module")
def java_redis_vectors(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    work = tmp_path_factory.mktemp("redis-java")
    classpath_file = work / "classpath.txt"
    subprocess.run(  # noqa: S603
        [
            str(MAVEN),
            "-o",
            "-q",
            f"-Dmaven.repo.local={MAVEN_REPOSITORY}",
            "-DskipTests",
            "compile",
            "dependency:build-classpath",
            f"-Dmdep.outputFile={classpath_file}",
        ],
        cwd=JAVA_PROJECT,
        check=True,
        capture_output=True,
        text=True,
    )
    classpath = f"{JAVA_PROJECT / 'target' / 'classes'}:{classpath_file.read_text(encoding='utf-8').strip()}"
    subprocess.run(  # noqa: S603
        [
            str(JAVA / "javac"),
            "-cp",
            classpath,
            "-d",
            str(work),
            str(TARGET_ROOT / "tests" / "java" / "RedisCodecVectors.java"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    result = subprocess.run(  # noqa: S603
        [str(JAVA / "java"), "-cp", f"{work}:{classpath}", "RedisCodecVectors"],
        check=True,
        capture_output=True,
        text=True,
    )
    vectors: dict[str, Any] = {}
    for line in result.stdout.splitlines():
        name, wire, _decoded_class = line.split("\t", 2)
        vectors[name] = json.loads(wire)
    return vectors


def _python_wire(value: Any, **kwargs: Any) -> Any:
    return json.loads(JavaRedisCodec.encode(value, **kwargs))


def test_spring_redis_serializer_core_wire_format_matches_python(java_redis_vectors: dict[str, Any]) -> None:
    assert java_redis_vectors["string"] == _python_wire("hello")
    assert java_redis_vectors["integer"] == _python_wire(7)
    assert java_redis_vectors["long"] == _python_wire(2_147_483_648)
    assert java_redis_vectors["boolean"] == _python_wire(True)
    nested = {"enabled": True}
    assert java_redis_vectors["map"] == _python_wire(
        {
            "text": "hello",
            "number": 2_147_483_648,
            "list": ["a", "b"],
            "nested": nested,
        }
    )
    assert java_redis_vectors["list"] == _python_wire(["a", 2_147_483_648, nested])
    epoch_in_shanghai = datetime.fromtimestamp(0, ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
    assert java_redis_vectors["date"] == _python_wire(epoch_in_shanghai)


def test_spring_redis_serializer_domain_pojo_wire_format_matches_python(java_redis_vectors: dict[str, Any]) -> None:
    assert java_redis_vectors["pojo"] == _python_wire(
        {
            "id": "voice-1",
            "languages": None,
            "name": "sample",
            "remark": None,
            "reference_audio": None,
            "reference_text": None,
            "sort": 2,
            "tts_model_id": None,
            "tts_voice": None,
            "voice_demo": None,
        },
        java_type="xiaozhi.modules.timbre.vo.TimbreDetailsVO",
        field_java_types={"sort": "java.lang.Long"},
    )
    assert java_redis_vectors["model-pojo"] == _python_wire(
        {
            "id": "model-1",
            "model_type": "LLM",
            "model_code": None,
            "model_name": None,
            "is_default": None,
            "is_enabled": None,
            "config_json": {"type": "openai", "api_key": "secret"},
            "doc_link": None,
            "remark": None,
            "sort": None,
            "updater": None,
            "update_date": None,
            "creator": None,
            "create_date": None,
        },
        java_type="xiaozhi.modules.model.entity.ModelConfigEntity",
        field_java_types={
            "configJson": "cn.hutool.json.JSONObject",
            "creator": "java.lang.Long",
            "updater": "java.lang.Long",
        },
    )
    assert java_redis_vectors["dict-list"] == _python_wire(
        [{"name": "China", "key": "+86"}],
        item_java_type="xiaozhi.modules.sys.vo.SysDictDataItem",
    )
