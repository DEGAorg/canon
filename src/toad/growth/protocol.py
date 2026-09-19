"""Public protocol for the Growth right-pane plugin.

Canon TUI provides the section slot, status badge, refresh timer, and
ACP ``open_panel`` routing. The private ``toad.extensions.dega_growth``
submodule provides the actual widgets, data, and sub-tab UX. This file
defines the contract between them.

Plugin architecture with dependency inversion: the module imports this
protocol; the host has no compile-time dependency on the module.

Lifecycle (host calls these in order):

    available() → mount(container) → [refresh()...]

The host wraps ``refresh()`` calls in badge state transitions
(``UPDATING`` → ``POLLING`` on success, ``ERROR`` on exception). The
panel is responsible for everything that lives inside ``container``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from textual.widget import Widget


@runtime_checkable
class GrowthPanel(Protocol):
    """A pluggable Growth panel.

    Manifest fields are read by the host at discovery time without
    instantiating Textual widgets, so they must be plain attributes (or
    properties) on the panel object.
    """

    # --- manifest ---
    id: str
    """Stable identifier used for ACP ``open_panel`` routing (e.g. ``"growth"``)."""

    title: str
    """Toolbar button label and TabPane title (e.g. ``"Growth"``)."""

    accent: str
    """CSS colour for the section's left-border accent (e.g. ``"purple"``)."""

    refresh_seconds: int | None
    """Auto-refresh cadence. ``None`` disables host-driven refresh."""

    # --- lifecycle ---

    async def available(self) -> bool:
        """Return ``True`` if the panel can serve data right now.

        Called before ``mount`` and again before each scheduled refresh.
        Returning ``False`` flips the host's badge to ``OFFLINE``.
        """
        ...

    async def mount(self, container: "Widget") -> None:
        """Populate ``container`` with the panel's widget tree.

        Called once when the section first becomes visible. The panel
        owns everything inside ``container``: layout, sub-tabs,
        DataTables, detail screens, key handlers. Use
        ``container.app.push_screen(...)`` from inside mounted widgets
        to surface modal screens.
        """
        ...

    async def refresh(self) -> None:
        """Re-fetch and update the already-mounted widgets in place.

        Called by the host on its timer (every ``refresh_seconds``
        seconds). Should not re-mount; should not assume the section is
        currently visible. Raise on transient failures — the host
        translates exceptions into the section's ``ERROR`` badge state.
        """
        ...
