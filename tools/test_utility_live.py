"""Headless unit test for the DEGA UtilityView live-signal parser.

Tests the pure `_parse_signal_lines` method (no Textual event loop needed,
so it cannot hang) plus syntax of the utility module.
"""
from __future__ import annotations

import ast
from pathlib import Path

from toad.extensions.dega_panel.utility import UtilityView


def make_view() -> UtilityView:
    # Instantiate without mounting; _parse_signal_lines is instance-independent.
    class _Pane:
        def __init__(self):
            self.elements = {"Silver Fire": 5, "Golden Water": 3, "Obsidian Earth": 2}

    return UtilityView(_Pane())


def test_parse_signal_lines() -> None:
    view = make_view()
    lines = [
        "INJURY SIGNAL: Giannis Antetokounmpo (MIL) -> Questionable | Impact: 2.6% | Confidence: 80% | Affected markets: 4",
        "MOMENTUM LAG: \"Jayson Tatum (BOS)\" moved 2.1¢ | 1 lagged market(s) detected",
        "EXECUTED (dry-run): BUY_YES | Market: Doncic questionable | $10 @ 55.00¢",
        "Fetched 160 markets, 76 injury reports",  # noise -> ignored
    ]
    rows = view._parse_signal_lines(lines)
    print("rows:", rows)
    assert len(rows) == 3, f"expected 3 rows, got {len(rows)}"

    market, signal, prob, delta = rows[0]
    assert "Giannis" in market and signal == "Injury" and prob == "2.6"
    assert rows[1][1] == "Momentum" and rows[1][2] == "2.1"
    assert rows[2][1] == "Buy_Yes" and "Doncic" in rows[2][0]

    # No recognised lines -> empty (caller falls back to static SIGNALS).
    assert view._parse_signal_lines(["hello world", "noise here"]) == []


def test_module_syntax() -> None:
    # Resolve the real module file instead of a stale relative path.
    import inspect

    p = Path(inspect.getfile(UtilityView))
    ast.parse(p.read_text())
    print("syntax: OK")


if __name__ == "__main__":
    test_module_syntax()
    test_parse_signal_lines()
    print("\nUTILITY LIVE-PARSER UNIT: PASS")
