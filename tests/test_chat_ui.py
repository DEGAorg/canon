from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from eth_account import Account
from textual.app import App, ComposeResult
from textual.widgets import Button, Collapsible, Input, Label, ListView, Static

from toad.extensions.dega_panel import auth_store, chat_identity, chat_presence, registry_client
from toad.extensions.dega_panel.chat import ChatView
from toad.extensions.dega_panel.chat_contact import remember_contact
from toad.extensions.dega_panel.chat_identity import configured_wallet_address


@pytest.fixture
def wallet_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(auth_store, 'CANON_DIR', tmp_path)
    monkeypatch.setattr(chat_identity, 'CANON_DIR', tmp_path)
    monkeypatch.setattr(registry_client, '_DEGA_CHAT_ENV', tmp_path / 'dega-chat.env')
    monkeypatch.setattr(chat_presence, 'PRESENCE_FILE', tmp_path / 'presence.json')
    monkeypatch.delenv('DEGA_CHAT_PK', raising=False)
    return tmp_path


@pytest.mark.parametrize('source', ['file', 'environment', 'wallet'])
def test_wallet_address_available_without_registration(wallet_dir, monkeypatch, source):
    key = '01' * 32
    if source == 'file':
        (wallet_dir / 'dega-chat.env').write_text('DEGA_CHAT_PK=' + key)
        monkeypatch.setenv('DEGA_CHAT_PK', '02' * 32)
    elif source == 'environment':
        monkeypatch.setenv('DEGA_CHAT_PK', key)
        (wallet_dir / 'wallet.env').write_text('WALLET_PRIVATE_KEY=' + '02' * 32)
    else:
        (wallet_dir / 'wallet.env').write_text('WALLET_PRIVATE_KEY=' + key)
    assert configured_wallet_address() == Account.from_key(key).address


def test_nostr_identity_does_not_imply_wallet_is_configured(wallet_dir):
    (wallet_dir / 'chat-identity.json').write_text('{"secret_key_nsec":"saved-chat-key"}')
    assert configured_wallet_address() is None


def test_invalid_wallet_error_does_not_disclose_key(wallet_dir):
    (wallet_dir / 'wallet.env').write_text('WALLET_PRIVATE_KEY=invalid-secret')
    with pytest.raises(ValueError, match='Invalid chat wallet key') as error:
        configured_wallet_address()
    assert 'invalid-secret' not in str(error.value)


class ChatApp(App):
    def __init__(self, directory):
        super().__init__()
        self.directory = directory

    def compose(self) -> ComposeResult:
        yield ChatView(
            SimpleNamespace(elements={}), offline=True,
            identity_path=self.directory / 'identity.json',
            contacts_path=self.directory / 'contacts.json',
        )


@pytest.mark.asyncio
@pytest.mark.parametrize('configured', [False, True])
async def test_profile_visible_before_registration_even_when_registry_unavailable(
    wallet_dir, configured
):
    key = '01' * 32
    if configured:
        (wallet_dir / 'wallet.env').write_text('WALLET_PRIVATE_KEY=' + key)
    app = ChatApp(wallet_dir)
    async with app.run_test() as pilot:
        view = app.query_one(ChatView)
        view._offline = False
        view._registry = None
        view._registry_error = 'RPC unavailable'
        await view._render_profile()
        await pilot.pause()
        profile = str(view.query_one('#profile', Static).render())
        assert 'Wallet' in profile
        assert 'Unable to check registry' in profile
        assert (Account.from_key(key).address if configured else 'Not configured') in profile
        assert key not in profile
        assert view._me.short_id() not in view._header()
        view._offline = True


