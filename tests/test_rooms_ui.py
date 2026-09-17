"""Rooms can be managed through the TUI and the same local command service."""

import asyncio
from types import SimpleNamespace

import pytest
from textual.app import App, ComposeResult
from textual.pilot import Pilot
from textual.containers import VerticalScroll
from textual.widgets import Button, Collapsible, Input, Label

from toad.extensions.dega_panel import auth_store, chat_presence
from toad.extensions.dega_panel.chat import ChatView
from toad.extensions.dega_panel.rooms.commands import execute
from toad.extensions.dega_panel.rooms.view import RoomConfirm, RoomsView


class Host(App):
    def __init__(self, directory):
        super().__init__()
        self.directory = directory

    def compose(self) -> ComposeResult:
        chat = ChatView(
            SimpleNamespace(elements={}),
            offline=True,
            identity_path=self.directory / "identity.json",
            contacts_path=self.directory / "contacts.json",
        )
        chat._my_username = "tester"
        yield chat


async def settle_room_ui(pilot: Pilot) -> None:
    """Drain UI events and finite workers in the offline test host."""
    async with asyncio.timeout(30):
        await pilot.pause()
        await pilot.app.workers.wait_for_complete()
        await pilot.pause()


@pytest.mark.parametrize("width", [60, 106])
async def test_create_room_and_cancel_close(tmp_path, monkeypatch, width):
    monkeypatch.setattr(auth_store, "CANON_DIR", tmp_path)
    monkeypatch.setattr(chat_presence, "PRESENCE_FILE", tmp_path / "presence.json")
    app = Host(tmp_path)
    async with app.run_test(size=(width, 42)) as pilot:
        view = app.query_one(RoomsView)
        await settle_room_ui(pilot)
        assert await pilot.click("#room-new")
        await settle_room_ui(pilot)
        assert view.display
        view.query_one("#room-name", Input).value = "Launch team"
        assert await pilot.click("#room-create")
        await settle_room_ui(pilot)
        assert str(view.query_one("#room-heading", Label).render()) == "Launch team"
        assert view.query_one("#room-composer-row").display
        view.query_one("#room-composer", Input).value = "We are ready"
        await pilot.click("#room-send")
        await settle_room_ui(pilot)
        assert len(view.query(".room-line")) == 1
        mine = view.query_one(".room-line.mine")
        row = view.query_one(".room-message.mine")
        assert mine.region.right == row.content_region.right
        await view._mount_message(view.query_one("#room-history", VerticalScroll), {
            "author": "a" * 64, "timestamp": 1, "text": "Other member",
            "deliveries": [], "status": "received",
        })
        await pilot.pause()
        theirs = view.query_one(".room-line.theirs")
        other_row = view.query_one(".room-message.theirs")
        assert theirs.region.x == other_row.content_region.x
        assert mine.region.x > theirs.region.x
        assert view.query_one("#room-composer", Input).value == ""
        assert view.query_one("#room-send", Button).region.right <= width
        # A second room is independent and selectable through the same service.
        other = await execute(view.service, {"action": "create", "name": "Other team"})
        assert not (
            await execute(view.service, {"action": "history", "room_id": other["room_id"]})
        )["messages"]
        app.save_screenshot(str(tmp_path / f"rooms-{width}.svg"))
        assert not view.query_one("#room-create-form").display
        assert not view.query_one("#room-retry").display
        view.query_one("#room-settings", Collapsible).collapsed = False
        await settle_room_ui(pilot)
        await pilot.click("#room-close")
        await settle_room_ui(pilot)
        assert isinstance(app.screen, RoomConfirm)
        assert app.focused.id == "room-cancel"
        await pilot.press("escape")
        await settle_room_ui(pilot)
        assert view.query_one("#room-composer-row").display
        await pilot.click("#room-close")
        await settle_room_ui(pilot)
        await pilot.click("#room-confirm")
        await settle_room_ui(pilot)
        assert not view.query_one("#room-composer-row").display


async def test_socket_commands_use_same_room_service(tmp_path, monkeypatch):
    from toad.socket_controller import _dispatch

    monkeypatch.setattr(auth_store, "CANON_DIR", tmp_path)
    monkeypatch.setattr(chat_presence, "PRESENCE_FILE", tmp_path / "presence.json")
    app = Host(tmp_path)
    async with app.run_test() as pilot:
        view = app.query_one(RoomsView)
        await view.activate()
        app.query_one(ChatView).show_room(True)
        created = await _dispatch(app, {"cmd": "room", "action": "create", "name": "Agent room"})
        room_id = created["room_id"]
        await _dispatch(
            app,
            {
                "cmd": "room",
                "action": "send",
                "room_id": room_id,
                "text": "From the socket",
            },
        )
        view.selected = room_id
        await view.refresh_rooms()
        await settle_room_ui(pilot)
        assert str(view.query_one("#room-heading", Label).render()) == "Agent room"
        assert len(view.query(".room-line")) == 1
        error = await _dispatch(app, {"cmd": "room", "action": "respond", "accept": "yes"})
        assert "error" in error


async def test_room_drafts_do_not_follow_new_rooms(tmp_path, monkeypatch):
    monkeypatch.setattr(auth_store, "CANON_DIR", tmp_path)
    monkeypatch.setattr(chat_presence, "PRESENCE_FILE", tmp_path / "presence.json")
    app = Host(tmp_path)
    async with app.run_test() as pilot:
        view = app.query_one(RoomsView)
        await view.activate()
        app.query_one(ChatView).show_room(True)
        view.query_one("#room-name", Input).value = "First"
        await view._perform("create", None)
        first = view.selected
        view.query_one("#room-composer", Input).value = "Private draft"
        view.query_one("#room-name", Input).value = "Second"
        await view._perform("create", first)
        assert view.query_one("#room-composer", Input).value == ""
        assert view.drafts[first] == "Private draft"
        from textual.widgets import ListView

        listing = app.query_one("#rooms-list", ListView)
        listing.index = view.room_ids.index(first)
        listing.focus()
        await pilot.press("enter")
        await settle_room_ui(pilot)
        assert view.query_one("#room-composer", Input).value == "Private draft"


