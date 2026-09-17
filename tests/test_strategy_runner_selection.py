from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from toad.extensions.dega_panel import runner as runner_mod
from toad.extensions.dega_panel.runner import StrategyManifest, detect_manifest, run_strategy


@pytest.mark.asyncio
async def test_run_strategy_prefers_dry_run_then_live_then_build(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    manifest = StrategyManifest(
        key="demo",
        path=tmp_path,
        scripts={
            "build": "echo build",
            "dry-run": "echo dry",
            "live": "echo live",
            "start": "echo start",
        },
        runnable=True,
        dry_run_command="dry-run",
        live_command="live",
        build_command="build",
    )

    monkeypatch.setattr(runner_mod, "detect_manifest", lambda _key: manifest)
    monkeypatch.setattr(runner_mod, "ensure_deps", AsyncMock())

    seen: list[list[str]] = []

    async def fake_run_generic(cmd: list[str], cwd: Path, on_line, *, timeout=None) -> int:
        seen.append(cmd)
        return 0

    monkeypatch.setattr(runner_mod, "_run_generic", fake_run_generic)

    await run_strategy("demo", confirmed=True)
    await run_strategy("demo", confirmed=True, live=True, live_confirm=True)
    await run_strategy("demo", confirmed=True, script="build")

    assert seen == [
        ["npm", "run", "build"],            # compiled before the dry run
        ["npm", "run", "dry-run"],
        ["npm", "run", "build"],            # compiled before the live run
        ["npm", "run", "live"],
        ["npm", "run", "build"],            # build asked for explicitly: no double build
    ]


def test_detect_manifest_requires_an_execution_script(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """F4: build/compile and checkers are never the strategy entrypoint."""
    import json

    strategies = tmp_path / "strategies"
    strategies.mkdir()

    def make(key: str, scripts: dict[str, str]) -> None:
        d = strategies / key
        d.mkdir()
        (d / "package.json").write_text(
            json.dumps({"name": key, "scripts": scripts}), encoding="utf-8"
        )

    make("checkers", {"typecheck": "tsc --noEmit", "lint": "eslint .", "check": "npm run lint"})
    make("builder", {"build": "tsc"})
    make("dashboard", {"typecheck": "tsc", "server": "node server.js"})
    make("starter", {"dev": "tsx watch src/x.ts", "start": "node dist/x.js", "build": "tsc"})

    monkeypatch.setattr(runner_mod, "_safe_dest", lambda key: strategies / key)

    checkers = detect_manifest("checkers")
    assert checkers.runnable is False
    assert "no runnable script" in checkers.run_hint

    builder = detect_manifest("builder")
    assert builder.runnable is False, "a build-only package is not runnable"
    assert builder.build_command == "build"

    dashboard = detect_manifest("dashboard")
    assert dashboard.runnable is True
    assert dashboard.run_command == "server"

    starter = detect_manifest("starter")
    assert starter.runnable is True
    assert starter.run_hint == "npm run start", "start wins over dev"
    assert starter.build_command == "build"
    assert starter.run_command == "start"


@pytest.mark.asyncio
async def test_run_strategy_builds_before_running(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A package with a build step must be compiled before it is started."""
    manifest = StrategyManifest(
        key="demo",
        path=tmp_path,
        scripts={"build": "tsc", "start": "node dist/index.js"},
        runnable=True,
        build_command="build",
        dry_run_command="start",
        live_command="start",
    )

    monkeypatch.setattr(runner_mod, "detect_manifest", lambda _key: manifest)
    monkeypatch.setattr(runner_mod, "ensure_deps", AsyncMock())

    seen: list[list[str]] = []

    async def fake_run_generic(cmd: list[str], cwd: Path, on_line, *, timeout=None) -> int:
        seen.append(cmd)
        return 0

    monkeypatch.setattr(runner_mod, "_run_generic", fake_run_generic)

    await run_strategy("demo", confirmed=True)

    assert seen == [["npm", "run", "build"], ["npm", "run", "start"]]


@pytest.mark.asyncio
async def test_run_strategy_fails_when_build_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    manifest = StrategyManifest(
        key="demo",
        path=tmp_path,
        scripts={"build": "tsc", "start": "node dist/index.js"},
        runnable=True,
        build_command="build",
        dry_run_command="start",
        live_command="start",
    )
    monkeypatch.setattr(runner_mod, "detect_manifest", lambda _key: manifest)
    monkeypatch.setattr(runner_mod, "ensure_deps", AsyncMock())

    seen: list[list[str]] = []

    async def fake_run_generic(cmd: list[str], cwd: Path, on_line, *, timeout=None) -> int:
        seen.append(cmd)
        return 1  # build fails

    monkeypatch.setattr(runner_mod, "_run_generic", fake_run_generic)

    with pytest.raises(runner_mod.RunError, match="build failed"):
        await run_strategy("demo", confirmed=True)

    assert seen == [["npm", "run", "build"]], "must not run the strategy after a failed build"


@pytest.mark.asyncio
async def test_run_strategy_tolerates_build_failure_when_sources_run_directly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """tsx/ts-node runners work without dist/, so a failed build must not block them."""
    manifest = StrategyManifest(
        key="demo",
        path=tmp_path,
        scripts={"build": "tsc", "start": "tsx src/index.ts"},
        runnable=True,
        build_command="build",
        dry_run_command="start",
        live_command="start",
    )
    monkeypatch.setattr(runner_mod, "detect_manifest", lambda _key: manifest)
    monkeypatch.setattr(runner_mod, "ensure_deps", AsyncMock())

    seen: list[list[str]] = []

    async def fake_run_generic(cmd: list[str], cwd: Path, on_line, *, timeout=None) -> int:
        seen.append(cmd)
        return 1 if cmd[-1] == "build" else 0

    monkeypatch.setattr(runner_mod, "_run_generic", fake_run_generic)

    await run_strategy("demo", confirmed=True)

    assert seen == [["npm", "run", "build"], ["npm", "run", "start"]]


@pytest.mark.parametrize("script", ["live", "start:live"])
def test_dedicated_live_script_preserves_its_declared_arguments(script):
    manifest = StrategyManifest(key="oracle", path=Path("."))
    assert runner_mod._build_command(manifest, script, True) == ["npm", "run", script]


def test_generic_live_script_still_receives_opt_in():
    manifest = StrategyManifest(key="generic", path=Path("."))
    assert runner_mod._build_command(manifest, "start", True) == [
        "npm", "run", "start", "--", "--live"
    ]


@pytest.fixture(autouse=True)
def authorized_access(tmp_path, monkeypatch):
    """Supply backend authorization at the network boundary for runner selection tests."""
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace
    from toad.extensions.dega_panel import access_grants as access

    monkeypatch.setattr(access, "ACCESS_FILE", tmp_path / "access.json")
    monkeypatch.setattr(access, "load_auth", lambda: SimpleNamespace(
        session=SimpleNamespace(user_id="test", session_token="fixture")))
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(access, "_request", AsyncMock(return_value={
        "grant": {"id": "test-grant", "scope": "all_strategies", "strategyKey": None,
                  "activatedAt": now.isoformat(),
                  "expiresAt": (now + timedelta(days=1)).isoformat()},
        "serverTime": now.isoformat(),
    }))