@pytest.mark.asyncio
@pytest.mark.parametrize('width', [60, 100])
async def test_chat_actions_are_grouped_with_inputs(wallet_dir, width):
    app = ChatApp(wallet_dir)
    async with app.run_test(size=(width, 38)) as pilot:
        view = app.query_one(ChatView)
        view._my_username = 'tester'
        view._my_nodes = ['tester']
        await view.rebuild()
        await pilot.pause()
        disclosure = view.query_one("#add-contact-section")
        assert not disclosure.display
        view.query_one("#contact-new", Button).press()
        await pilot.pause()
        invite = view.query_one('#contact-name', Input)
        send = view.query_one('#composer', Input)
        invite_button = view.query_one('#btn-add-contact', Button)
        send_button = view.query_one('#btn-send', Button)
        assert invite.parent is invite_button.parent.parent
        assert app.focused is invite
        assert send.parent is send_button.parent
        assert invite_button.region.y >= invite.region.bottom
        assert not view.query_one("#conv-col").display
        assert invite.region.width > 20
        assert invite_button.region.width < invite.region.width
        send.value = "Keep my draft"
        view.query_one("#contact-cancel", Button).press()
        await pilot.pause()
        assert view.query_one("#conv-col").display
        assert send.value == "Keep my draft"
        assert send_button.region.x > send.region.x
        assert send_button.region.right <= width
        assert send_button.region.bottom <= 38
        assert str(view.query_one('.composer-hint', Static).render()) == 'Enter send · Tab next'
        assert 'maria' not in invite.placeholder
        assert not invite.value
        assert not view.query_one('#open-node-block').display
        assert view.query_one('#btn-clear-state').parent.id == 'conversation-toolbar'
        assert view.query_one('#profile').display


@pytest.mark.asyncio
async def test_contacts_do_not_claim_online_status(wallet_dir):
    remember_contact('0x01', username='known', pubkey=b'\x01' * 32,
                     path=wallet_dir / 'contacts.json')
    remember_contact('0x02', username='incomplete', path=wallet_dir / 'contacts.json')
    app = ChatApp(wallet_dir)
    async with app.run_test() as pilot:
        view = app.query_one(ChatView)
        view._my_username = 'tester'
        await view._render_contacts()
        await pilot.pause()
        assert view.query_one('#contacts-section', Collapsible).title == 'Contacts · 2'
        labels = [str(label.render()) for label in view.query('#contacts Static')]
        assert all('●' not in label for label in labels)
        assert all('key unavailable' not in label for label in labels)
        indicators = list(view.query('.contact-key-help'))
        assert len(indicators) == 1
        indicator = indicators[0]
        assert indicator.content_region.height == 1
        assert indicator.content_region.width >= 1
        assert indicator.tooltip == 'Chat key unavailable'
        assert str(indicator.label) == '!'
        notify = Mock()
        view.notify = notify
        indicator.focus()
        await pilot.press('enter')
        assert 'chat key is unavailable' in notify.call_args.args[0]
        view._selected_contact = {'username': 'incomplete', 'pubkey': ''}
        deliver = AsyncMock()
        view._me.deliver_to = deliver
        view.query_one('#composer', Input).value = 'Do not broadcast this'
        await view._send_message()
        deliver.assert_not_called()
        assert not view._sent


@pytest.mark.asyncio
async def test_contact_without_chat_key_is_not_added(wallet_dir, monkeypatch):
    app = ChatApp(wallet_dir)
    async with app.run_test():
        view = app.query_one(ChatView)
        view._my_username = 'tester'
        view.query_one('#contact-name', Input).value = 'incomplete'
        monkeypatch.setattr(view._registry, 'resolve_member', Mock(return_value={
            'username': 'incomplete', 'wallet': '0x02', 'pubkey': b''
        }))
        invite = Mock()
        monkeypatch.setattr(view._registry, 'invite', invite)
        await view._add_contact()
        invite.assert_not_called()