@pytest.mark.parametrize("width", [60, 106])
async def test_shared_sidebar_scrolls_and_switches_conversations(tmp_path, monkeypatch, width):
    from textual.widgets import ListView
    from toad.extensions.dega_panel.chat_contact import remember_contact

    monkeypatch.setattr(auth_store, "CANON_DIR", tmp_path)
    monkeypatch.setattr(chat_presence, "PRESENCE_FILE", tmp_path / "presence.json")
    for index in range(30):
        remember_contact(
            f"wallet-{index}",
            username=f"Friend {index:02}",
            pubkey=index.to_bytes(32, "big"),
            path=tmp_path / "contacts.json",
        )
    app = Host(tmp_path)
    async with app.run_test(size=(width, 42)) as pilot:
        chat = app.query_one(ChatView)
        rooms = app.query_one(RoomsView)
        chat._my_username = "Me"
        await chat.rebuild()
        await rooms.activate()
        for index in range(20):
            await rooms.service.create_room(f"Team {index:02}")
        await rooms.refresh_rooms()
        await settle_room_ui(pilot)
        contacts = chat.query_one("#contacts", ListView)
        listing = chat.query_one("#rooms-list", ListView)
        assert len(contacts.children) == 30
        assert contacts.max_scroll_y > 0
        assert listing.max_scroll_y > 0
        contacts.index = 29
        contacts.focus()
        await pilot.press("enter")
        await settle_room_ui(pilot)
        assert chat._selected_contact["username"] == "Friend 29"
        chat.query_one("#composer", Input).value = "DM draft"
        listing.index = 19
        listing.focus()
        await pilot.press("enter")
        await settle_room_ui(pilot)
        assert rooms.display and not chat.query_one("#conv-col").display
        assert not chat.query(".selected-contact")
        assert str(rooms.query_one("#room-heading", Label).render()) == "Team 19"
        rooms.query_one("#room-composer", Input).value = "Room draft"
        contacts.index = 29
        contacts.focus()
        await pilot.press("enter")
        await settle_room_ui(pilot)
        assert not rooms.display and chat.query_one("#conv-col").display
        assert chat.query_one("#composer", Input).value == "DM draft"
        assert listing.index is None
        listing.index = 19
        listing.focus()
        await pilot.press("enter")
        await settle_room_ui(pilot)
        assert rooms.query_one("#room-composer", Input).value == "Room draft"
        for section in ["contacts-section", "rooms-section"]:
            group = chat.query_one(f"#{section}", Collapsible)
            group.collapsed = True
            await settle_room_ui(pilot)
            assert group.collapsed
            group.collapsed = False
        await settle_room_ui(pilot)
        assert rooms.query_one("#room-composer").region.bottom <= 42
        app.save_screenshot(str(tmp_path / f"shared-chat-{width}.svg"))


@pytest.mark.parametrize("width", [60, 106])
async def test_add_contact_is_available_while_viewing_room(tmp_path, monkeypatch, width):
    monkeypatch.setattr(auth_store, "CANON_DIR", tmp_path)
    monkeypatch.setattr(chat_presence, "PRESENCE_FILE", tmp_path / "presence.json")
    app = Host(tmp_path)
    async with app.run_test(size=(width, 42)) as pilot:
        chat = app.query_one(ChatView)
        chat._my_username = "Me"
        await chat.rebuild()
        await settle_room_ui(pilot)
        await pilot.click("#room-new")
        await settle_room_ui(pilot)
        group = chat.query_one("#add-contact-section", Collapsible)
        group.collapsed = False
        await settle_room_ui(pilot)
        field = chat.query_one("#contact-name", Input)
        field.focus()
        await pilot.press("m", "a", "r", "i", "a")
        await settle_room_ui(pilot)
        assert field.value == "maria"
        assert chat.query_one(RoomsView).display
        assert not chat.query_one("#conv-col").display
        assert chat.query_one("#btn-add-contact").is_on_screen
        app.save_screenshot(str(tmp_path / f"add-contact-{width}.svg"))


async def test_room_ui_waits_for_delayed_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(auth_store, "CANON_DIR", tmp_path)
    monkeypatch.setattr(chat_presence, "PRESENCE_FILE", tmp_path / "presence.json")
    app = Host(tmp_path)
    async with app.run_test(size=(106, 42)) as pilot:
        await settle_room_ui(pilot)
        assert await pilot.click("#room-new")
        await settle_room_ui(pilot)
        view = app.query_one(RoomsView)
        started, release = asyncio.Event(), asyncio.Event()
        write = view.service.journal.write

        async def held_write(*args, **kwargs):
            started.set()
            await release.wait()
            return await write(*args, **kwargs)

        monkeypatch.setattr(view.service.journal, "write", held_write)
        view.query_one("#room-name", Input).value = "Delayed room"
        assert await pilot.click("#room-create")
        async with asyncio.timeout(30):
            await started.wait()
        waiting = asyncio.create_task(settle_room_ui(pilot))
        try:
            await pilot.pause()
            assert not waiting.done()
            assert view.selected is None
        finally:
            release.set()
            await waiting
        assert str(view.query_one("#room-heading", Label).render()) == "Delayed room"
        assert view.query_one("#room-composer-row").display
