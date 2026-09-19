"""Property-based tests for DEGA app helpers and parsers."""

from __future__ import annotations

import string

import pytest
from hypothesis import given, settings, strategies as st

from toad.extensions.dega_panel.registry_client import (
    MAX_USERNAME,
    RegistryError,
    VALID_CHARS,
    canonical_username,
    display_name,
    validate_username,
)
from toad.extensions.dega_panel.utility import UtilityView


ALLOWED = tuple(sorted(VALID_CHARS))
NOISE_CHARS = string.ascii_lowercase + string.digits + " .,_-/"


class _Pane:
    def __init__(self) -> None:
        self.elements = {"Silver Fire": 5, "Golden Water": 3, "Obsidian Earth": 2}


def make_view() -> UtilityView:
    return UtilityView(_Pane())


@st.composite
def valid_username_inputs(draw: st.DrawFn) -> str:
    core = draw(st.text(alphabet=ALLOWED, min_size=1, max_size=MAX_USERNAME))
    left_ws = draw(st.text(alphabet=" \t", max_size=2))
    right_ws = draw(st.text(alphabet=" \t", max_size=2))
    suffix = draw(st.sampled_from(["", ".dega", " .dega", ".dega ", " .dega "]))
    return f"{left_ws}{core}{right_ws}{suffix}"


@st.composite
def invalid_username_inputs(draw: st.DrawFn) -> str:
    kind = draw(st.sampled_from(["empty", "too_long", "bad_char"]))
    if kind == "empty":
        return ""
    if kind == "too_long":
        return draw(st.text(alphabet=ALLOWED, min_size=MAX_USERNAME + 1, max_size=MAX_USERNAME + 8))
    core = draw(st.text(alphabet=ALLOWED, min_size=1, max_size=MAX_USERNAME))
    # Must not be rescued by canonical_username().strip().removesuffix(".dega").strip()
    bad = draw(st.sampled_from(["@", "/", "#", "\u2603", "!", "$", "%"]))
    pos = draw(st.integers(min_value=0, max_value=len(core)))
    return core[:pos] + bad + core[pos:]


@st.composite
def signal_case(draw: st.DrawFn):
    kind = draw(st.sampled_from(["injury", "momentum", "executed", "noise"]))
    if kind == "injury":
        player = draw(st.text(alphabet=string.ascii_letters + " -'", min_size=1, max_size=20).filter(lambda s: "|" not in s and "(" not in s and ")" not in s))
        team = draw(st.text(alphabet=string.ascii_uppercase, min_size=1, max_size=4))
        status = draw(st.text(alphabet=string.ascii_letters + " -", min_size=1, max_size=12).filter(lambda s: "|" not in s))
        impact = draw(st.integers(min_value=0, max_value=999)) / 10
        impact_s = f"{impact:.1f}"
        line = (
            f"INJURY SIGNAL: {player} ({team}) -> {status} | "
            f"Impact: {impact_s}% | Confidence: 80% | Affected markets: 4"
        )
        return line, (f"{player.strip()} ({team}) -> {status.strip()}", "Injury", impact_s, "")
    if kind == "momentum":
        market = draw(st.text(alphabet=string.ascii_letters + string.digits + " -_()", min_size=1, max_size=25).filter(lambda s: "|" not in s and '"' not in s))
        moved = draw(st.integers(min_value=0, max_value=999)) / 10
        moved_s = f"{moved:.1f}"
        line = f'MOMENTUM LAG: "{market}" moved {moved_s}¢ | 1 lagged market(s) detected'
        return line, (market, "Momentum", moved_s, "")
    if kind == "executed":
        action = draw(st.sampled_from(["BUY_YES", "SELL_NO", "HOLD"]))
        market = draw(st.text(alphabet=string.ascii_letters + string.digits + " -_()", min_size=1, max_size=25).filter(lambda s: "|" not in s))
        line = f"EXECUTED (dry-run): {action} | Market: {market}"
        return line, (market, action.title(), "", "")
    line = draw(st.text(alphabet=NOISE_CHARS, min_size=1, max_size=40))
    return line, None


@settings(max_examples=150)
@given(raw=valid_username_inputs())
def test_validate_username_accepts_valid_inputs(raw: str) -> None:
    canon = validate_username(raw)
    assert canon == canonical_username(raw)
    assert 1 <= len(canon) <= MAX_USERNAME
    assert all(c in VALID_CHARS for c in canon)
    assert display_name(canon) == f"{canon}.dega"


@settings(max_examples=150)
@given(raw=invalid_username_inputs())
def test_validate_username_rejects_invalid_inputs(raw: str) -> None:
    with pytest.raises(RegistryError):
        validate_username(raw)


@settings(max_examples=120)
@given(cases=st.lists(signal_case(), min_size=0, max_size=10))
def test_parse_signal_lines_matches_templates(cases: list[tuple[str, tuple[str, str, str, str] | None]]) -> None:
    view = make_view()
    lines = [line for line, _ in cases]
    expected = []
    for line, row in cases:
        if row is None:
            continue
        # Mirror the parser's .strip() on the textual fields so the property
        # stays aligned with the implementation instead of overspecifying spaces.
        market, signal, prob, delta = row
        expected.append((market.strip(), signal, prob, delta))
    assert view._parse_signal_lines(lines) == expected


@settings(max_examples=80)
@given(noise=st.lists(st.text(alphabet=NOISE_CHARS, min_size=1, max_size=30), min_size=1, max_size=10))
def test_parse_signal_lines_ignores_noise(noise: list[str]) -> None:
    view = make_view()
    assert view._parse_signal_lines(noise) == []