@pytest.mark.asyncio
async def test_presence_is_explicit_opt_in_and_only_shared_while_visible(wallet_dir):
    from textual.widgets import Checkbox

    app = ChatApp(wallet_dir)
    async with app.run_test(size=(100, 38)) as pilot:
        view = app.query_one(ChatView)
        toggle = view.query_one('#presence-sharing', Checkbox)
        assert not toggle.value
        assert not view._can_share_presence()
        view._my_username = 'tester'
        await view.rebuild()
        await pilot.pause()
        details = view.query_one('#account-details', Collapsible)
        assert details.collapsed
        details.collapsed = False
        await pilot.pause()
        assert view.query_one('#presence-disclosure').is_on_screen
        assert await pilot.click(toggle)
        assert chat_presence.sharing_enabled(view._me.pubkey)
        view._offline = False
        assert view._can_share_presence()
        refresh = AsyncMock(return_value={})
        view._presence.refresh = refresh
        view.display = False
        await pilot.pause()
        assert not view._can_share_presence()
        await view._refresh_presence()
        refresh.assert_not_called()
        view.display = True
        await pilot.pause()
        view._my_username = None
        await view._refresh_presence()
        refresh.assert_not_called()
        assert not view._can_share_presence()
        view._my_username = 'tester'
        assert await pilot.click(toggle)
        assert not chat_presence.sharing_enabled(view._me.pubkey)
        assert not view._can_share_presence()
        view._offline = True


@pytest.mark.asyncio
async def test_online_indicator_expires_without_claiming_offline(wallet_dir):
    import time

    key = '02' * 32
    remember_contact('0x02', username='recipient', pubkey=bytes.fromhex(key),
                     path=wallet_dir / 'contacts.json')
    app = ChatApp(wallet_dir)
    async with app.run_test() as pilot:
        view = app.query_one(ChatView)
        view._my_username = 'tester'
        view._selected_contact = {'username': 'recipient', 'pubkey': key}
        await view.rebuild()
        await pilot.pause()
        view._online_until = {key: int(time.time()) + 90}
        view._update_presence_labels()
        assert '●' in str(view.query_one('.contact-presence', Static).render())
        assert 'Online' in str(view.query_one('#conversation-title', Label).render())
        view._online_until = {key: int(time.time()) - 1}
        view._update_presence_labels()
        assert '●' not in str(view.query_one('.contact-presence', Static).render())
        recipient = str(view.query_one('#conversation-title', Label).render())
        assert 'Online' not in recipient
        assert 'Offline' not in recipient


@pytest.mark.asyncio
async def test_conversation_orders_full_dates_and_seconds(wallet_dir):
    from datetime import datetime

    app = ChatApp(wallet_dir)
    async with app.run_test(size=(100, 38)):
        view = app.query_one(ChatView)
        view._my_username = "tester"
        view._selected_contact = {"pubkey": "peer"}
        older = datetime(2026, 9, 15, 23, 59, 50).timestamp()
        newer = datetime(2026, 9, 16, 0, 1, 10).timestamp()
        view._sent = [{
            "text": "third [bold]literal[/bold]", "time": "00:01", "timestamp": newer + 1, "to": "peer",
        }]
        view._received = [
            {"text": "second", "time": "00:01", "timestamp": newer, "from": "peer"},
            {"text": "first", "time": "23:59", "timestamp": older, "from": "peer"},
        ]
        await view._render_conversation()
        bubbles = [str(widget.render()) for widget in view.query(".bubble")]
        assert [text.split("\n")[-1] for text in bubbles] == [
            "first", "second", "third [bold]literal[/bold]",
        ]
        assert [str(widget.render()) for widget in view.query(".day-divider")] == [
            "Sep 15, 2026", "Sep 16, 2026",
        ]


@pytest.mark.asyncio
async def test_inbox_keeps_epoch_and_handles_invalid_dates(wallet_dir, monkeypatch):
    import asyncio

    app = ChatApp(wallet_dir)
    async with app.run_test():
        view = app.query_one(ChatView)
        view._my_username = "tester"
        view._me.fetch_dms = AsyncMock(return_value=[
            {"event_id": "valid", "text": "hello", "time": "1789579001"},
            {"event_id": "missing", "text": "no date"},
            {"event_id": "invalid", "text": "bad date", "time": "invalid"},
            {"event_id": "overflow", "text": "huge date", "time": "9" * 100},
        ])
        view.rebuild = AsyncMock()
        with monkeypatch.context() as scoped:
            scoped.setattr("toad.extensions.dega_panel.chat.asyncio.sleep",
                           AsyncMock(side_effect=asyncio.CancelledError))
            with pytest.raises(asyncio.CancelledError):
                await view._inbox_poll_loop()
        assert [message["timestamp"] for message in view._received] == [1789579001, 0, 0, 0]


