# Growth panel — implementation handoff

> **Historical handoff — Growth is shipped.** For the current extension
> architecture standard (of which Growth is the reference
> implementation), see [`extension-architecture.md`](extension-architecture.md).

Hand-off doc for finishing the Growth right-pane panel in canon-tui. The
data layer (private submodule `dega_growth`) is complete and verified
against the live Sheet; what remains is canon-tui side wiring, mirroring
the existing `outreach` / `rpa_outreach` pattern.

Branch: `feat/growth-provider` (off `origin/main`).

## TL;DR

- The protocol/registry shim is committed on this branch
  (`src/toad/growth/{__init__,protocol,registry}.py`).
- The private data provider `dega_growth` lives at
  `~/dega/aidd/dega_growth`, repo
  `https://github.com/DEGAorg/dega_growth`. It already reads/writes the
  shared Sheet and has a passing live smoke test.
- Remaining work is **all canon-tui side**: submodule, panel routes,
  card widgets, ACP routing, agent tools. Mirror `toad.outreach` /
  `toad.extensions.rpa_outreach`.

## Architecture (mirror rpa_outreach)

| Public (this repo) | Private (submodule) |
|--------------------|---------------------|
| `src/toad/outreach/protocol.py` — `OutreachInfoProvider` Protocol + dataclasses | `src/toad/extensions/rpa_outreach/rpa_outreach/provider.py` |
| `src/toad/outreach/registry.py` — `discover()` import-probes the extension | extension exposes `provider` attr |
| `src/toad/widgets/outreach_cards.py` — Textual card widgets | `panel.py` composes snapshot → widgets |
| `PANEL_ROUTES` in `src/toad/widgets/project_state_pane.py` — registers panel | — |
| `action_show_outreach` / `action_hide_outreach` in `src/toad/screens/main.py` | — |

Replicate every row above for `growth` / `dega_growth`. The protocol shim
is already in place — start with the submodule.

## Protocol contract (do NOT change without updating dega_growth)

`src/toad/growth/protocol.py` defines:

- `Channel` enum — `UNICLUBS`, `DISCORDS`, `TELEGRAMS`
- `StepState` enum
- `Step`, `Objective`, `GrowthSnapshot` dataclasses
- `GrowthInfoProvider` Protocol with `available()` and `snapshot()`

`GrowthSnapshot` shape:

```python
@dataclass(frozen=True, slots=True)
class GrowthSnapshot:
    objectives: list[Objective]
    targets_by_channel: dict[Channel, int]
    sends_24h: int
    replies_pending: int
```

`dega_growth` already returns this exact shape from
`GrowthProvider.snapshot()`. If you change the protocol you must change
both sides.

## Remaining work (in order)

1. **Add the submodule**
   ```bash
   git submodule add git@github.com:DEGAorg/dega_growth.git \
     src/toad/extensions/dega_growth
   ```
   Make sure the submodule's package layout exposes
   `toad.extensions.dega_growth` — the extension currently ships its
   importable code as `dega_growth/` at the repo root. You may need a
   thin `__init__.py` shim at `src/toad/extensions/dega_growth/__init__.py`
   that re-exports `provider` from the submodule's actual package, OR
   adjust the registry's `_EXTENSION_MODULE` constant to match the real
   import path. Pick whichever is less invasive — the registry's expectation
   is just "an importable module that has a `.provider` attribute".

