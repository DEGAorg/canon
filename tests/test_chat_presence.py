import asyncio
import json
import time
from unittest.mock import AsyncMock, Mock

import pytest
from nostr_sdk import Event, EventBuilder, Kind, Tag, Timestamp
from websockets.asyncio.server import serve

from toad.extensions.dega_panel.chat_presence import (
    KIND, LIFETIME, STATUS_TYPE, PresenceClient, online_until, save_sharing, sharing_enabled,
)
from toad.extensions.dega_panel.chat_protocol import ChatNode


def signed(node, *, created=1000, expires='1090', status='online', kind=KIND, tag=STATUS_TYPE):
    unsigned = (EventBuilder(Kind(kind), status).custom_created_at(Timestamp.from_secs(created))
                .tags([Tag.parse(['d', tag]), Tag.parse(['expiration', expires])])
                .finalize_unsigned(node._keys.public_key()))
    return node._keys.sign_event(unsigned)


def test_expiration_and_author_validation():
    node = ChatNode()
    event = signed(node)
    assert online_until([event], {node.pubkey}, 1000) == {node.pubkey: 1090}
    assert online_until([event], {node.pubkey}, 1090) == {}
    assert online_until([event], {'another-author'}, 1000) == {}
    damaged = json.loads(event.as_json())
    damaged['sig'] = '00' * 64
    assert online_until([Event.from_json(json.dumps(damaged))], {node.pubkey}, 1000) == {}


@pytest.mark.parametrize('changes', [
    {'created': 1016}, {'expires': '1091'}, {'expires': '999'}, {'expires': 'bad'},
    {'status': 'offline'}, {'kind': 4}, {'tag': 'general'},
])
def test_invalid_or_unrelated_status_is_unknown(changes):
    node = ChatNode()
    assert online_until([signed(node, **changes)], {node.pubkey}, 1000) == {}


def test_opt_in_is_per_identity_and_private_on_disk(tmp_path):
    path = tmp_path / 'presence.json'
    assert not sharing_enabled('alice', path)
    save_sharing('alice', True, path)
    assert sharing_enabled('alice', path)
    assert not sharing_enabled('bob', path)
    assert path.stat().st_mode & 0o777 == 0o600
    save_sharing('alice', False, path)
    assert not sharing_enabled('alice', path)
    path.write_text('broken json')
    assert not sharing_enabled('alice', path)


@pytest.mark.asyncio
async def test_toggle_off_during_connect_does_not_publish(monkeypatch):
    node = ChatNode()
    client = Mock(send_event=AsyncMock(), disconnect=AsyncMock())
    sharing = True

    async def connect(*args, **kwargs):
        nonlocal sharing
        sharing = False

    monkeypatch.setattr(node, '_client', lambda: client)
    monkeypatch.setattr(node, '_connect', connect)
    assert await PresenceClient(node).refresh(set(), share=lambda: sharing) == {}
    client.send_event.assert_not_called()
    client.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_failure_then_recovery_and_cancellation_disconnect(monkeypatch):
    node, peer = ChatNode(), ChatNode()
    client = Mock(fetch_events=AsyncMock(side_effect=[OSError('relay down'),
                  [signed(peer, created=int(time.time()), expires=str(int(time.time()) + LIFETIME))]]),
                  disconnect=AsyncMock())
    monkeypatch.setattr(node, '_client', lambda: client)
    monkeypatch.setattr(node, '_connect', AsyncMock())
    transport = PresenceClient(node)
    assert await transport.refresh({peer.pubkey}, share=lambda: False) == {}
    assert peer.pubkey in await transport.refresh({peer.pubkey}, share=lambda: False)
    client.fetch_events = AsyncMock(side_effect=asyncio.CancelledError)
    with pytest.raises(asyncio.CancelledError):
        await transport.refresh({peer.pubkey}, share=lambda: False)
    assert client.disconnect.await_count == 3


@pytest.mark.asyncio
async def test_two_real_clients_exchange_signed_presence_through_local_relay():
    stored = {}

    async def relay(socket):
        async for raw in socket:
            message = json.loads(raw)
            if message[0] == 'EVENT':
                event = message[1]
                assert Event.from_json(json.dumps(event)).verify()
                stored[event['id']] = event
                await socket.send(json.dumps(['OK', event['id'], True, '']))
            elif message[0] == 'REQ':
                subscription, filters = message[1], message[2:]
                for event in stored.values():
                    if any(event['pubkey'] in f.get('authors', []) and
                           event['kind'] in f.get('kinds', []) for f in filters):
                        await socket.send(json.dumps(['EVENT', subscription, event]))
                await socket.send(json.dumps(['EOSE', subscription]))

    async with serve(relay, '127.0.0.1', 0) as server:
        address = f'ws://127.0.0.1:{server.sockets[0].getsockname()[1]}'
        alice = PresenceClient(ChatNode(relays=[address]))
        bob = PresenceClient(ChatNode(relays=[address]))
        await alice.refresh(set(), share=lambda: False)
        assert not stored
        await alice.refresh(set(), share=lambda: True)
        assert len(stored) == 1
        result = await bob.refresh({alice.node.pubkey}, share=lambda: True)
        assert alice.node.pubkey in result
        result = await alice.refresh({bob.node.pubkey}, share=lambda: True)
        assert bob.node.pubkey in result
        assert len(stored) == 2  # Alice's second refresh is heartbeat-throttled.


@pytest.mark.parametrize('tags', [
    [['d', STATUS_TYPE]],
    [['expiration', '1090']],
    [['d', STATUS_TYPE], ['expiration', '1090'], ['expiration', '1091']],
    [['d', STATUS_TYPE], ['d', 'general'], ['expiration', '1090']],
    [['d', STATUS_TYPE], ['expiration', '1090', 'unexpected']],
])
def test_missing_or_ambiguous_tags_are_not_presence(tags):
    node = ChatNode()
    unsigned = (EventBuilder(Kind(KIND), 'online').custom_created_at(Timestamp.from_secs(1000))
                .tags([Tag.parse(tag) for tag in tags]).finalize_unsigned(node._keys.public_key()))
    event = node._keys.sign_event(unsigned)
    assert online_until([event], {node.pubkey}, 1000) == {}
