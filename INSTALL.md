# Install Canon TUI

## For AI agents — bootstrap instructions

You are installing Canon TUI (`canon-app`), a terminal interface for visualizing AI agent
activity. It provides the `canon` and `canon-ctl` binaries via `uv tool install`.

The public repository is `DEGAorg/canon`, branch `main`. The installed Python
package is named `canon-app`; its executable is `canon`.

### 1. Install from the repository or the built wheel

1. Check prerequisites:

   ```bash
   command -v uv >/dev/null 2>&1 || curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. Get the public code and install it:

   ```bash
   git clone --branch main https://github.com/DEGAorg/canon.git
   cd canon
   bash install.sh                                   # uv tool install . --force --reinstall
   ```


3. Verify:

   ```bash
   canon --version
   ls -la ~/.local/bin/canon
   ```

### 2. Prepare the wallet

Complete these steps as the installing agent; do not hand the user a list of ENV
edits or diagnostic commands. Core and strategy skills are a separate installation.
On Windows, install and run inside WSL; keep the profile on its Linux filesystem.

1. Use the user's OS account and `~/.canon` profile. Preserve existing files and
   wallets. Back up any configuration before an explicitly requested change.
2. Check for an existing effective signing key: `DEGA_CHAT_PK` in
   `~/.canon/dega-chat.env`, then the process environment, then
   `WALLET_PRIVATE_KEY` in `~/.canon/wallet.env`. Reuse the configured identity.
   Never silently replace it or generate a wallet that an existing override hides.
3. If no signing key exists, generate a cryptographically random Ethereum account
   with `eth_account.Account.create()` and write `WALLET_PRIVATE_KEY=<key>` to
   `~/.canon/wallet.env`. Use exclusive creation, directory mode 0700 and file
   mode 0600. If the file already exists but is malformed or lacks a key, preserve
   it and report the conflict instead of overwriting it.
4. Derive the public address from the effective key. Never print the private key,
   put it in command arguments, agent messages, logs, Git or the final report.
   Keep existing chat identity files intact.

`eth-account` is already installed with Canon. The installer agent can use the
installed tool's Python, without installing a second copy:

```bash
CANON_PYTHON="$(uv tool dir)/canon-app/bin/python"
```

Run wallet handling with that interpreter, keeping key values inside the process
and writing them directly to the protected file. Do not use shell tracing.

### 3. Generate the configuration

Create `~/.canon/dega-chat.env` with mode 0600 **before the first launch** when it
is absent. Leave `DEGA_CHAT_PK` empty so the generated wallet file supplies the key.
Preserve existing settings on reinstallation; report a mismatched network or
registry rather than silently changing an existing user's environment.

Resolve the network, backend URL, registry and token from the release's maintained
configuration defaults and deployment documentation; see
[configuration.md](docs/dega/configuration.md). Do not duplicate contract addresses
or network values in this installation guide. Updating deployment settings must
not require changing the user's installation command.

Generate the configuration using those release settings, with `DEGA_CHAT_PK` empty
when the wallet file supplies the key. Use exclusive file creation so a concurrent
launch cannot overwrite an existing ENV. Never copy the wallet key into the
configuration. If shipped defaults and deployment documentation disagree, report
the conflict rather than guessing or silently selecting a different network.

The agent performs checks internally: installed binaries, readable protected
wallet/configuration, effective wallet address, configured network, registry/token
contract code, matching `degaToken()`, token decimals, and current fee/TTL. Use
Canon's installed Web3 dependency. Read current terms from the configured registry;
do not assume a fixed fee or duration. If a check fails, report the actual result
instead of claiming readiness or changing contract settings. Do not send approvals,
register, fund wallets, deploy contracts or launch trading as part of installation.

### 4. Give the user the handoff

End with a short report, not another setup assignment:

- **Status:** installed and ready for funding/registration, or the specific blocker.
- **Wallet:** public address and whether it was created or reused.
- **Key storage:** local file path only (or identify an existing environment key).
  Tell the user to keep a private backup; losing the key loses access to that wallet.
- **Network:** the configured network, explicitly identifying testnet or mainnet.
- **Funding:** specify the configured network’s gas currency and fee token, and
  the current registration fee, payable from the displayed wallet address. Clearly
  distinguish test tokens from real assets when using a testnet.
- **Launch:** `canon .` from their project folder; no `uv run` is needed.
- **Next:** choose/sign into an AI agent if using agent workflows; for DEGA,
  use the panel to sign in, then choose a chat username, approve and register
  after funding. Core remains separate.

Record the installed commit/package version in the report. Do not ask the user
to inspect ENV files, run blockchain checks or share their private key.
This is an **agent-guided installation procedure**; `bash install.sh` alone
installs the binaries and does not generate the wallet or this configuration.

---

## For humans — guided setup

Give your coding agent this instruction:

> Install Canon from DEGAorg/canon main following INSTALL.md. Complete app installation, wallet preparation, configuration and the final handoff. Preserve existing wallets and settings.

For a binary-only installation (wallet/configuration still need the steps above):

```bash
git clone https://github.com/DEGAorg/canon.git && cd canon && bash install.sh
canon .                  # launch in the current project directory
```

Then open the DEGA panel with `Ctrl+G → DEGA` (Utility / Chat). See
[docs/dega/setup.md](docs/dega/setup.md) for the first-run onboarding (the DEGA env file is
generated automatically) and [docs/dega/README.md](docs/dega/README.md) for the full index.

---

## What gets installed

| Binary | Purpose |
|--------|---------|
| `canon` | TUI (agents, DEGA panel, chat, strategies) |
| `canon-ctl` | Socket/agent control interface (`canon-ctl raw '{...}'`) |

Installed via `uv tool install` into an isolated environment. No system Python packages are
modified. Two tools ship the same executables (`canon-tui` legacy and `canon-app`), so whichever was
installed last owns `~/.local/bin/canon`; `uv tool list` alone does not tell you which one is live.

## Usage

```bash
canon .                      # launch the TUI in the current project directory
canon -a <agent>             # skip the agent picker
canon serve                  # run Canon as a web app
canon-ctl raw '{"cmd":"room","action":"list"}'   # agent-facing control channel
```

## Updating

Update from the repository you originally installed from:

```bash
cd canon && git pull && bash install.sh
```

Alternatively, use `canon update` to reinstall from this repository, or
`canon update --check` to compare the installed and source versions.
