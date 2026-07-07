"""Tests for the encrypted-at-rest secret store (SECURITY-BASELINE section 6)."""

from __future__ import annotations

import os
import stat
import sys

import pytest

from studentaid_monarch_sync import secret_store

_TOKEN = "Servicer/P@ss+word=="
_KEYS = (
    "SERVICER_PASSWORD",
    "GMAIL_IMAP_APP_PASSWORD",
    "MONARCH_PASSWORD",
    "MONARCH_TOKEN",
    "MONARCH_MFA_SECRET",
)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_STORE_DIR", str(tmp_path))
    for k in _KEYS:
        monkeypatch.delenv(k, raising=False)
    yield


def test_seed_from_env_then_load_after_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("SERVICER_PASSWORD", _TOKEN)
    secret_store.load_into_env()  # migration: seeds the safe from env
    assert (tmp_path / "secrets.enc").exists()

    monkeypatch.delenv("SERVICER_PASSWORD", raising=False)  # .env stripped
    secret_store.load_into_env()
    assert os.environ.get("SERVICER_PASSWORD") == _TOKEN


def test_set_get_roundtrip_and_ciphertext(tmp_path, monkeypatch):
    secret_store.set_secret("MONARCH_TOKEN", _TOKEN)
    blob = (tmp_path / "secrets.enc").read_bytes()
    assert _TOKEN.encode() not in blob
    monkeypatch.delenv("MONARCH_TOKEN", raising=False)
    secret_store.load_into_env()
    assert os.environ.get("MONARCH_TOKEN") == _TOKEN


def test_set_secret_rejects_unmanaged():
    with pytest.raises(ValueError):
        secret_store.set_secret("SOME_OTHER", "x")


def test_load_is_best_effort(tmp_path):
    secret_store.load_into_env()  # nothing stored -> no raise
    assert "SERVICER_PASSWORD" not in os.environ
    (tmp_path / "secrets.enc").write_bytes(b"not-a-fernet-token")
    secret_store.load_into_env()  # corrupt -> no raise


def test_status_reports_booleans():
    assert secret_store.status()["MONARCH_PASSWORD"] is False
    secret_store.set_secret("MONARCH_PASSWORD", _TOKEN)
    assert secret_store.status()["MONARCH_PASSWORD"] is True


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX perms only")
def test_key_and_blob_chmod_600(tmp_path):
    secret_store.set_secret("SERVICER_PASSWORD", _TOKEN)
    for name in ("key", "secrets.enc"):
        mode = stat.S_IMODE((tmp_path / name).stat().st_mode)
        assert mode == 0o600, f"{name} mode {oct(mode)}"
