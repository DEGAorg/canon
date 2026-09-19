"""Tests for backend-authenticated strategy delivery (issue #2).

Covers the panel-side integration: the install fetcher path exercises the new
backend delivery branch without network, and strategy_access resolves no-session
and denied-eligibility behavior. Network is always stubbed.
"""

from __future__ import annotations

import asyncio
import io
import json
import tarfile
from pathlib import Path

import httpx
import pytest

from toad.extensions.dega_panel import (
    auth_store,
    install_store,
    installer,
    strategy_access,
)
from toad.extensions.dega_panel.auth_store import AuthState, Session


@pytest.fixture
def canon_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(auth_store, "CANON_DIR", tmp_path)
    monkeypatch.setattr(install_store, "CANON_DIR", tmp_path)
    monkeypatch.setattr(auth_store, "AUTH_FILE", tmp_path / "auth.json")
    monkeypatch.setattr(install_store, "INSTALLED_FILE", tmp_path / "installed.json")
    return tmp_path


def _make_tar_bytes(key: str) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        data = json.dumps({"name": key}).encode()
        info = tarfile.TarInfo(f"dega-{key}/package.json")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_install_via_backend_fetcher(canon_tmp: Path) -> None:
    """install_strategy with a fetcher downloads nothing from a public URL."""
    used = []

    async def fetcher(tar_path: Path) -> None:
        used.append(True)
        tar_path.write_bytes(_make_tar_bytes("test-key"))

    dest = asyncio.run(
        installer.install_strategy("test-key", "https://example.invalid/ignored", fetcher=fetcher)
    )
    assert used, "fetcher must be invoked (backend delivery)"
    assert (dest / "package.json").exists()
    assert install_store.is_installed("test-key")


def test_eligibility_no_session_is_none(canon_tmp: Path) -> None:
    """Without a session we get no decision (caller falls back, never blocks)."""
    assert auth_store.load_auth().is_logged_in is False
    assert asyncio.run(strategy_access.backend_eligibility("arbiter")) is None


def test_eligibility_with_session_returns_decision(canon_tmp: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    auth_store.save_auth(AuthState(session=Session(session_token="tok", user_id="u1", email="a@b.co")))

    class FakeClient:
        def __init__(self, timeout: float) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def get(self, *a, **k):
            return httpx.Response(200, json={"key": "arbiter", "eligible": False, "unmet": ["5 more"]})

    monkeypatch.setattr(strategy_access.httpx, "AsyncClient", FakeClient)
    decision = asyncio.run(strategy_access.backend_eligibility("arbiter"))
    assert decision is not None
    assert decision["eligible"] is False
    assert decision["unmet"] == ["5 more"]


def test_download_denied_raises(canon_tmp: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    auth_store.save_auth(AuthState(session=Session(session_token="tok", user_id="u1", email="a@b.co")))

    class FakeStream:
        def __init__(self, *a, **k):
            self._status = 403
            self._body = {"error": "Strategy locked", "unmet": ["5 more"]}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        @property
        def status_code(self) -> int:
            return self._status

        async def aread(self):
            return b""

        def json(self):
            return self._body

        async def raise_for_status(self):
            return None

        async def aiter_bytes(self):
            yield b""

    class FakeClient:
        def __init__(self, timeout: float):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        def stream(self, *a, **k):
            return FakeStream()

    monkeypatch.setattr(strategy_access.httpx, "AsyncClient", FakeClient)
    with pytest.raises(strategy_access.StrategyAccessError, match="refused"):
        asyncio.run(strategy_access.backend_download_archive("arbiter", Path("/tmp/x.tar.gz")))


def test_rule_unmet_counts_class_with_variant_suffix() -> None:
    """Parity with the backend: a rule named by class counts 'Class Default' too."""
    from toad.extensions.dega_panel.data import Rule

    arbiter = Rule(total=10, per_element={"Obsidian Earth": 5})
    assert arbiter.unmet({"Obsidian earth Default": 7, "Silver fire Default": 3}) == []
    assert arbiter.unmet({"Obsidian Earth Default": 5, "Golden Water Default": 5}) == []
    # distinct class must not be credited toward another class rule
    assert Rule(per_element={"Golden Water": 1}).unmet({"Obsidian earth Default": 5}) == [
        "1 x Golden Water"
    ]
    # total gate still enforced
    assert Rule(total=10).unmet({"Silver fire Default": 4}) == ["6 more"]