@pytest.mark.asyncio
@pytest.mark.parametrize("width", [60, 100])
async def test_selected_contact_stays_marked_while_composing_and_after_refresh(wallet_dir, width):
    remember_contact("0x01", username="maria", pubkey=b"\x01" * 32,
                     path=wallet_dir / "contacts.json")
    remember_contact("0x02", username="alex", pubkey=b"\x02" * 32,
                     path=wallet_dir / "contacts.json")
    app = ChatApp(wallet_dir)
    async with app.run_test(size=(width, 38)) as pilot:
        view = app.query_one(ChatView)
        view._my_username = "tester"
        await view.rebuild()
        await pilot.pause()
        title = view.query_one("#conversation-title", Label)
        assert str(title.render()) == "Conversation"
        assert not view.query("#recipient-status")
        rows = list(view.query(".contact-row"))
        await pilot.click(rows[0])
        await pilot.pause()
        assert str(title.render()) == "maria"
        assert rows[0].has_class("selected-contact")
        assert not rows[1].has_class("selected-contact")
        assert app.focused.id == "composer"
        await pilot.press("h", "i")
        assert view.query_one("#composer", Input).value == "hi"
        await view._render_contacts()
        await pilot.pause()
        rows = list(view.query(".contact-row"))
        assert rows[0].has_class("selected-contact")
        contacts_list = view.query_one("#contacts", ListView)
        contacts_list.focus()
        contacts_list.index = 1
        await pilot.press("enter")
        await pilot.pause()
        assert str(title.render()) == "alex"
        assert rows[1].has_class("selected-contact")
        assert not rows[0].has_class("selected-contact")
        assert app.focused.id == "composer"


@pytest.mark.asyncio
async def test_private_history_switching_drafts_and_clear(wallet_dir):
    for name, key in [("maria", "01"), ("alex", "02")]:
        remember_contact("0x" + key, username=name, pubkey=bytes.fromhex(key * 32),
                         path=wallet_dir / "contacts.json")
    app = ChatApp(wallet_dir)
    async with app.run_test(size=(100, 38)) as pilot:
        view = app.query_one(ChatView)
        view._my_username = "tester"
        view._received = [
            {"from": "01" * 32, "text": "from maria", "time": "12:00", "timestamp": 100},
            {"from": "02" * 32, "text": "from alex", "time": "12:00", "timestamp": 100},
        ]
        view._sent = [
            {"to": "01" * 32, "text": "to maria", "time": "12:01", "timestamp": 101},
            {"to": "02" * 32, "text": "to alex", "time": "12:01", "timestamp": 101},
        ]
        await view.rebuild()
        await pilot.pause()
        assert not view.query(".bubble")
        assert view.query_one("#btn-send", Button).disabled
        rows = list(view.query(".contact-row"))
        await pilot.click(rows[0])
        await pilot.pause()
        assert [str(w.render()).split("\n")[-1] for w in view.query(".bubble")] == [
            "from maria", "to maria",
        ]
        view.query_one("#composer", Input).value = "draft for maria"
        await pilot.click(rows[1])
        await pilot.pause()
        assert view.query_one("#composer", Input).value == ""
        assert [str(w.render()).split("\n")[-1] for w in view.query(".bubble")] == [
            "from alex", "to alex",
        ]
        await view._clear_state()
        await view.rebuild()
        await pilot.pause()
        assert not view.query(".bubble")
        rows = list(view.query(".contact-row"))
        await pilot.click(rows[0])
        await pilot.pause()
        assert len(view.query(".bubble")) == 2
        assert view.query_one("#composer", Input).value == "draft for maria"


