# DEGA / Canon — Testing

What tests exist for the DEGA/Canon stack, what is verified, and how to run them.

## Status (re-verified 2026-09-16)

- **Backend (Encore, `dega_agents_fe`):**
  - `npm run test` — vitest suite, no infra needed: **34 passed, 2 skipped** (identity F1, cookies
    A3, email guard, dev-route gate, `users.id` metadata, and `core/strategies/catalog.test.ts` with
    12 cases). The two DB suites skip themselves when no database is reachable, so an offline run is
    never a false failure. `npm run test:logic` runs the logic/device subset alone: **21 passed**
    (verified 2026-09-16).
  - `npm run test:db` — `encore test` (isolated test DB, Node 22): **7 files / 32 tests passed**,
    including the DB integration suites (`user.integration.test.ts` 5, `device.atomic.test.ts` 5).
    Last verified 2026-09-12; it needs the Encore runtime + a test DB, so it was not re-run on
    2026-09-16.
  - `npm run test:e2e` — `script/e2e_device_auth.py`, real HTTP against the running backend +
    Postgres: passes, and now covers **account creation**. It creates A and B through
    `POST /users/login-encore` (the same code path as the real login) and asserts that creating B
    does not return A; psql is used only for read-back checks and cleanup. Needs the backend up —
    last verified 2026-09-12.
- **`forge test` (contract):** **24 passed / 0 failed** in 5 suites (verified 2026-09-16):
  `Registry.t.sol` 7, `Expiry.t.sol` 10 (expiry/renewal/reentrancy), `Fuzz.t.sol` 7
  (fuzz + stateful invariants).
