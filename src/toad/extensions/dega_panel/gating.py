"""Element-gating thresholds, configurable at runtime.

The access rules for each strategy (how many Silver Fire / Golden Water /
Obsidian Earth unlock it) were previously hardcoded as `Build.rule` in
`data.py`. That makes changing thresholds a code edit.

This module treats them as configuration, matching the backend's JSON
feature-flag model: an optional JSON file (path from `DEGA_GATING_FILE`,
default ~/.canon/gating.json) can override any build's rule and the
per-node chat cap. When no file (or no key) is present we fall back to the
build's own `Rule`. Core originals have no default rule: None means unconfigured,
not open access. Eligibility and purchases are always decided by the backend.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from toad.extensions.dega_panel.auth_store import CANON_DIR
from toad.extensions.dega_panel.data import BUILDS_BY_KEY, Rule

DEFAULT_GATING_FILE = CANON_DIR / "gating.json"
# Default chat cap if config doesn't say otherwise (client asked 10).
DEFAULT_MAX_USERS_PER_NODE = 10
# Default one-time fee to open a chat node, in $DEGA tokens (8 decimals).
# Fee == 0 means free tier. Configurable: {"chat_fee_weega": N}.
DEFAULT_CHAT_FEE_WEEGA = 0


def _load() -> dict:
    """Read the gating config, tolerating a missing/invalid file."""
    raw = os.environ.get("DEGA_GATING_FILE") or str(DEFAULT_GATING_FILE)
    if not Path(raw).exists():
        return {}
    try:
        data = json.loads(Path(raw).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (ValueError, OSError):
        return {}


def _rule_from_config(cfg: dict, key: str) -> Rule | None:
    """Build a Rule from the config's ``rules`` map, or None."""
    rules = cfg.get("rules", {}) or {}
    entry = rules.get(key) or rules.get(key.split("(")[0].strip())  # allow bare name
    if not isinstance(entry, dict):
        return None
    total = int(entry.get("total", 0) or 0)
    per = entry.get("per_element") or {}
    return Rule(total=total, per_element={k: int(v) for k, v in per.items() if int(v) > 0})


def rule_for(key: str) -> Rule | None:
    """Return display thresholds when configured; None never implies free access."""
    cfg = _load()
    override = _rule_from_config(cfg, key)
    if override is not None:
        return override
    build = BUILDS_BY_KEY.get(key)
    return build.rule if build else None


def max_users_per_node() -> int:
    """Configurable per-node chat cap (default 10 per client)."""
    cfg = _load()
    try:
        return int(cfg.get("max_users_per_node", DEFAULT_MAX_USERS_PER_NODE))
    except (TypeError, ValueError):
        return DEFAULT_MAX_USERS_PER_NODE


def chat_fee_weega() -> int:
    """Parametrizable $DEGA fee to open a chat node (0 = free tier).

    Read from the same gating JSON so it can be tuned without redeploying:
    {"chat_fee_weega": <amount in weega, 1 DEGA = 1e8 weega>}.
    """
    cfg = _load()
    try:
        return int(cfg.get("chat_fee_weega", DEFAULT_CHAT_FEE_WEEGA))
    except (TypeError, ValueError):
        return DEFAULT_CHAT_FEE_WEEGA


def save_defaults() -> None:
    """Write the current build rules as an editable JSON config file.

    Only run on demand, so a user can see and tweak the thresholds. Idempotent:
    does not overwrite an existing file (the user's own edits are respected).
    """
    from toad.extensions.dega_panel.data import BUILDS

    out = DEFAULT_GATING_FILE
    if out.exists():
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    rules = {
        b.key: {
            "total": b.rule.total,
            "per_element": dict(b.rule.per_element),
        }
        for b in BUILDS if b.rule is not None
    }
    payload = {"max_users_per_node": DEFAULT_MAX_USERS_PER_NODE, "rules": rules}
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")