@pytest.mark.asyncio
async def test_send_requires_one_recipient_and_preserves_failed_draft(wallet_dir):
    app = ChatApp(wallet_dir)
    async with app.run_test():
        view = app.query_one(ChatView)
        view._my_username = "tester"
        view._offline = False
        send = AsyncMock(return_value="test-sent-event")
        view._me.send_encrypted = send
        composer = view.query_one("#composer", Input)
        composer.value = "private message"
        await view._send_message()
        send.assert_not_called()
        view._selected_contact = {"pubkey": "01" * 32}
        send.side_effect = RuntimeError("relay unavailable")
        await view._send_message()
        assert composer.value == "private message"
        assert not view._sent
        send.reset_mock(side_effect=True)
        await view._send_message()
        send.assert_awaited_once_with("01" * 32, "private message")
        assert view._sent[0]["to"] == "01" * 32
        assert composer.value == ""
        view._offline = True


@pytest.mark.asyncio
async def test_switching_contacts_during_send_keeps_recipient_and_draft(wallet_dir):
    import asyncio

    app = ChatApp(wallet_dir)
    async with app.run_test():
        view = app.query_one(ChatView)
        view._my_username = "tester"
        view._offline = False
        started, finish = asyncio.Event(), asyncio.Event()

        async def delayed_send(recipient, text):
            assert recipient == "01" * 32
            assert text == "for maria"
            started.set()
            await finish.wait()
            return "test-delayed-event"

        view._me.send_encrypted = delayed_send
        view._selected_contact = {"pubkey": "01" * 32}
        composer = view.query_one("#composer", Input)
        composer.value = "for maria"
        pending = asyncio.create_task(view._send_message())
        await started.wait()
        view._selected_contact = {"pubkey": "02" * 32}
        composer.value = "draft for alex"
        finish.set()
        await pending
        assert composer.value == "draft for alex"
        assert view._sent[0]["to"] == "01" * 32
        assert not view.query(".bubble")
        view._offline = True


@pytest.mark.asyncio
async def test_unregistered_sender_history_is_accessible_without_mislabeling(wallet_dir):
    from toad.extensions.dega_panel.chat_contact import contacts

    registered = bytes(range(32))
    actual = "7c" * 32
    remember_contact("0x01", username="e2etest", pubkey=registered,
                     path=wallet_dir / "contacts.json")
    app = ChatApp(wallet_dir)
    async with app.run_test(size=(100, 38)) as pilot:
        view = app.query_one(ChatView)
        view._my_username = "tester"
        await view._remember_incoming_sender(actual)
        await view._remember_incoming_sender(actual)
        known = contacts(path=wallet_dir / "contacts.json")
        assert len(known) == 2
        assert known[0]["pubkey"] == registered.hex()
        assert known[1]["pubkey"] == actual
        assert known[1]["username"] == ""
        view._received = [
            {"from": actual, "text": "older message", "time": "12:00", "timestamp": 100},
        ]
        await view.rebuild()
        await pilot.pause()
        rows = list(view.query(".contact-row"))
        await pilot.click(rows[0])
        await pilot.pause()
        assert not view.query(".bubble")
        await pilot.click(rows[1])
        await pilot.pause()
        assert "older message" in str(view.query_one(".bubble", Static).render())
        assert "e2etest" not in str(view.query_one("#conversation-title", Label).render())


@pytest.mark.asyncio
async def test_add_contact_is_local_and_never_invites_on_chain(wallet_dir, monkeypatch):
    from toad.extensions.dega_panel.chat_contact import contacts

    app = ChatApp(wallet_dir)
    async with app.run_test():
        view = app.query_one(ChatView)
        view._my_username = "tester"
        resolve = Mock(return_value={
            "username": "maria", "wallet": "0x01", "pubkey": b"\x01" * 32,
        })
        invite = Mock(side_effect=AssertionError("DM contacts must not write to the registry"))
        monkeypatch.setattr(view._registry, "resolve_member", resolve)
        monkeypatch.setattr(view._registry, "invite", invite)
        for _ in range(2):
            view.query_one("#contact-name", Input).value = "maria.dega"
            await view._add_contact()
        assert len(contacts(path=wallet_dir / "contacts.json")) == 1
        assert contacts(path=wallet_dir / "contacts.json")[0]["pubkey"] == "01" * 32
        assert view.query_one("#contact-name", Input).value == ""
        invite.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["unknown", "network", "storage"])
