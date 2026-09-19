#!/usr/bin/env python3
"""DEGA Canon chat BOT (residente).

Escucha los relays públicos por DMs kind-4 dirigidos a la identidad del bot
(`bot.dega`, wallet `~/.canon/bot/wallet.env`) y responde al remitente con un
DM NIP-44 cifrado. Corre como proceso aparte mientras el usuario usa la TUI
de Canon (pedro.dega) para mantener un chat bidireccional en vivo.

Config (todo en ~/.canon/bot/):
- wallet.env   -> la clave EVM del bot (0600); su identidad Nostr se deriva de
  ella, de modo que wallet <-> pubkey <-> bot.dega son una sola clave.
- env          -> {"username", "rpc", "registry", "token"}.
- seen.json    -> event_ids ya respondidos (dedupe, se crea automáticamente).

Uso:
  uv run python tools/chat_bot.py            # loop por defecto
  uv run python tools/chat_bot.py --once     # un solo ciclo de escucha/lectura
  DEGA_RELAYS=wss://relay.damus.io uv run python tools/chat_bot.py

En modo loop pulsa Ctrl-C para salir.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from nostr_sdk import Keys

from toad.extensions.dega_panel.chat_protocol import ChatNode, DEFAULT_RELAYS

CANON = Path(os.path.expanduser("~/.canon"))
BOT_DIR = CANON / "bot"
BOT_WALLET = BOT_DIR / "wallet.env"
BOT_ENV = BOT_DIR / "env"
SEEN_FILE = BOT_DIR / "seen.json"

RELAYS = [r.strip() for r in
          os.environ.get("DEGA_RELAYS", ",".join(DEFAULT_RELAYS)).split(",") if r.strip()]

GREETING = (
    "hola! soy el bot de DEGA Canon ({username}.dega). "
    "este mensaje llega cifrado NIP-44 por un relay público y lo descifré "
    "con mi clave. escribime lo que quieras."
)


def _wallet_pk() -> str:
    if not BOT_WALLET.exists():
        print("[bot] missing ~/.canon/bot/wallet.env — run tools/chat_bot_provision.py", file=sys.stderr)
        raise SystemExit(2)
    for line in BOT_WALLET.read_text(encoding="utf-8").splitlines():
        if line.startswith("WALLET_PRIVATE_KEY="):
            v = line.split("=", 1)[1].strip()
            return v[2:] if v.startswith("0x") else v
    raise SystemExit("[bot] WALLET_PRIVATE_KEY not found")


def _username() -> str:
    if BOT_ENV.exists():
        try:
            return json.loads(BOT_ENV.read_text()).get("username", "bot")
        except ValueError:
            pass
    return "bot"


def _load_seen() -> set[str]:
    if not SEEN_FILE.exists():
        return set()
    try:
        return set(json.loads(SEEN_FILE.read_text()))
    except (ValueError, OSError):
        return set()


def _save_seen(seen: set[str]) -> None:
    SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SEEN_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(sorted(seen)))
    try:
        tmp.chmod(0o600)
    except OSError:
        pass
    tmp.replace(SEEN_FILE)


def _autoreply(text: str) -> str:
    """Simple canned-but-honest reply so the chat feels bidirectional."""
    low = text.lower().strip()
    if any(k in low for k in ("hola", "hi", "hello", "hey", "buenas")):
        return "hola! por acá estoy, escuchando en el relay. seguí, te leo."
    if any(k in low for k in ("quien sos", "quién sos", "who are you", "tu nombre")):
        return "soy el bot de DEGA Canon. abrí mi propio nodo on-chain y te hablo cifrado por Nostr."
    if any(k in low for k in ("como", "cómo", "ayuda", "help", "q hace", "qué hace")):
        return "recibo DMs por relay y te respondo. es E2E: solo tu clave y la mía leen esto."
    if any(k in low for k in ("adios", "adiós", "bye", "chau", "chao")):
        return "chau! quedó todo cifrado en el relay. cuando vuelvas seguimos."
    return (
        f"recibido ({len(text)} chars) y descifrado OK por NIP-44. "
        f"no soy muy listo, pero el transporte funciona: tu DM llegó del relay "
        f"hasta mi clave."
    )


async def one_cycle(node: ChatNode, seen: set[str], print_in: bool) -> int:
    """Poll DMs addressed to the bot, reply to each unseen sender. Returns replies sent."""
    try:
        dms = await node.fetch_dms()
    except Exception as exc:  # noqa: BLE001 - relay flakiness is retryable
        print(f"[bot] fetch failed: {exc}")
        return 0

    replied = 0
    for dm in dms:
        eid = dm.get("event_id")
        sender = dm.get("from", "")
        if not eid or not sender:
            continue
        if eid in seen:
            continue
        seen.add(eid)
        if print_in:
            t = time.strftime("%H:%M")
            print(f"\n[bot] DM de {sender[:12]}… ({t}): {dm.get('text')!r}")
        reply = _autoreply(dm.get("text") or "")
        try:
            await node.send_encrypted(sender, reply)
            replied += 1
            print(f"[bot] -> respondí a {sender[:12]}… : {reply!r}")
        except Exception as exc:  # noqa: BLE001
            print(f"[bot] reply send failed to {sender[:12]}…: {exc}")
    return replied


async def run_loop(node: ChatNode, interval: float, seen: set[str]) -> None:
    print(f"[bot] escuchando como {_username()}.dega  pubkey={node.pubkey[:16]}…")
    print(f"[bot] relays: {', '.join(RELAYS)}   (Ctrl-C para salir)\n")
    while True:
        try:
            await one_cycle(node, seen, print_in=True)
            _save_seen(seen)
        except Exception as exc:  # noqa: BLE001
            print(f"[bot] ciclo falló: {exc}")
        await asyncio.sleep(interval)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="un solo ciclo de escucha")
    ap.add_argument("--interval", type=float, default=8.0, help="segundos entre polls")
    args = ap.parse_args()

    pk = _wallet_pk()
    # Identity derives from the bot EVM key, matching bot.dega on-chain.
    node = ChatNode(secret_key=Keys.parse(pk).secret_key().to_bech32(), relays=RELAYS)
    seen = _load_seen()

    if args.once:
        print(f"[bot] once: {_username()}.dega  pubkey={node.pubkey[:16]}…")
        n = await one_cycle(node, seen, print_in=True)
        _save_seen(seen)
        print(f"[bot] ciclo terminado, {n} respuestas enviadas")
        return 0

    try:
        await run_loop(node, args.interval, seen)
    except KeyboardInterrupt:
        _save_seen(seen)
        print("\n[bot] detenido. progreso guardado en seen.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
