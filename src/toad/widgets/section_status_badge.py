"""SectionStatusBadge — pulsing dot + state + relative-update label.

A single-line live status pill for the right-pane sections. Renders as

    ● LIVE   ·   3s ago

with the dot pulsing every 800ms while the state is "live" or
"updating", static otherwise. Owners (sections, panes, widgets) call
:meth:`mark_updated` whenever the underlying data refreshes; the
badge keeps its own timer to re-render the relative timestamp every
second so "3s ago" stays honest without the owner having to do
anything.

The component is intentionally dumb about *what* refreshed — it only
tracks "when was the last update?" and "what state should I claim?".
Sections set the state once on mount (typically ``State.LIVE`` for
streaming, ``State.POLLING`` for periodic, ``State.IDLE`` for
inactive), then call ``mark_updated()`` from their existing refresh
hooks.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from rich.text import Text
from textual.reactive import reactive
from textual.timer import Timer
from textual.widgets import Static


__all__ = ["SectionStatusBadge", "BadgeState"]


_PULSE_INTERVAL = 0.8
_TICK_INTERVAL = 1.0


class BadgeState(str, Enum):
    """The badge has six well-known states.

    Each state controls the dot colour and the verb shown after it.
    Section owners pick the state that fits their refresh shape and
    don't usually toggle between them at runtime — except for ``ERROR``
    / ``IDLE`` overrides during failure or shutdown.
    """

    LIVE = "live"          # Streaming source — pulses
    POLLING = "polling"    # Interval-driven refresh — pulses
    UPDATING = "updating"  # One-off refresh in flight — pulses faster
    IDLE = "idle"          # Source available but quiet — static
    ERROR = "error"        # Refresh failed — static, red
    OFFLINE = "offline"    # No source / disabled — static, dim


_STATE_LABELS: dict[BadgeState, str] = {
    BadgeState.LIVE: "LIVE",
    BadgeState.POLLING: "POLLING",
    BadgeState.UPDATING: "UPDATING",
    BadgeState.IDLE: "IDLE",
    BadgeState.ERROR: "ERROR",
    BadgeState.OFFLINE: "OFFLINE",
}

_STATE_COLOURS: dict[BadgeState, str] = {
    BadgeState.LIVE: "bright_green",
    BadgeState.POLLING: "cyan",
    BadgeState.UPDATING: "yellow",
    BadgeState.IDLE: "grey50",
    BadgeState.ERROR: "red",
    BadgeState.OFFLINE: "grey30",
}

_PULSING_STATES = frozenset({BadgeState.LIVE, BadgeState.POLLING, BadgeState.UPDATING})


class SectionStatusBadge(Static):
    """Compact status pill for right-pane section headers.

    Usage::

        badge = SectionStatusBadge(BadgeState.POLLING)
        # … later, from the section's refresh hook:
        badge.mark_updated()
        # … on permanent failure:
        badge.set_state(BadgeState.ERROR, message="GH 401")
    """

    DEFAULT_CSS = """
    SectionStatusBadge {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    """

    state: reactive[BadgeState] = reactive(BadgeState.IDLE, init=False)

    def __init__(
        self,
        state: BadgeState = BadgeState.IDLE,
        *,
        message: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._last_update: datetime | None = None
        self._message = message
        self._pulse_on = True
        self._pulse_timer: Timer | None = None
        self._tick_timer: Timer | None = None
        # Initial state goes through ``set_reactive`` so the watcher
        # doesn't fire on construction (the widget isn't mounted yet
        # and the pulse timer can't be created until it is).
        self.set_reactive(SectionStatusBadge.state, state)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def mark_updated(self) -> None:
        """Record that the underlying source just refreshed.

        Resets the relative-time counter shown after the state label.
        Does not change ``state`` — sections call this from their
        existing refresh hooks; state transitions go through
        :meth:`set_state`.
        """
        self._last_update = datetime.now(tz=timezone.utc)
        self.refresh()

    def set_state(self, state: BadgeState, *, message: str | None = None) -> None:
        """Move to a new state, optionally with a one-line message.

        ``message`` is appended after the state label (useful for
        ``ERROR``: ``● ERROR  ·  GH 401``). Cleared by passing
        ``message=None`` or by transitioning to a non-error state.
        """
        self._message = message
        self.state = state

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        self._tick_timer = self.set_interval(_TICK_INTERVAL, self.refresh)
        self._sync_pulse_timer()

    def on_unmount(self) -> None:
        if self._pulse_timer is not None:
            self._pulse_timer.stop()
            self._pulse_timer = None
        if self._tick_timer is not None:
            self._tick_timer.stop()
            self._tick_timer = None

    # ------------------------------------------------------------------
    # Reactive watcher
    # ------------------------------------------------------------------

    def watch_state(self, _old: BadgeState, _new: BadgeState) -> None:
        # The pulse timer only runs while the state pulses; flipping
        # to/from a static state should add or drop it.
        self._sync_pulse_timer()
        self._pulse_on = True
        self.refresh()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _sync_pulse_timer(self) -> None:
        wants_pulse = self.state in _PULSING_STATES
        if wants_pulse and self._pulse_timer is None:
            self._pulse_timer = self.set_interval(_PULSE_INTERVAL, self._toggle_pulse)
        elif not wants_pulse and self._pulse_timer is not None:
            self._pulse_timer.stop()
            self._pulse_timer = None
            self._pulse_on = True  # leave the dot lit when static

    def _toggle_pulse(self) -> None:
        self._pulse_on = not self._pulse_on
        self.refresh()

    def render(self) -> Text:
        colour = _STATE_COLOURS[self.state]
        dot_text = "●" if self._pulse_on else "○"
        label = _STATE_LABELS[self.state]
        text = Text()
        text.append(dot_text, style=f"bold {colour}")
        text.append(" ", style="")
        text.append(label, style=f"bold {colour}")
        if self._message:
            text.append("  ·  ", style="dim")
            text.append(self._message, style=colour)
        if self._last_update is not None:
            text.append("  ·  ", style="dim")
            text.append(_relative_time(self._last_update), style="dim")
        return text


def _relative_time(when: datetime) -> str:
    """Compact relative timestamp: ``3s ago``, ``2m ago``, ``1h ago``."""
    now = datetime.now(tz=timezone.utc)
    delta = (now - when).total_seconds()
    if delta < 1:
        return "just now"
    if delta < 60:
        return f"{int(delta)}s ago"
    if delta < 3600:
        return f"{int(delta // 60)}m ago"
    if delta < 86400:
        return f"{int(delta // 3600)}h ago"
    return f"{int(delta // 86400)}d ago"
