# Canon setup details and troubleshooting

[Start with the beginner guide](../../GETTING_STARTED.md) · [Configuration reference](configuration.md)

Detailed platform setup, agent adapters, manual installation, execution-path differences,
troubleshooting, and official learning resources. Last checked: 18 September 2026.

## Platform and dependency setup

### Choose the right terminal

On macOS, open Terminal or your preferred terminal app. On Linux, open a terminal.
On Windows, install WSL and run the rest of this guide **inside the Linux terminal**.
Keep the project and `~/.canon` in that Linux home directory, rather than mixing Windows
and WSL installations.

Microsoft's official starting command, run in an administrator PowerShell window, is:

```powershell
wsl --install
```

Restart if requested, open the installed Linux distribution, and finish creating its
Linux user. See [Microsoft's WSL installation guide](https://learn.microsoft.com/en-us/windows/wsl/install).

### Required and optional tools

| Tool | Why you need it | Official instructions |
| --- | --- | --- |
| Bash, `curl`, and Git | Execute installation scripts and retrieve public source | [Git](https://git-scm.com/install/), [curl](https://curl.se/docs/install.html) |
| `uv` | Installs Canon in its own Python environment | [Astral uv installation](https://docs.astral.sh/uv/getting-started/installation/) |
| Python 3.14+ | Canon's runtime; `uv` can download it | [Python management with uv](https://docs.astral.sh/uv/guides/install-python/) |
| Node.js with npm/npx | Agent adapters and JavaScript/TypeScript templates | [Node.js downloads](https://nodejs.org/en/download) |
| `pnpm` | Some Core components and templates | [pnpm installation](https://pnpm.io/installation) |
| `jq`, `tmux` | Core hooks/orchestration and launcher features that use them | [jq](https://jqlang.org/download/), [tmux](https://github.com/tmux/tmux/wiki/Installing) |
| Browser and internet | Agent authentication, DEGA device approval, downloads, and services | Use a browser on the same computer for the easiest setup |

Use a supported Node.js **LTS** release; the official page listed Node 24 LTS when
this guide was checked. Follow a template's `engines` and `packageManager` constraints
if it needs a particular version. You do not need Docker, a production database,
a blockchain node, or a contract deployment for ordinary Canon use.

Provider requirements differ: Anthropic documents macOS 13+, Ubuntu 20.04+/Debian 10+
and at least 4 GB RAM for Claude Code. Gemini's current docs list macOS 15+ or
Ubuntu 20.04+, Node 20+, and 4 GB for light use/16 GB for heavier sessions. Check the
[Claude requirements](https://code.claude.com/docs/en/setup) and
[Gemini requirements](https://geminicli.com/docs/get-started/installation/) for your chosen route.
Canon plus an agent and an automation needs more resources than a CLI running alone.

### Install the basic tools

For macOS, Git's official page explains Command Line Tools and package-manager options.
If you use [Homebrew](https://brew.sh/), install it following its website first; then:

```bash
brew install git jq tmux
```

On Ubuntu or Debian, including Ubuntu inside WSL:

```bash
sudo apt-get update
sudo apt-get install -y git curl ca-certificates jq tmux
```

Install Node.js using the **official download page's instructions for your OS**.
Open a new terminal and verify:

```bash
git --version
curl --version
node --version
npm --version
npx --version
```

Install uv using Astral's official macOS/Linux installer:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Open a new terminal so PATH changes take effect, then:

```bash
uv --version
uv python install 3.14
uv tool update-shell
python3 --version
```

Core also calls the unversioned `python3` command. If that command is missing, run
`uv python install 3.14 --default`, reopen the terminal, and verify `python3 --version`.
Do not change an existing system Python merely to install Canon.

The Python installation is explicit here for a predictable setup; uv can also fetch
missing Python versions automatically. See [uv Python management](https://docs.astral.sh/uv/guides/install-python/)
and [tool installation](https://docs.astral.sh/uv/concepts/tools/).

If Core or your chosen template requires pnpm, use its
[official installation guide](https://pnpm.io/installation), then check `pnpm --version`.
Install package dependencies with that package's own manager and lockfile; do not
replace a pnpm lockfile with a new npm lockfile to work around an error.

**Checkpoint:** Git, Node/npm/npx, and uv are available in the same terminal where
Canon will run. A `.sh` file is a shell script, not a separate app dependency.
Use `bash install.sh` only from a directory that actually contains that script.

## Agent installation details

Choose **one** option below. Finish its browser login before using it in Canon.
A browser-only AI chat account or desktop app does not establish that its CLI and
Canon adapter are installed.

### Option A: Claude Code

Anthropic's official native installer for macOS/Linux/WSL:

```bash
curl -fsSL https://claude.ai/install.sh | bash
```

Reopen the terminal if needed, then:

```bash
claude --version
claude
```

Complete the authentication prompts using an account with Claude Code access or
another supported provider billing arrangement. Follow the
[official quickstart](https://code.claude.com/docs/en/quickstart) and
[setup/authentication instructions](https://code.claude.com/docs/en/setup).

The audited Canon release launches `claude-code-acp`, supplied separately:

```bash
npm install -g @zed-industries/claude-code-acp
command -v claude-code-acp
```

This is an **ACP-maintainer package**, not Anthropic's installer. See the
[adapter's upstream repository](https://github.com/agentclientprotocol/claude-agent-acp)
and the compatibility note below. Exit the standalone Claude session when finished;
Canon will start its own agent connection.

### Option B: Codex CLI

OpenAI's official standalone installer for macOS/Linux:

```bash
curl -fsSL https://chatgpt.com/codex/install.sh | sh
```

Open a new terminal if necessary, then:

```bash
codex --version
codex
```

Complete the offered authentication flow, such as Sign in with ChatGPT. See
[OpenAI's Codex CLI documentation](https://developers.openai.com/codex/cli/).

Canon's bundled Codex definition launches `npx @zed-industries/codex-acp`.
This is a separate ACP adapter; npm/npx and network access must be available.
The adapter may ask for authentication too. Follow its prompts rather than assuming
that every adapter version shares the CLI's existing login. See the
[adapter maintainer's instructions](https://github.com/zed-industries/codex-acp).

### Option C: Gemini CLI

With a supported Node.js installed:

```bash
npm install -g @google/gemini-cli
gemini --version
gemini
```

Choose **Sign in with Google** and finish the browser flow, or follow Google's
API-key/Vertex AI route if that is how your organization authenticates.
Personal and organization accounts have different project requirements. See
[Google's installation guide](https://geminicli.com/docs/get-started/installation/)
and [authentication guide](https://geminicli.com/docs/get-started/authentication/).

The audited Canon definition invokes `gemini --experimental-acp`; it does not use
the Claude or Codex adapter. If your installed Gemini version rejects that flag,
report the exact version and error instead of substituting an unrelated launch command.

### Adapter compatibility note

On the date checked, npm marks the `@zed-industries/claude-code-acp` and
`@zed-industries/codex-acp` package names as deprecated in favor of
`@agentclientprotocol/claude-agent-acp` and `@agentclientprotocol/codex-acp`.
Canon's audited definitions still use the older names. A deprecation notice is not
proof that launch succeeded or failed. Installing only a renamed binary does not
change the command Canon expects.

The guide documents the shipped integration; it does not claim that every latest
agent/adapter combination was tested. If an adapter fails, keep the error and request
a compatible Canon release rather than bypassing its integration.
Sources: [Claude package metadata](https://registry.npmjs.org/@zed-industries/claude-code-acp/latest),
[Codex package metadata](https://registry.npmjs.org/@zed-industries/codex-acp/latest), and
[Canon agent definitions](https://github.com/DEGAorg/canon/tree/main/src/toad/data/agents).

**Checkpoint:** your selected CLI can answer a simple prompt such as “Say hello”
after authentication. You will check the Canon connection separately in the beginner guide’s “Open Canon and sign in” step.


## Manual app installation, if you prefer

```bash
uv tool install 'git+https://github.com/DEGAorg/canon.git@main' --force --reinstall
uv tool update-shell
```

Open a new terminal, then verify:

```bash
canon --version
canon --help
command -v canon
command -v canon-ctl
```

Alternative checkout-based installation:

```bash
git clone https://github.com/DEGAorg/canon.git
cd canon
bash install.sh
```

Choose one installation route. Do not clone the application repository into the
folder where you intend to develop your strategy.

**Manual installation checkpoint:** binaries exist, but that alone does not prove
a signing wallet was prepared. Follow the wallet/configuration portions of
[INSTALL.md](https://github.com/DEGAorg/canon/blob/main/INSTALL.md), preferably with your
agent. A fresh launch generates missing chat defaults; it does not replace the
explicit wallet-preparation step. Keep a private backup of the signing key and chat
profile. Do not paste those secrets into an agent conversation or support ticket.


## Prepare an editable Canon project

The panel download is the authorized source package. The **Core project lifecycle**
uses an editable copy in your project. Ask the agent inside Canon:

> Use the installed canon-start workflow in this project, in dry-run mode only.
> Use the exact template I activated; verify it appears in `canon strategies`.
> Scaffold the project and copy the authorized source into `strategies/<key>`, preserving
> any existing edits and excluding private environment files, dependencies, and runtime state.
> Read its README, CANON.md, manifest, lockfile, and actual entrypoint. Follow its Canon
> adapter preparation instructions, and preserve the strategy logic. List missing
> credentials without exposing secrets. Run the package's own checks and the root
> adapter checks separately, with nonzero executed tests. Continue through the supervised
> project dry-run. Do not trade live, substitute another strategy, or fabricate results.

Do not type the angle-bracket placeholder literally; name the selected template in
your request. The agent should record it in `docs/strategy-<key>.md`, configure
`strategies/<key>/` using that package's manager/lockfile, and wire the project's
`src/main.ts` to the prepared adapter. Put secrets only in the file that this editable
package actually loads. The current Core workflow does not require wallet creation,
funding, or onboarding for dry-run initialization.

**Verify your Core workflow is current:** it must select from `canon strategies`,
prepare the editable package, and check both the package and root adapter. If it instead
auto-selects a Core example or asks to fund a wallet just to initialize dry-run, update
Core before continuing. See the [maintained canon-start workflow](https://raw.githubusercontent.com/DEGAorg/claude-code-config/main/commands/canon-start.md).

### Launch through the project lifecycle, observe, and stop

1. Have the agent continue `canon-start` through its supervised **dry-run** phase,
   without `--live`. Review the selected source and entrypoint before launch.
2. In Canon, inspect the project State/Flow/Execution information. The project's
   `.canon/state.json`, `.canon/flow.json`, and `.canon/execution/` contain the relevant
   state/logs. Ask the agent for the actual supervisor PID, child process, and log path.
3. Wait for **at least two completed cycles**, allowing for the configured interval
   and API latency. Confirm the supervisor and strategy remain alive after the launch
   command returns and between cycles.
4. Ask whether the run used live data, recorded fixtures, or synthetic inputs. A server
   starting, an empty signal table, or “no errors” alone does not prove correct execution.
5. Ask the agent: “Stop this project's recorded Canon supervisor and verify its strategy
   process and descendants exit cleanly. Preserve source, configuration, and logs.”
6. Confirm stopped state before restarting. Do not kill unrelated Node/Python processes.

**The Strategies tab's `r` and `x` shortcuts are a different runner.** They run/stop a
package script in the global download directory, selected from `package.json`. They do
not automatically prepare or manage the editable Core project adapter. Some packages'
ordinary scripts differ from their `CANON.md` entrypoint and may be one-shot commands.
Do not use `r` as a substitute for the supervised path above or assume its “dry-run”
label alone proves order safety. The separate panel runner logs to
`~/.canon/execution/<strategy-key>.log`; its Stop action does not stop the Core supervisor.

**Dry-run means no real order submission.** It does not guarantee live market data or
remove the need for data credentials. Some templates intentionally simulate prices/fills.
See the [per-template configuration reference](configuration.md#automation-specific-environment-reference). A completed dry-run does not establish profitability
or live-trading readiness.

**Checkpoint:** the editable source and configuration are recorded, two supervised cycles
completed, data mode is understood, and the supervisor and descendants stopped cleanly.
If a service/key is missing, record “blocked by configuration” instead of “working.”


## Troubleshooting and updates

| Symptom | What to check next |
| --- | --- |
| `uv`, `node`, or `canon`: command not found | Reopen the terminal; check PATH and `command -v <tool>`. Run `uv tool update-shell` for uv-installed tool paths. Do not install a second copy blindly. |
| `claude-code-acp` missing, or Codex adapter will not start | Check Node/npm/npx and the exact launch command in the shipped agent definition. See the adapter compatibility note. A standalone CLI login is not proof the adapter works. |
| Core instruction URL cannot be read | Check connectivity and repository access. Report the failure; do not claim Canon Bootstrap was installed. |
| `canon-start` missing | Verify Canon Bootstrap and the host-specific skill/command installation; restart the agent session. |
| Canon opens, but the agent cannot answer | Finish the selected provider/adapter authentication and check provider access/quota. DEGA login does not pay for or authenticate that provider. |
| Login points at localhost or the wrong service | Check `DEGA_API_URL` in both the launching shell and chat file. The shell wins for this key; correct it and restart Canon. |
| Chat still points to an old network | Existing configuration is preserved. Review `DEGA_CHAT_RPC` and `DEGA_CHAT_REGISTRY` in the chat file, which win over shell values, then restart. |
| Elements are unavailable | Check the connected account and backend reachability. Reconnect after resolving the error; do not edit the balance cache. |
| Strategy download denied | Check authentication, current grant, and the displayed access policy. Activation consumes Elements; copying a cache does not grant download access. |
| Template installed but exits immediately | Read its package-context logs, missing dependencies, entrypoint, data keys, and interval. A missing service/key is a configuration blocker. |
| No signals | Verify completed cycles, source responses, market availability, and filters. No signal may be a valid decision; it does not prove strategy correctness. |
| App package runner reaches its memory limit | Check the template's use and machine capacity. `DEGA_STRAT_MEM_MB` applies to that runner; it is not the Core supervisor's universal memory setting. |
| Chat says wallet not configured | Verify the effective chat key source without printing it. Complete INSTALL.md's wallet step, then verify the public address. |
| Registration transaction timed out | Save the hash; check the configured chain's transaction status and Canon's registration state. Pending is not failed. Do not create another wallet or repeatedly register. |
| Contact not found | Check spelling, active registration, network/registry, and the contact's chat key. |
| Room remains Joining | Keep the owner online so membership confirmation can complete; check relay connectivity. |
| Message failed | Keep its error and check relay/network state. Use room delivery retry where offered; publication is not a read receipt. |
| Edited source has no effect | Verify which runner you launched. Panel `r` runs the global download; the supervised project uses the prepared editable copy under `strategies/<key>`. |

To update the **app**, stop strategies, close Canon, and reinstall the published source:

```bash
uv tool install 'git+https://github.com/DEGAorg/canon.git@main' --force --reinstall
```

For reproducibility, replace `main` with a published commit. A commit from a private
repository may not exist publicly. The public repository may be refreshed as a new
single-commit snapshot; a stale local clone may not support a normal fast-forward pull.
Use the installation command above rather than force-resetting a folder with personal edits.

Restart `canon .` from your project afterward. Updating the app does not automatically
update Core, rewrite an existing chat configuration, or replace your edited templates.
Update Core using its maintained procedure; back up template modifications before
reinstalling a template.


## Official docs and videos

Videos illustrate workflows; use current installation documentation for commands and
requirements. A video's model names or interface can differ from today's release.

| Topic | Official documentation | Official video/demo, where verified |
| --- | --- | --- |
| Claude Code | [Quickstart](https://code.claude.com/docs/en/quickstart), [requirements](https://code.claude.com/docs/en/setup) | [Anthropic: Claude Code Foundations](https://www.anthropic.com/webinars/claude-code-foundations). Webinar page; access/recording may require registration. |
| Codex CLI | [OpenAI CLI guide](https://developers.openai.com/codex/cli/) | [Using OpenAI Codex CLI with GPT-5-Codex](https://www.youtube.com/watch?v=iqNzfK4_meQ), linked by the [official OpenAI video library](https://learn.chatgpt.com/videos). Older demo, not current model advice. |
| Gemini CLI | [Installation](https://geminicli.com/docs/get-started/installation/), [authentication](https://geminicli.com/docs/get-started/authentication/), [Google hands-on codelab](https://codelabs.developers.google.com/gemini-cli-hands-on) | [Google for Developers: AI coding with Gemini CLI](https://www.youtube.com/watch?v=zEMXCoqJodE). Official channel; video playback was not tested for this guide. |
| uv and Python | [uv installation](https://docs.astral.sh/uv/getting-started/installation/), [Python management](https://docs.astral.sh/uv/guides/install-python/) | [Astral's uv announcement with embedded demonstrations](https://astral.sh/blog/uv-unified-python-packaging). Product demos, not a dedicated beginner installation course. |
| Node/npm | [Node.js official downloads](https://nodejs.org/en/download) | No separate official installation video verified for this guide. |
| Git | [Official Git installation](https://git-scm.com/install/) | Use the official written instructions; no installation video verified here. |
| WSL | [Microsoft installation instructions](https://learn.microsoft.com/en-us/windows/wsl/install) | No separate video required for the documented setup. |
| Core | [Maintained apply-core procedure](https://raw.githubusercontent.com/DEGAorg/claude-code-config/main/commands/apply-core.md) | No separate public Core installation video verified. |
| Canon | [INSTALL.md](https://github.com/DEGAorg/canon/blob/main/INSTALL.md), [README](https://github.com/DEGAorg/canon) | [DEGA walkthrough](https://youtu.be/_UwtkUlj_n8). Supplied by the project owner as private; it may require access and may show an older layout. |
