# Canon configuration reference

[Start with the beginner guide](../../GETTING_STARTED.md) · [Setup and troubleshooting](setup-and-troubleshooting.md)

Use this reference when changing a network, backend, wallet, template settings, or
advanced process controls. Ordinary first-time setup uses the generated defaults.

Last checked: 18 September 2026.

## Configuration, contracts, and wallets

### Know which configuration you are changing

| Scope | Typical location | Reader |
| --- | --- | --- |
| Agent account/settings | Provider-managed CLI profile | Claude/Codex/Gemini and its adapter |
| Core installation | `~/.degacore/` plus agent-specific skills | Core workflows |
| Chat/backend defaults | `~/.canon/dega-chat.env` | Canon's explicitly supported settings |
| Default chat signing wallet | `~/.canon/wallet.env` | Canon chat wallet fallback |
| Automation configuration | The editable project's `strategies/<key>/` configuration, as documented by that package | That package's loader through the project adapter |
| Process variables | Exported in the shell before starting `canon .` | Canon and inherited child processes |

Do not assume an arbitrary variable in `dega-chat.env` is exported to strategies.
The app's package runner inherits Canon's process environment; the Core project
supervisor follows its own launcher configuration. Each template decides whether and
where to load a `.env` file. Canon does not automatically inject the chat wallet file
into every automation.

### Mainnet reference

| Setting | Shipped production value |
| --- | --- |
| Chain | Ethereum mainnet, ID `1` |
| Default RPC | `https://ethereum-rpc.publicnode.com` |
| Registry | `0x4c698AC2f25dD82386658080223583e0EEbB523f` |
| DEGA token | `0x97aeE01ed2aabAd9F54692f94461AE761D225f17` |
| Website | `https://ai-agents.degaplatform.com/` |
| API | `https://ai-agents-api.degaplatform.com` |

The deployment documentation recorded **6,719,270 DEGA**, **365 days**, and capacity
**10**. These are deployment reference values, not a current price quote or universal
room-member limit. Read the registry's current fee, TTL, and token before funding or
confirming a transaction. The token is obtained through `degaToken()` and its decimals
are read from the token contract.

### Supported chat/backend settings

The generated file is `~/.canon/dega-chat.env`. Its parser expects plain `KEY=VALUE`
lines: **do not add `export`, shell quotes, `$VARIABLE` expansion, or inline comments**.
For a normal production installation, leave generated defaults in place.

```dotenv
DEGA_API_URL=https://ai-agents-api.degaplatform.com
DEGA_CHAT_BACKEND=chain
DEGA_CHAT_RPC=https://ethereum-rpc.publicnode.com
DEGA_CHAT_REGISTRY=0x4c698AC2f25dD82386658080223583e0EEbB523f
DEGA_CHAT_PK=
```

An empty `DEGA_CHAT_PK` does not erase a key exported in the shell. The effective
precedence below still applies. Edit an existing file carefully; do not replace it
with this example and accidentally discard other settings.

| Variable | Where it is read / priority | Purpose |
| --- | --- | --- |
| `DEGA_API_URL` | Process → chat file → `http://127.0.0.1:4000` fallback | Device login and strategy backend. Fresh generated files set production. |
| `DEGA_CHAT_BACKEND` | Process → chat file → `chain` | `chain` is normal use; `simulated` is isolated testing, not mainnet registration. |
| `DEGA_CHAT_RPC` | Chat file → process → mainnet RPC above | RPC for chat registry reads and transactions. |
| `DEGA_CHAT_REGISTRY` | Chat file → process → registry above | Selected registry contract. Must match the intended RPC network. |
| `DEGA_CHAT_PK` | Chat file → process → `WALLET_PRIVATE_KEY` in `~/.canon/wallet.env` | Effective chat signing key; secret. An explicit programmatic client argument can override configuration. |

Changing RPC/registry can point you at another deployment; changing only the RPC does
not deploy or change a contract. There is no supported `DEGA_CHAT_TOKEN` override,
`DEGA_CHAT_ENV` path override, or environment setting that changes on-chain fee/TTL/capacity.
A shell-only `WALLET_PRIVATE_KEY` is not the chat file fallback.

### Wallet separation

The normal chat wallet file has the key name `WALLET_PRIVATE_KEY`. Keep its value in
that protected file, not in this guide or shell-command history. Restrict the directory
and existing sensitive files, for example:

```bash
chmod 700 ~/.canon
chmod 600 ~/.canon/wallet.env ~/.canon/dega-chat.env
```

Run the `chmod 600` command only once those files exist. Keep an offline/private backup.
Chat derives its Nostr identity from the effective signing key; replacing that key
can switch both wallet and chat identity. To use a different chat wallet, stop Canon,
back up the profile, explicitly update the effective key source, restart, and verify
the public address before any transaction. Do not change keys to “fix” a login error.

