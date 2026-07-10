"""
Keychain-backed encryption helper (PRD 8.1 — encrypted at rest).

A single Fernet key is stored in the macOS login Keychain via the `security`
CLI (no third-party Keychain dependency). The key is created on first use and
read back on subsequent runs. Callers get a Cipher that transparently encrypts
and decrypts strings; if the Keychain or `cryptography` is unavailable, the
Cipher degrades to a no-op so memory keeps working (plaintext) rather than
breaking — a warning is logged so the degradation is visible.
"""
from __future__ import annotations

import logging
import subprocess

log = logging.getLogger(__name__)

_SERVICE = "cortana-memory"
_ACCOUNT = "cortana"
_PREFIX = "enc:v1:"  # marks ciphertext so we can detect/skip legacy plaintext


def _keychain_get() -> str | None:
    r = subprocess.run(
        ["security", "find-generic-password", "-s", _SERVICE, "-a", _ACCOUNT, "-w"],
        capture_output=True, text=True,
    )
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


def _keychain_set(secret: str) -> bool:
    # -U updates if it already exists.
    r = subprocess.run(
        ["security", "add-generic-password", "-s", _SERVICE, "-a", _ACCOUNT,
         "-w", secret, "-U"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        log.warning("Keychain store failed: %s", r.stderr.strip())
        return False
    return True


def _get_or_create_key() -> bytes | None:
    """Return a urlsafe-base64 Fernet key from the Keychain, creating one if absent."""
    existing = _keychain_get()
    if existing:
        return existing.encode()
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        return None
    key = Fernet.generate_key()
    if not _keychain_set(key.decode()):
        return None
    log.info("Created new Cortana memory key in macOS Keychain.")
    return key


class Cipher:
    """Transparent string encrypt/decrypt. No-op if encryption is unavailable."""

    def __init__(self, enabled: bool = True):
        self._fernet = None
        if not enabled:
            log.info("Memory encryption disabled by config — storing plaintext.")
            return
        try:
            from cryptography.fernet import Fernet
            key = _get_or_create_key()
            if key is not None:
                self._fernet = Fernet(key)
                log.info("Memory encryption active (Keychain-backed).")
            else:
                log.warning("No encryption key available — storing plaintext.")
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("Encryption unavailable (%s) — storing plaintext.", exc)

    @property
    def active(self) -> bool:
        return self._fernet is not None

    def encrypt(self, plaintext: str) -> str:
        if self._fernet is None or plaintext is None:
            return plaintext
        token = self._fernet.encrypt(plaintext.encode()).decode()
        return _PREFIX + token

    def decrypt(self, value: str) -> str:
        if value is None or self._fernet is None or not value.startswith(_PREFIX):
            # Not encrypted (or no cipher) — return as-is (handles legacy plaintext).
            return value
        try:
            return self._fernet.decrypt(value[len(_PREFIX):].encode()).decode()
        except Exception:
            return value  # corrupt/foreign token — surface raw rather than crash
