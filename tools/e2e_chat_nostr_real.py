#!/usr/bin/env python3
"""E2E REAL del chat DEGA por Nostr (path de red, NO simulado).

Dos ChatNode conectados a relays públicos reales. A cifra (NIP-44) y publica un
DM kind-4 dirigido al pubkey de B; B hace fetch_events en los mismos relays,
encuentra el evento dirigido a él y lo descifra. Valida el transporte real
(relay + cifrado E2E + entrega), el núcleo que `OfflineChatNode` no cubre.

Uso: DEGA_RELAYS=wss://relay.damus.io,wss://nos.lol uv run python tools/e2e_chat_nostr_real.py
"""
import asyncio
import os
import time

from toad.extensions.dega_panel.chat_protocol import ChatNode, DEFAULT_RELAYS

RELAYS = [r.strip() for r in
          os.environ.get("DEGA_RELAYS", ",".join(DEFAULT_RELAYS)).split(",") if r.strip()]


async def main() -> int:
    print(f"Relays: {RELAYS}")
    a = ChatNode(relays=RELAYS)
    b = ChatNode(relays=RELAYS)
    print(f"A pubkey: {a.pubkey[:16]}…\nB pubkey: {b.pubkey[:16]}…")

    msg = f"mensaje-real-{int(time.time())}"
    print(f"1. A -> publica DM cifrado a B: {msg!r}")

    # Publicar desde A. Puede tardar en propagar; reintentamos hasta confirmar
    # que el evento quedó en el relay (poll desde B con fetch_events).
    try:
        event_id = await a.send_encrypted(b.pubkey, msg)
        print(f"   publicado event_id={event_id[:16]}…")
    except Exception as e:
        print(f"   FALLO al publicar: {e}")
        return 1

    # B busca el evento dirigido a él (fetch_events en la red)
    found = None
    for attempt in range(6):
        await asyncio.sleep(2 * attempt + 1)
        try:
            dms = await b.fetch_dms()
        except Exception as e:
            print(f"   fetch [{attempt}]: {e}")
            continue
        for dm in dms:
            if msg in dm.get("text", ""):
                found = dm
                break
        if found:
            break
        print(f"   fetch [{attempt}]: aún no (dm count={len(dms)})")

    if not found:
        print("FALLO E2E: B no recibió el DM en los relays")
        return 1

    print(f"2. B recibió y descifró (NIP-44 E2E): {found['text']!r} (time={found.get('time')!r})")
    if found["text"] == msg:
        print("\nE2E-CHAT-NOSTR-REAL PASS")
        return 0
    print("FALLO E2E: el texto descifrado no coincide")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))