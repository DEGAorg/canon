"""AutomationPanel — state summary + System/Flow tabs (diagrams) + always-visible logs.

Layout:

    [state summary — single status row + metrics]
    Tabs: System | Flow            ← diagrams only
      System (default):
        [build diagram]            ← collapses to a chip once we leave build
        [live diagram]             ← persists with last seen status once seen
      Flow:
        [strategy flow.json DAG]
    [logs — always visible below the tabs, regardless of active tab]
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from textual.app import ComposeResult
from textual.containers import HorizontalScroll, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static, TabbedContent, TabPane

from toad.widgets.automation_dag import AutomationDag
from toad.widgets.canon_phase_diagram import CanonPhaseDiagram
from toad.widgets.canon_state import CanonState, LogEntry

log = logging.getLogger(__name__)

MAX_LOG_LINES = 50

LOG_LEVEL_COLORS: dict[str, str] = {
    "error":   "red bold",
    "warn":    "yellow",
    "warning": "yellow",
    "info":    "white",
    "debug":   "dim",
}

PHASE_ICONS: dict[str, str] = {
    "init":     "⚙",
    "scaffold": "▶",
    "strategy": "◎",
    "develop":  "▶",
    "run":      "◐",
    "live":     "⬆",
}

# What status values mean "the runner is actively working" — drives the
# auto-switch to System once per execution phase. Polling is included
# because the dry-run runner writes status="polling" not "running".
RUNNING_STATUSES: frozenset[str] = frozenset({"running", "polling"})

# Friendly labels for live sub-states; falls back to raw status.
LIVE_STATUS_LABELS: dict[str, str] = {
    "deposit-pending": "Awaiting Deposit",
    "funds-detected":  "Deposit Received",
    "onboarding":      "Onboarding",
    "ready":           "Wallet Ready",
    "running":         "Running Live",
    "timeout":         "Deposit Timeout",
}

STATUS_COLORS: dict[str, str] = {
    "running":           "green",
    "polling":           "cyan",
    "complete":          "cyan",
    "waiting_for_input": "yellow",
    "waiting":           "yellow",
    "ready":             "green",
    "error":             "red",
    "timeout":           "red",
    "idle":              "dim",
    "":                  "dim",
}

# Metric keys to skip in summaries (already conveyed elsewhere).
HIDDEN_METRIC_KEYS: frozenset[str] = frozenset({"mode"})


METRIC_LABEL_ALIASES: dict[str, str] = {
    "cycles":        "Runs",
    "runs":          "Runs",
    "signals":       "Opportunities",
    "opportunities": "Opportunities",
    "games":         "Games",
    "markets":       "Markets",
    "errors":        "Errors",
    "mode":          "Mode",
}


def _humanize_metric_key(raw: str) -> str:
    aliased = METRIC_LABEL_ALIASES.get(raw.lower())
    if aliased is not None:
        return aliased
    return raw.replace("_", " ").replace("-", " ").strip().title() or raw


def _parse_iso(raw: str) -> datetime | None:
    text = raw.replace("Z", "+00:00") if raw.endswith("Z") else raw
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _format_elapsed(since: datetime | None) -> str:
    if since is None:
        return ""
    delta = int((datetime.now(timezone.utc) - since).total_seconds())
    if delta < 60:
        return f"{delta}s"
    if delta < 3600:
        return f"{delta // 60}m"
    h = delta // 3600
    m = (delta % 3600) // 60
    return f"{h}h {m}m"


def _format_log_timestamp(raw: str) -> str:
    if not raw:
        return ""
    parsed = _parse_iso(raw)
    if parsed is None:
        return raw[-8:] if len(raw) >= 8 else raw
    return parsed.astimezone().strftime("%H:%M:%S")


def _render_log(entry: LogEntry) -> str:
    color = LOG_LEVEL_COLORS.get(entry.level, "white")
    ts = _format_log_timestamp(entry.timestamp)
    ts_markup = f"[dim]{ts:<10}[/] " if ts else ""
    return f"  {ts_markup}[{color}]{entry.message}[/]"


def _phase_sublabel(state: CanonState) -> str:
    """Friendly description of what's happening *inside* the current phase."""
    if state.phase == "live":
        return LIVE_STATUS_LABELS.get(state.status, state.status)
    if state.flow and state.flow.active:
        # Resolve flow.active to a label if defined.
        for k, v in state.flow.labels:
            if k == state.flow.active:
                return v
        return state.flow.active
    return ""


def _format_metric_chips(metrics: tuple[tuple[str, str], ...]) -> list[str]:
    """Hide zero values for non-error metrics; highlight errors red."""
    out: list[str] = []
    for k, v in metrics:
        kl = k.lower()
        if kl in HIDDEN_METRIC_KEYS:
            continue
        is_error = "error" in kl
        # Skip zero unless it's an error count (zero errors is informative).
        if v in ("0", "0.0", "") and not is_error:
            continue
        color = "red bold" if is_error and v not in ("0", "0.0", "") else "bold"
        out.append(f"{_humanize_metric_key(k)}: [{color}]{v}[/]")
    return out


