"""Authenticated eligibility and entitled archive delivery; GET never consumes elements."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx

from toad.extensions.dega_panel.auth_store import load_auth, read_dega_env
from toad.extensions.dega_panel.device_client import DEFAULT_API_URL


class StrategyAccessError(Exception):
    """Backend rejected a strategy request (401/403/404/network)."""


def _api_base() -> str:
    return (
        os.environ.get("DEGA_API_URL")
        or read_dega_env("DEGA_API_URL")
        or DEFAULT_API_URL
    ).rstrip("/")


def session_token() -> str | None:
    """Bearer token when the panel is signed in, else None."""
    state = load_auth()
    if not state.is_logged_in or state.session is None:
        return None
    return state.session.session_token or None


async def backend_eligibility(key: str) -> dict[str, Any] | None:
    """Ask the backend for this account's access decision.

    Returns the parsed JSON ``{key, eligible, unmet, ...}`` when a decision was
    obtained, or ``None`` when there is no session / the backend is unreachable.
    An ineligible verdict is still a decision (eligible=False), so callers must
    distinguish ``None`` (no decision) from ``{"eligible": False}`` (denied).
    """
    token = session_token()
    if not token:
        return None
    url = f"{_api_base()}/strategies/eligibility"
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            resp = await c.get(url, params={"key": key}, headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError:
        return None
    if resp.status_code == 200:
        return resp.json()
    return None


async def backend_download_archive(key: str, dest_tar: Path) -> None:
    """Stream the protected archive to ``dest_tar`` via the backend.

    Raises ``StrategyAccessError`` when the backend denies access or the request
    fails; the caller should surface the message and not fall back to a public
    URL when we are signed in (a denial is a real policy decision).
    """
    token = session_token()
    if not token:
        raise StrategyAccessError("not signed in — strategy delivery requires a session")
    url = f"{_api_base()}/strategies/archive"
    try:
        async with httpx.AsyncClient(timeout=120.0) as c, c.stream(
            "GET",
            url,
            params={"key": key},
            headers={"Authorization": f"Bearer {token}"},
        ) as resp:
                if resp.status_code in (401, 403):
                    await resp.aread()
                    body = resp.json()
                    hint = f" — {body.get('message', 'Access required')}"
                    raise StrategyAccessError(
                        f"backend refused {key} ({resp.status_code}){hint}"
                    )
                if resp.status_code == 404:
                    raise StrategyAccessError(f"strategy {key} is not available on the backend")
                resp.raise_for_status()
                with dest_tar.open("wb") as f:
                    async for chunk in resp.aiter_bytes():
                        f.write(chunk)
    except httpx.HTTPError as exc:
        raise StrategyAccessError(f"backend delivery failed: {exc}") from exc