An automation may use `PRIVATE_KEY`, `POLYMARKET_PRIVATE_KEY`, an exchange credential,
or no signing key at all. **There is no universal automation-wallet environment variable.**
Use the template's actual schema. A chat wallet funded on Ethereum does not establish
that a trading wallet is funded on another chain. Keep trading credentials scoped to
that automation; avoid globally exporting a funded wallet key into all child processes.

### Process-only paths and runner controls

These are read from the environment of the running app, not loaded as arbitrary entries
from `dega-chat.env`. Set them before launching Canon; paths are advanced overrides.

| Variable | Default / effect |
| --- | --- |
| `DEGA_CHAT_IDENTITY_FILE` | `~/.canon/chat-identity.json`; chat identity persistence |
| `DEGA_CHAT_CONTACTS_FILE` | `~/.canon/chat-contacts.json`; contacts and selected node |
| `DEGA_CHAT_INBOX_FILE` | `~/.canon/chat-inbox.json`; cached inbox |
| `DEGA_CHAT_ROOMS_DIR` | `~/.canon/rooms/`; identity-scoped SQLite journals |
| `DEGA_GATING_FILE` | `~/.canon/gating.json`; local feature/test configuration, not backend access grants or on-chain fee control |
| `DEGA_STRAT_MEM_MB` | App package-runner memory cap, default `6144` MiB; not a universal Core-supervisor setting |

Example of a non-secret, process-scoped override:

```bash
DEGA_STRAT_MEM_MB=4096 canon .
```

Nostr relay defaults are currently `wss://relay.damus.io` and `wss://nos.lol`.
There is no shipped relay-list environment setting; do not invent `NOSTR_RELAYS` and
expect Canon to read it. Changing relays requires the supported code/configuration
interface of the release, not a token payment.

Session/access files such as `auth.json`, `strategy-access.json`, and `installed.json`
are application state, not settings to edit to unlock a feature. Logs are under
`~/.canon/execution/`; chat state and recovery records are under `~/.canon/`.
Do not delete transaction-recovery records to resolve a timeout.

### Core and agent-session overrides

These are advanced **process** settings, not chat-file entries:

| Variable | Meaning |
| --- | --- |
| `DEGA_CORE_HOME` | Core installation root; normally `~/.degacore`. Keep it aligned with the actual installed scripts. |
| `CANON_NO_AUTO_BYPASS=1` | Stops Canon from automatically selecting `bypassPermissions` when an agent exposes that mode. It does not reset an already-resumed agent permission mode. |
| `TOAD_CWD` | Project path supplied by Canon to agent adapters; normally leave unset. |
| `TOAD_SOCKET` | Current Canon control socket supplied to adapters; do not copy another session's socket value. |
| `ENABLE_TOOL_SEARCH` | Canon defaults this to `false` for child agents unless already set in the parent. Usually leave it to the integration. |
| `CANON_RUN_ID` | Project-supervisor telemetry identifier; generated per run, not a value to reuse manually. |

For a new session where you want to prevent automatic permission bypass, launch:

```bash
CANON_NO_AUTO_BYPASS=1 canon .
```

Check the agent's displayed permission mode as well, especially when resuming a session.
This controls agent tool permissions; it does not add a chat-registration confirmation
or turn a live strategy into dry-run.

### Automation-specific environment reference

This appendix covers the **11 catalogue templates audited for this guide**. The downloaded
archive's `CANON.md`, `.env.example`, and actual configuration reader remain the authority
for that archive version. An example may omit an optional variable supported by code.
Do not paste all these variables into one global file.

For each template, use its documented configuration file in the **editable package directory
launched by the prepared project adapter**, unless its loader says otherwise. References
below to forced mode, wallet stripping, and notification suppression describe those
package-specific lifecycle adapters, not every ordinary package script selected by panel `r`. Values such as API keys and wallet
keys below are variable names only, never example credentials.

