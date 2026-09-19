"""Curated selection leaves the original startup workflow in place."""
import json
from unittest.mock import AsyncMock

import pytest
from click.testing import CliRunner

from toad.acp.prompt import build
from toad.cli import main
from toad.extensions.dega_panel.access_grants import StrategyAccessError
from toad.extensions.dega_panel.runner import StrategyManifest
from toad.strategy_selection import available_strategies


@pytest.mark.asyncio
async def test_only_authorized_downloads_are_offered(tmp_path, monkeypatch):
    monkeypatch.setattr("toad.strategy_selection.load_installed", lambda: ["arbiter", "oracle-bot"])
    monkeypatch.setattr("toad.strategy_selection.ensure_access", AsyncMock(
        side_effect=[None, StrategyAccessError("expired")],
    ))
    monkeypatch.setattr("toad.strategy_selection.detect_manifest", lambda key: StrategyManifest(
        key=key, path=tmp_path / key, name="Arbiter",
    ))
    assert await available_strategies() == [
        {"key": "arbiter", "name": "Arbiter", "path": str(tmp_path / "arbiter")},
    ]


def test_selection_does_not_scaffold_or_generate_state(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("toad.strategy_selection.load_installed", lambda: [])
    result = CliRunner().invoke(main, ["strategies"])
    assert result.exit_code == 0
    assert json.loads(result.output) == []
    assert list(tmp_path.iterdir()) == []
    assert "start" not in main.commands


@pytest.mark.parametrize("prompt", ["Use the canon-start skill", "/canon-start --live"])
def test_only_selection_is_overridden(tmp_path, prompt):
    blocks = build(tmp_path, prompt)
    assert blocks[0]["text"] == prompt
    note = blocks[1]["text"]
    assert "original workflow" in note
    assert "wallet detection/creation" in note
    assert "live preflight/onboarding" in note
    assert "canon strategies" in note
    assert "Never enumerate Core" in note


def test_discussion_does_not_invoke_startup(tmp_path):
    assert len(build(tmp_path, "Explain the canon-start bug")) == 1
