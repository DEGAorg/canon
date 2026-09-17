"""Tests for the right-pane section status badge."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from textual.app import App

from toad.widgets.section_status_badge import (
    BadgeState,
    SectionStatusBadge,
    _relative_time,
)


def _strip(badge: SectionStatusBadge) -> str:
    """Plain-text rendering of the badge's current Rich Text."""
    return badge.render().plain


class _Harness(App):
    def __init__(self, badge: SectionStatusBadge) -> None:
        super().__init__()
        self.badge = badge

    def compose(self):
        yield self.badge


class TestRelativeTime:
    def test_seconds(self) -> None:
        when = datetime.now(tz=timezone.utc) - timedelta(seconds=5)
        assert _relative_time(when) == "5s ago"

    def test_minutes(self) -> None:
        when = datetime.now(tz=timezone.utc) - timedelta(minutes=3, seconds=2)
        assert _relative_time(when) == "3m ago"

    def test_hours(self) -> None:
        when = datetime.now(tz=timezone.utc) - timedelta(hours=2)
        assert _relative_time(when) == "2h ago"

    def test_just_now(self) -> None:
        when = datetime.now(tz=timezone.utc)
        assert _relative_time(when) == "just now"


class TestRendering:
    async def _mounted(self, badge: SectionStatusBadge) -> str:
        async with _Harness(badge).run_test() as pilot:
            await pilot.pause()
            return _strip(badge)

    def test_idle_renders_label(self) -> None:
        async def run() -> str:
            return await self._mounted(SectionStatusBadge(BadgeState.IDLE))

        text = asyncio.run(run())
        assert "IDLE" in text
        assert "●" in text or "○" in text

    def test_error_with_message(self) -> None:
        async def run() -> str:
            badge = SectionStatusBadge(BadgeState.ERROR, message="GH 401")
            return await self._mounted(badge)

        text = asyncio.run(run())
        assert "ERROR" in text
        assert "GH 401" in text

    def test_mark_updated_adds_relative_time(self) -> None:
        async def run() -> str:
            badge = SectionStatusBadge(BadgeState.POLLING)
            async with _Harness(badge).run_test() as pilot:
                await pilot.pause()
                badge.mark_updated()
                await pilot.pause()
                return _strip(badge)

        text = asyncio.run(run())
        # mark_updated() ran an instant ago — must show "just now" (or 0s).
        assert "just now" in text or "0s ago" in text

    def test_set_state_changes_label(self) -> None:
        async def run() -> str:
            badge = SectionStatusBadge(BadgeState.IDLE)
            async with _Harness(badge).run_test() as pilot:
                await pilot.pause()
                badge.set_state(BadgeState.LIVE)
                await pilot.pause()
                return _strip(badge)

        assert "LIVE" in asyncio.run(run())


class TestPulse:
    def test_pulse_only_for_live_states(self) -> None:
        """The pulse timer is created for ``LIVE`` / ``POLLING`` /
        ``UPDATING`` and stopped for static states. We assert against
        the private timer because the visual blink is what the test
        is fundamentally about, not a side effect.
        """

        async def run() -> tuple[bool, bool]:
            badge = SectionStatusBadge(BadgeState.LIVE)
            async with _Harness(badge).run_test() as pilot:
                await pilot.pause()
                live_has_timer = badge._pulse_timer is not None
                badge.set_state(BadgeState.IDLE)
                await pilot.pause()
                idle_has_timer = badge._pulse_timer is not None
                return live_has_timer, idle_has_timer

        live, idle = asyncio.run(run())
        assert live is True
        assert idle is False
