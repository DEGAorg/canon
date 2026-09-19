# Worker conversation capture in the plan tab

The plan-execution tab has a per-item "worker log" pane wired to
`.orchestrator/plans/<slug>/logs/<id>.log`, but in real runs the file
only contains the worker's **final summary line** — none of the agent's
thinking, tool calls, or output. The pane therefore looks empty until
the worker exits, then shows one line.

Goal: make the worker pane show the live agent conversation as the run
unfolds, so the user can actually watch what each agent is doing.

## What's already built

| Layer | File | What it does |
|------|------|--------------|
| Source | `orch-engine.sh` (core) | Spawns each worker in its own tmux session named `orch-<slug>-<id>` |
| Source | `orch-engine.sh` (core) | Writes a one-line summary to `logs/<id>.log` when the worker exits |
| Sink | `src/toad/data/plan_execution_model.py` | Polls each subscribed item's log file, posts diffs |
| Sink | `src/toad/widgets/plan_worker_log_pane.py` | Renders the diffs in a `RichLog` widget |
| Glue | `src/toad/widgets/plan_execution_tab.py` | Routes dep-graph selection → `PlanWorkerLogPane.set_item_id` |

The pipe is correct. The file is the bottleneck.

## Why the file is thin

`orch-engine.sh` runs the worker like:

```bash
tmux new-session -d -s "orch-${SLUG}-${ID}" "$WORKER_CMD"
# … wait …
echo "Item ${ID} complete. <summary>" >> "logs/${ID}.log"
```

The agent's actual conversation lives in the tmux pane scrollback; it
never reaches disk. When the session dies, the scrollback is gone.

## Options

### Option 1 — capture tmux to disk in core (preferred)

**Scope:** one extra line in the worker spawn block of `orch-engine.sh`.

**How:** use tmux `pipe-pane` to mirror everything the agent prints into
the log file the TUI is already watching.

```bash
SESSION="orch-${SLUG}-${ID}"
LOG="${PLAN_DIR}/logs/${ID}.log"

tmux new-session -d -s "${SESSION}" "${WORKER_CMD}"
tmux pipe-pane -O -t "${SESSION}" "cat >> '${LOG}'"
```

`-O` keeps existing pipes alive; `cat` appends the raw stream. The TUI
sees diffs through the same `subscribe_log` path it uses today — no
canon-tui change required.

**Pros**
- Zero TUI work.
- Survives canon restart (history is on disk).
- Same code path the existing summary line writes through.
- DRY with what the engine already does.

**Cons**
- Raw tmux output includes ANSI escape codes — the existing `RichLog`
  handles ANSI but the file gets big. Mitigate with a max-size cap or
  rotate per-iteration.
- `tmux pipe-pane` only captures from the moment it's invoked. Run it
  immediately after `new-session -d` to avoid losing the first frames.

**Estimate:** ~20 minutes including a smoke run.

### Option 2 — live tmux capture in the TUI (no core dep)

**Scope:** new "Watch live" toggle on `PlanWorkerLogPane`.

**How:** when toggled on, the pane spawns a Textual worker that runs

```bash
tmux capture-pane -p -e -S - -t orch-<slug>-<id>
```

on a 1 Hz interval and streams the diff into the `RichLog`. Pane keeps
the existing file-tail behaviour as a fallback for items whose tmux
session has died.

**Pros**
- Works without touching core.
- Reads scrollback on attach — first frames don't get lost.

**Cons**
- Duplicates a code path the engine should own.
- Spawns a subprocess per second per watched item (cheap, but
  measurable on a 7-item plan).
- Stops working if the user runs canon on a different host than the
  tmux server (rare, but possible).
- Doesn't survive worker exit — once the tmux session ends the
  scrollback is gone.

**Estimate:** ~2-3 hours including the toggle UI, polling worker, ANSI
plumbing, and tests.

### Option 3 — hybrid

Core does (1), TUI keeps the file-tail. Live "Watch tmux" toggle from
(2) becomes a follow-up only if (1) misses early frames.

This is what I'd ship.

## Decision points

1. **Approve Option 1** in core. Two-line change in `orch-engine.sh`,
   no schema churn.
2. **File-size cap** for `logs/<id>.log` — pick a number (10 MB? 50?).
   Rotate or truncate when exceeded.
3. **ANSI handling.** `RichLog` strips/renders ANSI; verify a real run
   doesn't fill the pane with control sequences.
4. **Privacy / secret leakage.** The tmux stream may include the agent
   prompt + tool call output. If any of that is sensitive (API keys
   passed to a tool, etc.), `pipe-pane` will dump it to disk and into
   any reader. Not a new risk vs. the existing summary line, but worth
   confirming we're OK with it.

## Open questions

- Should the engine record one log per **review iteration** or one
  log per **item across iterations**? Today it's per-item; iterations
  overwrite. If we capture full conversations, history matters more —
  consider `logs/<id>.<iter>.log` so reviewers can scroll back into a
  prior REVISE round.
- Do we want an "agent identity" column in the log so the user can
  tell which model produced which line on a multi-agent plan?

## Action items

- [ ] Open issue on `claude-code-config` for Option 1 (paste the
      `pipe-pane` snippet above; reference this doc).
- [ ] After (1) lands, smoke-test from canon-tui — open a real plan,
      confirm the worker pane streams the agent conversation.
- [ ] If first-frame loss shows up, do Option 2 as a complement.
- [ ] Decide on log-size cap + rotation policy.
- [ ] Decide on per-iteration vs per-item log file naming.
