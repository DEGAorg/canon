"""Read-only discovery of downloaded curated strategies for the existing workflow."""
from __future__ import annotations

import asyncio
import json

import click

from toad.extensions.dega_panel.access_grants import StrategyAccessError, ensure_access
from toad.extensions.dega_panel.data import BUILDS_BY_KEY
from toad.extensions.dega_panel.install_store import load_installed
from toad.extensions.dega_panel.runner import RunError, detect_manifest


async def available_strategies() -> list[dict[str, str]]:
    """List authorized downloads without starting, scaffolding, or activating anything."""
    choices = []
    for key in load_installed():
        if key not in BUILDS_BY_KEY:
            click.echo(f"{key}: not in the current template catalogue; local files retained", err=True)
            continue
        try:
            await ensure_access(key)
            manifest = detect_manifest(key)
        except (StrategyAccessError, RunError) as exc:
            click.echo(f"{key}: {exc}", err=True)
            continue
        choices.append({"key": key, "name": manifest.name or key, "path": str(manifest.path)})
    return choices


@click.command("strategies")
def strategies() -> None:
    """List activated, downloaded curated strategies for canon-start selection."""
    try:
        click.echo(json.dumps(asyncio.run(available_strategies())))
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
