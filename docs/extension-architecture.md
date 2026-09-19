# Extension Architecture

How optional, third-party modules plug into Canon TUI. This is the
**canonical reference** for new extensions; it supersedes
[`third-party-module-integration.md`](third-party-module-integration.md)
(Outreach reference, legacy pattern) and
[`growth-handoff.md`](growth-handoff.md) (Growth wiring notes).

---

## TL;DR

Canon TUI is the **host**. Extensions live under
`src/toad/extensions/<module>/` (typically as private git submodules)
and are discovered at startup via a registry probe. No hard
dependencies: if the module is missing, Canon runs without the section.

Two patterns coexist in the tree:

| Pattern | Example | Data lives in | Rendering lives in | Status |
|---------|---------|---------------|--------------------|--------|
| **A. Data Provider** | `rpa_outreach` / Outreach | extension | **canon-tui** | Legacy |
| **B. Panel Plugin**  | `dega_growth` / Growth   | extension | **extension** | **Current standard** |

The architectural shift between A and B is **full dependency inversion
of the UI**. In A, the host knows what the panel looks like; the
extension only feeds it data. In B, the host knows only that there is
*some* widget, and the extension owns the entire widget tree.

New extensions MUST follow Pattern B. Pattern A remains documented only
to describe Outreach until it is migrated.

---

## Common Foundations (both patterns)

Both patterns share the same conditional-plugin scaffolding:

```
Host startup
  └─ registry.discover() import-probes toad.extensions.<module>
       ├─ ImportError      → return None  → section omitted, no error
       ├─ wrong shape      → return None  → log warning, section omitted
       └─ satisfies Proto  → return obj   → host mounts the section
```

Shared rules:

- **No compile-time dependency**: the host imports the Protocol from
  `src/toad/<module>/protocol.py`; the extension imports that same
  Protocol. The host never imports anything from
  `src/toad/extensions/<module>/`.
- **Discovery is silent on absence**: missing submodule → no section.
  Misconfigured submodule (no `provider` / `panel` attr, fails
  `isinstance`) → log warning + omit. Never crash the host.
- **Configuration belongs to the extension**: DSNs, sheet IDs, service
  account paths, etc. are resolved inside the extension (env var first,
  then a `.env` committed to the private submodule). The host never
  knows the credentials shape.
- **Refresh cadence is host-driven**: the host owns the timer; the
  extension declares its cadence (Pattern B) or accepts a fixed cadence
  (Pattern A).
- **Section state is host-owned**: section badge (`UPDATING` /
  `POLLING` / `OFFLINE` / `ERROR`), tab order, accent border, ACP
  `open_panel` routing — all decided by the host.

---

## Pattern A — Data Provider (legacy: Outreach)

The extension exposes a `provider` object that satisfies a Protocol of
the form `available() + snapshot() → DataClasses`. The host owns all
the widgets and rebuilds them from each snapshot.

### Protocol shape

`src/toad/outreach/protocol.py`:

```python
@runtime_checkable
class OutreachInfoProvider(Protocol):
    async def available(self) -> bool: ...
    async def snapshot(self) -> OutreachSnapshot: ...

@dataclass(frozen=True, slots=True)
class OutreachSnapshot:
    prospects: ProspectsCard
    sends: SendsCard | None
    hackathons: list[HackathonStat]
    accounts: list[AccountStat] | None
```

The Protocol ships the **data contract** (frozen dataclasses) the host
will render.

### Host responsibilities

In `project_state_pane.py`:

- Calls `discover_outreach()` at startup; caches the provider.
- Lays out the section's widget tree itself
  (`StatLine` / `Histogram` / `RankedBar` / `AccountDot` from
  `src/toad/widgets/outreach_cards.py`).
- Drives a refresh timer. On each tick: `provider.available()` →
  `provider.snapshot()` → walk the dataclasses and update each widget.
- Owns CSS, accent colour, tab ID, badge transitions, ACP routing.

