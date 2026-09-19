#!/usr/bin/env python3
"""Run the actual DEGA widgets with disposable fixtures and no network access."""

from __future__ import annotations

# Canon imports must follow the temporary HOME setup to isolate user state.
# ruff: noqa: E402

import argparse
import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

# Resolve source before replacing HOME. Never load an installed Canon package.
START_DIRECTORY = Path.cwd()
SOURCE = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE))
SANDBOX = tempfile.TemporaryDirectory(prefix="canon-dega-preview-")
for name in tuple(os.environ):
    if name.startswith(("DEGA_", "CANON_", "WALLET_", "XDG_")):
        os.environ.pop(name)
os.environ.pop("NO_COLOR", None)
os.environ.update(HOME=SANDBOX.name, DEGA_CHAT_BACKEND="simulated", TERM="xterm-256color", FORCE_COLOR="1")
os.chdir(SANDBOX.name)


def deny_external_actions(event: str, args: tuple) -> None:
    """Stop networking and process launches even if a fixture boundary is missed."""
    if event in {
        "socket.connect",
        "socket.getaddrinfo",
        "subprocess.Popen",
        "os.system",
    }:
        raise RuntimeError(f"DEMO preview blocks external action: {event}")


from textual.app import App, ComposeResult
from textual.widgets import Button, Collapsible, Footer, Input, Static, TabbedContent
from toad.extensions.dega_panel import auth_store, chat_contact, utility
from toad.extensions.dega_panel.auth_store import AuthState, Session
from toad.extensions.dega_panel.chat import ChatView
from toad.extensions.dega_panel.chat_protocol import (
    OfflineChatNode,
    make_node,
)
from toad.extensions.dega_panel.pane import DegaPane
from toad.extensions.dega_panel.rooms.service import RoomService
from toad.extensions.dega_panel.rooms.view import RoomsView

sys.addaudithook(deny_external_actions)

STATE = AuthState(
    session=Session("demo-only", "demo", "carlos@example.test", "Carlos Demo"),
    elements={"Silver Fire": 3, "Golden Water": 2, "Obsidian Earth": 1},
    total_elements=6,
)


class FixtureClient:
    """Replace the device flow and Elements API with local fixture responses."""

    base_url = "https://preview.invalid"

    async def request_code(self):
        return {
            "device_code": "demo",
            "user_code": "DEMO-ONLY",
            "verification_uri": "/demo",
            "expires_in": 60,
            "interval": 1,
        }

    async def poll_token(self, *_args, **_kwargs):
        await asyncio.sleep(0.5)
        return {
            "status": "approved",
            "session_token": "demo-only",
            "user": {"id": "demo", "email": "carlos@example.test"},
        }

    async def fetch_elements(self, _email):
        return {
            "user": {"email": "carlos@example.test", "addresses": []},
            "totalElements": 6,
            "aggregatedElements": STATE.elements,
            "elementCount": {},
        }


async def eligibility(_key: str) -> dict:
    return {"state": "active" if auth_store.load_auth().is_logged_in else "unavailable"}


def fixture_highlight(self, event) -> None:
    """Serve access state synchronously instead of scheduling backend workers."""
    if isinstance(event.item, utility.BuildRow):
        self._selected = event.item.build.key
        self._access[self._selected] = {
            "state": "active" if auth_store.load_auth().is_logged_in else "unavailable"
        }
        self.refresh_detail()


async def blocked_strategy(self, *_args, **_kwargs):
    self.notify("DEMO: activation, installation and execution are disabled")
    return False


ORIGINAL_DELIVER = OfflineChatNode.deliver_to
ORIGINAL_ROOM_SEND = RoomService.send


async def delayed_direct(self, *args, **kwargs):
    await asyncio.sleep(1)
    return await ORIGINAL_DELIVER(self, *args, **kwargs)


async def delayed_room(self, *args, **kwargs):
    await asyncio.sleep(1)
    return await ORIGINAL_ROOM_SEND(self, *args, **kwargs)


class Preview(App):
    """An interactive host for production widgets; all state is disposable."""

    CSS = """
    Screen { overflow: hidden; }
    #demo-banner { height: auto; background: $warning; color: $background; padding: 0 1; }
    DegaPane { height: 1fr; }
    """
    BINDINGS: ClassVar[list] = [("ctrl+q", "quit", "Exit preview")]

    def compose(self) -> ComposeResult:
        yield Static(
            "DEMO · fixture data · no external actions",
            id="demo-banner",
        )
        yield DegaPane(client=FixtureClient())
        yield Footer()

    async def on_mount(self) -> None:
        chat = self.query_one(ChatView)
        peer = make_node(offline=True)
        registry = chat._registry
        registry.open_node("carlos", nostr_pubkey=chat._me.pubkey)
        registry._sim.open_node(
            "maria", "0xdemo", nostr_pubkey=bytes.fromhex(peer.pubkey)
        )
        chat_contact.add_my_node("carlos")
        chat_contact.remember_contact(
            "0xdemo", username="maria", pubkey=bytes.fromhex(peer.pubkey)
        )
        chat._my_username = "carlos"
        chat._my_nodes = ["carlos"]
        chat._selected_contact = chat_contact.contacts()[0]
        chat._registration = registry.registration_status()
        chat._sent = [
            {
                "text": "Ready to review the strategy?",
                "time": "10:30",
                "timestamp": time.time(),
                "to": peer.pubkey,
                "status": "",
            }
        ]
        chat._received = [
            {
                "text": "Yes, let’s check the dry-run results.",
                "time": "10:31",
                "timestamp": time.time(),
                "from": peer.pubkey,
                "event_id": "fixture",
            }
        ]
        service = await chat.room_service()
        room_id = await service.create_room("Strategy review")
        await ORIGINAL_ROOM_SEND(service, room_id, "Welcome to the review room.")
        rooms = self.query_one(RoomsView)
        rooms.selected = room_id
        rooms.creating = False
        await chat.rebuild()
        self.ready = True


