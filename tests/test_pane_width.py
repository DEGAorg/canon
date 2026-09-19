"""Tests for the right-pane width keybindings + socket round-trip.

Pins the agent-facing protocol and the keybinding behaviour added in
plan ``20260505-pane-width`` (item 1):

- `,` / `.` step the pane width by ``PANE_WIDTH_STEP_CHARS`` cells, clamped
  to ``[PANE_WIDTH_MIN_CHARS, PANE_WIDTH_MAX_CHARS]``.
- ``set_pane_width`` accepts a percentage string (``"40%"``); validation
  range is ``[PANE_WIDTH_MIN_PCT, PANE_WIDTH_MAX_PCT]``.
- ``get_pane_width`` returns the current width string.
- Both socket commands accept the ``screen.`` namespace (``screen.set_pane_width``).
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest

from toad.screens.main import (
    MainScreen,
    PANE_WIDTH_DEFAULT,
    PANE_WIDTH_MAX_CHARS,
    PANE_WIDTH_MAX_PCT,
    PANE_WIDTH_MIN_CHARS,
    PANE_WIDTH_MIN_PCT,
    PANE_WIDTH_STEP_CHARS,
    _parse_percentage,
)
from toad.socket_controller import _dispatch


# ---------------------------------------------------------------------------
# _parse_percentage — pure validator
# ---------------------------------------------------------------------------


class TestParsePercentage:
    def test_accepts_min_value(self) -> None:
        assert _parse_percentage(f"{PANE_WIDTH_MIN_PCT}%") == PANE_WIDTH_MIN_PCT

    def test_accepts_max_value(self) -> None:
        assert _parse_percentage(f"{PANE_WIDTH_MAX_PCT}%") == PANE_WIDTH_MAX_PCT

    def test_accepts_default_value(self) -> None:
        # The reactive default ("50%") must always parse cleanly.
        assert _parse_percentage(PANE_WIDTH_DEFAULT) == int(
            PANE_WIDTH_DEFAULT.rstrip("%")
        )

    def test_rejects_below_min(self) -> None:
        with pytest.raises(ValueError):
            _parse_percentage(f"{PANE_WIDTH_MIN_PCT - 1}%")

    def test_rejects_above_max(self) -> None:
        with pytest.raises(ValueError):
            _parse_percentage(f"{PANE_WIDTH_MAX_PCT + 1}%")

    def test_rejects_missing_percent_sign(self) -> None:
        with pytest.raises(ValueError):
            _parse_percentage("50")

    def test_rejects_non_numeric(self) -> None:
        with pytest.raises(ValueError):
            _parse_percentage("half%")

    def test_rejects_empty_string(self) -> None:
        with pytest.raises(ValueError):
            _parse_percentage("")


# ---------------------------------------------------------------------------
# Keybinding wiring
# ---------------------------------------------------------------------------


def _binding_for(action: str) -> Any:
    """Return the ``Binding`` whose ``action`` matches, or ``None``."""
    for b in MainScreen.BINDINGS:
        if getattr(b, "action", None) == action:
            return b
    return None


class TestKeybindings:
    """The ``,`` and ``.`` keys must be wired to narrow / widen actions."""

    def test_narrow_pane_bound_to_comma(self) -> None:
        binding = _binding_for("narrow_pane")
        assert binding is not None, (
            "expected MainScreen.BINDINGS to contain narrow_pane"
        )
        # Textual canonicalises ``,`` as the key name ``comma``.
        assert binding.key == "comma", f"expected key='comma', got {binding.key!r}"

    def test_widen_pane_bound_to_full_stop(self) -> None:
        binding = _binding_for("widen_pane")
        assert binding is not None, (
            "expected MainScreen.BINDINGS to contain widen_pane"
        )
        # Textual canonicalises ``.`` as the key name ``full_stop``.
        assert binding.key == "full_stop", (
            f"expected key='full_stop', got {binding.key!r}"
        )


# ---------------------------------------------------------------------------
# Action behaviour — narrow / widen / set / get
#
# We borrow the ``MainScreen`` action methods onto a lightweight stub so we
# don't have to mount a full Textual app. The stub mimics the surface the
# action methods touch: ``pane_width`` is a plain attribute (not the reactive
# descriptor) and ``_current_pane_chars`` returns a known integer.
# ---------------------------------------------------------------------------


class _StubScreen:
    """Minimal stand-in for ``MainScreen`` with the action methods attached."""

    # Borrow the unbound methods we want to exercise.
    _clamp_chars = MainScreen._clamp_chars
    action_widen_pane = MainScreen.action_widen_pane
    action_narrow_pane = MainScreen.action_narrow_pane
    action_set_pane_width = MainScreen.action_set_pane_width
    action_get_pane_width = MainScreen.action_get_pane_width

    def __init__(self, current_chars: int, initial_width: str = PANE_WIDTH_DEFAULT) -> None:
        self.pane_width = initial_width
        self._current = current_chars

    def _current_pane_chars(self) -> int:
        return self._current


class TestWidenPane:
    def test_widen_increments_by_step(self) -> None:
        screen = _StubScreen(current_chars=60)
        screen.action_widen_pane()
        assert screen.pane_width == str(60 + PANE_WIDTH_STEP_CHARS)

    def test_widen_clamps_at_max(self) -> None:
        screen = _StubScreen(current_chars=PANE_WIDTH_MAX_CHARS)
        screen.action_widen_pane()
        assert screen.pane_width == str(PANE_WIDTH_MAX_CHARS)

    def test_widen_clamps_when_one_step_below_max(self) -> None:
        screen = _StubScreen(current_chars=PANE_WIDTH_MAX_CHARS - 1)
        screen.action_widen_pane()
        assert screen.pane_width == str(PANE_WIDTH_MAX_CHARS)

    def test_widen_writes_string_not_int(self) -> None:
        # The reactive holds CSS-compatible strings, not ints.
        screen = _StubScreen(current_chars=55)
        screen.action_widen_pane()
        assert isinstance(screen.pane_width, str)


class TestNarrowPane:
    def test_narrow_decrements_by_step(self) -> None:
        screen = _StubScreen(current_chars=60)
        screen.action_narrow_pane()
        assert screen.pane_width == str(60 - PANE_WIDTH_STEP_CHARS)

    def test_narrow_clamps_at_min(self) -> None:
        screen = _StubScreen(current_chars=PANE_WIDTH_MIN_CHARS)
        screen.action_narrow_pane()
        assert screen.pane_width == str(PANE_WIDTH_MIN_CHARS)

    def test_narrow_clamps_when_one_step_above_min(self) -> None:
        screen = _StubScreen(current_chars=PANE_WIDTH_MIN_CHARS + 1)
        screen.action_narrow_pane()
        assert screen.pane_width == str(PANE_WIDTH_MIN_CHARS)


class TestSetGetPaneWidth:
    def test_set_then_get_round_trip(self) -> None:
        screen = _StubScreen(current_chars=50)
        applied = screen.action_set_pane_width("40%")
        assert applied == "40%"
        assert screen.action_get_pane_width() == "40%"

    def test_set_at_lower_bound(self) -> None:
        screen = _StubScreen(current_chars=50)
        screen.action_set_pane_width(f"{PANE_WIDTH_MIN_PCT}%")
        assert screen.action_get_pane_width() == f"{PANE_WIDTH_MIN_PCT}%"

    def test_set_at_upper_bound(self) -> None:
        screen = _StubScreen(current_chars=50)
        screen.action_set_pane_width(f"{PANE_WIDTH_MAX_PCT}%")
        assert screen.action_get_pane_width() == f"{PANE_WIDTH_MAX_PCT}%"

    def test_set_invalid_percentage_raises(self) -> None:
        screen = _StubScreen(current_chars=50)
        with pytest.raises(ValueError):
            screen.action_set_pane_width("10%")
        # Invalid input must not mutate state.
        assert screen.action_get_pane_width() == PANE_WIDTH_DEFAULT

    def test_set_non_percentage_raises(self) -> None:
        screen = _StubScreen(current_chars=50)
        with pytest.raises(ValueError):
            screen.action_set_pane_width("50")
        assert screen.action_get_pane_width() == PANE_WIDTH_DEFAULT


# ---------------------------------------------------------------------------
# Socket dispatch — _FakeApp
#
# The real socket layer hands off ``set_pane_width`` to
# ``app.screen.action_set_pane_width`` (sync) and ``get_pane_width`` to
# ``app.screen.action_get_pane_width``. We model both with a stateful fake
# so a "set then get" pair round-trips through the dispatcher.
# ---------------------------------------------------------------------------


class _FakeScreen:
    """Stateful fake screen that mirrors the socket-facing contract."""

    def __init__(self, initial_width: str = PANE_WIDTH_DEFAULT) -> None:
        self._width = initial_width
        self.set_calls: list[str] = []
        self.get_calls: int = 0

    def action_set_pane_width(self, width: str) -> str:
        # Mirror the real action: validate, then store.
        _parse_percentage(width)
        self._width = width
        self.set_calls.append(width)
        return width

    def action_get_pane_width(self) -> str:
        self.get_calls += 1
        return self._width


class _FakeApp:
    """Mimics the subset of ``textual.app.App`` used by ``_dispatch``."""

    def __init__(self, screen: _FakeScreen | None = None) -> None:
        self.screen = screen if screen is not None else _FakeScreen()
        self.log = MagicMock()

    def query(self, _selector: str) -> list[Any]:
        return []


class TestSocketSetPaneWidth:
    def test_dispatch_routes_set_to_screen_action(self) -> None:
        app = _FakeApp()
        request = {
            "cmd": "action",
            "name": "set_pane_width",
            "args": {"width": "40%"},
        }
        response = asyncio.run(_dispatch(app, request))
        assert response == {"ok": True}
        assert app.screen.set_calls == ["40%"]
        assert app.screen.action_get_pane_width() == "40%"

    def test_dispatch_set_accepts_namespaced_action_name(self) -> None:
        """``screen.set_pane_width`` is the canonical agent-facing name."""
        app = _FakeApp()
        request = {
            "cmd": "action",
            "name": "screen.set_pane_width",
            "args": {"width": "60%"},
        }
        response = asyncio.run(_dispatch(app, request))
        assert response == {"ok": True}
        assert app.screen.set_calls == ["60%"]

    def test_dispatch_set_requires_args(self) -> None:
        app = _FakeApp()
        response = asyncio.run(
            _dispatch(app, {"cmd": "action", "name": "set_pane_width"})
        )
        assert "error" in response
        assert app.screen.set_calls == []

    def test_dispatch_set_requires_width_string(self) -> None:
        app = _FakeApp()
        response = asyncio.run(
            _dispatch(
                app, {"cmd": "action", "name": "set_pane_width", "args": {}}
            )
        )
        assert "error" in response
        assert app.screen.set_calls == []

    def test_dispatch_set_rejects_non_string_width(self) -> None:
        app = _FakeApp()
        response = asyncio.run(
            _dispatch(
                app,
                {
                    "cmd": "action",
                    "name": "set_pane_width",
                    "args": {"width": 40},
                },
            )
        )
        assert "error" in response
        assert app.screen.set_calls == []

    def test_dispatch_set_invalid_percentage_returns_error(self) -> None:
        app = _FakeApp()
        response = asyncio.run(
            _dispatch(
                app,
                {
                    "cmd": "action",
                    "name": "set_pane_width",
                    "args": {"width": "10%"},
                },
            )
        )
        assert "error" in response, response
        # Width below the floor must not be applied.
        assert app.screen.action_get_pane_width() == PANE_WIDTH_DEFAULT

    def test_dispatch_set_above_max_returns_error(self) -> None:
        app = _FakeApp()
        response = asyncio.run(
            _dispatch(
                app,
                {
                    "cmd": "action",
                    "name": "set_pane_width",
                    "args": {"width": "90%"},
                },
            )
        )
        assert "error" in response, response
        assert app.screen.action_get_pane_width() == PANE_WIDTH_DEFAULT


class TestSocketGetPaneWidth:
    def test_dispatch_get_returns_current_width(self) -> None:
        app = _FakeApp(_FakeScreen(initial_width="50%"))
        response = asyncio.run(
            _dispatch(app, {"cmd": "action", "name": "get_pane_width"})
        )
        assert response == {"ok": True, "width": "50%"}
        assert app.screen.get_calls == 1

    def test_dispatch_get_accepts_namespaced_action_name(self) -> None:
        app = _FakeApp(_FakeScreen(initial_width="50%"))
        response = asyncio.run(
            _dispatch(app, {"cmd": "action", "name": "screen.get_pane_width"})
        )
        assert response == {"ok": True, "width": "50%"}


class TestSocketRoundTrip:
    """A set followed by a get returns what was set."""

    def test_set_then_get(self) -> None:
        app = _FakeApp()
        set_response = asyncio.run(
            _dispatch(
                app,
                {
                    "cmd": "action",
                    "name": "set_pane_width",
                    "args": {"width": "40%"},
                },
            )
        )
        assert set_response == {"ok": True}

        get_response = asyncio.run(
            _dispatch(app, {"cmd": "action", "name": "get_pane_width"})
        )
        assert get_response == {"ok": True, "width": "40%"}

    def test_namespaced_set_then_namespaced_get(self) -> None:
        app = _FakeApp()
        asyncio.run(
            _dispatch(
                app,
                {
                    "cmd": "action",
                    "name": "screen.set_pane_width",
                    "args": {"width": "70%"},
                },
            )
        )
        get_response = asyncio.run(
            _dispatch(app, {"cmd": "action", "name": "screen.get_pane_width"})
        )
        assert get_response == {"ok": True, "width": "70%"}

    def test_invalid_set_does_not_change_width(self) -> None:
        app = _FakeApp(_FakeScreen(initial_width="50%"))
        bad_response = asyncio.run(
            _dispatch(
                app,
                {
                    "cmd": "action",
                    "name": "set_pane_width",
                    "args": {"width": "not-a-percent"},
                },
            )
        )
        assert "error" in bad_response

        get_response = asyncio.run(
            _dispatch(app, {"cmd": "action", "name": "get_pane_width"})
        )
        # The earlier value must persist after a rejected set.
        assert get_response == {"ok": True, "width": "50%"}