class AutomationPanel(Widget):
    """Right-pane automation section: header + System tab + Flow tab.

    Receives state via the ``state`` reactive, set by MainScreen forwarding
    CanonStateWidget.CanonStateUpdated messages down.
    """

    state: reactive[CanonState] = reactive(  # type: ignore[assignment]
        CanonState, always_update=True
    )

    DEFAULT_CSS = """
    AutomationPanel {
        height: 1fr;
    }
    AutomationPanel #state-summary {
        height: auto;
        max-height: 3;
        padding: 0 1;
        background: $surface;
        color: $text;
        border-bottom: solid $surface-lighten-2;
    }

    AutomationPanel #automation-tabs {
        height: auto;
        max-height: 22;
    }
    AutomationPanel #system-pane {
        height: auto;
    }

    /* Build: chip vs full DAG */
    AutomationPanel #build-collapsed {
        height: 1;
        padding: 0 1;
        color: $success;
        display: none;
    }
    AutomationPanel.build-collapsed #build-collapsed {
        display: block;
    }
    AutomationPanel.build-collapsed #build-diagram {
        display: none;
    }

    /* Live: chip vs full DAG. Default = chip visible, DAG hidden. */
    AutomationPanel #live-collapsed {
        height: 1;
        padding: 0 1;
        color: $text-muted;
        display: block;
    }
    AutomationPanel #live-diagram {
        display: none;
    }
    AutomationPanel.live-expanded #live-collapsed {
        display: none;
    }
    AutomationPanel.live-expanded #live-diagram {
        display: block;
    }

    AutomationPanel #automation-logs {
        height: 1fr;
        min-height: 8;
        border-top: solid $surface-lighten-2;
    }
    AutomationPanel .log-line {
        padding: 0 1;
        height: auto;
    }
    AutomationPanel .empty-state {
        color: $text-muted;
        text-style: italic;
        padding: 1;
        text-align: center;
    }
    AutomationPanel .error-banner {
        background: $error 30%;
        color: $text;
        text-style: bold;
        padding: 0 1;
        height: auto;
    }

    /* Workflow tab — strategy flow.json DAG */
    AutomationPanel #dag-scroll {
        height: auto;
        max-height: 10;
    }
    AutomationPanel #automation-dag {
        height: auto;
        width: auto;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._active_since: datetime | None = None
        self._last_active: str = ""
        self._auto_switched_phase: str = ""   # which exec phase we last auto-switched for
        self._auto_switching: int = 0          # counter: programmatic switch in flight
        self._setup_complete: bool = False
        self._log_filter: str | None = None
        # Live persistence: once we see phase=live, keep showing it.
        self._seen_live: bool = False
        self._last_live_status: str = ""

    def compose(self) -> ComposeResult:
        yield Static("", id="state-summary")
        with TabbedContent(id="automation-tabs"):
            with TabPane("Pipeline", id="tab-pipeline"):
                with Vertical(id="system-pane"):
                    yield Static(
                        "[green]✓[/] Build pipeline complete",
                        id="build-collapsed",
                    )
                    yield CanonPhaseDiagram(mode="build", id="build-diagram")
                    yield Static(
                        "[dim]⬆ Live trading — not started[/]",
                        id="live-collapsed",
                    )
                    yield CanonPhaseDiagram(mode="live", id="live-diagram")
            with TabPane("Workflow", id="tab-workflow"):
                with HorizontalScroll(id="dag-scroll"):
                    yield AutomationDag(id="automation-dag")
        with VerticalScroll(id="automation-logs"):
            yield Static(
                "Waiting for logs…",
                classes="empty-state",
                id="automation-logs-empty",
            )

    def on_mount(self) -> None:
        # Mark setup complete after first refresh so initial TabActivated
        # messages don't get mistaken for user tab selections.
        self.call_after_refresh(self._mark_setup_complete)
        # Tick once a second so the elapsed-time display keeps moving
        # between state.json updates (which only land every few seconds).
        self.set_interval(1.0, self._tick_elapsed)

    def _mark_setup_complete(self) -> None:
        self._setup_complete = True

    def _tick_elapsed(self) -> None:
        """Refresh the state summary so the elapsed counter ticks each second."""
        if self.state.phase:
            self._refresh_state_summary(self.state)

    def watch_state(self, state: CanonState) -> None:
        self._track_elapsed(state)
        self._track_live_persistence(state)
        self._refresh_collapse(state)
        self._maybe_auto_switch(state)
        self._refresh_state_summary(state)

        # Build diagram: always reflects current state.
        self.query_one("#build-diagram", CanonPhaseDiagram).state = state

        # Live diagram: use current state when in live phase, else replay last.
        live = self.query_one("#live-diagram", CanonPhaseDiagram)
        if state.phase == "live":
            live.state = state
        elif self._seen_live:
            live.state = CanonState(phase="live", status=self._last_live_status)

        # Strategy Flow DAG: full state.
        self.query_one("#automation-dag", AutomationDag).update_state(state)
        self.call_after_refresh(self._refresh_logs, state)

    # ------------------------------------------------------------------
    # Live persistence + collapse logic
    # ------------------------------------------------------------------

    def _track_live_persistence(self, state: CanonState) -> None:
        if state.phase == "live":
            self._seen_live = True
            if state.status:
                self._last_live_status = state.status

    def _refresh_collapse(self, state: CanonState) -> None:
        # Build collapses once we're in live or have ever been live.
        if state.phase == "live" or self._seen_live:
            self.add_class("build-collapsed")
        else:
            self.remove_class("build-collapsed")

        # Live expands only while we're currently in the live phase.
        # Outside of live, show the chip — with last-status text if we've
        # seen it, otherwise a neutral "not started" placeholder.
        if state.phase == "live":
            self.add_class("live-expanded")
        else:
            self.remove_class("live-expanded")
            chip = self.query_one("#live-collapsed", Static)
            if self._seen_live and self._last_live_status:
                label = LIVE_STATUS_LABELS.get(
                    self._last_live_status, self._last_live_status
                )
                chip.update(f"[cyan]⬆[/] Live trading — last: [bold]{label}[/]")
            else:
                chip.update("[dim]⬆ Live trading — not started[/]")

    # ------------------------------------------------------------------
    # Auto-switch — once per execution phase, when actively running.
    # ------------------------------------------------------------------

    def on_tabbed_content_tab_activated(
        self, event: TabbedContent.TabActivated
    ) -> None:
        if self._auto_switching > 0:
            self._auto_switching -= 1

    def _maybe_auto_switch(self, state: CanonState) -> None:
        is_executing = (
            state.phase in ("run", "live")
            and state.status in RUNNING_STATUSES
            and self._auto_switched_phase != state.phase
        )
        if is_executing:
            self._auto_switched_phase = state.phase
            tabs = self.query_one("#automation-tabs", TabbedContent)
            if tabs.active != "tab-pipeline":
                self._auto_switching += 1
                tabs.active = "tab-pipeline"

    # ------------------------------------------------------------------
    # State summary (single status row, always visible above tabs)
    # ------------------------------------------------------------------

    def _track_elapsed(self, state: CanonState) -> None:
        # Use phase change as the elapsed-time anchor — survives runner
        # restarts within the same phase.
        if state.phase and state.phase != self._last_active:
            self._active_since = datetime.now(timezone.utc)
            self._last_active = state.phase

    def _refresh_state_summary(self, state: CanonState) -> None:
        summary = self.query_one("#state-summary", Static)
        if not state.phase:
            summary.update("[dim]○ idle · No automation running[/]")
            return

        status = state.status or "idle"
        status_color = STATUS_COLORS.get(status, "white")
        icon = PHASE_ICONS.get(state.phase, "◈")
        sublabel = _phase_sublabel(state)

        # Line 1: ● status · ▶ phase → sublabel · elapsed · iter N
        line1 = [f"[{status_color}]● {status}[/]"]
        phase_text = f"{icon} [bold]{state.phase}[/]"
        if sublabel and sublabel.lower() != state.phase.lower():
            phase_text += f" → {sublabel}"
        line1.append(phase_text)
        elapsed = _format_elapsed(self._active_since)
        if elapsed:
            line1.append(elapsed)
        if state.iteration:
            line1.append(f"iter {state.iteration}")
        lines = [" · ".join(line1)]

        # Line 2: metric chips (zero-valued non-errors filtered out)
        chips = _format_metric_chips(state.metrics)
        if chips:
            lines.append(" · ".join(chips))

        # Line 3: error banner if set
        if state.error:
            lines.append(f"[red bold]ERROR:[/] {state.error}")

        summary.update("\n".join(lines))

    # ------------------------------------------------------------------
    # Logs
    # ------------------------------------------------------------------

    def on_automation_dag_node_selected(
        self, event: AutomationDag.NodeSelected
    ) -> None:
        """Selecting a Flow node filters the logs in the System tab."""
        self._log_filter = event.node_id
        tabs = self.query_one("#automation-tabs", TabbedContent)
        self._auto_switching += 1
        tabs.active = "tab-pipeline"
        self.call_after_refresh(self._refresh_logs, self.state)

    async def _refresh_logs(self, state: CanonState) -> None:
        scroll = self.query_one("#automation-logs", VerticalScroll)
        await scroll.remove_children()

        logs = state.logs
        if self._log_filter:
            logs = tuple(
                e for e in logs
                if self._log_filter in e.message or self._log_filter in e.level
            )

        if not logs:
            label = (
                f"No logs for step '{self._log_filter}'"
                if self._log_filter
                else "Waiting for logs…"
            )
            await scroll.mount(
                Static(label, classes="empty-state", id="automation-logs-empty")
            )
            return

        recent = logs[-MAX_LOG_LINES:]
        widgets = [
            Static(_render_log(e), classes="log-line") for e in reversed(recent)
        ]
        await scroll.mount_all(widgets)
        scroll.scroll_home(animate=False)

        if state.error:
            await scroll.mount(
                Static(
                    f"[red bold]ERROR:[/] {state.error}",
                    classes="error-banner",
                )
            )
