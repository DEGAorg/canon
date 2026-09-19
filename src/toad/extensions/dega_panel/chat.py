"""Chat sub-tab: registered identities and private Nostr direct messages.

A chat **node** is owned by whoever paid the (configurable) $DEGA fee for a
unique ``username.dega``. Contacts are resolved from the registry and saved locally. Messages are NIP-44 E2E-encrypted DMs sent to a
public Nostr relay (free, no API key, no infra owned by DEGA).

The view shows, on-chain by default (testnet): the user's profile, the
multi-node list, a contacts list (resolved from the node's members + local
directory), and the fee-gated conversation. Test harnesses can override the
backend internally when needed.

Own messages sit right-aligned and theirs left-aligned (WhatsApp convention).
"""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import time
from datetime import datetime
from typing import cast

from rich.text import Text

from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual import on
from textual.events import Resize
from textual.widgets import Button, Checkbox, Collapsible, Input, Label, ListItem, ListView, Static

from toad.extensions.dega_panel.registration import Registration, RenewalQuote
from toad.extensions.dega_panel.chat_contact import (
    add_my_node,
    contacts,
    remember_contact,
    set_active_node,
)
from toad.extensions.dega_panel.chat_identity import (
    configured_wallet_address,
    load_or_create_identity,
)
from toad.extensions.dega_panel.chat_presence import (
    POLL_INTERVAL,
    PresenceClient,
    save_sharing,
    sharing_enabled,
)
from toad.extensions.dega_panel.chat_protocol import (
    fee_display,
    ChatNode,
    OfflineChatNode,
    make_node,
)
from toad.extensions.dega_panel.registry_client import (
    RegistryClient,
    RegistryError,
    _read_chat_env_key,
    display_name,
)

from toad.extensions.dega_panel.rooms.protocol import PREFIX, RoomError
from toad.extensions.dega_panel.rooms.service import RoomService
from toad.extensions.dega_panel.rooms.view import RoomsView


def default_registry_backend() -> str:
    """The panel's chat backend.

    Order of precedence: ~/.canon/dega-chat.env, then process env, then
    ``chain``. This keeps the app plug-and-play for users while still letting
    internal test harnesses override the backend when needed.
    """
    return os.environ.get("DEGA_CHAT_BACKEND") or _read_chat_env_key("DEGA_CHAT_BACKEND") or "chain"


def default_offline() -> bool:
    """Offline flag derived from the configured backend.

    Internal test harnesses may force a non-chain backend.
    """
    return default_registry_backend() != "chain"