async def test_add_contact_failure_preserves_input(wallet_dir, monkeypatch, failure):
    from toad.extensions.dega_panel.chat_contact import contacts

    app = ChatApp(wallet_dir)
    async with app.run_test():
        view = app.query_one(ChatView)
        view._my_username = "tester"
        resolve = Mock(return_value={
            "username": "maria", "wallet": "0x01", "pubkey": b"\x01" * 32,
        })
        if failure == "unknown":
            resolve.return_value = {}
        elif failure == "network":
            resolve.side_effect = OSError("unavailable")
        else:
            monkeypatch.setattr("toad.extensions.dega_panel.chat.remember_contact",
                                Mock(side_effect=OSError("read only")))
        monkeypatch.setattr(view._registry, "resolve_member", resolve)
        view.query_one("#contact-name", Input).value = "maria.dega"
        await view._add_contact()
        assert view.query_one("#contact-name", Input).value == "maria.dega"
        assert not contacts(path=wallet_dir / "contacts.json")


@pytest.mark.asyncio
async def test_invalid_registered_peer_preserves_private_message_draft(wallet_dir):
    app = ChatApp(wallet_dir)
    async with app.run_test():
        view = app.query_one(ChatView)
        view._my_username = "tester"
        view._offline = False
        view._selected_contact = {"pubkey": bytes(range(32)).hex()}
        view.notify = Mock()
        composer = view.query_one("#composer", Input)
        composer.value = "keep this private draft"
        await view._send_message()
        assert composer.value == "keep this private draft"
        assert not view._sent
        assert "invalid peer key" in view.notify.call_args.args[0]
        view._offline = True


@pytest.mark.parametrize("recipient,expected", [
    ({"pubkey": "ab" * 32}, "abababababab"),
    ({"wallet": "0x123"}, "0x123"),
    ({"username": "maria", "pubkey": "ab" * 32}, "maria"),
])
async def test_presence_label_supports_contacts_without_wallet(wallet_dir, recipient, expected):
    app = ChatApp(wallet_dir)
    async with app.run_test():
        view = app.query_one(ChatView)
        view._selected_contact = recipient
        view._online_until[recipient.get("pubkey", "")] = float("inf")
        view._update_presence_labels()
        assert str(view.query_one("#conversation-title", Label).render()) == expected + " · Online"


@pytest.mark.asyncio
@pytest.mark.parametrize("width", [60, 106])
async def test_unregistered_chat_stays_on_registration(wallet_dir, width):
    from toad.extensions.dega_panel.rooms.view import RoomsView

    app = ChatApp(wallet_dir)
    async with app.run_test(size=(width, 42)) as pilot:
        view = app.query_one(ChatView)
        await pilot.pause()
        for selector in ["#contacts-section", "#rooms-section", "#conv-scroll"]:
            assert not view.query_one(selector).display
        assert view.query_one("#open-node-block").display
        view.show_room(True)
        assert not view.query_one(RoomsView).display
        assert view.query_one("#conv-col").display
        view.on_button_pressed(Button.Pressed(view.query_one("#room-new", Button)))
        await pilot.pause()
        assert not view.query_one(RoomsView).display
        view._my_username = "tester"
        await view._render_actions()
        assert view.query_one("#contacts-section").display
        assert view.query_one("#rooms-section").display
        view.show_room(True)
        assert view.query_one(RoomsView).display
        view._my_username = None
        await view._render_actions()
        assert not view.query_one(RoomsView).display
        assert view.query_one("#conv-col").display
        assert view.query_one("#open-node-block").display


