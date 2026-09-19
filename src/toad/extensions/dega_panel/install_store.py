"""Tracks which strategy workflows the user has installed locally.

The installed set is just a JSON list in ~/.canon/installed.json. It is read on
mount so the catalogue can show an installed/uninstalled badge, and updated on
install/uninstall. No network and no Textual here, so it is unit-testable.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from toad.extensions.dega_panel.auth_store import CANON_DIR, _ensure_dir

INSTALLED_FILE = CANON_DIR / "installed.json"


def strategies_dir() -> Path:
    """Where cloned strategies live: ~/.canon/strategies/<key>."""
    _ensure_dir()
    d = CANON_DIR / "strategies"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_installed() -> list[str]:
    if not INSTALLED_FILE.exists():
        return []
    try:
        data = json.loads(INSTALLED_FILE.read_text(encoding="utf-8"))
        return [k for k in data if isinstance(k, str)] if isinstance(data, list) else []
    except (ValueError, OSError):
        return []


def save_installed(installed: list[str]) -> None:
    _ensure_dir()
    tmp = INSTALLED_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(sorted(set(installed)), indent=2), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(INSTALLED_FILE)


def is_installed(key: str) -> bool:
    return key in load_installed()


def mark_installed(key: str) -> None:
    installed = load_installed()
    if key not in installed:
        installed.append(key)
        save_installed(installed)


def mark_uninstalled(key: str) -> None:
    installed = load_installed()
    if key in installed:
        installed.remove(key)
        save_installed(installed)
