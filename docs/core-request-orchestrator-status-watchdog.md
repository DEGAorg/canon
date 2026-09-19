# Core request: orchestrator status watchdog + richer per-item state

**Repo:** `claude-code-config`
**Files:** `scripts/orch-engine.sh`, `scripts/orch-state.sh`, `scripts/orch-run.sh`
**Why this matters:** canon-tui's plan-execution panel reads `state.json` as truth. When the engine dies ungracefully the state file is stale, the panel shows `running` forever, users mistrust the panel and stop opening it. Fixing this restores the panel as a reliable live view.

---

## Bug — top-level `status` stays `"running"` after crash

The engine writes `status: "failed"` only on graceful exit paths
(orch-engine.sh:1009 et al.). Any of the following leaves the file
claiming the run is alive when it isn't:

- Operator hits `Ctrl-C` or kills the tmux session
- tmux server dies / machine sleeps / network drops mid-`gh` call
- Python OOM in a worker brings down the parent
- A `set -e` failure in an unhandled branch

There is a `lastHeartbeat` field, but no consumer of it. canon-tui has
no signal it can use to declare the run dead — it shows whatever the
file says.

## Requested fixes (small, isolated, no schema break)

### 1. EXIT/INT/TERM trap on engine

In `orch-engine.sh`, install a trap near the top:

```bash
_on_engine_exit() {
  local code=$?
  if [[ "${code}" -ne 0 ]] && [[ "$(jq -r '.status' "${ORCH_STATE_FILE}")" == "running" ]]; then
    local now
    now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    jq --arg now "${now}" --arg code "${code}" \
       '.status = "failed"
        | .updatedAt = $now
        | .lastError = ("engine exited with code " + $code)
        | .finalReview.status = (if .finalReview.status == "running" then "aborted" else .finalReview.status end)' \
       "${ORCH_STATE_FILE}" >"${ORCH_STATE_FILE}.tmp" && mv "${ORCH_STATE_FILE}.tmp" "${ORCH_STATE_FILE}"
  fi
}
trap _on_engine_exit EXIT INT TERM
```

This alone covers ~80% of the "stays running" cases.

### 2. Heartbeat staleness watchdog

A second process needs to flag plans whose engine is gone. Cheapest
landing: a guard in `orch-run.sh` that runs once at startup and
sweeps any preexisting `state.json` files:

```bash
# At the top of orch-run.sh, before spawning the engine:
for sf in "${ORCH_PLANS_DIR}"/*/state.json; do
  [[ -f "${sf}" ]] || continue
  status=$(jq -r '.status // "unknown"' "${sf}")
  [[ "${status}" == "running" ]] || continue
  hb=$(jq -r '.lastHeartbeat // ""' "${sf}")
  [[ -n "${hb}" ]] || continue
  hb_epoch=$(date -j -f "%Y-%m-%dT%H:%M:%SZ" "${hb}" +%s 2>/dev/null || echo 0)
  now_epoch=$(date -u +%s)
  age=$((now_epoch - hb_epoch))
  # If heartbeat older than 2 minutes, mark aborted.
  if (( age > 120 )); then
    jq --arg now "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
       '.status = "aborted"
        | .updatedAt = $now
        | .lastError = "heartbeat stale (process dead)"
        | .finalReview.status = (if .finalReview.status == "running" then "aborted" else .finalReview.status end)' \
       "${sf}" >"${sf}.tmp" && mv "${sf}.tmp" "${sf}"
  fi
done
```

(Optional: lift this into a helper in `orch-state.sh` so other entry
points can reuse it — `orch_state_reap_stale`.)

### 3. Per-item stale detection — flip status, not just return IDs

`orch_detect_stale_workers` in `orch-state.sh` already finds items
whose `worker-<id>.log` hasn't been touched. It returns IDs but
doesn't mutate state. Make it set `.items[i].status = "aborted"` and
`.items[i].lastResult = "stale-no-output"` for each ID found, so the
TUI surfaces the per-item state without inferring it.

---

## Bonus — richer per-item state for liveness UX

Lower priority. Each is independent.

### a. `items[].phase` field

Today an item has `status` (queued/ready/running/review/done/failed)
but the TUI has to read other fields to know what *kind* of running
it's doing. Emit one of `spawning`, `awaiting-review`, `verifying`,
`reworking` so the panel can show a phase chip without inference.

### b. Per-criterion `verify.results[]`

Today verification posts a single rolled-up `verification.status` at
the end. Emit one entry per completion criterion as it runs:

```json
{
  "verify": {
    "status": "running",
    "results": [
      {"id": 1, "cmd": "uv run ruff check", "status": "passed", "elapsedMs": 234},
      {"id": 2, "cmd": "uv run pytest -q", "status": "running"}
    ]
  }
}
```

Lets the panel render a live verification checklist instead of a
single end-state badge.

### c. `events[]` JSONL alongside `state.json`

Append-only log: one line per orchestrator event.

```jsonl
{"ts":"2026-05-03T18:14:02Z","type":"item_promoted","id":3,"from":"queued","to":"ready"}
{"ts":"2026-05-03T18:14:05Z","type":"worker_spawned","id":3,"window":"worker-3"}
{"ts":"2026-05-03T18:15:22Z","type":"review_done","id":3,"verdict":"SHIP"}
```

canon-tui can stream this directly into a per-plan event-log panel
(the screenshot's "Event log // pm-trader cli" style) with no
re-parsing of `engine.log`.

---

## Verification (after changes land)

1. Start a plan with `orch-run.sh`, kill the tmux session mid-run.
2. Re-run `orch-run.sh` (or just open canon-tui and look at the
   plan-execution panel) — `state.json` should show `status: failed`
   or `aborted` within ~2 minutes of the kill.
3. canon-tui's `PlanExecutionModel` already handles `failed` /
   `aborted` correctly; no canon-tui changes required for (1)–(3).
4. For (a)–(c), canon-tui will need additive changes (separate
   issue) but they're purely additive — old plan files keep working.

---

---

## Bonus — `/canon-start` should surface the State panel

**Files:** `~/.claude/commands/canon-start.md` (Phase 1 — Initialize)

The TUI's State section in the right pane is hidden by default. The
user opens it via the toolbar or by asking the agent (``show me the
state``). When they invoke ``/canon-start``, ``.canon/state.json``
starts updating immediately but the panel stays hidden — confusing.

Stay consistent with the existing ``show me X`` pattern (which is
agent-driven, not state-watch): one-line addition near the top of
``canon-start.md``, same idiom as the existing ``terminal-ui-write.sh``
guards.

```bash
command -v canon-ctl >/dev/null && canon-ctl action "screen.show_state" || true
```

Why agent-side and not canon-tui auto-watch: every project with a
stale ``.canon/state.json`` would auto-pop the State panel on every
canon launch. Language-driven panel routing keeps the UI quiet by
default and predictable.

---

## Why I'm asking for this

canon-tui can polish the right-pane visuals all day, but if the
underlying state lies, every "● LIVE" badge is a lie. The watchdog
is the single highest-leverage core change for the live-feel of the
plan-execution panel.
