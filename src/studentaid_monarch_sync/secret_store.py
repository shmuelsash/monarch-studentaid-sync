"""Encrypted-at-rest secrets for this sync job (SECURITY-BASELINE section 6).

The loan-servicer password, the Gmail app password, and the Monarch
password/token/MFA-seed are persistent third-party secrets. Instead of plaintext
``environment:`` / ``.env`` values that anything with host access can read, they
live encrypted with Fernet in the job's own private safe -- a key file
(``chmod 600``) plus an encrypted blob, under ``/secrets`` (a per-deploy folder
the homelab dashboard also manages so the values can be set/rotated from a UI).
Each deploy (Ed Financial, Nelnet) mounts its own folder, so one servicer's job
can't read the other's secrets.

``load_into_env()`` decrypts the stored secrets into ``os.environ`` before the
job reads its config. It is best-effort: a missing/unreadable safe leaves the
environment untouched, so the ``.env`` fallback (the one-time migration window)
still applies and the job never hard-fails on a transient safe problem. It also
self-seeds from the legacy env var on first run, so the plaintext ``.env`` value
can be removed afterward.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from cryptography.fernet import Fernet

# Persistent third-party secrets this job manages. Everything else (servicer
# username/provider/account, Monarch email, MFA method) is non-secret config.
MANAGED: tuple[str, ...] = (
    "SERVICER_PASSWORD",
    "GMAIL_IMAP_APP_PASSWORD",
    "MONARCH_PASSWORD",
    "MONARCH_TOKEN",
    "MONARCH_MFA_SECRET",
)


def _store_dir() -> Path:
    return Path(os.environ.get("SECRET_STORE_DIR", "/secrets"))


def _key_file() -> Path:
    return _store_dir() / "key"


def _blob_file() -> Path:
    return _store_dir() / "secrets.enc"


def _chmod_600(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass  # best effort -- some filesystems (NFSv4 ACLs) reject chmod


def _fernet() -> Fernet:
    store = _store_dir()
    store.mkdir(parents=True, exist_ok=True)
    key_file = _key_file()
    if key_file.exists():
        return Fernet(key_file.read_bytes())
    key = Fernet.generate_key()
    key_file.write_bytes(key)
    _chmod_600(key_file)
    return Fernet(key)


def _read_all() -> dict[str, str]:
    blob = _blob_file()
    if not blob.exists():
        return {}
    data = json.loads(_fernet().decrypt(blob.read_bytes()).decode())
    return {str(k): str(v) for k, v in data.items()}


def _write_all(data: dict[str, str]) -> None:
    blob = _blob_file()
    blob.write_bytes(_fernet().encrypt(json.dumps(data).encode()))
    _chmod_600(blob)


def set_secret(name: str, value: str) -> None:
    """Encrypt and persist one managed secret (used by the dashboard/UI)."""
    if name not in MANAGED:
        raise ValueError(f"{name} is not a managed secret ({', '.join(MANAGED)})")
    data = _read_all()
    data[name] = value
    _write_all(data)
    if value:
        os.environ[name] = value


def _seed_from_env(data: dict[str, str]) -> dict[str, str]:
    changed = False
    for name in MANAGED:
        if not data.get(name) and os.environ.get(name):
            data[name] = os.environ[name]
            changed = True
    if changed:
        _write_all(data)
    return data


def load_into_env() -> None:
    """Decrypt stored secrets into os.environ (stored wins); best-effort.

    Also seeds the safe from the legacy env var once, so the plaintext value can
    be removed from .env after the first run. Never raises.
    """
    try:
        data = _seed_from_env(_read_all())
        for name, value in data.items():
            if value:
                os.environ[name] = value
    except Exception:  # noqa: BLE001 -- best-effort; .env fallback covers failures
        return


def status() -> dict[str, bool]:
    """Which managed secrets are set (never returns the values themselves)."""
    try:
        data = _read_all()
    except Exception:  # noqa: BLE001
        data = {}
    return {name: bool(data.get(name) or os.environ.get(name)) for name in MANAGED}