### Extension responsibilities

Implement the Protocol. Nothing more.

### Trade-offs

- ✅ Simple data contract; easy to mock in tests.
- ✅ Host has full control of look-and-feel consistency across panels.
- ❌ Every UI change requires editing canon-tui. The extension cannot
  add a sub-tab, a modal, a column, or a key binding on its own.
- ❌ Snapshots are coarse-grained. Write paths (e.g., toggling a
  `sent` flag) are awkward — they bypass the snapshot model and need
  ad-hoc additions to the Protocol.
- ❌ Host imports concrete widget code keyed to one module's data
  shape, which leaks the module's domain into the host repo.

---

## Pattern B — Panel Plugin (current standard: Growth)

The extension exposes a `panel` object that satisfies a Protocol of
the form *manifest + lifecycle*. The host mounts an empty container
and hands it to the panel; the panel owns everything inside.

### Protocol shape

`src/toad/growth/protocol.py`:

```python
@runtime_checkable
class GrowthPanel(Protocol):
    # --- manifest (read at discovery, before Textual init) ---
    id: str
    title: str
    accent: str
    refresh_seconds: int | None

    # --- lifecycle ---
    async def available(self) -> bool: ...
    async def mount(self, container: "Widget") -> None: ...
    async def refresh(self) -> None: ...
```

The Protocol ships the **lifecycle contract**. There is no data shape
in the public protocol — that lives entirely inside the extension.

### Lifecycle

```
discover()                  # registry returns panel, or None
  available()               # before first mount; False → OFFLINE badge
  mount(container)          # ONCE: build the widget tree inside container
  ─loop on refresh_seconds─
    available()             # False → OFFLINE
    refresh()               # update widgets in place; raise → ERROR badge
  ────────────────────────
```

Host wraps each `refresh()` in badge transitions: `POLLING` →
`UPDATING` → `POLLING` on success, `ERROR` on exception.

### Host responsibilities

In `project_state_pane.py`:

- Calls `discover_growth()` at startup.
- Reads the **manifest** (`title`, `accent`, `refresh_seconds`)
  without instantiating any Textual widgets — manifest fields are
  plain attributes.
- Adds the section to the right-pane, sets accent CSS, registers the
  ACP route (`PANEL_ROUTES[panel.id]`).
- Yields an empty `Vertical(id="growth-container")` inside the
  TabPane. On first show, calls `panel.mount(container)`. Drives the
  refresh timer per `refresh_seconds`.

The host never imports concrete widgets from the extension and never
sees the extension's data shape.

### Extension responsibilities

Everything inside the container: layout, sub-tabs (`TabbedContent`),
DataTables, detail modals (`container.app.push_screen(...)`), key
handlers, write paths to whatever backend. The extension picks its
own data source (Postgres, Sheets, REST, files) without the host
caring.

Concrete example — `src/toad/extensions/dega_growth/dega_growth/panel.py`
mounts a `TabbedContent` with **Overview / Discord / Telegram** tabs,
each with sub-tabs (Servers / Sends, Groups / Sends), Enter-to-open
detail modals, and a write path that calls
`SheetsSource.mark_sent(channel, row_index, sent=...)` to toggle the
`sent` column on the Google Sheet directly.

### Trade-offs

- ✅ The extension owns its domain end-to-end. New sub-tabs, columns,
  modals, key bindings, and write paths ship without touching
  canon-tui.
- ✅ Host repo stays domain-agnostic. Adding a tenth extension does
  not add ten widget files to canon-tui.
- ✅ Read/write parity: write paths are just methods on the extension's
  internal data source; no Protocol churn.
- ⚠️ Visual consistency is the extension's responsibility. Host
  provides accent + badge; the rest of the section's chrome is on
  the extension. Style discipline matters.
- ⚠️ Harder to mock the panel as a whole in host-side tests — but
  extension-side tests are simpler (the extension owns everything).

---

