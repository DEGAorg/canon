"""Keyboard-accessible room conversations and creator membership controls."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime
from typing import TYPE_CHECKING

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Collapsible,
    Input,
    Label,
    ListItem,
    ListView,
    Select,
    Static,
)

from toad.extensions.dega_panel.chat_contact import contacts
from toad.extensions.dega_panel.rooms.protocol import RoomError

if TYPE_CHECKING:
    from toad.extensions.dega_panel.rooms.service import RoomService
    from toad.extensions.dega_panel.chat import ChatView


class RoomConfirm(ModalScreen[bool]):
    """Confirm destructive membership actions with Cancel focused first."""

    AUTO_FOCUS = "#room-cancel"
    BINDINGS = [("escape", "cancel", "Cancel")]
    DEFAULT_CSS = """
    RoomConfirm { align: center middle; }
    RoomConfirm Vertical { width: 50; max-width: 90%; height: auto;
        padding: 1 2; border: round $primary; background: $surface; }
    RoomConfirm Horizontal { height: auto; align-horizontal: right; }
    RoomConfirm Label { height: auto; width: 1fr; margin-bottom: 1; }
    """

    def __init__(self, question: str) -> None:
        super().__init__()
        self.question = question

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self.question)
            with Horizontal():
                yield Button("Cancel", id="room-cancel")
                yield Button("Confirm", id="room-confirm", variant="error")

    def action_cancel(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "room-confirm")


class RoomsView(Vertical):
    """Render room state; mutations are delegated to the shared RoomService."""

    DEFAULT_CSS = """
    RoomsView { height: 1fr; }
    RoomsView #room-main { width: 1fr; height: 1fr; padding: 0 1; }
    RoomsView #room-heading { height: auto; text-style: bold; }
    RoomsView #room-state { height: auto; color: $text-muted; }
    RoomsView #room-history { height: 1fr; }
    RoomsView .room-message { width: 1fr; height: auto; margin-bottom: 1; }
    RoomsView .room-message.mine { align-horizontal: right; }
    RoomsView .room-message.theirs { align-horizontal: left; }
    RoomsView .room-line { width: auto; max-width: 80%; height: auto; padding: 0 1; }
    RoomsView .room-line.mine { background: $success 25%; }
    RoomsView .room-line.theirs { background: $panel; }
    RoomsView .room-controls { height: auto; }
    RoomsView .room-controls Input { width: 1fr; }
    RoomsView .room-controls Button { min-width: 8; width: auto; }
    RoomsView Collapsible { height: auto; padding: 0; border: none; }
    RoomsView Select { width: 1fr; }
    RoomsView #room-members { height: auto; max-height: 6; overflow-y: auto; }
    RoomsView #room-feedback { height: auto; color: $warning; }
    """

    def __init__(self, chat: ChatView) -> None:
        super().__init__()
        self.chat = chat
        self.selected: str | None = None
        self.room_ids: list[str] = []
        self.drafts: dict[str, str] = {}
        self.service: RoomService | None = None
        self.render_lock = asyncio.Lock()
        self.action_lock = asyncio.Lock()
        self.last_snapshot: str = ""
        self.creating = True

    def compose(self) -> ComposeResult:
        with Vertical(id="room-main"):
            yield Label("Select a room", id="room-heading", markup=False)
            yield Static(
                "Create a room or accept an invitation.",
                id="room-state",
                markup=False,
            )
            with Horizontal(classes="room-controls", id="room-create-form"):
                yield Input(placeholder="Room name", id="room-name", max_length=80)
                yield Button("Create", id="room-create", variant="primary")
            with Horizontal(classes="room-controls", id="room-response"):
                yield Button("Accept", id="room-accept", variant="primary")
                yield Button("Decline", id="room-decline")
            with Collapsible(title="Members and settings", id="room-settings", collapsed=True):
                yield Static(id="room-members", markup=False)
                with Vertical(id="room-owner-controls"):
                    yield Select([], prompt="Choose a contact or member", id="room-person")
                    with Horizontal(classes="room-controls"):
                        yield Button("Invite", id="room-invite")
                        yield Button("Remove / revoke", id="room-remove")
                    with Horizontal(classes="room-controls"):
                        yield Input(placeholder="New room name", id="room-rename-input")
                        yield Button("Rename", id="room-rename")
                    yield Button("Close room", id="room-close", variant="error")
                yield Button("Leave room", id="room-leave")
            yield Static(id="room-feedback", markup=False)
            yield Button("Retry pending deliveries", id="room-retry")
            yield VerticalScroll(id="room-history")
            with Horizontal(classes="room-controls", id="room-composer-row"):
                yield Input(placeholder="Message this room…", id="room-composer")
                yield Button("Send", id="room-send", variant="primary")

    def on_mount(self) -> None:
        for selector in [
            "#room-response",
            "#room-settings",
            "#room-composer-row",
            "#room-retry",
        ]:
            self.query_one(selector).display = False
        self.set_interval(2, self._refresh_if_visible)

    async def activate(self) -> None:
        chat = self.chat
        try:
            self.service = await chat.room_service()
            chat._start_inbox_poll()
            await self.refresh_rooms()
        except (RoomError, OSError, sqlite3.Error) as exc:
            self.query_one("#room-feedback", Static).update(f"Could not open rooms: {exc}")

    async def _refresh_if_visible(self) -> None:
        if self.chat.is_on_screen and self.service is not None:
            try:
                await self.refresh_rooms()
            except (RoomError, OSError, sqlite3.Error) as exc:
                self.query_one("#room-feedback", Static).update(f"Could not refresh rooms: {exc}")

    def _label(self, pubkey: str) -> str:
        chat = self.chat
        if self.service is not None and pubkey == self.service.me:
            return "You"
        known = contacts(path=chat._contacts_path)
        return next(
            (item["username"] for item in known if item["pubkey"] == pubkey and item["username"]),
            pubkey[:12] + "…",
        )

    async def refresh_rooms(self) -> None:
        if self.service is None:
            return
        async with self.render_lock:
            rooms = await self.service.rooms()
            room = next((item for item in rooms if item["id"] == self.selected), None)
            history = await self.service.history(self.selected) if self.selected else []
            unresolved = await self.service.unresolved(self.selected) if self.selected else 0
            snapshot = repr((rooms, self.selected, history, unresolved, self.creating))
            if snapshot == self.last_snapshot:
                return
            self.last_snapshot = snapshot
            listing = self.chat.query_one("#rooms-list", ListView)
            await listing.clear()
            self.room_ids = [item["id"] for item in rooms]
            for item in rooms:
                suffix = " · invited" if item["status"] == "invited" else ""
                await listing.append(ListItem(Label(item["name"] + suffix, markup=False)))
            if self.display and self.selected in self.room_ids:
                listing.index = self.room_ids.index(self.selected)
            else:
                listing.index = None
            self._render_controls(room)
            self.query_one("#room-retry").display = unresolved > 0
            self.query_one("#room-retry", Button).label = f"Retry {unresolved} pending deliveries"
            scroll = self.query_one("#room-history", VerticalScroll)
            await scroll.remove_children()
            for message in history:
                await self._mount_message(scroll, message)
            if history:
                scroll.scroll_end(animate=False)

    async def _mount_message(self, scroll: VerticalScroll, message: dict) -> None:
        timestamp = datetime.fromtimestamp(message["timestamp"]).strftime("%b %d · %H:%M")
        content = Text(f"{self._label(message['author'])} · {timestamp}\n", style="bold")
        content.append(message["text"], style="not bold")
        failures = [item for item in message["deliveries"] if item["status"] == "failed"]
        if failures:
            content.append(
                f"\nNot published to {len(failures)} member(s). Retry available.",
                style="yellow",
            )
        if message["status"] == "stale":
            content.append("\nDelayed message from an older membership state.", style="yellow")
        mine = self.service is not None and message["author"] == self.service.me
        side = "mine" if mine else "theirs"
        await scroll.mount(
            Horizontal(
                Static(content, classes=f"room-line {side}"),
                classes=f"room-message {side}",
            )
        )

    def _render_controls(self, room: dict | None) -> None:
        active = bool(room and room["status"] == "active" and not room["conflict"])
        owner = bool(room and self.service and room["owner"] == self.service.me)
        self.query_one("#room-heading", Label).update(room["name"] if room else "Select a room")
        status = (
            "Membership conflict — sending disabled"
            if room and room["conflict"]
            else (
                f"{len(room['members'])} member{'s' if len(room['members']) != 1 else ''}"
                f" · {room['status']}"
            )
            if room
            else "Create a room or accept an invitation."
        )
        if room and room["status"] == "joining":
            status = "Waiting for the room owner to confirm your membership"
        self.query_one("#room-state", Static).update(status)
        self.query_one("#room-response").display = bool(room and room["status"] == "invited")
        self.query_one("#room-settings").display = room is not None
        self.query_one("#room-owner-controls").display = owner and active
        self.query_one("#room-leave").display = active and not owner
        self.query_one("#room-composer-row").display = active
        self.query_one("#room-create-form").display = self.creating
        if room:
            names = [
                self._label(member) + (" (owner)" if member == room["owner"] else "")
                for member in room["members"]
            ]
            names.extend(
                self._label(item["recipient"]) + " (invited)" for item in room["pending_invites"]
            )
            self.query_one("#room-members", Static).update("\n".join(names))
            self._contact_options(room)

    def _contact_options(self, room: dict) -> None:
        keys = {
            item["pubkey"] for item in contacts(path=self.chat._contacts_path) if item["pubkey"]
        }
        keys.update(room["members"])
        keys.update(item["recipient"] for item in room["pending_invites"])
        keys.discard(room["owner"])
        selector = self.query_one("#room-person", Select)
        previous = selector.value
        selector.set_options([(self._label(pubkey), pubkey) for pubkey in sorted(keys)])
        if previous is not Select.BLANK and previous in keys:
            selector.value = previous

    async def select_room(self, event: ListView.Selected) -> None:
        event.stop()
        if event.index is None or event.index >= len(self.room_ids):
            return
        composer = self.query_one("#room-composer", Input)
        if self.selected:
            self.drafts[self.selected] = composer.value
        self.chat.show_room(True)
        self.selected = self.room_ids[event.index]
        self.creating = False
        composer.value = self.drafts.get(self.selected, "")
        await self.refresh_rooms()
        composer.focus()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        action = (event.button.id or "").removeprefix("room-")
        if action == "new":
            self.chat.show_room(True)
            await self.activate()
            self.creating = True
            await self.refresh_rooms()
            self.query_one("#room-name", Input).focus()
            return
        room_id = self.selected
        if action in {"close", "leave", "remove"}:
            selected = self.query_one("#room-person", Select).value
            value = str(selected) if selected is not Select.BLANK else ""

            def confirmed(yes: bool | None) -> None:
                if yes:
                    self.run_worker(self._perform(action, room_id, value))

            self.app.push_screen(RoomConfirm(f"{action.title()} for this room?"), confirmed)
            return
        self.run_worker(self._perform(action, room_id), group="room-ui")

    @on(Input.Submitted, "#room-composer")
    def send_on_enter(self) -> None:
        self.run_worker(self._perform("send", self.selected), group="room-ui")

    async def _perform(self, action: str, room_id: str | None, value: str = "") -> None:
        async with self.action_lock:
            await self._perform_action(action, room_id, value)

    async def _perform_action(self, action: str, room_id: str | None, value: str) -> None:
        try:
            if self.service is None:
                await self.activate()
            service = self.service
            if service is None:
                raise RoomError("storage_unavailable", "Room storage could not be opened")
            if action == "create":
                created = await service.create_room(self.query_one("#room-name", Input).value)
                composer = self.query_one("#room-composer", Input)
                if self.selected:
                    self.drafts[self.selected] = composer.value
                self.selected = created
                composer.value = ""
                self.query_one("#room-name", Input).value = ""
                self.creating = False
            elif action == "retry":
                await service.flush()
            elif room_id:
                await self._room_action(service, action, room_id, value)
            self.query_one("#room-feedback", Static).update("")
            await self.refresh_rooms()
        except (RoomError, OSError, sqlite3.Error) as exc:
            self.query_one("#room-feedback", Static).update(str(exc))

    async def _room_action(
        self, service: RoomService, action: str, room_id: str, value: str
    ) -> None:
        if action in {"accept", "decline"}:
            await service.respond(room_id, action == "accept")
        elif action == "invite":
            peer = self.query_one("#room-person", Select).value
            if peer is Select.BLANK:
                raise RoomError("invalid_payload", "Choose a contact first")
            await service.invite(room_id, str(peer))
        elif action == "send":
            composer = self.query_one("#room-composer", Input)
            body = composer.value
            await service.send(room_id, body)
            if self.selected == room_id and composer.value == body:
                composer.value = ""
        elif action == "leave":
            await service.leave(room_id)
        elif action in {"rename", "close", "remove"}:
            value = (
                self.query_one("#room-rename-input", Input).value if action == "rename" else value
            )
            await service.manage(room_id, action, value)
