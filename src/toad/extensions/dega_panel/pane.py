"""Root widget for the DEGA panel and the `DegaPanel` implementation.

The host gives us one container and a status badge; everything inside is
ours, including the sub-tabs. See `toad.dega.protocol`.
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static, TabbedContent, TabPane
from toad.extensions.dega_panel.auth_store import AuthState, clear_auth, load_auth
from toad.extensions.dega_panel.auth_view import AuthBar, FlowStatus, run_device_login
from toad.extensions.dega_panel.chat import ChatView
from toad.extensions.dega_panel.device_client import DeviceClient
from toad.extensions.dega_panel.logout_confirm import LogoutConfirm
from toad.extensions.dega_panel.utility import UtilityView


class ElementsBar(Static):
    """What GET /elements-aggregation/by-email returns, rendered."""

    DEFAULT_CSS = """
    ElementsBar {
        height: auto;
        padding: 0 1;
        border-bottom: solid $panel-lighten-2;
    }
    """

    def __init__(self, pane: DegaPane) -> None:
        super().__init__()
        self._pane = pane

    def render(self) -> str:
        held = self._pane.elements
        auth = getattr(self._pane, "auth", None)
        logged_in = bool(auth is not None and getattr(auth, "is_logged_in", False))
        if logged_in and auth is not None and auth.session:
            if auth.elements_error:
                return f"[b]Elements[/]  [yellow]{auth.elements_error}[/]"
            chips = "  ".join(
                f"[{'reverse b' if held.get(k) else 'dim'}] {k} {held.get(k, 0)} [/]"
                for k in sorted(held, key=lambda key: (
                    {"silver": 0, "golden": 1, "obsidian": 2, "diamond": 3}.get(key.lower().split()[0] if key else "", 4), key
                ))
            ) or "[dim]no elements[/]"
            total = sum(held.values())
            return f"[b]Elements[/] [dim]· {total} total[/]  {chips}"
        return "[dim]Sign in to view your elements[/]"



class DegaPane(Vertical):
    """Holdings bar plus the Utility / Chat sub-tabs.

    Bindings live here rather than on the app: Textual walks up from the
    focused widget, so they fire anywhere inside the panel. They do not
    fire while the chat composer has focus, which is what we want — there
    the digits are text.
    """

    DEFAULT_CSS = """
    DegaPane { height: 1fr; }
    DegaPane #dega-subtabs { height: 1fr; }
    """

    # Shown in the footer so the controls are discoverable without a mouse:
    # terminals that do not forward mouse events leave the sub-tabs otherwise
    # unreachable. The remove keys stay hidden to keep the footer readable.
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("t", "toggle_tab", "Strategies/Chat"),
        Binding("l", "login", "Sign in"),
        Binding("o", "logout", "Sign out", show=False),
    ]

    # Elements are a backend snapshot, fetched from the API and persisted in
    # auth state. They are not user-editable from the panel.
    elements: reactive[dict] = reactive({}, always_update=True)
    auth: reactive[AuthState] = reactive[AuthState](AuthState, init=False)

    def __init__(self, client: DeviceClient | None = None) -> None:
        super().__init__()
        self._client = client or DeviceClient()

    def compose(self) -> ComposeResult:
        yield AuthBar(id="auth-bar")
        with TabbedContent(id="dega-subtabs"):
            with TabPane("Strategies", id="tab-dega-utility"):
                yield ElementsBar(self)
                yield UtilityView(self)
            with TabPane("Chat", id="tab-dega-chat"):
                yield ChatView(self)

    def on_mount(self) -> None:
        """Restore a persisted session so the panel is usable offline."""
        state = load_auth()
        self.auth = state
        if state.is_logged_in and state.elements:
            self.elements = dict(state.elements)
        self.call_after_refresh(self._init_auth_bar)
        # Textual activates the LAST TabPane by default and the app then parks
        # focus on the first visible input (chat's #username), which snaps the
        # tab to Chat. Set Utility active synchronously here — children are
        # already mounted, so this runs before the post-mount focus pass and
        # the catalogue's #build-list becomes the first focusable widget.
        self._select_utility_tab()

    def _select_utility_tab(self) -> None:
        tabs = self.query_one("#dega-subtabs", TabbedContent)
        if tabs.active != "tab-dega-utility":
            tabs.active = "tab-dega-utility"
        # Keep focus inside the catalogue so TabbedContent does not follow an
        # Input that lives in the (now hidden) Chat pane back to Chat.
        for widget in self.query("#build-list"):
            widget.focus()
            return

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        if event.tabbed_content.id != "dega-subtabs":
            return
        if event.pane.id == "tab-dega-chat":
            self._kick_chat_activation()

    def _init_auth_bar(self) -> None:
        bar = self.query_one("#auth-bar", AuthBar)
        if self.auth.is_logged_in:
            email = self.auth.session.email if self.auth.session else ""
            bar.set_status(FlowStatus(phase="connected", email=email))
        else:
            bar.set_status(FlowStatus(phase="idle"))

    def on_auth_bar_login_requested(self, event: AuthBar.LoginRequested) -> None:
        """Route the sign-in button to the device login flow."""
        event.stop()
        self.action_login()

    def action_login(self) -> None:
        """Start the device flow against the DEGA backend."""
        if self.auth.is_logged_in:
            return
        bar = self.query_one("#auth-bar", AuthBar)
        # run_worker keeps a strong reference to the coroutine (unlike a bare
        # asyncio.create_task, which the loop can garbage-collect mid-flight).
        self.run_worker(
            run_device_login(
                self._client,
                on_status=bar.set_status,
                on_result=self._on_login_result,
            ),
            name="dega-device-login",
            exclusive=True,
        )

    def _on_login_result(self, state: AuthState | None, error: str | None) -> None:
        if state is not None and state.is_logged_in:
            self.auth = state
            if state.elements:
                self.elements = dict(state.elements)

    def action_logout(self) -> None:
        """Ask for confirmation before clearing the local session."""
        if not self.auth.is_logged_in:
            return
        self.app.push_screen(LogoutConfirm(), self._confirm_logout)

    def _confirm_logout(self, confirmed: bool | None) -> None:
        if not confirmed or not self.auth.is_logged_in:
            return
        clear_auth()
        self.auth = AuthState()
        self.elements = {}
        bar = self.query_one("#auth-bar", AuthBar)
        bar.set_status(FlowStatus(phase="idle"))

    async def watch_auth(self) -> None:
        """Repaint auth-sensitive widgets when the session changes.

        The top elements bar depends on both the persisted session and the
        current elements snapshot, so changing only `auth` must still repaint
        it. Without this, a successful login could update the auth bar but leave
        the top line showing the old "not signed in" rendering until some
        unrelated elements change happened to trigger a refresh.
        """
        for bar in self.query(ElementsBar):
            bar.refresh()
        for view in self.query(UtilityView):
            await view.rebuild()
        tabs = self.query_one("#dega-subtabs", TabbedContent)
        if tabs.active == "tab-dega-chat":
            for chat in self.query(ChatView):
                await chat.rebuild()

    async def watch_elements(self) -> None:
        """Repaint when the elements snapshot changes."""
        for bar in self.query(ElementsBar):
            bar.refresh()
        for view in self.query(UtilityView):
            await view.rebuild()
        # Rebuild ChatView only if it's visible (active tab)
        tabs = self.query_one("#dega-subtabs", TabbedContent)
        if tabs.active == "tab-dega-chat":
            for chat in self.query(ChatView):
                await chat.rebuild()

    def action_toggle_tab(self) -> None:
        """Cycle Strategies and Chat from the keyboard.

        Focus has to move into the incoming pane. Leaving it on a widget of
        the outgoing pane makes TabbedContent snap the tab straight back, so
        setting ``active`` alone looks like the key did nothing.
        """
        tabs = self.query_one("#dega-subtabs", TabbedContent)
        choices = ["tab-dega-utility", "tab-dega-chat"]
        target = choices[(choices.index(tabs.active) + 1) % len(choices)]
        self.screen.set_focus(None)
        tabs.active = target
        self.call_after_refresh(self._focus_in_tab, target)

    def _focus_in_tab(self, target: str) -> None:
        # Utility centres on the build list; chat centres on the composer.
        selector = {"tab-dega-chat": "#contacts"}.get(
            target, "#build-list",
        )
        preferred = list(self.query(selector))
        candidates = preferred + list(self.query_one(f"#{target}").query("*"))
        for widget in candidates:
            if widget.can_focus and not widget.disabled and widget.is_on_screen:
                widget.focus()
                return

    def _kick_chat_activation(self) -> None:
        tabs = self.query_one("#dega-subtabs", TabbedContent)
        if tabs.active != "tab-dega-chat":
            return
        for view in self.query(ChatView):
            if view._chat_ready:
                return
            view._set_open_node_status("Loading chat…")
            self.run_worker(view.ensure_chat_ready(), name="dega-chat-ready", exclusive=True)
            return



class DegaPanelImpl:
    """Satisfies `toad.dega.protocol.DegaPanel`.

    Manifest fields are plain attributes so the host can read them at
    discovery time without building any widget.
    """

    id = "dega"
    title = "DEGA"
    accent = "gold"
    # Minimal refresh to keep the badge state visible to the user. The panel
    # itself has no upstream to refresh (fixed mock data), so this is a low-cost
    # keep-alive that lets the badge pulse and show the section is active.
    refresh_seconds = 30

    def __init__(self, client: DeviceClient | None = None) -> None:
        self._pane: DegaPane | None = None
        self._client = client

    async def available(self) -> bool:
        return True

    async def mount(self, container: Widget) -> None:
        self._pane = DegaPane(client=self._client)
        await container.mount(self._pane)

    async def refresh(self) -> None:
        """No-op: the mock has no upstream to re-fetch."""
        return
