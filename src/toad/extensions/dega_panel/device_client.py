"""HTTP client for the DEGA device-flow (RFC 8628) auth and elements fetch.

Only the login and the elements snapshot touch the network; everything else in
the panel is offline. The base URL is configurable via the DEGA_API_URL env var
so local Encore dev (http://127.0.0.1:4000) and the deployed backend both work.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx

from toad.extensions.dega_panel.auth_store import read_dega_env

DEFAULT_API_URL = "http://127.0.0.1:4000"


class DeviceFlowError(Exception):
    """Raised for a non-transient, non-pending device-flow failure."""


class DeviceFlowPending(Exception):
    """Internal: signal that the token endpoint is still waiting for approval."""


class DeviceClient:
    """Thin async wrapper over the DEGA device-flow endpoints."""

    def __init__(self, base_url: str | None = None, timeout: float = 15.0) -> None:
        self.base_url = (
            base_url
            or os.environ.get("DEGA_API_URL")
            or read_dega_env("DEGA_API_URL")
            or DEFAULT_API_URL
        ).rstrip("/")
        self._timeout = timeout

    async def request_code(self) -> dict[str, Any]:
        """POST /device/code → {device_code, user_code, verification_uri, ...}."""
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            resp = await c.post(f"{self.base_url}/device/code")
            resp.raise_for_status()
            return resp.json()

    async def poll_token(
        self,
        device_code: str,
        *,
        expires_in: int = 600,
        interval: int = 5,
        on_pending: callable | None = None,
    ) -> dict[str, Any]:
        """Poll /device/token until the code is approved or it expires.

        Calls ``on_pending()`` before each retry so the UI can show progress.
        Returns the approved response with ``session_token`` and ``user``.
        """
        deadline = asyncio.get_event_loop().time() + expires_in
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            while True:
                resp = await c.post(
                    f"{self.base_url}/device/token",
                    json={"device_code": device_code},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("status") == "approved":
                        return data
                    # 200 but status != approved: still pending.
                elif resp.status_code == 404:
                    raise DeviceFlowError("device code is invalid or has expired")
                elif resp.status_code >= 500:
                    raise DeviceFlowError(
                        f"backend error ({resp.status_code}) while polling"
                    )
                else:
                    # Any other 4xx (400/401/403) is a real auth/protocol error,
                    # not "still pending" — surface it instead of polling to death.
                    raise DeviceFlowError(
                        f"backend rejected the poll ({resp.status_code})"
                    )
                if asyncio.get_event_loop().time() >= deadline:
                    raise DeviceFlowError(
                        "approval timed out — open the verification link, sign "
                        "in to your DEGA account, and approve the device code "
                        "before it expires"
                    )
                if on_pending:
                    on_pending()
                await asyncio.sleep(interval)

    async def fetch_elements(self, email: str) -> dict[str, Any]:
        """GET /elements-aggregation/v2/by-email — public, keyed by email."""
        params = {"email": email}
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            resp = await c.get(
                f"{self.base_url}/elements-aggregation/v2/by-email", params=params
            )
            resp.raise_for_status()
            return resp.json()
