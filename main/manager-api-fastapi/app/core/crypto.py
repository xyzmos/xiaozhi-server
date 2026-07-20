from __future__ import annotations

import hashlib
import secrets
import uuid

import bcrypt
from gmssl import func, sm2  # type: ignore[import-untyped]


def generate_database_token(value: str | None = None) -> str:
    source = value if value is not None else str(uuid.uuid4())
    return hashlib.md5(source.encode("utf-8"), usedforsecurity=False).hexdigest()


def bcrypt_hash(password: str, rounds: int = 10) -> str:
    encoded = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=rounds))
    # The bundled Java BCryptPasswordEncoder only accepts $2a$ hashes.
    return encoded.decode("ascii").replace("$2b$", "$2a$", 1)


def bcrypt_matches(password: str, encoded: str | None) -> bool:
    if not encoded or not encoded.startswith(("$2a$", "$2$")):
        return False
    normalized = encoded.replace("$2$", "$2a$", 1)
    try:
        return bcrypt.checkpw(password.encode("utf-8"), normalized.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        return False


def sm2_generate_keypair() -> tuple[str, str]:
    private_key = func.random_hex(64)
    helper = sm2.CryptSM2(private_key=private_key, public_key="", mode=1)
    public_point = str(helper._kg(int(private_key, 16), sm2.default_ecc_table["g"]))  # noqa: SLF001
    public_key = "04" + public_point
    return public_key, private_key


def sm2_encrypt_c1c3c2(public_key: str, plaintext: str) -> str:
    helper = sm2.CryptSM2(private_key="", public_key=public_key, mode=1)
    encrypted = helper.encrypt(plaintext.encode("utf-8"))
    if encrypted is None:
        raise ValueError("SM2 KDF returned an all-zero key")
    # BouncyCastle's SM2Engine emits the uncompressed-point marker.
    return "04" + bytes(encrypted).hex()


def sm2_decrypt_c1c3c2(private_key: str, ciphertext: str) -> str:
    normalized = ciphertext.strip().lower()
    if normalized.startswith("04"):
        normalized = normalized[2:]
    if len(normalized) < 128 + 64 or len(normalized) % 2:
        raise ValueError("invalid SM2 C1C3C2 ciphertext")
    helper = sm2.CryptSM2(private_key=private_key, public_key="", mode=1)
    decrypted = helper.decrypt(bytes.fromhex(normalized))
    if decrypted is None:
        raise ValueError("SM2 decryption failed")
    return bytes(decrypted).decode("utf-8")


def random_hex(length: int) -> str:
    return secrets.token_hex((length + 1) // 2)[:length]