- **pytest (canon-app):** `uv run python -m pytest tests/ -q` → **618 passed, 0 failed** at HEAD
  `c96ec3a` (verified 2026-09-16, after PR #10 "Align own room messages to the right").
  Before that PR the suite was 617 passed + 1 failure,
  `tests/test_rooms_ui.py::test_create_room_and_cancel_close[60]` — a Textual pilot timing assertion
  that **passed every time in isolation** (9 passed for the whole file) and failed in 2 of 3
  full-suite runs; under heavy parallel load a different UI test also failed
  (`test_chat_ui.py::test_add_contact_is_local_and_never_invites_on_chain`, only while `forge test`
  saturated the CPU). The PR added coverage to the same file and the run is clean now, but the
  failure mode was load-sensitive timing, so if it reappears treat it as the known flake and re-run
  the test alone before reporting a rooms/UI defect.
- **Run the suite with the right entrypoint.** `uv run pytest tests/` **aborts collection**:
  `tests/test_registration_ttl.py` does `from tests import test_chat_ui`, and the `pytest`
  entrypoint does not put the CWD on `sys.path`, so it dies with
  `ModuleNotFoundError: No module named 'tests'` and reports an error instead of results. Use
  `uv run python -m pytest tests/ -q` (which works as-is). This is a known gap; do not "fix" it by
  adding `pythonpath`/`tests/__init__.py` without an explicit decision.

## Backend: how to run

```bash
cd ~/projects/DEGA/dega_agents_fe/backend

# 1) Pure-logic tests (no Encore runtime, no infra)
npm run test:logic

# 2) Full vitest run (the DB suites skip themselves when no DB is reachable)
npm run test

# 3) E2E device-flow (needs the backend running + Postgres up)
npm run test:e2e

# 4) Encore integration (isolated test DB; Encore provisions its own Postgres)
npm run test:db
```

**Encore CLI:** `export PATH="$HOME/.encore/bin:$PATH"` (v1.58.5 verified here); the JS runtime
lives at `~/.encore/runtimes/js/encore-runtime.node` and is what `encore test` sets in
`ENCORE_RUNTIME_LIB`.

**Node version:** the backend requires Node 22. Node ≥23 removes `SlowBuffer` and crashes
`jsonwebtoken` at boot (`buffer-equal-constant-time`). The Encore **daemon** must be started with
Node 22 in its PATH, not just the CLI:

```bash
pkill -f 'encore daemon'; sleep 2
export PATH="$HOME/.nvm/versions/node/v22.15.1/bin:$PATH"
encore run
```

## Backend: local database networking note (WSL2)

The default docker `bridge` on this machine can silently stop forwarding to newly published ports.
Workaround in use: the Encore DB container runs on a user-defined network (`encore-db-net`,
published on `127.0.0.1:32768`). If `encore run` fails with `connection reset by peer` /
`dial error` on a fresh port, restore Docker:

```bash
# 1) recreate the DB container on the custom network (name Encore expects)
docker network create encore-db-net 2>/dev/null || true
docker rm -f sqldb-ai-agents-4eg2-default-da2vigibaa0ue4q70uag
docker run -d --name sqldb-ai-agents-4eg2-default-da2vigibaa0ue4q70uag \
  --network encore-db-net -p 32768:5432 --restart unless-stopped \
  -v sqldb-ai-agents-4eg2-da2vigibaa0ue4q70uag-default:/var/lib/postgresql \
  -e PGDATA=/var/lib/postgresql/data \
  -e POSTGRES_PASSWORD=postgres -e POSTGRES_HOST_AUTH_METHOD=trust \
  postgres:18
# 2) then encore run as above
```

## Headless TUI verification (layout must be verified this way)

After any widget/screen change, lint/type are not enough — run the headless harness:

```bash
uv run python tools/verify-tui.py --verbose        # all widgets
uv run python tools/verify-tui.py --widget dega     # DEGA panel only
```

Forces `DEGA_CHAT_BACKEND=simulated` so it runs without a chain signer.

## Contract tests

```bash
cd src/toad/extensions/dega_panel/contracts
forge test            # 24 passing / 0 failed (Registry 7, Expiry 10, Fuzz+invariants 7)
```

If it OOMs (`solc ... SIGKILL`), see the note + workaround in [contracts.md](contracts.md).

## Python / DEGA panel tests (canon-app)

```bash
# Fee formatting (F3) + identity precedence (F6) + runner (F2/F4)
uv run python -m pytest tests/test_dega_fee_formatting.py tests/test_chat_identity_precedence.py \
  tests/test_strategy_runner.py tests/test_strategy_runner_selection.py -q

# Panel live-signal parser
uv run pytest tools/test_utility_live.py

# Runner hardening
uv run pytest tools/test_runner_hardening.py

# Registration TTL + chain renewal (real Anvil nodes), rooms, presence
uv run python -m pytest tests/test_registration_ttl.py tests/test_registration_chain.py -q
uv run python -m pytest tests/test_rooms.py tests/test_rooms_ui.py -q
uv run python -m pytest tests/test_chat_presence.py -q

# Property tests (contract helpers + signal parser) - runs several seeds cleanly
uv run python -m pytest tests/test_dega_property_fuzz.py -q

# Full suite: 618 passed / 0 failed at HEAD (see Status above)
uv run python -m pytest tests/ -q
```

## E2E scripts (real, against public relays / Sepolia / local backend)

These are manual/integration scripts under `tools/` or the backend `script/`; they hit live
endpoints and need a real signer / running backend. Not part of the unit suite.

| Script | Validates |
|--------|-----------|
| `backend/script/e2e_device_auth.py` | Account creation through `/users/login-encore` (creating B must not return A) + device approval: session binding, single-use, cookie topology (needs backend + DB up) |
| `tools/e2e_fee_decimals_real.py` | Reads `decimals()` from the real Sepolia registry/token (18) |
| `tools/e2e_chat_nostr_real.py` | Real Nostr chat end-to-end against public relays |
| `tools/e2e_chat_bot_real.py` | Resident on-chain bot chatting (second node, `bot.dega`) |
| `tools/e2e_device_flow_real.py` | Device-flow auth against the live backend |
| `tools/e2e_login_encore_real.py` | Login against the Encore backend |
| `tools/e2e_ui_real.py` | Real UI smoke over the headless harness |
| `tools/e2e_race_condition.py` | Inbox/relay race-condition probe |
