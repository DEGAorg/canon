# Getting started with Canon

Go from a new computer to your first automation dry-run, chat contact, and room.
Last checked: **18 September 2026**.

**Canon** is the app. **Core** adds the agent workflows. Your **coding agent** helps
with setup and automations. **DEGA AI Agents** handles your DEGA account and Elements.
You need only one coding agent.

Follow the steps below in order. Environment variables, contract addresses, wallet
changes, and technical details are in the [configuration reference](docs/getting-started/configuration.md).
For platform-specific installation, adapter problems, or errors, use
[setup and troubleshooting](docs/getting-started/setup-and-troubleshooting.md).

## 1. Prepare your computer

Use macOS or Linux. On Windows, first follow
[Microsoft's WSL guide](https://learn.microsoft.com/en-us/windows/wsl/install), then
run these steps inside the Linux terminal.

Install these tools using their official instructions:

| Requirement | Install from |
| --- | --- |
| Git | [Git installation](https://git-scm.com/install/) |
| Node.js LTS, including npm/npx | [Node.js downloads](https://nodejs.org/en/download) |
| uv, for Canon's Python environment | [Astral uv installation](https://docs.astral.sh/uv/getting-started/installation/) |

For macOS/Linux/WSL, uv's installation command is:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Reopen your terminal, then check the tools and install Canon's Python runtime:

```bash
git --version
node --version
npm --version
uv --version
uv python install 3.14
python3 --version
```

If `python3` is missing, run `uv python install 3.14 --default`, reopen the terminal,
and check again. Core needs the `python3` command as well as Canon's Python environment.
See [uv's Python guide](https://docs.astral.sh/uv/guides/install-python/).

You also need internet access and a browser. Core will identify additional tools
such as pnpm, jq, or tmux when required. You do not need your own server or database.

## 2. Install and sign in to one coding agent

Choose **one** and follow its official installation and login instructions:

| Agent | Official setup | Start it after installation |
| --- | --- | --- |
| Claude Code | [Anthropic quickstart](https://code.claude.com/docs/en/quickstart) | `claude` |
| Codex CLI | [OpenAI CLI guide](https://developers.openai.com/codex/cli/) | `codex` |
| Gemini CLI | [Google installation](https://geminicli.com/docs/get-started/installation/) and [login](https://geminicli.com/docs/get-started/authentication/) | `gemini` |

Complete the browser authentication, then send a simple prompt to confirm the agent
responds. Your provider may require a subscription, billing, or account eligibility;
this is separate from your DEGA account.

Canon connects some agents through an additional adapter. Follow the
[adapter setup for your chosen agent](docs/getting-started/setup-and-troubleshooting.md#agent-installation-details)
before launching it inside Canon. That page also links
[official videos and tutorials](docs/getting-started/setup-and-troubleshooting.md#official-docs-and-videos).

## 3. Install Core

Paste this **into your authenticated agent**, not into the terminal:

> Read and follow https://raw.githubusercontent.com/DEGAorg/claude-code-config/main/commands/apply-core.md.
> Install DEGA Core for my agent, including Canon Bootstrap and its required skills,
> commands, dependencies, and state writer. Preserve existing settings. Verify the
> installation and report any blockers. Do not fund wallets or run live trading.

Choose **Canon Bootstrap** when offered. Wait for the agent to confirm it is installed.
Restart the agent if it cannot discover the new skills.

## 4. Install Canon

In the same agent, paste:

> Follow https://github.com/DEGAorg/canon/blob/main/INSTALL.md to install the public
> Canon app and prepare its wallet and configuration. Preserve existing wallets,
> identity files, and settings. Report the installed version, public wallet address,
> network, and current chat registration requirements. Never print private keys.
> Do not fund, approve, register, or trade on my behalf.

This guided procedure covers more than installing the app binary. Keep a private
backup of your wallet as instructed. Never share the private key in chat or support tickets.

Verify installation in a new terminal:

```bash
canon --version
```

If you prefer manual installation, use the
[manual setup instructions](docs/getting-started/setup-and-troubleshooting.md#manual-app-installation-if-you-prefer).

## 5. Open Canon and sign in

Create a project folder and launch Canon:

```bash
mkdir -p ~/canon-projects/my-first-automation
cd ~/canon-projects/my-first-automation
canon .
```

1. Select your installed coding agent in Canon and launch it using the displayed
   controls. Send a simple prompt to verify it responds **inside Canon**.
2. Open **[DEGA AI Agents](https://ai-agents.degaplatform.com/)** in your browser and
   sign in or create your account.
3. In Canon, press **Ctrl+G → DEGA → Sign in**.
4. Open Canon's verification link, approve the device code with the intended DEGA
   account, then return to Canon.
5. Confirm the connected email. Open **Strategies** to see your Elements.

Your coding-agent login and DEGA login are separate. If Elements cannot load, resolve
the displayed error before activating a strategy.

## 6. Activate an automation with Elements

1. In **DEGA → Strategies**, select a template and read its description.
2. Choose **Activate access** or press **a** with the catalogue focused.
3. Review the Element cost, selection limits, and duration before confirming. A new
   purchase permanently consumes the cheapest affordable option chosen by the backend.
   An available purchased slot or existing active grant can avoid new consumption.
4. Install the template using the displayed action or **i**.

If you lack the required Elements, resolve that through your DEGA account first.
Elements for strategy access are different from the on-chain DEGA tokens used for chat.

## 7. Run your first automation in dry mode

In the agent conversation **inside Canon**, paste this, naming your chosen template:

> Use the installed canon-start workflow for the template I activated. Prepare its
> editable copy in this project, preserve its strategy logic, and configure dry-run
> only. Tell me which credentials or services are missing. Validate the package and
> project, then launch through the supervised Canon project lifecycle. Verify at least
> two completed cycles and continued process liveness. Report whether data is live,
> recorded, or synthetic. Do not submit real orders.

For Claude, the entrypoint is `/canon-start`; for Codex it is `$canon-start`.
You can also ask for it in natural language. Follow the agent's configuration prompts
and supply secrets only through the protected local files it identifies.

Watch the project's state and execution output in Canon. Some templates need external
API keys, and a cycle may take several minutes. A running server or an empty signal
table alone does not mean the automation has completed a successful cycle.

When two cycles have completed, ask:

> Stop this project's Canon supervisor and verify that its strategy processes have
> exited. Preserve my source, configuration, and logs.

**Use this project workflow for the first run.** The Strategies tab's **r/x** shortcuts
control a separate package runner; they are not substitutes for this supervised setup.
See [execution details](docs/getting-started/setup-and-troubleshooting.md#launch-through-the-project-lifecycle-observe-and-stop)
if you need to diagnose which process is running.

Dry-run means no real orders, not necessarily live market data. It is not a guarantee
of profitable trading. Missing data credentials are a configuration blocker, not a
successful test.

## 8. Register for chat

You can complete the automation steps before funding chat.

1. Open **DEGA → Chat → Profile** and verify the public wallet address matches your
   installation handoff. If no wallet is configured, complete the installer first.
2. Confirm the network and current registration fee. Fresh defaults use **Ethereum
   mainnet**; existing settings are preserved. The installer should verify them.
3. Send the required **Ethereum-mainnet DEGA** and enough **mainnet ETH for gas** to
   that wallet address—not to a contract address. Gas varies; approval and registration
   may require separate transactions.
4. Enter your desired username. Review the address, network, and fee **before** choosing
   **Start chat**. That button can immediately sign and submit the approval/registration;
   there is no additional initial-registration confirmation screen.
5. Wait for an active registration. If a transaction times out, keep its hash and check
   its status before trying again. A timeout does not necessarily mean failure.

If already registered, reuse the identity. Registration status and **Renew** are inside
**Registration**; renewal shows terms for confirmation.

For contract addresses, wallet changes, and environment settings, use the
[configuration reference](docs/getting-started/configuration.md#mainnet-reference).

## 9. Add a contact and create a room

**Add a contact:**

1. Ask another registered Canon user for their exact chat username.
2. Choose **Contacts → Add contact**, enter the username, and confirm.
3. Select the saved contact, type a message, and press **Enter** or **Send**.

**Create a room:**

1. Choose **Rooms → New room**, enter a name, and select **Create**.
2. Open **Members and settings**, choose a saved contact, and select **Invite contact**.
3. The other person opens the invitation and chooses **Accept**. Keep the room owner
   online until membership becomes active.
4. Send a room message and confirm the other person receives it.

Both creation forms have **Cancel**, which returns to the previous conversation and
draft. Contacts, room invitations, and messages do not require another registration
payment. Keep one Canon process per chat identity.

## You are ready

- Your agent responds inside Canon and the correct DEGA account is connected.
- Your selected automation completed two supervised dry-run cycles and stopped cleanly.
- If funded, your chat identity is active and you exchanged direct and room messages.

For help, configuration changes, or updates:

- [Setup, adapters, troubleshooting, updates, and official videos](docs/getting-started/setup-and-troubleshooting.md)
- [Environment variables, contracts, wallets, and all 11 templates](docs/getting-started/configuration.md)
