# Core Extension Request: Flow Timestamps

**Repo:** `claude-code-config`
**Requested by:** `canon-tui` — automation panel elapsed-time display
**Priority:** P1 — needed for correct elapsed-time display. TUI has a session-local fallback but it resets on restart; this makes it authoritative.

---

## Problem

The automation panel header shows `▶ strategy · step 3 of 5 · 4m elapsed`.
The elapsed time ("4m") requires knowing when the current `active` step
started. Neither `state.json` nor `flow.json` currently contains a timestamp.

**v1 workaround (already in TUI):** the panel tracks `_active_since` in
memory — set to `datetime.now()` when `flow.active` changes. This works
correctly as long as the TUI process is running. If the TUI is restarted
mid-automation, the counter resets to zero and the elapsed display reads
"0s elapsed" until `active` changes again.

**v2 target:** core writes a persistent `active_since` timestamp so
elapsed time survives TUI restarts and is authoritative.

---

## Requested change

### `flow.json` — add `active_since`

Add one new field, written by `runner.ts` alongside the existing `active` /
`completed` mutation:

```jsonc
{
  // Existing — unchanged.
  "steps":     ["init", "scaffold", "strategy", "develop"],
  "labels":    [["init", "Init"], ...],
  "active":    "strategy",
  "completed": ["init", "scaffold"],

  // NEW — ISO 8601 UTC timestamp, set when active changes.
  "active_since": "2026-05-12T14:23:11.000Z"
}
```

**Rules:**
- Set `active_since` to the current UTC time whenever `active` is updated
  to a new value.
- Do **not** update `active_since` if `active` is being set to the same
  value it already holds (idempotent writes).
- Leave `active_since` absent (field not present) when `active` is `""`.

### `state.json` — add `phase_since` (optional, lower priority)

For the phase-level elapsed time (how long the overall `run` phase has
been active), a parallel field on `state.json` would be useful:

```jsonc
{
  "phase":      "run",
  "status":     "running",
  "iteration":  5,
  // NEW — ISO 8601 UTC timestamp, set when phase changes.
  "phase_since": "2026-05-12T14:20:00.000Z"
}
```

Set `phase_since` whenever `phase` transitions to a new value. This field
is lower priority — `active_since` on `flow.json` is sufficient for v2.

---

## `runner.ts` diff (sketch)

File: `canon/templates/runner.ts`, function `updateFlow(active, completed)` (~lines 131–151).

Current write:
```typescript
const flow = {
  ...existingFlow,
  active,
  completed,
};
```

New write:
```typescript
const activeSince =
  active && active !== existingFlow.active
    ? new Date().toISOString()
    : existingFlow.active_since;   // preserve if step unchanged

const flow = {
  ...existingFlow,
  active,
  completed,
  ...(activeSince ? { active_since: activeSince } : {}),
};
```

---

## TUI side — how `active_since` will be consumed

File: `src/toad/widgets/canon_state.py`

`FlowState` gains a new optional field:

```python
@dataclass(frozen=True)
class FlowState:
    ...
    active_since: str = ""   # ISO 8601 UTC; "" when not set
```

`_parse_flow()` reads it:
```python
active_since=data.get("active_since", "")
```

`AutomationPanel._refresh_header()` prefers `flow.active_since` when
non-empty; falls back to session-local `_active_since`:

```python
def _elapsed_source(self, flow: FlowState | None) -> datetime | None:
    if flow and flow.active_since:
        parsed = _parse_iso(flow.active_since)
        if parsed:
            return parsed
    return self._active_since   # session-local fallback
```

This means the transition from v1 → v2 is invisible to users: once core
ships `active_since`, the display becomes persistent automatically.

---

## Additive contract

- `active_since` is optional. TUI reads it with `.get("active_since", "")`.
  Old runners that do not write it produce no breakage — elapsed falls back
  to session-local.
- `steps` and `labels` are never touched by this change.
- No changes to `canon-start.md` — `cp strategies/<name>/flow.json .canon/flow.json`
  will not include `active_since` (it's runtime state), which is correct.
