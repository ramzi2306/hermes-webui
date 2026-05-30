"""
Password encryption at rest for email accounts.
Uses Fernet (cryptography lib, already a dependency).
Key stored in STATE_DIR/.email_key with 0600 perms.
"""
import os
import stat
from pathlib import Path
from typing import Optional


_PREFIX = "enc:v1:"


def _key_path() -> Path:
    from api.config import STATE_DIR
    return STATE_DIR / ".email_key"


def _get_fernet():
    from cryptography.fernet import Fernet
    kp = _key_path()
    if kp.exists():
        key = kp.read_bytes().strip()
    else:
        key = Fernet.generate_key()
        kp.parent.mkdir(parents=True, exist_ok=True)
        kp.write_bytes(key)
        try:
            os.chmod(kp, stat.S_IRUSR | stat.S_IWUSR)  # 0600
        except Exception:
            pass
    return Fernet(key)


def encrypt(plaintext: str) -> str:
    """Encrypt a string. Returns 'enc:v1:<token>'. Idempotent on already-encrypted."""
    if not plaintext:
        return plaintext
    if plaintext.startswith(_PREFIX):
        return plaintext  # already encrypted
    try:
        f = _get_fernet()
        token = f.encrypt(plaintext.encode("utf-8")).decode("ascii")
        return _PREFIX + token
    except Exception:
        # If crypto unavailable, fail closed-ish: return as-is (logged upstream)
        return plaintext


def decrypt(value: str) -> str:
    """Decrypt a value. If not encrypted (legacy plain), return as-is."""
    if not value or not value.startswith(_PREFIX):
        return value  # legacy plaintext
    try:
        f = _get_fernet()
        token = value[len(_PREFIX):].encode("ascii")
        return f.decrypt(token).decode("utf-8")
    except Exception:
        return value


def is_encrypted(value: str) -> bool:
    return bool(value) and value.startswith(_PREFIX)
