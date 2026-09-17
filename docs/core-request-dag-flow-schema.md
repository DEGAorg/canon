# Core Extension Request: DAG Shape in flow.json

**Repo:** `claude-code-config`
**Requested by:** `canon-tui` — AutomationDag renderer
**Priority:** P1 — needed to render the actual automation shape. TUI falls back to a linear chain until core ships this; that fallback is a placeholder, not the target.

---

## Background

The canon-tui automation panel now renders the flow as a DAG diagram.
It reads `.canon/flow.json`, which the runner seeds from
`strategies/<name>/flow.json` and mutates (`active`, `completed`) at
runtime.

**Fallback (in place now):** The TUI synthesises a linear chain from
`steps` when `nodes`/`edges` are absent. This keeps the panel from
crashing but does not show the real execution shape.

**Target (this request):** Strategies ship `nodes` and `edges` in their
seed `flow.json`. The runner never touches these fields — no runner
changes needed. The TUI renders the actual DAG immediately.

---

## Requested change

### Strategy seed file — add optional `nodes` and `edges`

File: `canon/templates/strategies/<name>/flow.json`

These two arrays are **optional**. When absent, the TUI falls back to
the linear chain synthesised from `steps`. When present, they drive
the exact visual shape.

```jsonc
{
  // Existing — unchanged. Runner reads/mutates these.
  "steps":     ["fetch", "enrich", "score", "notify"],
  "labels":    [["fetch", "Fetch leads"], ["score", "Score"], ...],
  "active":    "",
  "completed": [],

  // NEW — optional DAG shape. Runner ignores these entirely.
  "nodes": [
    { "id": "fetch",  "label": "Fetch leads",  "type": "build"  },
    { "id": "enrich", "label": "Enrich data",  "type": "build"  },
    { "id": "score",  "label": "Score",        "type": "gate"   },
    { "id": "notify", "label": "Notify",       "type": "deploy" }
  ],
  "edges": [
    { "from": "fetch",  "to": "enrich" },
    { "from": "fetch",  "to": "score"  },
    { "from": "enrich", "to": "notify" },
    { "from": "score",  "to": "notify" }
  ]
}
```

### Node types

| `type`   | Icon | Meaning                        |
|----------|------|--------------------------------|
| `build`  | `▶`  | Default — a work step          |
| `gate`   | `◆`  | Quality / approval checkpoint  |
| `deploy` | `⬆`  | Publish / send / deploy action |
| `review` | `◎`  | Human review step              |

Omit `type` to get the `build` default.

### Parallel branch example (fan-out / fan-in)

```jsonc
{
  "steps": ["fetch", "enrich_a", "enrich_b", "merge", "score"],
  "nodes": [
    { "id": "fetch",    "label": "Fetch",     "type": "build" },
    { "id": "enrich_a", "label": "Enrich A",  "type": "build" },
    { "id": "enrich_b", "label": "Enrich B",  "type": "build" },
    { "id": "merge",    "label": "Merge",     "type": "gate"  },
    { "id": "score",    "label": "Score",     "type": "gate"  }
  ],
  "edges": [
    { "from": "fetch",    "to": "enrich_a" },
    { "from": "fetch",    "to": "enrich_b" },
    { "from": "enrich_a", "to": "merge"   },
    { "from": "enrich_b", "to": "merge"   },
    { "from": "merge",    "to": "score"   }
  ]
}
```

This renders as two parallel lanes between Fetch and Merge.

---

## Contract

- `nodes` and `edges` are **never written or read by the runner** — they
  are static shape metadata in the seed file.
- Node `id` values must match entries in `steps` so the runner's
  `active`/`completed` updates apply correctly.
- Both fields are optional. Omitting them means linear fallback — no
  breakage, no migration needed for existing strategies.
- Unknown `type` values render with the `build` icon (`▶`) — safe to
  extend later.

---

## TUI side — already implemented

File: `src/toad/widgets/canon_state.py`

`_parse_flow()` already reads `nodes` and `edges` from `flow.json`:

```python
nodes = tuple(
    FlowNode(id=n["id"], label=n.get("label", n["id"]), type=n.get("type", "build"))
    for n in data.get("nodes", [])
    if "id" in n
)
edges = tuple(
    FlowEdge(from_id=e["from"], to_id=e["to"])
    for e in data.get("edges", [])
    if "from" in e and "to" in e
)
```

`AutomationDag` falls back to `FlowState.effective_nodes()` /
`effective_edges()` when `nodes`/`edges` are empty, which synthesises
the linear chain from `steps`.

No TUI changes needed once core strategies start shipping `nodes`/`edges`.