## Decision: which pattern for new work?

**Always Pattern B.** Pattern A exists in the tree only because
Outreach predates the standard. If you have a hammer-simple
read-only panel and Pattern A feels tempting, it is still cheaper in
the long run to ship a Pattern B panel because:

- Write paths are inevitable (everyone eventually wants a toggle, a
  retry button, a "mark as done").
- Sub-tabs / detail modals are inevitable for any non-trivial domain.
- Pattern B isolates churn — when the data source schema changes,
  only the extension recompiles.

Pattern A is acceptable only for trivial, **read-only**, single-card
panels with no foreseeable evolution. None currently planned.

---

## Integration checklist (Pattern B)

Touchpoints in canon-tui for a new extension `<mod>`:

| # | File | What to add |
|---|------|-------------|
| 1 | `src/toad/<mod>/protocol.py` | `Protocol` with manifest + `available` / `mount` / `refresh` |
| 2 | `src/toad/<mod>/registry.py` | `discover()` import-probes `toad.extensions.<ext>` |
| 3 | `src/toad/extensions/<ext>/` | The private submodule itself (provider, widgets, data source) |
| 4 | `src/toad/widgets/project_state_pane.py` | Section ID constant, `discover_<mod>()` at init, conditional mount, refresh timer, ACP route entry |
| 5 | `src/toad/screens/main.py` | `action_show_<mod>` / `action_hide_<mod>` + ACP `open_panel` handler |
| 6 | `src/toad/screens/main.tcss` | Accent left-border CSS for the section |
| 7 | Conductor prompt | Document `canon-ctl` panel commands for agents |

Submodule must expose a module-level `panel` attribute satisfying the
Protocol. Manifest fields must be plain attributes (not async, not
lazy) because the host reads them before Textual is initialized.

DSN / credentials resolution lives entirely in the submodule. Mirror
the `rpa_outreach` / `dega_growth` pattern: env var first
(`<MOD>_DATABASE_URL`, `<MOD>_SHEET_ID`, etc.), then a `.env` shipped
inside the private submodule (gitignored in the public repo, committed
in the private one).

---

## Migrating Outreach to Pattern B

Sketch only; not scheduled.

1. Move all widget code from `src/toad/widgets/outreach_cards.py`
   into `src/toad/extensions/rpa_outreach/rpa_outreach/panel.py`.
   Compose them inside a `mount(container)` that yields the existing
   card layout.
2. Replace `src/toad/outreach/protocol.py` with a manifest +
   lifecycle protocol mirroring `GrowthPanel`. Drop the public
   dataclasses (`ProspectsCard`, `SendsCard`, etc.) — they become
   internal to the extension.
3. In `project_state_pane.py`, swap the bespoke Outreach
   `yield StatLine(...)` / `yield Histogram(...)` block for a single
   empty container plus a `panel.mount(container)` call, identical to
   the Growth wiring.
4. Add `refresh()` to the provider; have it re-run the existing
   queries and update widgets in place.
5. Delete `src/toad/widgets/outreach_cards.py` once nothing in the
   host imports it.

After migration, the host has no domain knowledge of either Outreach
or Growth — only the lifecycle Protocol. That is the end state.

---

## Glossary

- **Host** — canon-tui. Provides section slots, badges, timers, ACP
  routing.
- **Extension** — code under `src/toad/extensions/<name>/`, usually a
  private git submodule. Implements the Protocol.
- **Protocol shim** — the pair `src/toad/<mod>/protocol.py` +
  `src/toad/<mod>/registry.py`. Lives in the public repo; defines the
  contract; has zero runtime dependency on the extension.
- **Manifest** — plain attributes on the panel object (`id`,
  `title`, `accent`, `refresh_seconds`) read by the host before any
  widget is constructed.
- **Snapshot** (Pattern A only) — frozen dataclass payload returned
  by `provider.snapshot()`. Absent from Pattern B; replaced by the
  panel's internal data model.
