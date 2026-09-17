# DEGA/Canon Operations Runbook

> **Superseded:** this file has been consolidated into [docs/dega/](dega/README.md). See
> [configuration.md](dega/configuration.md), [contracts.md](dega/contracts.md),
> [contract-deploy-testnet.md](dega/contract-deploy-testnet.md) and
> [sandbox-live.md](dega/sandbox-live.md). Kept as a historical redirect.

## Quick commands (still valid)
```bash
# TUI with the DEGA panel
cd ~/projects/DEGA/canon-app && uv run canon .

# Headless harness after UI changes
uv run python tools/verify-tui.py --widget dega

# Strategy logs
tail -f ~/.canon/execution/<key>.log
```

Apply to **testnet (Sepolia)**. Real live trading with funds is blocked and requires a Polygon
mainnet wallet — see [sandbox-live.md](dega/sandbox-live.md).

### Contract (Sepolia testnet) — historical

This section used to name "Registry v2 (active 09-04) `0x5FF86634…`". That deploy **allowed
multi-node and reverts `usernameOfOwner`** — it is not usable. The shipped default is the 09-15 v3
registry `0xf3D30Cf5…`, and the TTL deploy configured locally is `0x50600d8D…`; both use MockDEGA
`0x5f431e1a97b18C2a81c625E01B643BC836592455`.

- Current addresses, test counts and redeploy commands: [docs/dega/contracts.md](dega/contracts.md)
  and [docs/dega/contract-deploy-testnet.md](dega/contract-deploy-testnet.md).

### On-disk state
`~/.canon/{auth,chat-identity,chat-contacts,chat-inbox,installed}.json` (0600),
`~/.canon/strategies/`, `~/.canon/execution/<key>.log`.

### Chat (env config)
`DEGA_CHAT_BACKEND` (chain), `DEGA_CHAT_PK`, `DEGA_CHAT_REGISTRY`, `DEGA_CHAT_RPC`.

### Trading (blocked / paper-live)
`--confirm-real` signs against the Polymarket CLOB on Polygon mainnet. We use **paper-live**
(`--live` without `--confirm-real`). No funded `~/.canon/wallet.env` exists; do not pass
`--confirm-real`. See [sandbox-live.md](dega/sandbox-live.md).

---

See also: [docs/dega/README.md](dega/README.md) (index), DEGA vault.