class RenewRegistration(ModalScreen[bool]):
    """Confirm the on-chain charge before a registration renewal."""

    DEFAULT_CSS = """
    RenewRegistration { align: center middle; }
    RenewRegistration > Vertical {
        width: 60; max-width: 95%; height: auto; padding: 1 2;
        background: $surface; border: round $primary;
    }
    RenewRegistration Static { height: auto; margin-bottom: 1; }
    RenewRegistration Horizontal { height: auto; align-horizontal: right; }
    RenewRegistration Button { margin-left: 1; }
    """
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, quote: RenewalQuote) -> None:
        super().__init__()
        self.quote = quote

    def compose(self) -> ComposeResult:
        cost = fee_display(self.quote.fee, self.quote.decimals)
        seconds = self.quote.duration
        if seconds % 86400 == 0:
            duration = f"{seconds // 86400} {'day' if seconds == 86400 else 'days'}"
        else:
            duration = f"{seconds} seconds"
        pending = self.quote.pending
        with Vertical():
            yield Static("Check pending renewal" if pending else "Renew registration", markup=False)
            if pending:
                message = ("Check the previously approved transaction. "
                           "No additional period is purchased.")
            else:
                message = (
                    f"{display_name(self.quote.registration.username)}\n"
                    f"Extend by {duration} for {cost}, plus network gas.\n"
                    "Any remaining registration time is kept."
                )
            yield Static(message, markup=False)
            with Horizontal():
                yield Button("Cancel", id="cancel-renew")
                yield Button("Check transaction" if pending else "Confirm renewal",
                             id="confirm-renew", variant="primary")

    def action_cancel(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(event.button.id == "confirm-renew")


class ChatView(Vertical):
    """Profile + multi-node + contacts + E2E conversation (fee-gated)."""

    DEFAULT_CSS = """
    ChatView { height: 1fr; }
    ChatView #chat-wrap { height: 1fr; layout: horizontal; }
    ChatView #side {
        width: 28; background: $panel 25%; border-right: solid $panel-lighten-2;
        height: 1fr;
    }
    ChatView Collapsible { padding: 0; border: none; margin: 0; }
    ChatView .day-divider { height: 1; text-align: center; color: $text-muted; margin: 1 0; }
    ChatView #side Label.side-head { padding: 0 1; text-style: bold; }
    ChatView #side #contacts, ChatView #side #rooms-list {
        height: auto; max-height: 10; min-height: 1; background: transparent;
        overflow-y: auto;
    }
    ChatView #room-new, ChatView #contact-new { min-width: 10; width: 1fr; }
    ChatView #side Collapsible { height: auto; }
    ChatView #registration-status { height: auto; padding: 0 1; }
    ChatView #side #profile { height: auto; padding: 0 1; }
    ChatView #side #my-nodes-list { height: auto; max-height: 40%; background: transparent; }
    ChatView.compact #chat-wrap { layout: vertical; }
    ChatView.compact #side {
        width: 1fr; height: auto; max-height: 30%;
        border-right: none; border-bottom: solid $panel-lighten-2;
        overflow-y: auto;
    }
    ChatView.compact #side #contacts, ChatView.compact #side #rooms-list { max-height: 4; }
    ChatView.compact #side #my-nodes-list { max-height: 2; }
    ChatView #conv-col { width: 1fr; height: 1fr; }
    ChatView #room-list {
        height: 6; background: transparent;
        border-bottom: solid $panel-lighten-2;
    }
    ChatView ListItem { padding: 0 1; background: transparent; }
    ChatView ListItem.--highlight { background: $accent 25%; text-style: bold; }
    ChatView Button:focus { text-style: bold reverse; }
    ChatView .composer-hint { height: 1; color: $text-muted; padding: 0 1; }
    ChatView .contact-row { layout: horizontal; height: 1; }
    ChatView .contact-name { width: 1fr; height: 1; }
    ChatView .contact-presence { width: 2; height: 1; color: $success; }
    ChatView #presence-controls { height: auto; padding: 0 1; }
    ChatView #presence-sharing { width: 1fr; height: auto; border: none; padding: 0; }
    ChatView #presence-disclosure { height: auto; color: $text-muted; }
    ChatView #contacts .contact-row.selected-contact {
        background: $accent 25%; text-style: bold;
    }
    ChatView Button.contact-key-help {
        width: 3; min-width: 3; height: 1; padding: 0;
        border: none; color: $text-muted; background: transparent;
    }
    ChatView .contact-key-help:focus { text-style: reverse; }
    ChatView #chat-head { height: auto; padding: 0 1; }
    ChatView #username { margin: 0 0 1 0; background: $panel; color: $text; border: tall $panel-lighten-2; }
    ChatView #username.visible { display: block; }
    ChatView #add-contact-section { width: 1fr; height: 1fr; padding: 0 1; display: none; }
    ChatView #add-contact-section Label { height: auto; margin-bottom: 1; }
    ChatView #btn-add-contact { width: auto; min-width: 10; }
    ChatView .input-action { height: auto; }
    ChatView .input-action Input { width: 1fr; }
    ChatView .input-action Button { width: auto; min-width: 8; margin-left: 1; }
    ChatView #composer-row { padding: 0 1; }
    ChatView #conversation-toolbar { height: auto; padding: 0 1; }
    ChatView #conversation-title { width: 1fr; height: 3; content-align: left middle; }
    ChatView #btn-clear-state { width: auto; min-width: 12; }
    ChatView #btn-switch-node { width: auto; }
    ChatView .hidden { display: none; }
    ChatView #open-node-block {
        width: 100%; height: auto; padding: 0 1;
        layout: vertical;
        align-horizontal: left;
    }
    ChatView #open-node-status {
        height: auto;
        padding: 0 1;
        color: $text-muted;
    }
    ChatView #btn-open-node {
        background: $accent;
        color: $text;
        text-style: bold;
    }

    ChatView #conv-scroll { height: 1fr; padding: 0 1; }

    ChatView .badge { margin: 0 1 0 0; }
    ChatView .badge.online { color: $success; }
    ChatView .badge.relay { color: $accent; }
    ChatView .badge.off { color: $warning; }

    ChatView .row { width: 1fr; height: auto; margin-bottom: 1; }
    ChatView .row.mine { align-horizontal: right; }
    ChatView .row.theirs { align-horizontal: left; }
    ChatView .bubble {
        width: auto; max-width: 80%; height: auto; padding: 0 1;
    }
    ChatView .bubble.mine { background: $success 25%; }
    ChatView .bubble.theirs { background: $panel; }
    ChatView .bubble .head { color: $text 70%; }
    """

    def __init__(self, pane, *, offline: bool | None = None, registry_backend: str | None = None,
                 identity_path=None, contacts_path=None) -> None:
        super().__init__()
        self._pane = pane
        self._identity_path = identity_path
        self._contacts_path = contacts_path
        # Default to the on-chain (chain) backend for a real user; internal
        # test harnesses may override it when needed.
        if offline is None:
            offline = default_offline()
        self._offline = offline
        if registry_backend is None:
            registry_backend = default_registry_backend() if not offline else "test"
        self._registry_error: str | None = None
        self._registry: RegistryClient | None = None
        try:
            self._registry = RegistryClient(backend=registry_backend)
        except RegistryError as exc:
            # Real backend unreachable (no signer / RPC). Show it, don't fall
            # back to a mock — the user must wire DEGA_CHAT_PK or wallet.env.
            self._registry = None
            self._registry_error = str(exc)
        except (ValueError, TypeError):
            self._registry_error = "Invalid wallet configuration; check your local signing key"
        # My chat identity -> my Nostr node. On-chain reuses the persisted
        # identity so the handle/pubkey binding is stable; offline keeps a fresh
        # hermetic key for the harness.
        if offline:
            self._me: ChatNode = make_node(offline=True, store_path=self._inbox_store())
        else:
            keys, _created = load_or_create_identity(path=identity_path)
            self._me = ChatNode(secret_key=keys.secret_key().to_bech32())
        self._presence = PresenceClient(self._me)
        self._sharing = sharing_enabled(self._me.pubkey)
        self._presence_started = False
        self._online_until: dict[str, int] = {}
        self._sending = False
        self._sent: list[dict] = []  # locally-sent messages (own-side bubble)
        # Received DMs (network path, on-chain mode): [{event_id, from, text, time}]
        # merged chronologically with _sent in _render_conversation. In offline
        # (harness/test) mode we only show what this node sent, so this stays empty.
        self._received: list[dict] = []
        self._seen_received: set[str] = set()
        self._poll_started: bool = False
        self._my_username: str | None = None  # active node alias (bare)
        self._my_nodes: list[str] = []
        self._contact_return_to_room = False
        self._contacts: list[dict] = []
        self._drafts: dict[str, str] = {}
        self._selected_contact: dict | None = None
        self._relay_ok: bool | None = None  # None=unknown, True=relay reachable
        self._chat_ready: bool = False
        self._resume_started: bool = False
        self._resume_lock = asyncio.Lock()
        self._conversation_lock = asyncio.Lock()
        self._contacts_render_lock = asyncio.Lock()
        self._rooms_lock = asyncio.Lock()
        self._rooms_service: RoomService | None = None
        self._direct_history_loaded = False
        # Cache snapshot to avoid RPC calls during render (which runs in main thread)
        # Initialize with basic info; will update when chat activates.
        self._snapshot_cache: dict = {"fee_weega": 0}
        # Track if open_node is in progress to avoid resetting button label
        self._opening_node: bool = False
        self._registration: Registration | None = None
        self._registration_error: str | None = None
        self._registration_read_at = 0.0
        self._renewing = False
        self._registration_lock = asyncio.Lock()

    async def room_service(self) -> RoomService:
        """Return the identity-scoped service shared by room UI and relay polling."""
        from pathlib import Path
        from toad.extensions.dega_panel import auth_store

        async with self._rooms_lock:
            if self._rooms_service is None:
                base = Path(self._identity_path).parent if self._identity_path else auth_store.CANON_DIR
                directory = Path(os.environ.get("DEGA_CHAT_ROOMS_DIR", str(base / "rooms")))
                service = RoomService(self._me._keys, self._send_room_wire, directory)
                await service.open()
                self._rooms_service = service
            return self._rooms_service

    async def _send_room_wire(self, recipient: str, wire: str) -> str:
        if self._offline:
            raise RoomError("transport_unavailable", "Room relay is unavailable in offline mode")
        return await self._me.send_encrypted(recipient, wire)

    async def _restore_direct_history(self) -> None:
        if self._direct_history_loaded:
            return
        service = await self.room_service()
        existing = {entry.get("event_id") for entry in self._sent + self._received}
        for message in await service.direct_history():
            if message["event_id"] in existing:
                continue
            entry = {"event_id": message["event_id"], "text": message["text"],
                     "timestamp": message["timestamp"],
                     "time": time.strftime("%H:%M", time.localtime(message["timestamp"]))}
            if message["mine"]:
                entry["to"] = message["peer"]
                self._sent.append(entry)
            else:
                entry["from"] = message["peer"]
                self._received.append(entry)
                self._seen_received.add(message["event_id"])
        self._direct_history_loaded = True

    async def _retry_room_deliveries(self) -> None:
        if self._rooms_service is not None:
            try:
                await self._rooms_service.flush()
            except (OSError, sqlite3.Error):
                logging.getLogger(__name__).exception("room_outbox_storage_failed")
                self.notify("Could not save room delivery status; retrying later.", severity="error")

    async def on_unmount(self) -> None:
        if self._rooms_service is not None:
            await self._rooms_service.close()

    async def ensure_chat_ready(self) -> None:
        """Load on-chain identity only when the chat tab is actually opened."""
        await self.query_one(RoomsView).activate()
        if self._chat_ready:
            return
        async with self._resume_lock:
            try:
                await self._restore_direct_history()
            except (OSError, sqlite3.Error):
                logging.getLogger(__name__).exception("chat_history_restore_failed")
                self.notify("Could not open saved history. Check local storage.", severity="error")
                return
            if self._chat_ready:
                return
            self._resume_started = True
            try:
                self._set_open_node_status("Loading user from smart contract…")
                # Hide the open-node form while we resolve the on-chain user.
                await self.rebuild()
                # Load display terms and authoritative registration separately.
                if self._registry is not None and not self._offline:
                    try:
                        self._snapshot_cache = await asyncio.to_thread(self._registry.state_snapshot)
                    except Exception as exc:
                        logging.getLogger(__name__).warning("chat snapshot unavailable: %s", exc)
                await self._resume_node()
                self._chat_ready = True
                if not self._registration_error:
                    self._set_open_node_status("")
            finally:
                self._resume_started = False
                await self.rebuild()

    # --- helpers -----------------------------------------------------------
    def _inbox_store(self):
        """Where the offline chat persists E2E messages (~/.canon/chat-inbox.json)."""
        from toad.extensions.dega_panel.chat_store import DEFAULT_INBOX_FILE
        return DEFAULT_INBOX_FILE

    def _wallet(self) -> str:
        if self._offline:
            return "Test mode"
        try:
            return configured_wallet_address() or "Not configured"
        except ValueError:
            return "Invalid key — check wallet configuration"

    def _status(self) -> str:
        """Badge string for the header (relay / offline / node count)."""
        if self._offline:
            return "[dim]offline[/]"
        if not self._registry_error:
            return "[accent]relay·on-chain[/]"
        return "[red]chain backend unavailable[/] [dim](check DEGA_CHAT_PK / RPC / registry)[/]"

    # --- layout ------------------------------------------------------------
    def on_resize(self, event: Resize) -> None:
        self.set_class(event.size.width < 70, "compact")

    def compose(self) -> ComposeResult:
        yield Static(id="chat-head")
        with Horizontal(id="chat-wrap"):
            with VerticalScroll(id="side"):
                with Collapsible(title="Profile", id="account-details", collapsed=True):
                    yield Static(id="profile")
                    with Vertical(id="presence-controls"):
                        yield Checkbox(
                            "Share presence", value=self._sharing, id="presence-sharing",
                            compact=True,
                            tooltip=(
                                "Public on Nostr. After turning off, "
                                "status expires within 90 seconds."
                            ),
                        )
                        yield Static("Public on Nostr", id="presence-disclosure")
                    yield Label("My nodes", classes="side-head")
                    yield ListView(id="my-nodes-list")
                    yield Button("Switch node", id="btn-switch-node")
                with Collapsible(title="Registration", id="registration-section", collapsed=True):
                    yield Static("Checking registration…", id="registration-status", markup=False)
                    yield Button("Renew", id="btn-renew-registration", variant="primary", compact=True)
                    yield Button("Retry", id="btn-retry-registration", compact=True)
                with Collapsible(title="Contacts · 0", id="contacts-section", collapsed=False):
                    yield ListView(id="contacts")
                    yield Button("Add contact", id="contact-new", variant="primary", compact=True)
                with Collapsible(title="Rooms · 0", id="rooms-section", collapsed=False):
                    yield ListView(id="rooms-list")
                    yield Button("New room", id="room-new", variant="primary", compact=True)
            with Vertical(id="add-contact-section"):
                yield Label("Add contact · registered username")
                yield Input(placeholder="username.dega", id="contact-name")
                with Horizontal(classes="input-action"):
                    yield Button("Add contact", id="btn-add-contact", variant="primary")
                    yield Button("Cancel", id="contact-cancel")
            with Vertical(id="conv-col"):
                with Vertical(id="open-node-block"):
                    yield Input(
                        placeholder="Choose your username", id="username", classes="visible"
                    )
                    yield Button("Start chat", id="btn-open-node", variant="primary")
                yield Static("", id="open-node-status")
                with Horizontal(id="conversation-toolbar"):
                    yield Label("Conversation", id="conversation-title")
                    yield Button(
                        "Clear chat", id="btn-clear-state", variant="warning",
                        tooltip="Hide this conversation until the app restarts",
                    )
                yield VerticalScroll(id="conv-scroll")
                with Horizontal(id="composer-row", classes="input-action"):
                    yield Input(placeholder="Write a message...", id="composer")
                    yield Button("Send", id="btn-send", variant="primary")
                yield Static("Enter send · Tab next", classes="composer-hint", markup=False)

            yield RoomsView(self)

    async def on_mount(self) -> None:
        self.query_one(RoomsView).display = False
        await self._render_actions()
        self.set_interval(1, self._update_presence_labels)
        self.set_interval(15, self._retry_room_deliveries)
        # Keep mount fast so the host badge does not stay UPDATING while the
        # panel is still attaching. The on-chain wallet check happens lazily
        # when the Chat tab is actually opened.
        self.call_after_refresh(self._defer_rebuild)
        # Start background snapshot refresh task (every 30 seconds)
        self.set_interval(30.0, self._refresh_snapshot_cache)
        self.set_interval(1.0, self._render_registration)
    
    async def _refresh_snapshot_cache(self) -> None:
        """Refresh chain state without blocking typing or hiding RPC failures."""
        if not self._chat_ready or self._registry is None:
            return
        try:
            self._snapshot_cache = await asyncio.to_thread(self._registry.state_snapshot)
        except Exception as exc:
            logging.getLogger(__name__).warning("chat snapshot unavailable: %s", exc)
        await self._resume_node()
        await self.rebuild()

    def _defer_rebuild(self) -> None:
        self.run_worker(self.rebuild(), name="dega-chat-rebuild", exclusive=True)

    async def _resume_node(self) -> None:
        """Recover the wallet identity even when its registration has expired."""
        if self._registry is None:
            return
        async with self._registration_lock:
            try:
                registration = await asyncio.to_thread(self._registry.registration_status)
            except Exception as exc:
                self._registration_error = str(exc)
                return
            self._registration = registration
            self._registration_read_at = time.monotonic()
            self._registration_error = None
            self._my_username = registration.username or None
            self._my_nodes = [registration.username] if registration.username else []
            if not registration.username:
                return
            box = self.query_one("#username", Input)
            box.value = registration.username
            box.disabled = True
            set_active_node(registration.username, path=self._contacts_path)

    def _registration_active(self) -> bool:
        registration = self._registration
        if registration is None or self._registration_error:
            return False
        elapsed = max(0, time.monotonic() - self._registration_read_at)
        return registration.active and registration.checked_at + elapsed < registration.expires_at

    def _render_registration(self) -> None:
        status = self.query_one("#registration-status", Static)
        renewal = self.query_one("#btn-renew-registration", Button)
        retry = self.query_one("#btn-retry-registration", Button)
        registration = self._registration
        error = self._registration_error or self._registry_error
        retry.display = bool(error) and self._registry is not None
        renewal.display = bool(registration and registration.username)
        renewal.disabled = self._renewing or bool(error)
        renewal.label = "Renewing…" if self._renewing else "Renew"
        if self._renewing:
            text = "Registration · Awaiting confirmation…"
        elif error:
            text = "Registration · Unable to check"
        elif registration and registration.username:
            state = "Active" if self._registration_active() else "Expired"
            text = f"Registration · {state}\nExpires {registration.expiry_label}"
            if state == "Expired":
                text += "\nRenew to be discoverable"
        else:
            text = "Not registered" if registration else "Checking registration…"
        summary = text.split("\n", 1)[0].removeprefix("Registration · ")
        section = self.query_one("#registration-section", Collapsible)
        section.title = f"Registration · {summary}"
        section.tooltip = error or text
        status.update(text)
        status.tooltip = error

    async def _renew_registration(self) -> None:
        try:
            if self._registry is None:
                return
            quote = await asyncio.to_thread(self._registry.renewal_quote)
            if not await self.app.push_screen_wait(RenewRegistration(quote)):
                return
            self._render_registration()
            await asyncio.to_thread(self._registry.renew_node, quote)
            await self._resume_node()
            if self._registration_error:
                self.notify("Transaction confirmed; retry to refresh registration",
                            severity="warning")
            else:
                self.notify("Registration renewed")
        except Exception as exc:
            self._set_open_node_status(str(exc), error=True)
            self.notify(str(exc), severity="error")
        finally:
            self._renewing = False
            await self.rebuild()

    # --- actions -----------------------------------------------------------
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "room-new":
            event.stop()
            if self._my_username:
                self.run_worker(self.query_one(RoomsView).on_button_pressed(event))
        elif event.button.id == "btn-renew-registration":
            if not self._renewing:
                self._renewing = True
                self.run_worker(self._renew_registration(), group="renew-registration")
        elif event.button.id == "btn-retry-registration":
            self.run_worker(self._refresh_snapshot_cache(), group="registration-refresh")
        elif event.button.id == "btn-open-node":
            # Show feedback immediately, spawn work in background
            self._opening_node = True
            btn = self.query_one("#btn-open-node", Button)
            btn.disabled = True
            btn.label = "Connecting…"
            self.run_worker(self._open_node_and_rebuild(), exclusive=True, name="open-node")
        elif event.button.id == "contact-new":
            if not self.query_one("#add-contact-section").display:
                self._contact_return_to_room = self.query_one(RoomsView).display
            self.query_one(RoomsView).display = False
            self.query_one("#conv-col").display = False
            self.query_one("#add-contact-section").display = True
            self.query_one("#contact-name", Input).focus()
        elif event.button.id == "contact-cancel":
            self.show_room(self._contact_return_to_room)
            self.query_one("#contact-new", Button).focus()
        elif event.button.id == "btn-add-contact":
            self.run_worker(self._add_contact_and_rebuild(), exclusive=True, name="add-contact")
        elif event.button.id == "btn-send":
            self.run_worker(self._send_and_rebuild(), group="chat-send", name="send")
        elif event.button.id == "btn-switch-node":
            self.run_worker(self._switch_and_rebuild(), exclusive=True, name="switch")
        elif event.button.id == "btn-clear-state":
            self.run_worker(self._clear_and_rebuild(), exclusive=True, name="clear")
    
    async def _open_node_and_rebuild(self) -> None:
        try:
            await self._open_node()
        finally:
            self._opening_node = False
            await self._resume_node()
            await self.rebuild()
    
    async def _add_contact_and_rebuild(self) -> None:
        try:
            await self._add_contact()
        finally:
            await self.rebuild()
    
    async def _send_and_rebuild(self) -> None:
        try:
            await self._send_message()
        finally:
            await self.rebuild()
    
    async def _switch_and_rebuild(self) -> None:
        try:
            await self._switch_node()
        finally:
            await self.rebuild()
    
    async def _clear_and_rebuild(self) -> None:
        try:
            await self._clear_state()
        finally:
            await self.rebuild()

    @on(ListView.Selected, "#my-nodes-list")
    async def on_my_nodes_selected(self, event: ListView.Selected) -> None:
        event.stop()
        if not self._my_username:
            return
        idx = getattr(event, "index", None)
        if idx is None or idx < 0:
            return
        if idx >= len(self._my_nodes):
            return
        self._my_username = self._my_nodes[idx]
        set_active_node(self._my_username, path=self._contacts_path)
        box = self.query_one("#username", Input)
        box.value = self._my_username
        box.disabled = True
        self._selected_contact = None
        self._set_open_node_status(f"Switched to {display_name(self._my_username)}")
        await self.rebuild()

    def show_room(self, visible: bool) -> None:
        """Switch the conversation area without losing either conversation's draft."""
        visible = visible and bool(self._my_username)
        self.query_one("#add-contact-section").display = False
        self.query_one("#conv-col").display = not visible
        rooms = self.query_one(RoomsView)
        rooms.display = visible
        listing = self.query_one("#rooms-list", ListView)
        listing.index = (
            rooms.room_ids.index(rooms.selected)
            if visible and rooms.selected in rooms.room_ids else None
        )
        for row in self.query(".contact-row"):
            row.set_class(
                not visible and row.name == (self._selected_contact or {}).get("pubkey"),
                "selected-contact",
            )
        if visible:
            self.query_one("#contacts", ListView).index = None

    @on(ListView.Selected, "#rooms-list")
    async def on_room_selected(self, event: ListView.Selected) -> None:
        if self._my_username:
            await self.query_one(RoomsView).select_room(event)

    @on(ListView.Selected, "#contacts")
    async def on_contacts_selected(self, event: ListView.Selected) -> None:
        event.stop()
        idx = getattr(event, "index", None)
        if idx is None or idx < 0:
            return
        known = contacts(path=self._contacts_path)
        if idx >= len(known):
            return
        chosen = known[idx]
        self.show_room(False)
        composer = self.query_one("#composer", Input)
        if self._selected_contact:
            self._drafts[self._selected_contact.get("pubkey", "")] = composer.value
        self._selected_contact = chosen
        composer.value = self._drafts.get(chosen.get("pubkey", ""), "")
        for index, row in enumerate(self.query(".contact-row")):
            row.set_class(index == idx, "selected-contact")
        self.query_one("#composer", Input).focus()
        self._set_open_node_status("")
        self._update_presence_labels()
        await self._render_actions()
        await self._render_conversation()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "composer":
            event.stop()
            self.run_worker(self._send_and_rebuild(), group="chat-send", name="send")
            return
        elif event.input.id == "contact-name":
            self.run_worker(self._add_contact_and_rebuild(), exclusive=True, name="add-contact")
        await self.rebuild()

    @on(Button.Pressed, ".contact-key-help")
    def explain_missing_contact_key(self, event: Button.Pressed) -> None:
        """Explain a contact's missing key without crowding the contact list."""
        event.stop()
        self.notify(
            "This contact's chat key is unavailable, so messages cannot be sent yet. "
            "Ask them to confirm their registered username.",
            title="Contact needs attention",
        )

    # --- domain ------------------------------------------------------------
    async def _open_node(self) -> None:
        """Register only after authoritative wallet and fee reads succeed."""
        from toad.extensions.dega_panel.chat_identity import save_username
        from toad.extensions.dega_panel.registry_client import validate_username

        if self._registry_error or self._registry is None:
            self.notify(self._registry_error or "Chat registry unavailable", severity="error")
            return
        if self._my_username:
            return
        registry = self._registry
        try:
            canon = validate_username(self.query_one("#username", Input).value)
            self._set_open_node_status("Checking wallet registration…")
            registration = await asyncio.to_thread(registry.registration_status)
            if registration.username:
                await self._resume_node()
                return
            fee = await asyncio.to_thread(registry.fee_weega)
            decimals = await asyncio.to_thread(registry.fee_decimals)
            fee_label = fee_display(fee, decimals)
            self._set_open_node_status(f"Registering… paying {fee_label}")
            result = await asyncio.to_thread(
                registry.open_node, canon, nostr_pubkey=self._me.pubkey,
                nostr_secret=self._me._keys.secret_key().to_hex(),
            )
            if result.get("status") == "pending":
                self._set_open_node_status("Registration pending; check transaction confirmation")
                return
            save_username(canon, path=self._identity_path)
            self._my_nodes = add_my_node(canon, path=self._contacts_path)
            set_active_node(canon, path=self._contacts_path)
            self._set_open_node_status(f"Registered {display_name(canon)} (fee {fee_label})")
            self.notify(f"Registered {display_name(canon)}")
        except Exception as exc:
            self._set_open_node_status(str(exc), error=True)
            self.notify(str(exc), severity="error")

    async def _switch_node(self) -> None:
        self._set_open_node_status("Switching node…")
        """Cycle through the user's open nodes (multi-node support)."""
        if not self._my_nodes:
            return
        idx = (self._my_nodes.index(self._my_username) + 1) % len(self._my_nodes) if self._my_username in self._my_nodes else 0
        nxt = self._my_nodes[idx]
        self._my_username = nxt
        set_active_node(nxt, path=self._contacts_path)
        self.notify(f"Switched to node {display_name(nxt)}")

    async def _clear_state(self) -> None:
        """Clear only the selected conversation from this session's view."""
        recipient = (self._selected_contact or {}).get("pubkey")
        if not recipient:
            return
        self._sent = [message for message in self._sent if message["to"] != recipient]
        self._received = [message for message in self._received if message["from"] != recipient]
        self._drafts.pop(recipient, None)
        self.query_one("#composer", Input).value = ""
        self.notify("Conversation cleared for this session")

    async def _add_contact(self) -> None:
        if self._registry is None or self._registry_error:
            self.notify(self._registry_error or "backend unavailable", severity="error")
            return
        if not self._my_username:
            self.notify("Open a node first", severity="warning")
            return
        contact_input = self.query_one("#contact-name", Input)
        target = contact_input.value.strip()
        if not target:
            self.notify("Enter the person's registered username", severity="warning")
            return
        try:
            member = await asyncio.wait_for(
                asyncio.to_thread(self._registry.resolve_member, target), timeout=30,
            )
        except Exception as exc:
            self.notify(f"Could not look up contact: {exc}", severity="error")
            return
        if not member:
            self.notify(f"{target}: registration missing or expired", severity="error")
            return
        pub = member.get("pubkey") or b""
        if not pub:
            self.notify(
                f"{target}: no chat key available; ask them to check registration",
                severity="error",
            )
            return
        try:
            remember_contact(member["wallet"], username=member.get("username", ""),
                             pubkey=pub, path=self._contacts_path)
        except OSError as exc:
            self.notify(f"Could not save contact: {exc}", severity="error")
            return
        self.notify(f"Added {display_name(member['username'])} to contacts")
        contact_input.value = ""
        self.show_room(self._contact_return_to_room)
        self.query_one("#contact-new", Button).focus()

    async def _send_message(self) -> None:
        if self._sending:
            return
        if not self._my_username:
            self.notify("Open a node first", severity="warning")
            return
        composer = self.query_one("#composer", Input)
        text = composer.value.strip()
        recipient = (self._selected_contact or {}).get("pubkey")
        if not text:
            return
        if not recipient:
            self.notify("Select a contact with a chat key before sending", severity="warning")
            return
        self._sending = True
        timestamp = time.time()
        message = {
            "text": text, "time": time.strftime("%H:%M", time.localtime(timestamp)),
            "timestamp": timestamp, "to": recipient, "status": "Sending…",
        }
        self._sent.append(message)
        self._drafts.pop(recipient, None)
        composer.value = ""
        try:
            await self._render_actions()
            await self._render_conversation()
            if self._offline:
                peer = cast(OfflineChatNode, make_node(offline=True))
                peer.pubkey = recipient
                event_id = await cast(OfflineChatNode, self._me).deliver_to(peer, text)
            else:
                event_id = await self._me.send_encrypted(recipient, text)
            message.update(event_id=event_id, status="")
            try:
                service = await self.room_service()
                await service.remember_dm(event_id, peer=recipient, mine=True,
                                          timestamp=int(timestamp), body=text)
            except Exception as exc:
                self.notify(f"Message sent, but could not save local history: {exc}", severity="error")
        except (Exception, asyncio.CancelledError) as exc:
            if message.get("event_id"):
                self.notify("Message sent; local history update was interrupted.", severity="warning")
            else:
                if message in self._sent:
                    self._sent.remove(message)
                self._drafts[recipient] = text
                if (self._selected_contact or {}).get("pubkey") == recipient:
                    composer.value = text
                self.notify(f"Send failed; draft restored for retry: {exc}", severity="error")
            if isinstance(exc, asyncio.CancelledError):
                raise
        finally:
            self._sending = False
            await self._render_actions()
            await self._render_conversation()
            if (self._selected_contact or {}).get("pubkey") == recipient:
                composer.focus()

    # --- receiving (network path) ----------------------------------------
    @on(Checkbox.Changed, "#presence-sharing")
    def set_presence_sharing(self, event: Checkbox.Changed) -> None:
        """Persist explicit opt-in; turning off is observed before the next publish."""
        event.stop()
        if event.value == self._sharing:
            return
        try:
            save_sharing(self._me.pubkey, event.value)
        except OSError:
            event.checkbox.value = self._sharing
            self.notify("Could not save presence preference. Check local file permissions.")
            return
        self._sharing = event.value

    def _can_share_presence(self) -> bool:
        return bool(self._sharing and self._my_username and self.is_on_screen and not self._offline)

    async def _refresh_presence(self) -> None:
        if not self._my_username or not self.is_on_screen or self._offline:
            self._online_until = {}
        else:
            authors = {c["pubkey"] for c in contacts(path=self._contacts_path) if c.get("pubkey")}
            self._online_until = await self._presence.refresh(
                authors, share=self._can_share_presence
            )
        self._update_presence_labels()

    async def _presence_loop(self) -> None:
        while True:
            await self._refresh_presence()
            await asyncio.sleep(POLL_INTERVAL)

    def _update_presence_labels(self) -> None:
        now = int(time.time())
        for row in self.query(".contact-row"):
            online = self._online_until.get(row.name or "", 0) > now
            row.query_one(".contact-presence", Static).update("●" if online else " ")
            row.tooltip = "Online · recent presence signal" if online else None
        recipient = self._selected_contact
        label = "Conversation"
        if recipient:
            label = (
                recipient.get("username") or recipient.get("wallet")
                or (recipient.get("pubkey") or "")[:12] or "Conversation"
            )
            if self._online_until.get(recipient.get("pubkey", ""), 0) > now:
                label += " · Online"
        self.query_one("#conversation-title", Label).update(Text(label))

    def _start_inbox_poll(self) -> None:
        """Start the periodic inbox poll once a node is open on the network path.

        Only on-chain / non-offline ChatNodes actually receive from relays. In
        offline (test harness) mode there is no relay, so no poll is started.
        """
        if self._offline:
            return
        if self._poll_started:
            return
        self._poll_started = True
        self.run_worker(
            self._inbox_poll_loop(), name="dega-chat-inbox-poll", group="chat-inbox",
            exclusive=True,
        )

    async def _inbox_poll_loop(self) -> None:
        """Poll the relay for kind-4 DMs addressed to me and merge them in."""
        interval = 8.0
        while True:
            try:
                new = await self._me.fetch_dms()
            except Exception:  # noqa: BLE001 - relay flakiness; keep polling
                new = []
            added = False
            for dm in new:
                eid = dm.get("event_id")
                if not eid or eid in self._seen_received:
                    continue
                if dm.get("text", "").startswith(PREFIX):
                    try:
                        service = await self.room_service()
                        await service.ingest(dm.get("from", ""), dm["text"])
                    except (OSError, sqlite3.Error):
                        logging.getLogger(__name__).exception("room_inbound_storage_failed")
                        self.notify("Could not save room update; retrying later.", severity="error")
                        continue
                    except RoomError as exc:
                        self.notify(f"Room update: {exc}", severity="warning")
                    self._seen_received.add(eid)
                    continue
                await self._remember_incoming_sender(dm.get("from", ""))
                # Render the time as HH:MM (epoch secs -> local time).
                raw_time = dm.get("time")
                try:
                    timestamp = int(raw_time) if raw_time is not None else 0
                    hhmm = time.strftime("%H:%M", time.localtime(timestamp)) if timestamp else ""
                except (TypeError, ValueError, OverflowError, OSError):
                    timestamp = 0
                    hhmm = ""
                try:
                    service = await self.room_service()
                    await service.remember_dm(eid, peer=dm.get("from", ""), mine=False,
                                              timestamp=timestamp, body=dm.get("text", ""))
                except (OSError, sqlite3.Error):
                    logging.getLogger(__name__).exception("chat_inbound_storage_failed")
                    self.notify("Could not save message; retrying later.", severity="error")
                    continue
                self._seen_received.add(eid)
                self._received.append({
                    "event_id": eid,
                    "from": dm.get("from", ""),
                    "text": dm.get("text", ""),
                    "time": hhmm,
                    "timestamp": timestamp,
                })
                added = True
            if added:
                # Avoid echoing our own outbound events back into the "received"
                # column (send + poll can race and see the same event id only if
                # the relay returns events we signed — those won't match 'p' to us
                # for a DM we *sent*, so this is normally empty; keep for safety).
                await self.rebuild()
            await asyncio.sleep(interval)

    async def _remember_incoming_sender(self, sender: str) -> None:
        """Make received conversations selectable, even without a registered name."""
        if not sender:
            return
        known = contacts(path=self._contacts_path)
        if any(contact["pubkey"] == sender for contact in known):
            return
        username = ""
        if not self._offline and self._registry is not None:
            try:
                username = await asyncio.to_thread(self._registry.username_for_pubkey, sender)
            except Exception:
                logging.getLogger(__name__).warning(
                    "chat_sender_lookup_failed", extra={"sender_pubkey": sender}, exc_info=True,
                )
        remember_contact(
            sender, username=username, pubkey=bytes.fromhex(sender), path=self._contacts_path,
        )

    def _sender_label(self, pubkey: str) -> str:
        """Best-effort name for an incoming DM's sender (contact / node owner)."""
        pubkey = (pubkey or "").lower()
        for c in contacts(path=self._contacts_path):
            if (c.get("pubkey") or "").lower() == pubkey and c.get("username"):
                return display_name(c["username"])
        # Fall back to a short pubkey so the bubble is never empty.
        return f"{pubkey[:8]}…" if pubkey else "peer"

    # --- rendering ---------------------------------------------------------
    async def rebuild(self) -> None:
        # ONLY refresh snapshot periodically in background, not on every UI event
        # to avoid blocking the main thread during normal typing/interaction
        self.query_one("#chat-head", Static).update(self._header())
        await self._render_profile()
        self._render_registration()
        await self._render_my_nodes()
        await self._render_contacts()
        await self._render_actions()
        await self._render_conversation()
        # Once a node is open on the network path, start receiving DMs.
        if self._my_username and not self._offline:
            self._start_inbox_poll()
            if not self._presence_started:
                self._presence_started = True
                self.run_worker(
                    self._presence_loop(), name="chat-presence", group="chat-presence",
                    exclusive=True,
                )

    def _header(self) -> str:
        if self._registry_error:
            return f"[b]Chat[/]  [dim]on-chain[/] · [red]{self._registry_error}[/]"
        if self._my_username:
            return "[dim]End-to-end encrypted[/]"
        fee = ""
        if self._registry is not None and self._snapshot_cache is not None:
            snap = self._snapshot_cache
            # A missing key means "unknown", never "assume 8".
            snap_decimals = snap.get("fee_decimals")
            fee = (
                fee_display(snap.get("fee_weega", 0), snap_decimals)
                if snap.get("fee_weega") else "free tier"
            )
            fee = f" · fee {fee}"
        return f"[b]Chat[/]{fee}  {self._status()}"

    async def _render_profile(self) -> None:
        prof = self.query_one("#profile", Static)
        wallet = self._wallet()
        wallet_state = "Configured" if wallet.startswith("0x") else wallet
        wallet_line = f"\n{wallet}" if wallet.startswith("0x") else ""
        registration = "Not registered"
        if self._my_username:
            registration = display_name(self._my_username)
        elif self._registry_error:
            registration = "Unable to check registry"
        elif not self._chat_ready:
            registration = "Checking registry…"
        prof.update(
            f"[b]Wallet[/] · {wallet_state}{wallet_line}\n"
            f"[b]Registration[/]\n{registration}\n"
            f"[b]Chat key[/]\n{self._me.npub[:16]}…"
        )
        prof.tooltip = f"Wallet: {wallet}\nChat public key: {self._me.npub}"

    async def _render_my_nodes(self) -> None:
        lst = self.query_one("#my-nodes-list", ListView)
        await lst.clear()
        if not self._my_username:
            return
        for n in self._my_nodes:
            label = display_name(n)
            if self._my_username == n:
                label = f"[b]{label}[/]"
            await lst.append(ListItem(Static(label)))

    async def _render_contacts(self) -> None:
        async with self._contacts_render_lock:
            lst = self.query_one("#contacts", ListView)
            await lst.clear()
            section = self.query_one("#contacts-section", Collapsible)
            section.title = "Contacts · 0"
            if not self._my_username:
                return
            known = {c["wallet"].lower(): c for c in contacts(path=self._contacts_path)}
            section.title = f"Contacts · {len(known)}"
            if not known:
                await lst.append(ListItem(Static("[dim](no contacts yet)[/]")))
                return
            for w, c in known.items():
                label = c.get("username") or c.get("wallet", w)[:14]
                row = ListItem(
                    Static(" ", classes="contact-presence"),
                    Static(label, classes="contact-name"),
                    classes="contact-row", name=c.get("pubkey") or None,
                )
                row.set_class(
                    bool(not self.query_one(RoomsView).display and self._selected_contact and
                         c["wallet"] == self._selected_contact.get("wallet")),
                    "selected-contact",
                )
                await lst.append(row)
                if not c.get("pubkey"):
                    await row.mount(Button(
                        "!", classes="contact-key-help", compact=True, flat=True,
                        tooltip="Chat key unavailable",
                    ))
            self._update_presence_labels()

    def _set_open_node_status(self, text: str, error: bool = False) -> None:
        status = self.query_one("#open-node-status", Static)
        if error:
            status.update(f"[red]{text}[/]")
        else:
            status.update(f"[dim]{text}[/]")

    async def _render_actions(self) -> None:
        uname = self.query_one("#username", Input)
        contact_input = self.query_one("#contact-name", Input)
        composer = self.query_one("#composer", Input)
        open_btn = self.query_one("#btn-open-node", Button)
        add_contact_btn = self.query_one("#btn-add-contact", Button)
        send_btn = self.query_one("#btn-send", Button)
        clear_btn = self.query_one("#btn-clear-state", Button)
        swap_btn = self.query_one("#btn-switch-node", Button)
        registered = bool(self._my_username)
        recipient = (self._selected_contact or {}).get("pubkey")
        composer.disabled = self._sending or not bool(recipient)
        send_btn.disabled = self._sending or not bool(recipient)
        send_btn.label = "Sending…" if self._sending else "Send"
        clear_btn.disabled = self._sending or not bool(recipient)
        self.query_one("#contacts-section").display = registered
        self.query_one("#rooms-section").display = registered
        self.query_one("#conv-scroll").display = registered
        if not registered:
            self.show_room(False)
        self.query_one("#presence-controls").display = registered
        self.query_one("#open-node-block").display = not registered
        if not registered:
            self.query_one("#add-contact-section").display = False
        self.query_one("#conversation-toolbar").display = registered
        self.query_one("#composer-row").display = registered
        if not self._my_username:
            # No open node → there's no conversation to compose into. Hide the
            # composer so the "Write a message…" input doesn't show standalone.
            composer.display = False
            composer.value = ""
            # While resolving the on-chain user, don't offer the open-node form
            # or an editable username — you'd be trying to open a chat for a node
            # that hasn't loaded yet.
            if self._resume_started:
                uname.classes = "hidden"
                contact_input.classes = "hidden"
                open_btn.display = True
                open_btn.disabled = True
                open_btn.label = "Loading…"
                add_contact_btn.display = False
                send_btn.display = False
                swap_btn.display = False
                clear_btn.display = False
                return
            uname.classes = "visible"
            uname.disabled = False
            contact_input.classes = "hidden"
            open_btn.display = True
            open_btn.disabled = self._opening_node or bool(self._registration_error)
            add_contact_btn.display = False
            send_btn.display = False
            swap_btn.display = False
            clear_btn.display = True
            uname.focus()
            # Use cached fee from snapshot; fall back to 0
            # Don't reset label if opening is in progress
            if not self._opening_node:
                fee = self._snapshot_cache.get("fee_weega", 0)
                fee_decimals_btn = self._snapshot_cache.get("fee_decimals")
                fee_degas = fee_display(fee, fee_decimals_btn) if fee else "0 $DEGA"
                open_btn.label = f"Start chat ({fee_degas})"
        else:
            uname.classes = "hidden"
            # Show the composer only when a node is actually open.
            composer.display = True
            # Registered identities can look up and save contacts locally.
            contact_input.classes = ""
            open_btn.display = False
            add_contact_btn.display = True
            send_btn.display = True
            clear_btn.display = True
            swap_btn.display = len(self._my_nodes) > 1

    async def _render_conversation(self) -> None:
        async with self._conversation_lock:
            await self._render_selected_conversation()

    async def _render_selected_conversation(self) -> None:
        scroll = self.query_one("#conv-scroll", VerticalScroll)
        await scroll.remove_children()
        if self._resume_started and not self._my_username:
            await scroll.mount(Static("[dim]Loading your node from the smart contract…[/]"))
            return
        if not self._my_username:
            await scroll.mount(Static(
                "[dim]Configure your wallet, choose a username, then start chat. "
                "Registration pays the displayed fee once.[/]"
            ))
            return
        recipient = (self._selected_contact or {}).get("pubkey")
        if not recipient:
            await scroll.mount(Static("Select a contact to open a private conversation."))
            return
        sent = [message for message in self._sent if message["to"] == recipient]
        received = [message for message in self._received if message["from"] == recipient]
        if not sent and not received:
            await scroll.mount(Static("No messages with this contact yet. Say hello."))
            return
        entries: list[dict] = []
        for m in sent:
            entries.append({"mine": True, "who": display_name(self._my_username),
                            "text": m["text"], "time": m.get("time", ""),
                            "status": m.get("status", ""),
                            "timestamp": m["timestamp"]})
        for m in received:
            entries.append({"mine": False, "who": self._sender_label(m.get("from", "")),
                            "text": m.get("text", ""), "time": m.get("time", ""),
                            "timestamp": m["timestamp"]})
        entries.sort(key=lambda entry: entry["timestamp"])
        previous_day = None
        for entry in entries:
            timestamp = entry["timestamp"]
            day = (
                datetime.fromtimestamp(timestamp).strftime("%b %d, %Y")
                if timestamp else "Date unknown"
            )
            if day != previous_day:
                await scroll.mount(Static(day, classes="day-divider"))
                previous_day = day
            side = "mine" if entry["mine"] else "theirs"
            content = Text()
            content.append(f"{entry['who']} · {entry['time']}\n", style="dim bold")
            content.append(entry["text"], style="default")
            if entry.get("status"):
                content.append(f"\n{entry['status']}", style="dim")
            await scroll.mount(Horizontal(
                Static(content, classes=f"bubble {side}"), classes=f"row {side}",
            ))
        scroll.scroll_end(animate=False)