async def screenshots(directory: Path) -> None:
    """Export real widget layouts and exercise both delayed message composers."""
    directory.mkdir(parents=True, exist_ok=True)
    for width, height in ((100, 35), (60, 25)):
        auth_store.save_auth(STATE)
        app = Preview()
        async with app.run_test(size=(width, height)) as pilot:
            for _ in range(8):
                await pilot.pause()
            app.save_screenshot(str(directory / f"strategies-{width}.svg"))
            pane = app.query_one(DegaPane)
            tabs = pane.query_one("#dega-subtabs", TabbedContent)
            tabs_y = tabs.region.y
            pane.action_toggle_tab()
            await pilot.pause()
            chat = app.query_one(ChatView)
            await chat.ensure_chat_ready()
            chat.show_room(False)
            await chat.rebuild()
            await pilot.pause()
            assert tabs.region.y == tabs_y, "Tabs must not shift when opening Chat"
            app.save_screenshot(str(directory / f"chat-{width}.svg"))
            chat.query_one("#contact-new", Button).press()
            await pilot.pause()
            contact = chat.query_one("#contact-name", Input)
            assert not chat.query_one("#conv-col").display
            assert not chat.query_one(RoomsView).display
            assert contact.region.width > 20
            app.save_screenshot(str(directory / f"add-contact-{width}.svg"))
            chat.query_one("#contact-cancel", Button).press()
            await pilot.pause()
            assert not chat.query_one("#add-contact-section").display
            composer = chat.query_one("#composer", Input)
            assert composer.region.bottom < height, "DM composer must remain visible"
            composer.value = "Fixture send"
            task = asyncio.create_task(chat._send_message())
            await asyncio.sleep(0.1)
            assert composer.value == "" and chat._sending
            await task
            assert not chat._sending
            chat.show_room(True)
            rooms = app.query_one(RoomsView)
            await rooms.activate()
            await rooms.refresh_rooms()
            await pilot.pause()
            app.save_screenshot(str(directory / f"room-{width}.svg"))
            settings = rooms.query_one("#room-settings", Collapsible)
            settings.collapsed = False
            await pilot.pause()
            app.save_screenshot(str(directory / f"room-settings-{width}.svg"))
            settings.collapsed = True
            await pilot.pause()
            room_input = rooms.query_one("#room-composer", Input)
            assert room_input.region.bottom < height, "Room composer must remain visible"
            chat.query_one("#room-new", Button).press()
            await pilot.pause()
            assert not rooms.query_one("#room-history").display
            assert not rooms.query_one("#room-composer-row").display
            app.save_screenshot(str(directory / f"new-room-{width}.svg"))
            rooms.query_one("#room-create-cancel", Button).press()
            await pilot.pause()
            assert rooms.display and not rooms.creating
            room_input.value = "Fixture room send"
            rooms._start_send()
            await asyncio.sleep(0.1)
            assert room_input.value == "" and rooms.pending_send is not None
            await asyncio.sleep(1.2)
            await pilot.pause()
            assert rooms.pending_send is None
            pane._confirm_logout(True)
            await pilot.pause()
            assert not pane.auth.is_logged_in
            pane.action_login()
            await asyncio.sleep(0.8)
            await pilot.pause()
            assert pane.auth.is_logged_in
            await app.workers.wait_for_complete()
            await pilot.pause()
            app.set_focus(None)
            await pilot.pause()
    print(
        f"Exported twelve SVG previews; direct/room sends and login/logout passed: {directory}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--screenshots", type=Path, metavar="DIRECTORY")
    args = parser.parse_args()
    auth_store.save_auth(STATE)
    with (
        patch.object(utility, "backend_eligibility", eligibility),
        patch.object(
            utility.UtilityView, "on_list_view_highlighted", fixture_highlight
        ),
        patch.object(utility.UtilityView, "_activate", blocked_strategy),
        patch.object(utility.UtilityView, "_toggle", blocked_strategy),
        patch.object(utility.UtilityView, "_run", blocked_strategy),
        patch.object(utility.UtilityView, "_stop", blocked_strategy),
        patch.object(OfflineChatNode, "deliver_to", delayed_direct),
        patch.object(RoomService, "send", delayed_room),
    ):
        if args.screenshots:
            asyncio.run(screenshots((START_DIRECTORY / args.screenshots).resolve()))
        else:
            Preview().run()


if __name__ == "__main__":
    main()
