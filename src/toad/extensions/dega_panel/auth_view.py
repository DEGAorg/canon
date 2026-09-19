"""Login status bar and the device-flow driver for the DEGA panel.

The AuthBar is a thin view; the actual device-flow state machine lives in
``run_device_login`` which drives a ``DeviceClient`` against the DEGA backend and
persists the result with ``auth_store``. Kept importable without a live backend
so the headless verify harness can exercise it with a fake client.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button, Link, Static

from toad.extensions.dega_panel.auth_store import AuthState, Session, save_auth
from toad.extensions.dega_panel.device_client import DeviceClient


@dataclass
class FlowStatus:
    """What the auth bar shows right now."""

    phase: str = "idle"  # idle | connecting | waiting | connected | error
    user_code: str = ""
    verification_uri: str = ""
    email: str = ""
    error: str = ""


class AuthBar(Horizontal):
    """Login status line at the top of the panel body.

    Displays either a disconnected prompt, the live device-flow steps, or the
    connected identity. The pane drives it via :meth:`set_status`. When
    connected, a focusable "Sign out" button is shown next to the email (clickable /
    'o') so the user can drop the session (clears ~/.canon/auth.json).
    """

    DEFAULT_CSS = """
    AuthBar { height: auto; padding: 0 1; border-bottom: solid $panel-lighten-2; }
    AuthBar #auth-details { width: 1fr; height: auto; }
    AuthBar #auth-status-text { height: auto; }
    AuthBar #auth-verification-link { width: 1fr; }
    AuthBar #btn-login {
      dock: right; width: auto; min-width: 9; height: 1;
      border: none; padding: 0 1;
    }
    AuthBar #btn-logout {
      dock: right; width: auto; height: 1; padding: 0 2;
      background: $warning 20%; color: $warning; border: none; min-width: 10;
      content-align: center middle;
    }
    AuthBar #btn-logout:hover { background: $warning 35%; color: $text; }
    AuthBar Button:focus { text-style: reverse; }
    """

    class LoginRequested(Message):
        """The user pressed the sign-in button."""

    def compose(self) -> ComposeResult:
        with Vertical(id="auth-details"):
            yield Static("", id="auth-status-text")
            yield Link("", url="", id="auth-verification-link")
        yield Button("Sign in", id="btn-login", variant="primary")
        yield Button("Sign out", id="btn-logout", variant="warning")

    def on_mount(self) -> None:
        self.set_status(FlowStatus())

    def set_status(self, status: FlowStatus) -> None:
        self._status = status
        self.query_one("#auth-status-text", Static).update(self._render_text())
        b = self.query_one("#btn-logout", Button)
        b.display = status.phase == "connected"
        self.query_one("#btn-login", Button).display = status.phase in {"idle", "error"}
        link = self.query_one("#auth-verification-link", Link)
        link.display = status.phase == "waiting" and bool(status.verification_uri)
        link.url = status.verification_uri if link.display else ""
        link.text = link.url

    @on(Button.Pressed, "#btn-login")
    def request_login(self, event: Button.Pressed) -> None:
        """Start sign-in through the same device flow as the keyboard shortcut."""
        event.stop()
        self.post_message(self.LoginRequested())

    @on(Button.Pressed, "#btn-logout")
    def request_logout(self, event: Button.Pressed) -> None:
        """Only the deliberate sign-out control opens confirmation."""
        event.stop()
        from toad.extensions.dega_panel.pane import DegaPane

        pane = self.query_ancestor(DegaPane)
        if pane is not None and self._status.phase == "connected":
            pane.action_logout()

    def _render_text(self) -> str:
        s = self._status
        if s.phase == "idle":
            return "[dim]Not connected — press [b]l[/b] to sign in with DEGA[/]"
        if s.phase == "connecting":
            return "[yellow]Contacting DEGA…[/]"
        if s.phase == "waiting":
            return (
                f"[yellow]Waiting for approval[/] · enter [b]{s.user_code}[/] ·\n"
                "[dim]open the link below, sign in to your DEGA account, and "
                "approve this device[/]"
            )
        if s.phase == "syncing":
            return "[dim]Signed in · Loading Elements…[/]"
        if s.phase == "error":
            return f"[red]Sign-in failed:[/] {s.error}"
        if s.phase == "connected":
            return f"[green]● connected[/] [b]{s.email}[/]"
        return "[dim]—[/]"


async def _apply_approved(client: DeviceClient, approved: dict) -> AuthState:
    """Persist the approved session + fetched elements, return the new state.

    The session is saved FIRST, so a transient failure while fetching elements
    never discards a token that was already validly issued and consumed
    server-side. Elements are fetched best-effort; on failure the user stays
    logged in with whatever they had before.
    """
    user = approved.get("user", {})
    email = user.get("email", "")
    display_name = user.get("display_name", "") or ""
    session_token = approved.get("session_token", "")
    user_id = user.get("id", "")

    state = AuthState(
        session=Session(
            session_token=session_token,
            user_id=user_id,
            email=email,
            display_name=display_name,
        ),
    )
    # Persist the session immediately — the token is already consumed server-side.
    save_auth(state)

    # Best-effort elements fetch; never throw away a valid login on failure.
    elements_data: dict[str, int] = {}
    total = 0
    addresses: list[str] = []
    if email:
        try:
            aggr = await client.fetch_elements(email)
            elements_data = aggr.get("aggregatedElements", {}) or {}
            total = aggr.get("totalElements", 0) or 0
            addresses = aggr.get("user", {}).get("addresses", []) or []
        except Exception:  # noqa: BLE001 - login stays valid if balances fail
            state.elements_error = "Balance unavailable — reconnect to retry"
            elements_data = {}
            total = 0
            addresses = []

    state.elements = elements_data
    state.total_elements = total
    state.addresses = addresses
    save_auth(state)
    return state


def run_device_login(client: DeviceClient, on_status, on_result):
    """Build the device-flow coroutine (does NOT schedule it).

    Returns an awaitable coroutine the caller must run via Textual's
    ``run_worker`` (which retains a strong reference). Scheduling it with a bare
    ``asyncio.create_task`` would let the loop drop it — asyncio keeps only a
    weak reference to tasks, so the login could be garbage-collected mid-flight.

    ``on_status(FlowStatus)`` is called on every state change so the UI can
    repaint; ``on_result(AuthState | None, str | None)`` delivers the outcome
    (state on success, error string on failure).
    """

    async def _run() -> None:
        try:
            on_status(FlowStatus(phase="connecting"))
            code = await client.request_code()
            verification_uri = urljoin(
                client.base_url + "/", code.get("verification_uri", "/device")
            )
            on_status(
                FlowStatus(
                    phase="waiting",
                    user_code=code["user_code"],
                    verification_uri=verification_uri,
                )
            )

            def _still_waiting() -> None:
                on_status(
                    FlowStatus(
                        phase="waiting",
                        user_code=code["user_code"],
                        verification_uri=verification_uri,
                    )
                )

            approved = await client.poll_token(
                code["device_code"],
                expires_in=code.get("expires_in", 600),
                interval=code.get("interval", 5),
                on_pending=_still_waiting,
            )
            on_status(FlowStatus(phase="syncing"))
            state = await _apply_approved(client, approved)
            on_status(
                FlowStatus(phase="connected", email=state.session.email if state.session else "")
            )
            on_result(state, None)
        except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
            on_status(FlowStatus(phase="error", error=str(exc)))
            on_result(None, str(exc))

    return _run()
