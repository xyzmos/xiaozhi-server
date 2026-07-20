from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from app.core.crypto import sm2_decrypt_c1c3c2, sm2_encrypt_c1c3c2

TARGET_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = TARGET_ROOT.parents[1]
VECTOR_PATH = TARGET_ROOT / "tests" / "fixtures" / "sm2-c1c3c2-golden.json"
BCPROV = (
    REPOSITORY_ROOT
    / ".runtime"
    / "m2"
    / "org"
    / "bouncycastle"
    / "bcprov-jdk18on"
    / "1.78"
    / "bcprov-jdk18on-1.78.jar"
)
JAVA_HOME = REPOSITORY_ROOT / ".runtime" / "jdk" / "bin"


@pytest.fixture(scope="module")
def vector() -> dict[str, str]:
    return json.loads(VECTOR_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def java_classpath(tmp_path_factory: pytest.TempPathFactory) -> str:
    classes = tmp_path_factory.mktemp("sm2-java")
    command = [
        str(JAVA_HOME / "javac"),
        "-cp",
        str(BCPROV),
        "-d",
        str(classes),
        str(
            REPOSITORY_ROOT
            / "main"
            / "manager-api"
            / "src"
            / "main"
            / "java"
            / "xiaozhi"
            / "common"
            / "utils"
            / "SM2Utils.java"
        ),
        str(TARGET_ROOT / "tests" / "java" / "Sm2InteropCli.java"),
    ]
    subprocess.run(command, check=True, capture_output=True, text=True)  # noqa: S603
    return f"{classes}:{BCPROV}"


def java_sm2(classpath: str, operation: str, key: str, value: str) -> str:
    result = subprocess.run(  # noqa: S603
        [str(JAVA_HOME / "java"), "-cp", classpath, "Sm2InteropCli", operation, key, value],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def test_static_java_and_python_vectors_decrypt_in_python(vector: dict[str, str]) -> None:
    assert sm2_decrypt_c1c3c2(vector["privateKey"], vector["javaCiphertext"]) == vector["plaintext"]
    assert sm2_decrypt_c1c3c2(vector["privateKey"], vector["pythonCiphertext"]) == vector["plaintext"]


def test_static_java_and_python_vectors_decrypt_in_java(vector: dict[str, str], java_classpath: str) -> None:
    assert java_sm2(java_classpath, "decrypt", vector["privateKey"], vector["javaCiphertext"]) == vector["plaintext"]
    assert java_sm2(java_classpath, "decrypt", vector["privateKey"], vector["pythonCiphertext"]) == vector["plaintext"]


def test_fresh_ciphertexts_are_bidirectionally_compatible(vector: dict[str, str], java_classpath: str) -> None:
    java_ciphertext = java_sm2(java_classpath, "encrypt", vector["publicKey"], vector["plaintext"])
    assert java_ciphertext.startswith("04")
    assert sm2_decrypt_c1c3c2(vector["privateKey"], java_ciphertext) == vector["plaintext"]

    python_ciphertext = sm2_encrypt_c1c3c2(vector["publicKey"], vector["plaintext"])
    assert python_ciphertext.startswith("04")
    assert java_sm2(java_classpath, "decrypt", vector["privateKey"], python_ciphertext) == vector["plaintext"]
