#!/usr/bin/env python3
"""E2E real: pedro <-> bot bidireccional por relays públicos.

1. Crea un ChatNode con la identidad de PEDRO (la de la TUI, ~/.canon).
2. Pedro le manda un DM a la pubkey del BOT (bot.dega on-chain).
3. Corre la logica del bot (importa chat_bot) para que conteste.
4. Pedro vuelve a fetch_dms y confirma que recibio la respuesta del bot.

No toca la TUI; solo valida el transporte bidireccional real con las dos
identidades de la config (pedro = wallet principal, bot = ~/.canon/bot).
"""
import asyncio
import importlib.util
import json
import os
import pathlib
import sys
import time

from toad.extensions.dega_panel.chat_identity import load_or_create_identity
from toad.extensions.dega_panel.chat_protocol import ChatNode, DEFAULT_RELAYS

# load tools/chat_bot.py as a module (tools/ is not a package)
_spec = importlib.util.spec_from_file_location(
    "chat_bot", pathlib.Path(__file__).parent / "chat_bot.py"
)
if _spec is None or _spec.loader is None:  # pragma: no cover
    raise SystemExit("cannot load chat_bot.py")
botmod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(botmod)

RELAYS = [r.strip() for r in os.environ.get("DEGA_RELAYS", ",".join(DEFAULT_RELAYS)).split(",") if r.strip()]


def bot_pubkey() -> str:
    env = json.loads(pathlib.Path(os.path.expanduser("~/.canon/bot/env")).read_text())
    pk = botmod._wallet_pk()
    from nostr_sdk import Keys
    return Keys.parse(pk).public_key().to_hex()


async def main() -> int:
    # --- pedro identity (same file the TUI uses) ---
    keys, _ = load_or_create_identity(path=os.path.expanduser("~/.canon/chat-identity.json"))
    pedro = ChatNode(secret_key=keys.secret_key().to_bech32(), relays=RELAYS)
    bpub = bot_pubkey()
    print(f"pedro pubkey={pedro.pubkey[:16]}…\nbot   pubkey={bpub[:16]}…")

    # fresh dedupe so the test is repeatable
    botmod.SEEN_FILE.write_text("[]")

    # --- 1. pedro -> bot ---
    msg = f"prueba transporte bidireccional {int(time.time())}"
    print(f"1. pedro -> bot: {msg!r}")
    try:
        await pedro.send_encrypted(bpub, msg)
        print("   enviado")
    except Exception as e:
        print(f"   FALLO pedro->bot: {e}")
        return 1

    # --- 2. bot lee y responde ---
    await asyncio.sleep(3)  # let it propagate
    bot_node = ChatNode(secret_key=botmod._wallet_pk(), relays=RELAYS)
    seen = botmod._load_seen()
    n = await botmod.one_cycle(bot_node, seen, print_in=True)
    botmod._save_seen(seen)
    print(f"2. bot respondio a {n} DM(s)")
    if n == 0:
        print("FALLO E2E: el bot no recibio el DM de pedro")
        return 1

    # --- 3. pedro lee la respuesta ---
    found = None
    for attempt in range(6):
        await asyncio.sleep(2 * attempt + 1)
        try:
            dms = await pedro.fetch_dms()
        except Exception as e:
            print(f"   fetch [{attempt}]: {e}")
            continue
        for dm in dms:
            if dm.get("from", "").lower() == bpub.lower() and "recibido" in (dm.get("text") or ""):
                found = dm
                break
        if found:
            break
        print(f"   fetch [{attempt}]: aun no veo la respuesta del bot")

    if not found:
        print("FALLO E2E: pedro no recibio la respuesta del bot")
        return 1
    print(f"3. pedro recibio respuesta del bot: {found['text']!r}")
    print("\nE2E-CHAT-BOT-BIDIRECCIONAL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
