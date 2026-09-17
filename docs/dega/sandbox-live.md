# DEGA / Canon — Validated E2E: chat, resident bot, trading

What has been validated against live Sepolia and real Polymarket data, and how the trading sandbox
works.

## On-chain P2P chat (no mock)

- Lives in the **TUI** (`dega_panel/chat.py` → `ChatView`). The contract and relays are
  transparent to the user.
- Default backend **`chain`** (env `DEGA_CHAT_BACKEND`, default `"chain"`). `simulated` is only the
  headless harness opt-in (`tools/verify-tui.py` forces `DEGA_CHAT_BACKEND=simulated`).
- Nostr relays are **shared public** relays (not per-user): `relay.damus.io`, `nos.lol`.
- If the shell has stale `DEGA_CHAT_*` env vars, Canon now prefers `~/.canon/dega-chat.env`
  (simple `KEY=VALUE` lines) so the panel can ignore the stale shell and use the correct Sepolia
  RPC/registry/token.

### Flow
1. **Open node** — `openNode(username, nostrPubkey, proof)` registers `nombre.dega` + the user's Nostr
   pubkey on-chain (unique, `usernameTaken` guards).
2. **Invite by name** — `resolve_member('maria.dega')` returns `{username, pubkey, wallet}`;
   `invite(username, wallet)` adds the EVM member on-chain.
3. **Send/receive** — NIP-44 E2E DM (kind-4) over the shared relays.

### Identity (wallet-derived)
The Nostr keypair is **deterministically derived from the same secp256k1 on-chain signer key**
(env `DEGA_CHAT_PK` or `~/.canon/wallet.env`), so `wallet <-> nostr pubkey <-> nombre.dega` are
one key. Without a signer it falls back to a persisted key in `~/.canon/chat-identity.json`
(mode 0600) plus the alias. `chat_store.py` persists the message inbox locally as ciphertext only.

## Resident on-chain bot

A resident bot runs as a second node (`bot.dega`, wallet `0xB0c725...`) using the same chat
protocol; provisioned via `tools/chat_bot_provision.py` + `tools/chat_bot.py`; config under
`~/.canon/bot/`. Validated end-to-end against the live registry and public relays. Requires
Node 22 (`dega_agents_fe` crashes on Node 26). Never `--live` during testing.

## Trading (paper-live, real book)

Enabled safely:
- **`L`** in the catalogue → `run_live` → `_RunConfirm` + `_LiveConfirm` (type `LIVE`) →
  `runner.run_strategy(live=True, live_confirm=True)` which builds
  `npm run live` or `npm run start:live` for dedicated live scripts. Generic scripts
  retain the explicit `npm run <script> -- --live` opt-in.
- Dry stays `npm run <script>` (no `--live`); live without `live_confirm` is refused.

⚠️ **Real capital is not moving.** `arbiter` runs the live broker (paper fills against the
Polymarket live book) and only broadcasts real orders with `--confirm-real` + a funded
`WALLET_PRIVATE_KEY`/`POLYMARKET_PRIVATE_KEY`. There is currently **no funded wallet.env**, so no
real orders are placed. Do not pass `--confirm-real` until a risk-controlled production wallet
exists.

Verified run (real Polymarket data): `LIVE · FETCH 562 mkts → ANALYZE 45 nodes → DECIDE 0 orders
→ EXECUTE 0 fills · bankroll $1000`.

## Strategy delivery (backend-gated, no public downloads)

Strategy archives are **not** fetched from a repository URL. The 12 catalog tars live in the
backend repo (`dega_agents_fe/backend/strategies/<key>.tar.gz`) and are streamed by the agents API
(`GET /strategies/eligibility?key=` + `GET /strategies/archive?key=`), which re-verifies the signed-in
user's element grant on every request. `installer.install_strategy(..., fetcher=...)` takes either a
backend fetcher or a local directory (dev / headless harness) and **fails** with "sign in to download
via the backend" when neither is given; the old GitHub/codeload download path was removed. There is
no `DEGA_STRATEGIES_DIR` env override and no GCS fallback — the tars reach prod by a push to
`master`.

> `data.py`'s catalogue still carries a legacy `repo` field with
> `raw.githubusercontent.com/DEGAorg/canon-strategies/main/<key>.tar.gz` URLs (the temporary public
> staging repo). It is **not** used for delivery: `utility.py` installs through
> `backend_download_archive()`. Do not rewire the installer to that field.

> The strategies are third-party code: they are scanned (`scanner.py`) and run only after
> confirmation (+ type `LIVE` for live). `--ignore-scripts` on install.
Registration requires a local Nostr ownership proof; see [proof specification](nostr-registration-proof.md).