@pytest.mark.asyncio
async def test_pending_send_clears_input_and_prevents_duplicate(wallet_dir):
    import asyncio

    app = ChatApp(wallet_dir)
    async with app.run_test():
        view = app.query_one(ChatView)
        view._my_username = "tester"
        view._offline = False
        view._selected_contact = {"pubkey": "01" * 32}
        started, finish = asyncio.Event(), asyncio.Event()

        async def delayed_send(recipient, text):
            started.set()
            await finish.wait()
            return "optimistic-event"

        send = AsyncMock(side_effect=delayed_send)
        view._me.send_encrypted = send
        composer = view.query_one("#composer", Input)
        composer.value = "hello"
        pending = asyncio.create_task(view._send_message())
        await started.wait()
        assert composer.value == ""
        assert composer.disabled
        assert view.query_one("#btn-send", Button).disabled
        assert view._sent[0]["status"] == "Sending…"
        await view._render_actions()
        await view._render_conversation()
        assert composer.disabled
        assert "Sending…" in str(view.query_one(".bubble", Static).render())
        await view._send_message()
        send.assert_awaited_once()
        finish.set()
        await pending
        assert len(view._sent) == 1
        assert view._sent[0]["event_id"] == "optimistic-event"
        assert not composer.disabled
        view._offline = True


@pytest.mark.asyncio
async def test_registration_controls_are_in_fourth_sidebar_section(wallet_dir):
    app = ChatApp(wallet_dir)
    async with app.run_test():
        view = app.query_one(ChatView)
        section = view.query_one("#registration-section", Collapsible)
        assert section.collapsed
        assert section.query_one("#registration-status")
        assert section.query_one("#btn-renew-registration")
        assert section.query_one("#btn-retry-registration")
        assert [child.id for child in view.query_one("#side").children] == [
            "account-details", "registration-section", "contacts-section", "rooms-section",
        ]


@pytest.mark.asyncio
async def test_elements_are_inside_strategies_below_account_and_tabs(wallet_dir, monkeypatch):
    from textual.widgets import TabbedContent
    from toad.extensions.dega_panel.auth_view import AuthBar
    from toad.extensions.dega_panel.pane import DegaPane, ElementsBar

    monkeypatch.setattr("toad.extensions.dega_panel.pane.load_auth", auth_store.AuthState)
    monkeypatch.setattr(DegaPane, "_kick_chat_activation", lambda self: None)

    class Host(App):
        def compose(self):
            yield DegaPane()

    app = Host()
    async with app.run_test() as pilot:
        for _ in range(4):
            await pilot.pause()
        app.query_one(DegaPane)._select_utility_tab()
        await pilot.pause()
        tabs = app.query_one(TabbedContent)
        assert tabs.active == "tab-dega-utility"
        elements = app.query_one(ElementsBar)
        assert elements.query_ancestor("#tab-dega-utility") is not None
        assert app.query_one(AuthBar).region.bottom <= tabs.region.y
        assert elements.region.y > tabs.region.y


@pytest.mark.asyncio
async def test_cancelled_history_save_keeps_already_sent_message(wallet_dir):
    import asyncio

    app = ChatApp(wallet_dir)
    async with app.run_test():
        view = app.query_one(ChatView)
        view._my_username = "tester"
        view._offline = False
        view._selected_contact = {"pubkey": "01" * 32}
        view._me.send_encrypted = AsyncMock(return_value="confirmed-event")
        view.room_service = AsyncMock(return_value=SimpleNamespace(
            remember_dm=AsyncMock(side_effect=asyncio.CancelledError()),
        ))
        composer = view.query_one("#composer", Input)
        composer.value = "already delivered"
        with pytest.raises(asyncio.CancelledError):
            await view._send_message()
        assert composer.value == ""
        assert not composer.disabled
        assert view._sent[0]["event_id"] == "confirmed-event"
        assert not view._drafts
        view._offline = True


@pytest.mark.asyncio
async def test_collapsed_registration_discloses_status(wallet_dir):
    from toad.extensions.dega_panel.registration import Registration

    app = ChatApp(wallet_dir)
    async with app.run_test():
        view = app.query_one(ChatView)
        view._registration = Registration('tester', '0x01', 0, 0, 1, False, 1)
        view._registration_error = None
        view._registry_error = None
        view._render_registration()
        section = view.query_one('#registration-section', Collapsible)
        assert section.collapsed
        assert section.title == 'Registration · Expired'
        assert 'Expires 1970-01-01' in section.tooltip
        view._registration_error = 'RPC unavailable'
        view._render_registration()
        assert section.title == 'Registration · Unable to check'
        assert section.tooltip == 'RPC unavailable'