| Template key | Data and credential requirements | Dry-run interpretation |
| --- | --- | --- |
| `arbiter` | Public Polymarket endpoints; optional configured LLM provider/key | Canon uses a paper broker; no wallet needed |
| `oracle-bot` | Public Polymarket/ESPN; optional odds-service key for bookmaker consensus | Canon forces dry-run; no wallet needed; external notification hooks disabled |
| `court-edge-arifin` | Basketball/API settings including `BALLDONTLIE_API_KEY` and `POLYMARKET_API_KEY`; required features depend on the configured sources | Missing/mock market key can select fixed `0.50` prices; historical reconstruction is synthetic |
| `prediction-edge` | Public endpoint settings; no private key required for Canon dry-run | Fills/P&L include random simulation, not evidence of realized market performance |
| `courtshock` | JSON strategy/scenario/player-data configuration; optional odds-service adapter key | Can use replay fixtures; inspect the selected inputs rather than assuming live prices |
| `market-forecast` | Public market reads; basketball source uses `BALLDONTLIE_API_KEY`; authenticated connectors need their own credentials | Market data and paper execution are separate; missing source credentials can block the chosen feed |
| `nba-playoff-bot` | Public data path; trading API key belongs to submission path | Canon forces dry-run; no submission key needed for that path |
| `core-arb-binary` | Public feeds; no trading key for curated entrypoint | Paper bankroll/portfolio assumptions; curated runner accepts dry-run only |
| `core-mm-premium` | Public feeds; no trading key for curated entrypoint | Assumed empty paper portfolio; curated runner accepts dry-run only |
| `core-trade-momentum` | Public feeds; no trading key for curated entrypoint | Public data plus paper assumptions; curated runner accepts dry-run only |
| `core-mint-01` | Public reads; no wallet/API credentials for curated entrypoint | Read-only planner; no mint transaction is submitted |

The following controls are template-specific; similarly named keys are not automatically
interchangeable. Risk controls are listed so you can recognize them, not as suggested
trading parameters.

**`arbiter`** — inspect `src/config.ts` and `src/canon/runtime.ts`:

- Data: `POLYMARKET_GAMMA_URL`, `POLYMARKET_CLOB_URL`, `POLL_INTERVAL_MS`.
- Optional LLM: `LLM_PROVIDER` (default `none`), `LLM_MODEL`, `GROQ_API_KEY`,
  `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `OLLAMA_BASE_URL`.
- Paper/risk settings: `EXECUTION_MODE`, `BANKROLL`, `MIN_EDGE`, `KELLY_FRACTION`,
  `MAX_STAKE_PER_LEG`, `TAKER_FEE_BPS`. Canon's entrypoint still constructs the paper broker.

**`oracle-bot`** — inspect `.env.example`, `src/canon.ts`, and `src/utils/config-watcher.ts`:

- Data: `POLYMARKET_CLOB_URL`, `POLYMARKET_GAMMA_URL`, `POLYMARKET_WS_URL`,
  `ESPN_NBA_URL`, `ODDS_API_KEY`, `ODDS_API_BASE`.
- Timing/risk: `MARKET_POLL_MS`, `INJURY_POLL_MS`, `KELLY_FRACTION`, `MAX_BET_USDC`,
  `MIN_EV_THRESHOLD`, `MIN_CONFIDENCE`, `MIN_LIQUIDITY_USD`, `MIN_VOLUME_24H_USD`,
  `STOP_LOSS_PCT`, `TAKE_PROFIT_PCT`, `LOG_DIR`.
- Mode/wallet: `TRADING_MODE`, `WALLET_PRIVATE_KEY`, `WALLET_ADDRESS`. Wallet fields
  are unnecessary for Canon dry-run.
- Notifications: `DISCORD_WEBHOOK_URL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` are
  disabled by the Canon adapter. Its config watcher prefers package `.env` values
  over process values for watched settings.

**`court-edge-arifin`** — inspect `.env.example`, `src/index.ts`, and `CANON.md`:

- Source keys: `BALLDONTLIE_API_KEY`, `POLYMARKET_API_KEY`.
- Controls: `BANKROLL`, `EDGE_THRESHOLD`, `MAX_BET_FRACTION`, `MAX_OPEN_POSITIONS`,
  `MAX_EXPOSURE_FRACTION`, `STOP_LOSS_FRACTION`, `POLL_INTERVAL_MS`, `DRY_RUN`,
  `CANON_URL`, `LOG_PATH`.
- `WALLET_PRIVATE_KEY` is read by a separate non-dry CLI path; it is not a requirement
  for Canon's dry-run entrypoint. Check `CANON.md` for the synthetic-data limitations.

**`prediction-edge`** — inspect `.env.example`, `src/index.ts`, and `CANON.md`:

- Endpoints: `POLYMARKET_API_URL`, `POLYMARKET_CLOB_URL`, `POLYGON_RPC_URL`.
- Controls: `DRY_RUN`, `MAX_POSITION_SIZE_USD`, `STOP_LOSS_THRESHOLD`,
  `DAILY_LOSS_LIMIT_USD`, `MIN_WIN_RATE_THRESHOLD`, `MIN_EDGE_THRESHOLD`,
  `MOMENTUM_LAG_WINDOW_MS`, `INJURY_POLL_INTERVAL_MS`, `SIGNAL_COOLDOWN_MS`.
- `PRIVATE_KEY` is not needed for Canon dry-run. Simulated fills and P&L must remain
  labeled as simulated results.

**`courtshock`** — most settings are in `strategy.config.json`, not environment variables:

- Review bankroll, scoring/risk configuration, replay scenarios, and player data paths.
- `THE_ODDS_API_KEY` is optional for the odds adapter.
- `canon/entry.ts` strips wallet variables and forces dry-run; do not add a funded key
  merely to satisfy unrelated legacy documentation.

**`market-forecast`** — inspect `.env.example` and `src/config/env.ts`:

- Public/data settings: `POLYMARKET_HOST`, `KALSHI_BASE_URL`, `KALSHI_ENV`,
  `BALLDONTLIE_API_KEY`.
- Authenticated connector settings, only when that connector requires them:
  `POLYMARKET_PRIVATE_KEY`, `POLYMARKET_API_KEY`, `POLYMARKET_API_SECRET`,
  `POLYMARKET_API_PASSPHRASE`, `KALSHI_API_KEY_ID`, `KALSHI_PRIVATE_KEY_PATH`.
- Controls: `DRY_RUN`, `POLL_INTERVAL_MS`, `INITIAL_CAPITAL`, `MAX_DRAWDOWN_PERCENT`,
  `DAILY_LOSS_LIMIT`, `KELLY_FRACTION`. A private-key *path* identifies a protected local
  file; it is not an instruction to paste the key contents into a URL or command.

**`nba-playoff-bot`** — inspect `.env.example`, `src/index.ts`, and `canon/entry.ts`:

- `DRY_RUN`, `MIN_EDGE_THRESHOLD`, `MAX_TRADE_AMOUNT`, `CANON_POLL_INTERVAL_MS`.
- `POLYMARKET_API_KEY` is for the submission path, not required by Canon dry-run.
- The default cycle interval is five minutes; two cycles may take substantially longer
  than a short UI demonstration.

**Curated Core templates:**

- `core-arb-binary`, `core-mm-premium`, and `core-trade-momentum` use `POLL_INTERVAL_MS`
  and their `strategies/<strategy-name>/config.ts`; inspect `canon/start.ts`.
- `core-mint-01` uses `MINT_POLL_INTERVAL_MS`; inspect `curated/main.ts`.
- These curated entrypoints do not need a funded wallet. Inherited/shared files may
  mention `WALLET_PRIVATE_KEY`, `WALLET_PROXY_ADDRESS`, legacy `POLYMARKET_PRIVATE_KEY`
  and `POLYMARKET_PROXY_ADDRESS`, or a **project-local** `.canon/wallet.env`. That is
  distinct from the user-profile chat file `~/.canon/wallet.env` and is not a prerequisite
  for the curated dry-run paths.

The prepared project lifecycle adapters supply mode/entrypoint controls. Do not try to obtain live execution
by changing a dry-run flag in `.env`. Live execution needs a separate review of the
actual entrypoint, wallet, chain, venue permissions, credentials, and confirmation flow;
some curated templates deliberately provide no live execution path.

### Provider credentials and advanced overrides

Agent-provider authentication is independent of the template settings above. Prefer
the provider's browser-login procedure for an initial setup. If your organization
uses API keys, use its documented credential storage; do not put provider credentials
in the chat wallet file.

- Claude: [official setup/authentication](https://code.claude.com/docs/en/setup).
- Codex: [official CLI and authentication links](https://developers.openai.com/codex/cli/).
- Gemini: [Google login, API-key, and Vertex AI options](https://geminicli.com/docs/get-started/authentication/).

The list above covers Canon/DEGA settings and the audited templates' main configuration
interfaces. It is not an exhaustive list of every operating-system or third-party SDK
variable. Use the relevant provider's reference for proxies, enterprise endpoints,
cloud identities, and advanced authentication.


### Source and verification notes

Canon behavior was checked against the application source corresponding to public
snapshot `5eb6a68540194c30f9352e465cf82c9457038236`. Template configuration was audited
against strategy-repository source/archive state `f53d52a`; downloaded versions can differ.
These identifiers record the audit, not a claim that a newer published guide changes
those application behaviors.

Code references for maintainers:

- [Agent definitions](https://github.com/DEGAorg/canon/tree/main/src/toad/data/agents)
- [Chat file parser and defaults](https://github.com/DEGAorg/canon/blob/main/src/toad/extensions/dega_panel/auth_store.py)
- [Chat registry configuration](https://github.com/DEGAorg/canon/blob/main/src/toad/extensions/dega_panel/registry_client.py)
- [Chat wallet identity](https://github.com/DEGAorg/canon/blob/main/src/toad/extensions/dega_panel/chat_identity.py)
- [Strategy installer](https://github.com/DEGAorg/canon/blob/main/src/toad/extensions/dega_panel/installer.py)
- [Managed runner](https://github.com/DEGAorg/canon/blob/main/src/toad/extensions/dega_panel/runner.py)

This guide was researched and checked; it is not a report that every provider login,
live data service, or new user's funded mainnet registration was executed during writing.
