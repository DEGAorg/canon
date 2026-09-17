# Conductor Setup Guide

Conductor extends Toad with project management features: a socket controller
for external automation, a Project State split-screen pane with a Gantt
timeline, and agent context injection so AI agents can control the TUI.

> **Heads up:** the agent canon-tui spawns is allowed to run deterministic
> infrastructure scripts (canon-scaffold.sh, canon-cli, pnpm install)
> directly — it does **not** delegate them. See
> [`conductor-execution-contract.md`](conductor-execution-contract.md) for
> the full contract, the `CANON_TUI` / `TOAD_CWD` env variables we set on
> the spawned agent, and how to file a tool-relay bug if the agent ever
> reports work it did not actually do.

## Prerequisites

- Python 3.14+ with the Toad venv set up (see main README)
- `socat` for the CLI client (optional but recommended)
  - **macOS**: `brew install socat`
  - **Linux**: `apt install socat` / `dnf install socat`
- `gh` CLI authenticated (for `/timeline` command updates)

## Quick start

```bash
# Clone and set up
git clone git@github.com:DEGAorg/canon.git
cd conductor-view
uv venv && uv pip install -e .

# Run Toad
.venv/bin/toad

# In another terminal — test the socket
tools/toad-ctl.sh ping
```

## Features

### Socket controller

A Unix socket server starts automatically when Toad launches at
`~/.canon/sockets/toad-{pid}.sock`. Processes running as your user can send JSON commands to read
state or trigger actions.

```bash
tools/toad-ctl.sh ping                                    # health check
tools/toad-ctl.sh action "screen.toggle_project_state"    # toggle pane
tools/toad-ctl.sh action "screen.refresh_timeline"        # refresh data
tools/toad-ctl.sh snapshot                                # widget tree
tools/toad-ctl.sh query "Button"                          # CSS query
```

Full protocol docs: [socket-controller.md](socket-controller.md)

### Project State pane

A toggleable right-side split pane showing a Gantt timeline.

- **Toggle**: `ctrl+g` or `toad-ctl.sh action "screen.toggle_project_state"`
- **Auto-refresh**: fetches fresh data every 60 seconds while visible
- **Data source**: live GitHub Issues API + Projects API via `gh` CLI

### Timeline configuration

The pane reads its timeline config from `dega-core.yaml` in the project root:

```yaml
timeline:
  repo: DEGAorg/claude-code-config
  project_number: 8
```

The provider fetches milestones, issues, and project board items from the
configured repo. Gantt bars are derived from Start Date → Target Date per
issue, grouped by milestone, colored by project board Status.

If no `dega-core.yaml` is found or `gh` is not authenticated, the timeline
shows an error message.

### Refreshing the timeline

The timeline auto-refreshes every 60 seconds. To trigger an immediate refresh:

```bash
tools/toad-ctl.sh action "screen.refresh_timeline"
```

### Agent context injection

On the first prompt of each session, Toad prepends instructions to the
agent so it knows about the socket controller. The agent can then run
`toad-ctl.sh` commands via its terminal tool.

The context file lives at `src/toad/data/agent_context.md`.

## Architecture

```
GitHub Issues + Projects API           conductor-view / Toad (consumer)
┌──────────────────────┐              ┌──────────────────────────────┐
│ Milestones, Issues,  │   gh CLI    │ ProjectStatePane             │
│ Project board items  ├───────────►│ fetches via provider / 60s   │
│                      │              │ renders GanttTimeline widget │
└──────────────────────┘              │                              │
                                      │ Socket controller            │
                                      │ ~/.canon/sockets/toad-{pid}.sock        │
         Agent / Script               │ ◄── JSON commands           │
         ┌──────────┐                 │ ──► JSON responses          │
         │toad-ctl  ├────────────────►│                              │
         └──────────┘                 └──────────────────────────────┘
```

## Files

| File | Purpose |
|------|---------|
| `src/toad/socket_controller.py` | Unix socket server |
| `src/toad/widgets/project_state_pane.py` | Right pane with timeline |
| `src/toad/widgets/gantt_timeline.py` | Gantt chart renderer |
| `src/toad/data/agent_context.md` | Injected agent instructions |
| `tools/toad-ctl.sh` | CLI client for socket |
| `docs/socket-controller.md` | Socket protocol reference |
