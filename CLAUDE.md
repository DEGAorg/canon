# Conductor View (Agent View TUI)

Toad fork — terminal UI for visualizing AI agent activity. Python 3.14, Textual framework.

Upstream: [batrachian/toad](https://github.com/batrachian/toad) (AGPL-3.0)

## Repo Map

| Path | Purpose |
|------|---------|
| `src/toad/` | Main package — TUI application |
| `src/toad/extensions/dega_panel/` | DEGA panel (Utility / Chat / rooms), on-chain registry client, contracts, strategies runner |
| `src/toad/screens/` | Textual screen definitions |
| `src/toad/widgets/` | Custom Textual widgets |
| `src/toad/visuals/` | Visual rendering (charts, formatting) |
| `src/toad/acp/` | Agent Communication Protocol adapter |
| `src/toad/ansi/` | ANSI escape code handling |
| `src/toad/prompt/` | Prompt handling |
| `src/toad/data/` | Data models and storage |
| `tests/` | Test files |
| `tools/` | Dev utilities (echo client, QR generator) |
| `docs/` | Documentation |

## Working Conventions

- Language-specific standards load from `~/.claude/rules/` by file type
- Orchestrator config: `dega-core.yaml` (edit `check_command` for your toolchain — note it is
  `pytest -q && ruff check . && ty check`, and `pytest -q` does not collect `tests/` here; use
  `uv run python -m pytest tests/ -q` if you rely on that gate)
- Exec plans: GitHub Issues with `plan:draft` label on the repo configured in `dega-core.yaml`
  (`github.repo`, currently `DEGAorg/canon`) — fetched into `.orchestrator/plans/<slug>/` at run
  time. The DEGA/Canon work is tracked in `DEGAorg/canon`; align the config and this note before
  relying on plan sync.
- Runtime: Python 3.14, `uv` for deps, `ruff` for lint/format, `ty` for types
- Tests: `uv run python -m pytest tests/ -q` — **not** `pytest -q` / `uv run pytest tests/`:
  the `pytest` entrypoint does not put the CWD on `sys.path`, so `tests/test_registration_ttl.py`
  (`from tests import test_chat_ui`) aborts collection with
  `ModuleNotFoundError: No module named 'tests'` and the run reports an error instead of results.
- DEGA / Canon docs live under `docs/dega/` with `docs/dega/README.md` as the index; contract
  addresses and env vars must match the code defaults (see that index for the current state).

## Verifying TUI Changes

After modifying any widget or screen, **always** run the headless verification:

```bash
uv run python tools/verify-tui.py --verbose
```

This renders widgets in a headless Textual app and checks layout, scroll behavior, and rendering. Lint/type checks do not catch layout bugs — only this does.

- `--widget gantt` — test only the Gantt timeline
- `--widget imports` — test only that all modules import cleanly
- Add new widget checks to `tools/verify-tui.py` as widgets are added

### Running dev vs installed

| Command | What it runs |
|---------|-------------|
| `uv run canon .` | Always uses local source (for dev) |
| `canon .` | Installed snapshot (stale until reinstalled) |
| `bash install.sh` | Reinstalls from local source (`--reinstall` busts uv cache) |

## Timeline Architecture

The Gantt timeline reads live data from GitHub (milestones, issues, project board) via a provider abstraction.

### Data flow

```
dega-core.yaml (timeline.repo, timeline.project_number)
  → GitHubTimelineProvider (gh CLI subprocess)
    → fetch_milestones(), fetch_items(), fetch_fields()
  → build_timeline() joins issues + project items, groups by milestone
    → TimelineData (start_date, total_days, groups, gates)
  → GanttTimeline widget renders bars with fixed chars-per-week + 2D scroll
```

### Key files

| File | Role |
|------|------|
| `src/toad/widgets/github_views/timeline_provider.py` | `TimelineProvider` protocol — provider-agnostic interface |
| `src/toad/widgets/github_views/github_timeline_provider.py` | GitHub implementation (only provider for now) |
| `src/toad/widgets/github_views/timeline_data.py` | `TimelineData` model + `build_timeline()` transform |
| `src/toad/widgets/gantt_timeline.py` | Gantt renderer + `GanttTimeline` widget |
| `src/toad/widgets/project_state_pane.py` | Mounts the timeline tab, owns the refresh timer |
| `src/toad/widgets/github_views/fetch.py` | Shared `_run_gh()` subprocess executor |

### GitHub data source

- Repo: `DEGAorg/claude-code-config` (configured in `dega-core.yaml`)
- Project board: #8 ("Canon Hackathon")
- Custom fields: Status (Todo/In Progress/Done), Effort, Start Date, Target Date
- Labels: `p1-must-ship`..`p4-cut`, `risk:low`..`risk:high`, `gate`
- Milestones group related issues; due dates show as diamond markers on the axis

### Adding a new provider

Implement the `TimelineProvider` protocol in a new file, then update `ProjectStatePane._make_provider()` to select it based on config.

## Textual Layout Gotchas

- `Static` with Rich Text does **not** auto-expand width — set `styles.min_width` explicitly to enable horizontal scroll
- `ScrollableContainer` handles both axes; don't nest `VerticalScroll` inside `HorizontalScroll`
- `height: auto` on a scroll container collapses it — use `height: 1fr`
- Use `call_after_refresh()` for scroll-to operations; layout isn't settled during `on_mount`

## Orchestrator

Execution plans live **only on GitHub** — no local plan files. Plans are issues on `DEGAorg/canon` with the `plan:draft` label. The orchestrator fetches them into `.orchestrator/plans/<slug>/` at run time; that directory is ephemeral and gitignored.

```bash
# Create a plan (writes a GitHub issue, not a local file)
/plan <task description>

# Run a plan from its issue number (spawns parallel workers in tmux worktrees)
bash ~/.claude/scripts/orch-run.sh <YYYYMMDD-slug> --issue N
```

The orchestrator parses the progress log, respects `(deps: N)` annotations, and spawns worker agents. PRs target the `canon` branch (configured in `dega-core.yaml`).

## Session Start

Check open issues with `plan:draft` or `plan:in-progress` on `DEGAorg/canon` before starting new work:

```bash
gh issue list --repo DEGAorg/canon --label "plan:draft,plan:in-progress"
```
