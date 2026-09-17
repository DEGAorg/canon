"""Account-scoped local access windows; remote reads never renew or spend elements."""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from uuid import uuid4

import httpx

from toad.extensions.dega_panel.auth_store import CANON_DIR, load_auth
from toad.extensions.dega_panel.strategy_access import StrategyAccessError, _api_base

ACCESS_FILE = CANON_DIR / "strategy-access.json"


@dataclass(frozen=True)
class Grant:
    id: str
    scope: str
    strategyKey: str | None
    activatedAt: str
    expiresAt: str

    @classmethod
    def parse(cls, raw: dict) -> Grant:
        grant = cls(**raw)
        if grant.scope not in ("strategy", "all_strategies"):
            raise ValueError("Invalid scope")
        if (grant.scope == "strategy") != isinstance(grant.strategyKey, str):
            raise ValueError("Invalid strategy scope")
        if _epoch(grant.expiresAt) <= _epoch(grant.activatedAt):
            raise ValueError("Invalid access window")
        return grant


def _epoch(value: str) -> float:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Access time must include timezone")
    return parsed.timestamp()


def _identity() -> tuple[str, str]:
    session = load_auth().session
    if session is None or not session.session_token:
        raise StrategyAccessError("Sign in before activating or starting a strategy")
    return f"{_api_base()}|{session.user_id}", session.session_token


def _load() -> dict:
    try:
        data = json.loads(ACCESS_FILE.read_text())
        if not isinstance(data, dict):
            return {}
        return {account: state for account, state in data.items() if isinstance(state, dict)
                and isinstance(state.get("grants", {}), dict)
                and isinstance(state.get("requests", {}), dict)}
    except (OSError, ValueError):
        return {}


def _save(data: dict) -> None:
    ACCESS_FILE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = ACCESS_FILE.with_name(f".{ACCESS_FILE.name}.{uuid4().hex}.tmp")
    try:
        with open(temporary, "x", opener=lambda p, flags: os.open(p, flags, 0o600)) as output:
            json.dump(data, output)
        temporary.replace(ACCESS_FILE)
    finally:
        temporary.unlink(missing_ok=True)


def cached_grant(key: str) -> Grant | None:
    account, _ = _identity()
    state = _load().get(account, {})
    if not isinstance(state, dict):
        return None
    records = state.get("grants", {})
    if not isinstance(records, dict):
        return None
    for record in records.values():
        try:
            grant = Grant.parse(record["grant"])
            wall_elapsed = time.time() - record["savedAt"]
            if wall_elapsed < 0:
                continue
            elapsed = wall_elapsed
            # monotonic clocks remain useful within the same boot, including sleep on macOS.
            monotonic_elapsed = time.monotonic() - record["monotonicAt"]
            if monotonic_elapsed >= 0:
                elapsed = max(elapsed, monotonic_elapsed)
            now = _epoch(record["serverTime"]) + elapsed
            if (_epoch(grant.activatedAt) <= now < _epoch(grant.expiresAt)
                    and (grant.scope == "all_strategies" or grant.strategyKey == key)):
                return grant
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    return None


async def _request(method: str, path: str, **kwargs) -> dict:
    _, token = _identity()
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.request(method, f"{_api_base()}{path}",
                headers={"Authorization": f"Bearer {token}"}, **kwargs)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("Invalid access response")
            return data
    except (httpx.HTTPError, ValueError) as exc:
        raise StrategyAccessError("Could not verify strategy access; retry without reactivating") from exc


def _store_response(account: str, response: dict) -> Grant | None:
    raw = response.get("grant")
    if raw is None:
        return None
    try:
        grant = Grant.parse(raw)
        _epoch(response["serverTime"])
    except (TypeError, ValueError, KeyError) as exc:
        raise StrategyAccessError("Invalid access response; retry synchronization") from exc
    data = _load()
    state = data.setdefault(account, {})
    state.setdefault("grants", {})[grant.id] = {
        "grant": asdict(grant), "serverTime": response["serverTime"],
        "savedAt": time.time(), "monotonicAt": time.monotonic(),
    }
    _save(data)
    return grant


async def ensure_access(key: str) -> Grant:
    """Check local access first; recover remotely only when no valid window remains."""
    account, _ = _identity()
    grant = cached_grant(key)
    if grant is not None:
        return grant
    response = await _request("GET", "/strategies/access", params={"key": key})
    if _identity()[0] != account:
        raise StrategyAccessError("Account changed; retry")
    _store_response(account, response)
    grant = cached_grant(key)
    if grant is None:
        raise StrategyAccessError("Access expired or not activated. Activate access before starting.")
    return grant


async def activate_access(key: str, *, purchase_id: str | None = None) -> Grant:
    """Explicit purchase, retaining its idempotency key across uncertain network failures."""
    account, _ = _identity()
    data = _load()
    state = data.setdefault(account, {})
    request = state.setdefault("requests", {}).setdefault(key, uuid4().hex)
    _save(data)
    payload = {"strategyKey": key, "idempotencyKey": request}
    if purchase_id is not None:
        payload["purchaseId"] = purchase_id
    response = await _request("POST", "/strategies/activate", json=payload)
    if _identity()[0] != account:
        raise StrategyAccessError("Account changed; retry")
    grant = _store_response(account, response)
    if grant is None:
        raise StrategyAccessError("Activation returned no access window")
    data = _load()
    data[account]["requests"].pop(key, None)
    _save(data)
    if cached_grant(key) is None:
        raise StrategyAccessError("Previous activation has expired. Activate again explicitly.")
    return grant
