# Canon

**An AI workspace for building, running, and managing automations from your terminal.**

Canon brings coding agents, project tools, editable strategy templates, and DEGA chat
into one terminal application. Work with an agent in your project, configure a strategy,
run it in dry mode, and follow its execution without leaving the workspace.

## Getting started

**[Start here: the zero-to-Canon guide](GETTING_STARTED.md).**

Follow the complete sequence: prerequisites, coding-agent setup, Core and Canon
installation, DEGA login, strategy activation, your first supervised dry-run, and chat.

## What you can do

- **Build with agents.** Work with compatible coding agents, a shell, file navigation,
  diffs, and resumable sessions.
- **Use editable strategy templates.** Browse the DEGA catalogue, activate access with
  Elements, and prepare a template in your project.
- **Run and inspect automations.** Use Core's supervised project workflow to validate
  dry-runs, observe execution, and stop processes.
- **Chat with contacts and rooms.** Register a DEGA chat identity, exchange encrypted
  direct messages, and create invite-based group conversations.

Canon is the app. **DEGA Core** supplies the agent skills and project workflows.
**[DEGA AI Agents](https://ai-agents.degaplatform.com/)** provides account sign-in,
Element balances, and strategy access.

## Documentation

| Guide | What it covers |
| --- | --- |
| [Getting started](GETTING_STARTED.md) | From a new computer to a running automation and chat. |
| [Setup and troubleshooting](docs/getting-started/setup-and-troubleshooting.md) | Detailed installation, agent adapters, updates, troubleshooting, and official tutorials. |
| [Configuration reference](docs/getting-started/configuration.md) | Environment variables, contracts, wallets, and template-specific settings. |
| [Installation procedure](INSTALL.md) | The guided app installation and first-run setup used by your coding agent. |
| [DEGA documentation](docs/dega/README.md) | Integration details for strategy access, chat, rooms, and registration. |
| [Testing](docs/dega/testing.md) | Development checks and test guidance. |
| [Agent control interface](docs/socket-controller.md) | Programmatic interaction with Canon. |

For bugs or feature requests, [open an issue](https://github.com/DEGAorg/canon/issues).

## Attribution and license

Canon is built on [Toad](https://github.com/batrachian/toad), created by
[Will McGugan](https://github.com/willmcgugan), and the
[Textual](https://github.com/Textualize/textual) framework. Canon extends that foundation
with DEGA account integration, strategy workflows, and encrypted chat.

Licensed under [AGPL-3.0](LICENSE).