2. **Verify discovery**
   ```python
   from toad.growth.registry import discover
   p = discover()
   assert p is not None
   assert (await p.available()) is True
   snap = await p.snapshot()
   assert len(snap.objectives) >= 1  # seeded hackathon-may-2026
   ```
   This requires the dega_growth submodule's `service_account.json` and
   `.env` to be present locally. They are gitignored — the developer
   must copy them in (or for first-time setup, create a new SA per
   dega_growth's CLAUDE.md).

3. **Build the card widgets** at `src/toad/widgets/growth_cards.py`
   following `outreach_cards.py` style. Suggested cards:
   - `ObjectivesCard` — list objectives with step progress bars
   - `TargetsCard` — `targets_by_channel` as a stat line per channel
   - `SendsCard` — `sends_24h` + last-N excerpts (tool: pull recent sends from provider)
   - `RepliesCard` — `replies_pending` count

4. **Add panel composition** at
   `src/toad/extensions/dega_growth/.../panel.py` (mirrors
   `rpa_outreach/panel.py`). Lazy-imports the card widgets, returns a
   `list[Widget]` from a `GrowthSnapshot`.

5. **Register the panel** in `PANEL_ROUTES` at
   `src/toad/widgets/project_state_pane.py`. Add a `section-growth` /
   `tab-growth` entry following the outreach pattern.

6. **Wire show/hide actions** in `src/toad/screens/main.py`:
   `action_show_growth` / `action_hide_growth` mirroring
   `action_show_outreach` (see line 344-375 in main.py).

7. **ACP `open_panel` routing** — the existing PANEL_ROUTES dispatch
   in main.py (around line 426 / 463) already handles new entries
   generically. Just confirm the route exists and a manual
   `open_panel growth` works.

8. **Agent tools** (separate from the panel):
   - `summarize_state` — return a one-paragraph summary of the snapshot
   - `due_followups` — given the seeded hackathon objective deadlines,
     return targets with `joined_date` past N days and no recent send
   - `draft_content` — given a target row + tone hint, return a
     suggested message; dega_growth doesn't draft, the agent does.

## Constraints — read these before touching anything

The dega_growth repo's `CLAUDE.md` sets two hard rules that bind canon-tui
when it imports/uses the provider:

- **Email tab is no-go.** The shared Sheet contains an email tab
  used by the `email-campaign` service in production. Never read, write,
  or reference it from anywhere — including agent tools and tests.
  `dega_growth.SheetsSource` only knows the 5 allowed tab names; don't
  introduce code that bypasses it.

- **Sends are canonical on the Sheet** (`discord_sends` /
  `telegram_sends` tabs). There is no markdown sends log. If you build a
  "log a send" agent tool, it must write to the Sheet via the provider's
  Sheets client, not to a markdown file.

## What's already done

### dega_growth (private repo)

- New SA `dega-growth-sheets@dega-dbb-prod.iam.gserviceaccount.com`
  (Editor on the email-campaign Sheet)
- `service_account.json` + `.env` (gitignored, exist locally only)
- 5 tabs bootstrapped with correct headers — see
  `dega_growth/scripts/bootstrap_tabs.py`
- `GrowthProvider`, `SheetsSource` (with `fetch_sends`), `ProgressStore`,
  schemas
- 3-test live smoke suite (`tests/test_provider_smoke.py`) — passing
- `STATUS.md`, `PLAN.md`, `CLAUDE.md` documenting state and rules

### canon-tui (this repo, this branch)

- `src/toad/growth/{__init__,protocol,registry}.py` — committed on
  `feat/growth-provider`

## How to verify when you're done

```bash
# from canon-tui root
git submodule status | grep dega_growth     # expect a hash
uv run pytest tests/growth/                 # whatever tests you add
```

Then in the running TUI: open the Growth panel, see the seeded
`hackathon-may-2026` objective render with channel target counts and a
`sends_24h: 0` line.

## Pointers

- Public protocol/registry: `src/toad/growth/`
- Private extension: `~/dega/aidd/dega_growth/` (will become a submodule)
- Mirror pattern: `src/toad/outreach/` + `src/toad/extensions/rpa_outreach/`
- Panel routes: `src/toad/widgets/project_state_pane.py` (`PANEL_ROUTES`)
- Show/hide actions: `src/toad/screens/main.py` (search `action_show_outreach`)
- Card widget style: `src/toad/widgets/outreach_cards.py`
