"""The panel autogenerates ~/.canon/dega-chat.env on first run.

Verifies the seeded template carries the backend URL and the current registry
(defaults a fresh install points at the deployed backend/prod and Sepolia v3),
that it is idempotent (never overwrites an existing file), and that the resolver
reads keys back from it.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from toad.extensions.dega_panel import auth_store


@pytest.fixture
def canon_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(auth_store, "CANON_DIR", tmp_path)
    return tmp_path


def test_seeds_env_template_on_first_run(canon_dir: Path) -> None:
    auth_store._ensure_dir()
    env = canon_dir / "dega-chat.env"
    text = env.read_text(encoding="utf-8")
    assert "DEGA_API_URL=https://ai-agents-api.degaplatform.com" in text
    assert "DEGA_CHAT_REGISTRY=0xf3D30Cf5FEBCa40Ff1E6A7254BEE34f170fAb088" in text
    assert "DEGA_CHAT_PK=" in text
    # env resolution reads the seeded value
    assert auth_store.read_dega_env("DEGA_API_URL") == "https://ai-agents-api.degaplatform.com"


def test_does_not_overwrite_existing_env(canon_dir: Path) -> None:
    env = canon_dir / "dega-chat.env"
    env.write_text("DEGA_CHAT_REGISTRY=0xabc\n", encoding="utf-8")
    auth_store._ensure_dir()
    assert env.read_text(encoding="utf-8") == "DEGA_CHAT_REGISTRY=0xabc\n"


def test_read_dega_env_skips_comments_and_blanks(canon_dir: Path) -> None:
    env = canon_dir / "dega-chat.env"
    env.write_text(
        "# a comment\n\nDEGA_API_URL=https://prod.example\nDEGA_CHAT_BACKEND=chain\n",
        encoding="utf-8",
    )
    assert auth_store.read_dega_env("DEGA_API_URL") == "https://prod.example"
    assert auth_store.read_dega_env("DEGA_CHAT_BACKEND") == "chain"
    assert auth_store.read_dega_env("DEGA_CHAT_PK") is None


def test_read_dega_env_missing_file_returns_none(canon_dir: Path) -> None:
    assert auth_store.read_dega_env("DEGA_API_URL") is None