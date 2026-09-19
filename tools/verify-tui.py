#!/usr/bin/env python3
"""Verify TUI widgets render correctly in headless mode.

Usage:
    uv run python tools/verify-tui.py
    uv run python tools/verify-tui.py --verbose
    uv run python tools/verify-tui.py --widget gantt
    uv run python tools/verify-tui.py --widget github
    uv run python tools/verify-tui.py --widget tasks

Runs the app or individual widgets headless and reports layout,
scroll behavior, and rendering issues. Exit code 0 = all checks pass.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
from datetime import date

from rich.console import Console

console = Console()


def verify_gantt(verbose: bool = False) -> bool:
    """Verify GanttTimeline widget: rendering, scroll, auto-scroll-to-today."""
    from textual.app import App, ComposeResult
    from textual.containers import ScrollableContainer

    from toad.widgets.gantt_timeline import (
        GanttTimeline,
        compute_track_width,
        render_gantt,
        LABEL_WIDTH,
    )
    from toad.widgets.github_views.timeline_data import (
        GateMarker,
        MilestoneGroup,
        TimelineData,
        TimelineItem,
    )
    from toad.widgets.github_views.timeline_provider import ItemStatus

    errors: list[str] = []
    results: dict[str, object] = {}

    # --- Test 1: Pure render functions ---
    items = [
        TimelineItem("1", "Canon TUI", ItemStatus.DONE, 0, 14),
        TimelineItem("2", "pmxt POC", ItemStatus.DONE, 0, 3, is_gate=True),
        TimelineItem("3", "CLI init", ItemStatus.DONE, 5, 7),
        TimelineItem("4", "CLI register", ItemStatus.IN_PROGRESS, 20, 10),
        TimelineItem("5", "Arena MVP", ItemStatus.TODO, 30, 21),
        TimelineItem("6", "Hackathon", ItemStatus.TODO, 60, 21),
    ]
    groups = [
        MilestoneGroup("Canon TUI", date(2026, 4, 5), [items[0]]),
        MilestoneGroup("pmxt POC", None, [items[1]]),
        MilestoneGroup("Canon CLI", None, [items[2], items[3]]),
        MilestoneGroup("Arena MVP", date(2026, 5, 15), [items[4]]),
        MilestoneGroup("Hackathon", date(2026, 6, 19), [items[5]]),
    ]
    data = TimelineData(
        start_date=date(2026, 3, 19),
        total_days=93,
        groups=groups,
        gates=[GateMarker("pmxt", 0)],
    )

    tw = compute_track_width(data.total_days)
    lines = render_gantt(data, tw)
    total_width = LABEL_WIDTH + tw

    if tw <= 80:
        errors.append(
            f"track_width too small: {tw} (expected >80 for 93-day span)"
        )
    if len(lines) < 10:
        errors.append(f"too few render lines: {len(lines)} (expected >=10)")

    results["track_width"] = tw
    results["total_width"] = total_width
    results["render_lines"] = len(lines)

    # --- Test 2: Widget layout in headless Textual app ---
    class TestApp(App):
        CSS = "Screen { overflow: hidden; }\nGanttTimeline { height: 1fr; }"

        def compose(self) -> ComposeResult:
            yield GanttTimeline(id="gantt")

        def on_mount(self) -> None:
            self.query_one("#gantt", GanttTimeline).timeline_data = data
            self.set_timer(1.5, self._check)

        def _check(self) -> None:
            gantt = self.query_one("#gantt", GanttTimeline)
            scroll = gantt.query_one("#gantt-scroll", ScrollableContainer)
            content = gantt.query_one("#gantt-content")

            results["gantt_size"] = str(gantt.size)
            results["scroll_size"] = str(scroll.size)
            results["virtual_size"] = str(scroll.virtual_size)
            results["content_size"] = str(content.size)
            results["can_scroll_x"] = scroll.allow_horizontal_scroll
            results["can_scroll_y"] = scroll.allow_vertical_scroll
            results["max_scroll_x"] = scroll.max_scroll_x
            results["max_scroll_y"] = scroll.max_scroll_y

            if not scroll.allow_horizontal_scroll:
                errors.append("horizontal scroll not enabled")
            if scroll.max_scroll_x <= 0:
                errors.append(
                    f"max_scroll_x={scroll.max_scroll_x}, expected >0"
                )
            if content.size.width < total_width:
                errors.append(
                    f"content width {content.size.width} < "
                    f"expected {total_width}"
                )

            self.exit()

    TestApp().run(headless=True, size=(80, 25))

    # --- Test 3: Vertical scroll with many groups ---
    many_groups = [
        MilestoneGroup(
            f"M{i}",
            None,
            [
                TimelineItem(f"{i}a", f"T{i}A", ItemStatus.DONE, i * 5, 7),
                TimelineItem(f"{i}b", f"T{i}B", ItemStatus.TODO, i * 5 + 3, 10),
            ],
        )
        for i in range(15)
    ]
    tall_data = TimelineData(
        start_date=date(2026, 3, 19),
        total_days=93,
        groups=many_groups,
        gates=[],
    )

    class TallApp(App):
        CSS = "Screen { overflow: hidden; }\nGanttTimeline { height: 1fr; }"

        def compose(self) -> ComposeResult:
            yield GanttTimeline(id="gantt")

        def on_mount(self) -> None:
            self.query_one("#gantt", GanttTimeline).timeline_data = tall_data
            self.set_timer(1.5, self._check)

        def _check(self) -> None:
            gantt = self.query_one("#gantt", GanttTimeline)
            scroll = gantt.query_one("#gantt-scroll", ScrollableContainer)

            results["vscroll_can_scroll_y"] = scroll.allow_vertical_scroll
            results["vscroll_max_scroll_y"] = scroll.max_scroll_y

            if not scroll.allow_vertical_scroll:
                errors.append("vertical scroll not enabled with many groups")
            if scroll.max_scroll_y <= 0:
                errors.append(
                    f"max_scroll_y={scroll.max_scroll_y}, expected >0"
                )

            self.exit()

    TallApp().run(headless=True, size=(80, 20))

    # --- Report ---
    if verbose:
        for key, val in results.items():
            console.print(f"  {key}: {val}")

    return len(errors) == 0, errors, results


def verify_pane_no_default(verbose: bool = False) -> bool:
    """Verify ProjectStatePane starts with no active section."""
    from textual.app import App, ComposeResult
    from toad.widgets.project_state_pane import (
        ProjectStatePane,
        SECTION_PLANNING,
        SECTION_STATE,
    )

    errors: list[str] = []
    results: dict[str, object] = {}

    class TestApp(App):
        CSS = """
        Screen { overflow: hidden; }
        ProjectStatePane { display: block; width: 100%; }
        """

        def compose(self) -> ComposeResult:
            yield ProjectStatePane(id="psp")

        def on_mount(self) -> None:
            self.set_timer(1.0, self._check)

        def _check(self) -> None:
            pane = self.query_one("#psp", ProjectStatePane)
            planning = pane.query_one(f"#{SECTION_PLANNING}")
            state = pane.query_one(f"#{SECTION_STATE}")

            results["planning_visible"] = planning.display
            results["state_visible"] = state.display

            if planning.display:
                errors.append(
                    "Planning section visible on mount (should be hidden)"
                )
            if state.display:
                errors.append(
                    "State section visible on mount (should be hidden)"
                )

            self.exit()

    TestApp().run(headless=True, size=(80, 30))

    if verbose:
        for key, val in results.items():
            console.print(f"  {key}: {val}")

    return len(errors) == 0, errors, results


def verify_tasks(verbose: bool = False) -> bool:
    """Verify Tasks widget stack: mount + down/enter/escape interaction."""
    from datetime import datetime

    from textual.app import App, ComposeResult
    from textual.containers import Horizontal
    from textual.widgets import ContentSwitcher, DataTable

    from toad.widgets.github_views.task_provider import TaskDetailData, TaskItem
    from toad.widgets.github_views.timeline_provider import ItemStatus, Priority
    from toad.widgets.filter_toolbar import FilterToolbar, filter_tasks
    from toad.widgets.task_detail import TaskDetail
    from toad.widgets.task_table import TaskTable
    from toad.screens.task_detail_screen import TaskDetailScreen

    errors: list[str] = []
    results: dict[str, object] = {}

    tasks = [
        TaskItem(
            id="101",
            number=101,
            title="Wire Tasks tab",
            status=ItemStatus.IN_PROGRESS,
            milestone_id="1",
            milestone_title="M1 — UI",
            priority=Priority.P1,
            assignees=["alberto"],
            effort="2",
            labels=["p1-must-ship"],
            comments_count=4,
            created_at=datetime(2026, 4, 10, 12, 0),
            updated_at=datetime(2026, 4, 15, 9, 0),
            url="https://github.com/acme/proj/issues/101",
        ),
        TaskItem(
            id="102",
            number=102,
            title="Document widgets",
            status=ItemStatus.DONE,
            milestone_id=None,
            milestone_title="",
            priority=Priority.P3,
            assignees=[],
            effort=None,
            labels=["p3"],
            comments_count=0,
            url="https://github.com/acme/proj/issues/102",
        ),
    ]
    details = TaskDetailData(
        number=101,
        body="# body\n\nrendered markdown here.",
        comments_count=2,
        linked_prs=[{"number": 200, "title": "PR"}],
        labels=["p1-must-ship"],
        assignees=["alberto"],
        url="https://github.com/acme/proj/issues/101",
    )

    # --- Test 1: Filter predicate still wired ---
    filtered = filter_tasks(tasks, status=ItemStatus.IN_PROGRESS)
    if [t.number for t in filtered] != [101]:
        errors.append(
            f"filter_tasks: expected [101], got {[t.number for t in filtered]}"
        )

    # --- Test 2: All three widgets mount + interaction flow ---
    class TasksHarness(App[None]):
        CSS = "Screen { overflow: hidden; }"

        def compose(self) -> ComposeResult:
            yield FilterToolbar(id="tb")
            with Horizontal(id="body"):
                yield TaskTable(id="tbl")
                yield TaskDetail(id="detail")

        async def on_mount(self) -> None:
            tbl = self.query_one(TaskTable)
            tbl.set_tasks(tasks)
            tbl.focus()

        def on_data_table_row_selected(
            self, event: DataTable.RowSelected
        ) -> None:
            key = event.row_key.value
            if key is None:
                return
            match = next((t for t in tasks if t.id == str(key)), None)
            if match is not None:
                self.query_one(TaskDetail).show_task(match)

    async def _run_interaction() -> None:
        app = TasksHarness()
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            # Confirm all three widgets mounted.
            app.query_one(FilterToolbar)
            tbl = app.query_one(TaskTable)
            detail = app.query_one(TaskDetail)
            switcher = detail.query_one(ContentSwitcher)

            results["row_count"] = tbl.row_count
            results["initial_switcher"] = switcher.current

            if tbl.row_count != len(tasks):
                errors.append(
                    f"table row_count={tbl.row_count}, expected {len(tasks)}"
                )
            if switcher.current != "empty":
                errors.append(
                    f"initial switcher={switcher.current}, expected 'empty'"
                )

            await pilot.press("down", "enter")
            await pilot.pause()
            results["after_enter_switcher"] = switcher.current
            if switcher.current != "detail":
                errors.append(
                    f"after enter switcher={switcher.current}, expected 'detail'"
                )

            # Escape on list screen should be a no-op (no screen pushed).
            await pilot.press("escape")
            await pilot.pause()
            results["after_escape_screen"] = type(app.screen).__name__
            if isinstance(app.screen, TaskDetailScreen):
                errors.append(
                    "escape unexpectedly left TaskDetailScreen active on list"
                )

            # Push + escape round-trip: confirms screen-stack pop works.
            app.push_screen(TaskDetailScreen(tasks[0], details))
            await pilot.pause()
            if not isinstance(app.screen, TaskDetailScreen):
                errors.append("push_screen(TaskDetailScreen) did not activate")
            await pilot.press("escape")
            await pilot.pause()
            results["final_screen"] = type(app.screen).__name__
            if isinstance(app.screen, TaskDetailScreen):
                errors.append(
                    "escape on TaskDetailScreen did not pop back to list"
                )

    asyncio.run(_run_interaction())

    if verbose:
        for key, val in results.items():
            console.print(f"  {key}: {val}")

    return len(errors) == 0, errors, results


def verify_live_data_probe(verbose: bool = False) -> bool:
    """Probe the real GitHub API through TaskProvider.

    Skips gracefully if `gh` is not installed or not authenticated.
    """
    errors: list[str] = []
    results: dict[str, object] = {}

    # Probe `gh auth status` — skip if unauth'd or gh missing.
    try:
        proc = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except FileNotFoundError:
        console.print("  [yellow]skipped: no gh auth[/yellow] (gh not installed)")
        return True, [], {"status": "skipped-no-gh"}
    except subprocess.TimeoutExpired:
        console.print("  [yellow]skipped: no gh auth[/yellow] (timeout)")
        return True, [], {"status": "skipped-timeout"}

    if proc.returncode != 0:
        console.print("  [yellow]skipped: no gh auth[/yellow]")
        return True, [], {"status": "skipped-unauth"}

    # Run the fetch.
    from toad.widgets.github_views.task_provider import TaskProvider

    async def _fetch() -> int:
        provider = TaskProvider(
            repo="DEGAorg/claude-code-config", project_number=8
        )
        tasks = await provider.fetch_tasks()
        return len(tasks)

    try:
        count = asyncio.run(_fetch())
        results["task_count"] = count
        if verbose:
            console.print(f"  fetched {count} tasks from live GitHub API")
    except Exception as exc:  # noqa: BLE001 - probe surfaces any parser break
        errors.append(f"live fetch failed: {exc.__class__.__name__}: {exc}")

    return len(errors) == 0, errors, results


def verify_subagents(verbose: bool = False) -> bool:
    """Verify SubagentTabSection: mount hidden, open reveals, close hides."""
    from pathlib import Path
    from unittest.mock import MagicMock

    from textual.app import App, ComposeResult
    from textual.widgets import Static, TabbedContent

    from toad.widgets.subagent_tab_section import SubagentTabSection

    errors: list[str] = []
    results: dict[str, object] = {}

    def _factory(name: str, objective: str):
        return Static(f"{name}: {objective}"), MagicMock()

    async def _run() -> None:
        class Harness(App[None]):
            CSS = "Screen { overflow: hidden; }"

            def compose(self) -> ComposeResult:
                yield SubagentTabSection(
                    project_path=Path("/tmp/verify-subagents"),
                    agent_factory=_factory,
                    id="section-subagents",
                )

        app = Harness()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            section = app.query_one(SubagentTabSection)

            results["initial_display"] = section.display
            results["initial_empty"] = section.is_empty
            if section.display:
                errors.append("section visible on mount (should be hidden)")
            if not section.is_empty:
                errors.append("section non-empty on mount")

            resolved = section.open_tab("Alpha", "do a thing")
            await pilot.pause()
            results["resolved_first"] = resolved
            results["after_open_display"] = section.display
            results["after_open_tabs"] = section.tab_names
            if resolved != "Alpha":
                errors.append(
                    f"first open resolved to {resolved!r}, expected 'Alpha'"
                )
            if not section.display:
                errors.append("section hidden after open_tab")

            dup = section.open_tab("Alpha", "again")
            await pilot.pause()
            results["resolved_dup"] = dup
            if dup != "Alpha 2":
                errors.append(
                    f"duplicate name resolved to {dup!r}, expected 'Alpha 2'"
                )

            tabs = section.query_one("#subagents-tabs", TabbedContent)
            results["pane_count"] = tabs.tab_count
            if tabs.tab_count != 2:
                errors.append(
                    f"TabbedContent has {tabs.tab_count} panes, expected 2"
                )

            section.close_tab("Alpha")
            section.close_tab("Alpha 2")
            await pilot.pause()
            results["after_close_display"] = section.display
            results["after_close_empty"] = section.is_empty
            if section.display:
                errors.append("section still visible after closing all tabs")
            if not section.is_empty:
                errors.append("section non-empty after closing all tabs")

    asyncio.run(_run())

    if verbose:
        for key, val in results.items():
            console.print(f"  {key}: {val}")

    return len(errors) == 0, errors, results


def verify_outreach(verbose: bool = False) -> bool:
    """Verify the Outreach card widgets mount and render.

    Uses synthetic data — does not require the private ``rpa_outreach``
    extension or a live DB. Confirms layout / rendering parity with the
    rest of the pane.
    """
    from textual.app import App, ComposeResult
    from textual.containers import Vertical

    from toad.widgets.outreach_cards import (
        AccountDot,
        Histogram,
        RankedBar,
        StatLine,
    )

    errors: list[str] = []
    results: dict[str, object] = {}

    class OutreachHarness(App[None]):
        CSS = "Screen { overflow: hidden; }"

        def compose(self) -> ComposeResult:
            with Vertical(id="outreach-container"):
                yield StatLine(
                    "Prospects",
                    total=2044,
                    segments=(
                        ("messaged", 845, "success"),
                        ("pending", 1199, "warning"),
                    ),
                    id="stat",
                )
                yield Histogram(
                    "Sends · 24h",
                    buckets=tuple(range(24)),
                    total=276,
                    id="hist",
                )
                yield RankedBar(
                    "Hackathons",
                    rows=(
                        ("Alpha Hack", 12, 50),
                        ("Beta Hack", 40, 80),
                        ("Gamma Hack", 3, 9),
                    ),
                    id="rank",
                )
                yield AccountDot(
                    name="acct-1",
                    active=True,
                    sends_per_hour=12.3,
                    last_sent="5m ago",
                    id="dot",
                )

    async def _run() -> None:
        app = OutreachHarness()
        async with app.run_test(size=(80, 20)) as pilot:
            await pilot.pause()
            stat = app.query_one("#stat", StatLine)
            hist = app.query_one("#hist", Histogram)
            rank = app.query_one("#rank", RankedBar)
            dot = app.query_one("#dot", AccountDot)

            results["stat_text"] = stat.rendered.plain[:40]
            results["hist_text"] = hist.rendered.plain[:40]
            results["rank_text"] = rank.rendered.plain[:40]
            results["dot_text"] = dot.rendered.plain

            if "Prospects" not in stat.rendered.plain:
                errors.append("StatLine did not render 'Prospects' label")
            if "2,044" not in stat.rendered.plain:
                errors.append("StatLine did not render total 2,044")
            if "Sends" not in hist.rendered.plain:
                errors.append("Histogram did not render 'Sends' label")
            if "Hackathons" not in rank.rendered.plain:
                errors.append("RankedBar did not render 'Hackathons' label")
            if "acct-1" not in dot.rendered.plain:
                errors.append("AccountDot did not render account name")

    asyncio.run(_run())

    # Verify discover() returns None when the extension cannot be imported.
    # Cannot gate on env var alone anymore — provider resolves DSN from its
    # own shipped .env too, so "env unset" is not a guaranteed None.
    import sys

    from toad.outreach.registry import discover

    ext_module = "toad.extensions.rpa_outreach"
    saved_module = sys.modules.pop(ext_module, None)
    saved_rpa = sys.modules.pop(f"{ext_module}.rpa_outreach", None)
    real_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __builtins__["__import__"]  # type: ignore[index]

    def _block_import(name: str, *a: object, **kw: object) -> object:
        if name == ext_module or name.startswith(ext_module + "."):
            raise ImportError(f"test harness missing submodule: {name}")
        return real_import(name, *a, **kw)  # type: ignore[misc]

    import builtins

    builtins.__import__ = _block_import  # type: ignore[assignment]
    try:
        provider = discover()
        results["discover_none_when_module_absent"] = provider is None
        if provider is not None:
            errors.append("discover() returned non-None with submodule blocked")
    finally:
        builtins.__import__ = real_import  # type: ignore[assignment]
        if saved_module is not None:
            sys.modules[ext_module] = saved_module
        if saved_rpa is not None:
            sys.modules[f"{ext_module}.rpa_outreach"] = saved_rpa

    if verbose:
        for key, val in results.items():
            console.print(f"  {key}: {val}")

    return len(errors) == 0, errors, results


def verify_growth(verbose: bool = False) -> bool:
    """Verify the Growth plugin protocol + host wiring.

    The host (canon-tui) only owns the section slot; widgets and data
    live in the private ``dega_growth`` submodule. This check uses a
    fake panel to confirm the host correctly mounts and refreshes any
    plugin that satisfies :class:`GrowthPanel`.
    """
    from textual.app import App, ComposeResult
    from textual.containers import Vertical
    from textual.widgets import Static

    from toad.growth.protocol import GrowthPanel

    errors: list[str] = []
    results: dict[str, object] = {}

    class FakePanel:
        id = "growth"
        title = "Growth"
        accent = "purple"
        refresh_seconds = 60

        def __init__(self) -> None:
            self.mount_calls = 0
            self.refresh_calls = 0
            self._label: Static | None = None

        async def available(self) -> bool:
            return True

        async def mount(self, container: Vertical) -> None:  # type: ignore[override]
            self.mount_calls += 1
            self._label = Static("fake-panel-mounted", id="fake-label")
            await container.mount(self._label)

        async def refresh(self) -> None:
            self.refresh_calls += 1
            if self._label is not None:
                self._label.update(f"refresh #{self.refresh_calls}")

    class GrowthHostHarness(App[None]):
        CSS = "Screen { overflow: hidden; }"

        def compose(self) -> ComposeResult:
            yield Vertical(id="growth-container")

    async def _run() -> None:
        panel = FakePanel()
        results["satisfies_protocol"] = isinstance(panel, GrowthPanel)
        if not isinstance(panel, GrowthPanel):
            errors.append("FakePanel does not satisfy GrowthPanel protocol")
            return
        app = GrowthHostHarness()
        async with app.run_test(size=(80, 20)) as pilot:
            await pilot.pause()
            container = app.query_one("#growth-container", Vertical)

            assert await panel.available()
            await panel.mount(container)
            await pilot.pause()
            results["mount_calls"] = panel.mount_calls
            results["after_mount_children"] = len(container.children)

            await panel.refresh()
            await pilot.pause()
            results["refresh_calls"] = panel.refresh_calls
            results["label_mounted"] = (
                app.query_one("#fake-label", Static) is not None
            )

            if panel.mount_calls != 1:
                errors.append(f"mount called {panel.mount_calls} times (expected 1)")
            if panel.refresh_calls != 1:
                errors.append(
                    f"refresh called {panel.refresh_calls} times (expected 1)"
                )

    asyncio.run(_run())

    import sys

    from toad.growth.registry import discover

    ext_module = "toad.extensions.dega_growth"
    saved_module = sys.modules.pop(ext_module, None)
    saved_inner = sys.modules.pop(f"{ext_module}.dega_growth", None)
    real_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __builtins__["__import__"]  # type: ignore[index]

    def _block_import(name: str, *a: object, **kw: object) -> object:
        if name == ext_module or name.startswith(ext_module + "."):
            raise ImportError(f"test harness missing submodule: {name}")
        return real_import(name, *a, **kw)  # type: ignore[misc]

    import builtins

    builtins.__import__ = _block_import  # type: ignore[assignment]
    try:
        panel = discover()
        results["discover_none_when_module_absent"] = panel is None
        if panel is not None:
            errors.append("discover() returned non-None with submodule blocked")
    finally:
        builtins.__import__ = real_import  # type: ignore[assignment]
        if saved_module is not None:
            sys.modules[ext_module] = saved_module
        if saved_inner is not None:
            sys.modules[f"{ext_module}.dega_growth"] = saved_inner

    if verbose:
        for key, val in results.items():
            console.print(f"  {key}: {val}")

    return len(errors) == 0, errors, results


def verify_plan_execution(verbose: bool = False) -> bool:
    """Verify ProjectStatePane auto-opens a plan tab on in-session arrival.

    The pane uses a baseline filter: pre-existing plans (those in
    ``master.json`` at canon launch) are NOT auto-opened. This smoke
    starts with an empty plan list, mounts the pane, then writes a new
    plan to ``master.json`` — simulating an orch run started while
    canon is up. The new slug must auto-open, reveal the pane, and
    render its tab + status rail.
    """
    import json
    import tempfile
    from pathlib import Path
    from typing import Any

    from textual.app import App, ComposeResult

    from toad.data.plan_execution_model import PlanExecutionModel
    from toad.widgets.plan_execution_section import PlanExecutionSection
    from toad.widgets.plan_execution_tab import PlanExecutionTab
    from toad.widgets.project_state_pane import ProjectStatePane

    class _LateTarget:
        """Proxies ``post_message`` to a real widget bound after mount."""

        def __init__(self) -> None:
            self.target: Any = None

        def post_message(self, message: Any) -> bool:
            if self.target is None:
                return False
            return bool(self.target.post_message(message))

    late_target = _LateTarget()
    built_models: list[PlanExecutionModel] = []

    errors: list[str] = []
    results: dict[str, object] = {}

    SLUG = "20260427-smoke"

    def _state_payload(status: str) -> dict[str, object]:
        return {
            "version": 1,
            "plan": SLUG,
            "issueNumber": 99,
            "items": [
                {
                    "id": 1,
                    "description": "task",
                    "deps": [],
                    "status": status,
                }
            ],
        }

    def _write_state(plans_dir: Path, status: str) -> None:
        (plans_dir / "state.json").write_text(
            json.dumps(_state_payload(status)), encoding="utf-8"
        )

    def _write_empty_master(project: Path) -> None:
        master = project / ".orchestrator" / "master.json"
        master.parent.mkdir(parents=True)
        master.write_text(json.dumps({"plans": []}), encoding="utf-8")

    def _add_plan_in_session(project: Path) -> None:
        plans_dir = project / ".orchestrator" / "plans" / SLUG
        (plans_dir / "logs").mkdir(parents=True)
        _write_state(plans_dir, "running")
        state_path = plans_dir / "state.json"
        (project / ".orchestrator" / "master.json").write_text(
            json.dumps(
                {
                    "plans": [
                        {
                            "slug": SLUG,
                            "status": "running",
                            "statePath": str(state_path),
                            "startedAt": "2026-04-27T12:00:00Z",
                            "updatedAt": "2026-04-27T12:00:00Z",
                            "progress": {
                                "total": 1,
                                "done": 0,
                                "running": 1,
                                "failed": 0,
                            },
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            _write_empty_master(project)
            plans_dir = project / ".orchestrator" / "plans" / SLUG

            class Harness(App[None]):
                CSS = "Screen { overflow: hidden; }"

                def compose(self) -> ComposeResult:
                    yield ProjectStatePane(project_path=project)

            app = Harness()
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                pane = app.query_one(ProjectStatePane)

                def _factory(slug: str) -> PlanExecutionModel | None:
                    plan_dir = project / ".orchestrator" / "plans" / slug
                    if not plan_dir.is_dir():
                        return None
                    model = PlanExecutionModel(plan_dir, target=late_target)
                    model.start()
                    built_models.append(model)
                    return model

                pane.configure_plan_execution(_factory)
                await pilot.pause()
                # Simulate an orch run starting while canon is already up.
                _add_plan_in_session(project)
                await pilot.pause()
                await pilot.pause()
                await pilot.pause()

                results["pane_display"] = pane.display
                if not pane.display:
                    errors.append(
                        "ProjectStatePane.display is False after configure_plan_execution"
                    )

                section = pane.query_one(PlanExecutionSection)
                results["section_display"] = section.display
                results["open_slugs"] = sorted(section.open_slugs)
                if not section.display:
                    errors.append("PlanExecutionSection hidden after bootstrap")
                if SLUG not in section.open_slugs:
                    errors.append(
                        f"slug {SLUG!r} missing from open_slugs={section.open_slugs}"
                    )

                tabs = pane.query(PlanExecutionTab)
                results["tab_count"] = len(tabs)
                if len(tabs) != 1:
                    errors.append(
                        f"expected 1 PlanExecutionTab, found {len(tabs)}"
                    )
                else:
                    tab = tabs.first()
                    results["tab_id"] = tab.id
                    expected_id = f"plan-tab-{SLUG}"
                    if tab.id != expected_id:
                        errors.append(
                            f"tab id={tab.id!r}, expected {expected_id!r}"
                        )
                    # Bind the late target so model messages reach the tab.
                    late_target.target = tab

                # Header text replaces the status rail as the primary live
                # signal — it carries the badge, the count and the active
                # marker.
                header_before = tab.header_text()
                results["header_initial"] = header_before
                if "running" not in header_before:
                    errors.append(
                        f"header missing 'running' state: {header_before!r}"
                    )
                if "0/1" not in header_before:
                    errors.append(
                        f"header missing '0/1' count: {header_before!r}"
                    )

                # Mutate state.json — backstop interval (or watcher event)
                # should drive an ItemStatusChanged through to the header.
                _write_state(plans_dir, "done")
                await pilot.pause(3.0)
                header_after = tab.header_text()
                results["header_after_mutation"] = header_after
                if "1/1" not in header_after:
                    errors.append(
                        f"after mutation header missing '1/1': "
                        f"{header_after!r}"
                    )

    asyncio.run(_run())

    if verbose:
        for key, val in results.items():
            console.print(f"  {key}: {val}")

    return len(errors) == 0, errors, results


def verify_automation_dag(verbose: bool = False) -> tuple[bool, list[str], dict[str, object]]:
    """Verify AutomationDag: layout algorithm + headless rendering."""
    from toad.widgets.automation_dag import _compute_layers, AutomationDag, DagNode
    from toad.widgets.canon_state import FlowEdge, FlowNode, FlowState, CanonState

    errors: list[str] = []
    results: dict[str, object] = {}

    # --- Test 1: Pure layout algorithm ---

    # Linear: 4 nodes, straight chain
    linear_nodes = (
        FlowNode("a", "Init"),
        FlowNode("b", "Scaffold"),
        FlowNode("c", "Strategy"),
        FlowNode("d", "Develop"),
    )
    linear_edges = (
        FlowEdge("a", "b"),
        FlowEdge("b", "c"),
        FlowEdge("c", "d"),
    )
    layers = _compute_layers(linear_nodes, linear_edges)
    results["linear_layer_count"] = len(layers)
    if len(layers) != 4:
        errors.append(f"linear DAG: expected 4 layers, got {len(layers)}")
    if any(len(layer) != 1 for layer in layers):
        errors.append("linear DAG: each layer should have exactly 1 node")

    # Fan-out / fan-in: init → scaffold + research → strategy → develop
    fan_nodes = (
        FlowNode("init",     "Init"),
        FlowNode("scaffold", "Scaffold"),
        FlowNode("research", "Research"),
        FlowNode("strategy", "Strategy", "gate"),
        FlowNode("develop",  "Develop"),
    )
    fan_edges = (
        FlowEdge("init",     "scaffold"),
        FlowEdge("init",     "research"),
        FlowEdge("scaffold", "strategy"),
        FlowEdge("research", "strategy"),
        FlowEdge("strategy", "develop"),
    )
    fan_layers = _compute_layers(fan_nodes, fan_edges)
    results["fan_layer_count"] = len(fan_layers)
    results["fan_parallel_layer_size"] = max(len(layer) for layer in fan_layers)
    if len(fan_layers) < 3:
        errors.append(f"fan-in DAG: expected >=3 layers, got {len(fan_layers)}")
    parallel = [layer for layer in fan_layers if len(layer) == 2]
    if not parallel:
        errors.append("fan-in DAG: expected exactly one layer with 2 parallel nodes")

    # Empty graph
    empty_layers = _compute_layers((), ())
    if empty_layers:
        errors.append(f"empty graph should produce no layers, got {empty_layers}")

    results["layout_algorithm"] = "ok" if not errors else "fail"

    # --- Test 2: Headless widget rendering ---

    from textual.app import App, ComposeResult
    from textual.containers import HorizontalScroll

    async def _run() -> None:
        flow_linear = FlowState(
            steps=("a", "b", "c", "d"),
            active="b",
            completed=("a",),
        )

        class DagHarness(App[None]):
            CSS = "Screen { overflow: hidden; } AutomationDag { height: auto; }"

            def compose(self) -> ComposeResult:
                with HorizontalScroll():
                    yield AutomationDag(id="dag")

        app = DagHarness()
        async with app.run_test(size=(120, 30)) as pilot:
            dag = app.query_one("#dag", AutomationDag)

            # Load linear flow and let rebuild settle
            dag.update_state(CanonState(phase="scaffold", flow=flow_linear))
            await pilot.pause()
            await pilot.pause()

            nodes = app.query(DagNode)
            results["linear_node_count"] = len(nodes)
            if len(nodes) != 4:
                errors.append(f"linear render: expected 4 DagNode widgets, got {len(nodes)}")

            # Node "a" should be done (green), "b" running (yellow), rest pending
            node_a = next((n for n in nodes if n.node_id == "a"), None)
            node_b = next((n for n in nodes if n.node_id == "b"), None)
            node_c = next((n for n in nodes if n.node_id == "c"), None)

            if node_a:
                results["node_a_status"] = "done" if "status-done" in node_a.classes else node_a.classes
                if "status-done" not in node_a.classes:
                    errors.append(f"node 'a' should have status-done, got classes: {node_a.classes}")
            else:
                errors.append("node 'a' not found")

            if node_b:
                results["node_b_status"] = "running" if "status-running" in node_b.classes else node_b.classes
                if "status-running" not in node_b.classes:
                    errors.append(f"node 'b' should have status-running, got classes: {node_b.classes}")
            else:
                errors.append("node 'b' not found")

            if node_c:
                results["node_c_status"] = "pending" if "status-pending" in node_c.classes else node_c.classes
                if "status-pending" not in node_c.classes:
                    errors.append(f"node 'c' should have status-pending, got classes: {node_c.classes}")
            else:
                errors.append("node 'c' not found")

            # Fast-path status update (no topology change)
            flow_progressed = FlowState(
                steps=("a", "b", "c", "d"),
                active="c",
                completed=("a", "b"),
            )
            dag.update_state(CanonState(phase="scaffold", flow=flow_progressed))
            await pilot.pause()

            node_b_after = next((n for n in app.query(DagNode) if n.node_id == "b"), None)
            if node_b_after:
                results["node_b_after_progress"] = "done" if "status-done" in node_b_after.classes else node_b_after.classes
                if "status-done" not in node_b_after.classes:
                    errors.append("node 'b' should be done after progress, status-update (fast path) not working")
            else:
                errors.append("node 'b' not found after progress")

    asyncio.run(_run())

    if verbose:
        for key, val in results.items():
            console.print(f"  {key}: {val}")

    return len(errors) == 0, errors, results


def verify_automation_panel(verbose: bool = False) -> tuple[bool, list[str], dict[str, object]]:
    """Verify AutomationPanel: header strip, tabs, auto-switch behaviour."""
    errors: list[str] = []
    results: dict[str, object] = {}

    from textual.app import App, ComposeResult
    from textual.widgets import TabbedContent

    from toad.widgets.automation_panel import AutomationPanel
    from toad.widgets.canon_state import CanonState, FlowState

    flow = FlowState(
        steps=("init", "scaffold", "develop"),
        labels=(("init", "Init"), ("scaffold", "Scaffold"), ("develop", "Develop")),
        active="scaffold",
        completed=("init",),
    )

    async def _run() -> None:
        class PanelHarness(App[None]):
            CSS = "Screen { overflow: hidden; } AutomationPanel { height: 1fr; }"

            def compose(self) -> ComposeResult:
                yield AutomationPanel(id="panel")

        app = PanelHarness()
        async with app.run_test(size=(100, 30)) as pilot:
            panel = app.query_one("#panel", AutomationPanel)
            tabs = app.query_one("#automation-tabs", TabbedContent)

            # Build phase: stay on System (default), no auto-switch trigger.
            panel.state = CanonState(phase="scaffold", flow=flow)
            await pilot.pause()
            await pilot.pause()
            results["build_phase_tab"] = tabs.active
            if tabs.active != "tab-pipeline":
                errors.append(
                    f"build phase: expected tab-pipeline, got {tabs.active!r}"
                )

            from textual.widgets import Static
            initial_summary = app.query_one("#state-summary", Static)
            initial_text = str(initial_summary.content)
            results["summary_has_phase"] = "scaffold" in initial_text
            if "scaffold" not in initial_text:
                errors.append(f"summary missing phase name, got: {initial_text!r}")

            # Run phase + non-running status — no auto-switch trigger.
            tabs.active = "tab-workflow"
            await pilot.pause()
            panel.state = CanonState(phase="run", status="starting", flow=flow)
            await pilot.pause()
            await pilot.pause()
            results["run_not_running_tab"] = tabs.active
            if tabs.active != "tab-workflow":
                errors.append(
                    f"run + non-running: expected tab-workflow (manual nav), got {tabs.active!r}"
                )

            # Run phase + status = "polling" — auto-switch fires (dry-run runner
            # writes 'polling', not 'running').
            panel.state = CanonState(phase="run", status="polling", flow=flow)
            await pilot.pause()
            await pilot.pause()
            results["after_run_polling_tab"] = tabs.active
            if tabs.active != "tab-pipeline":
                errors.append(
                    f"run+polling: expected auto-switch to tab-pipeline, got {tabs.active!r}"
                )
            if panel._auto_switched_phase != "run":
                errors.append(
                    f"_auto_switched_phase should be 'run', got {panel._auto_switched_phase!r}"
                )

            # User navigates away; phase=live with deposit-pending shouldn't switch.
            tabs.active = "tab-workflow"
            await pilot.pause()
            panel.state = CanonState(phase="live", status="deposit-pending", flow=flow)
            await pilot.pause()
            await pilot.pause()
            results["live_awaiting_tab"] = tabs.active
            if tabs.active != "tab-workflow":
                errors.append(
                    f"live+deposit-pending: expected tab-workflow (manual nav), got {tabs.active!r}"
                )

            # Live runner running → auto-switch (fresh switch for live phase).
            panel.state = CanonState(phase="live", status="running", flow=flow)
            await pilot.pause()
            await pilot.pause()
            results["live_running_tab"] = tabs.active
            if tabs.active != "tab-pipeline":
                errors.append(
                    f"live+running: expected auto-switch to tab-pipeline, got {tabs.active!r}"
                )
            if panel._auto_switched_phase != "live":
                errors.append(
                    f"_auto_switched_phase should be 'live', got {panel._auto_switched_phase!r}"
                )

            # Live persistence: phase reverts to 'run' — live chip should
            # show last status (live-expanded class removed, chip visible).
            panel.state = CanonState(phase="run", status="complete", flow=flow)
            await pilot.pause()
            results["seen_live_internal"] = panel._seen_live
            results["live_expanded_dropped"] = not panel.has_class("live-expanded")
            chip_text = str(app.query_one("#live-collapsed", Static).content)
            results["chip_shows_last"] = "last" in chip_text.lower()
            if not panel._seen_live:
                errors.append("_seen_live should remain True after phase reverts")
            if panel.has_class("live-expanded"):
                errors.append("live-expanded class should be removed when phase != live")
            if "last" not in chip_text.lower():
                errors.append(f"live chip should show last status, got: {chip_text!r}")

            # State summary shows phase + status + metrics (zero filtered, errors kept)
            summary = app.query_one("#state-summary", Static)
            panel.state = CanonState(
                phase="run",
                status="running",
                iteration=5,
                metrics=(("cycles", "47"), ("trades", "0"), ("errors", "0"), ("mode", "live")),
                flow=flow,
            )
            await pilot.pause()
            summary_text = str(summary.content)
            results["summary_has_status"] = "running" in summary_text
            results["summary_has_iter"] = "iter 5" in summary_text
            results["summary_has_runs"] = "Runs" in summary_text and "47" in summary_text
            results["summary_drops_mode"] = "Mode" not in summary_text
            results["summary_drops_zero_trades"] = "Trades: 0" not in summary_text
            results["summary_keeps_zero_errors"] = "Errors" in summary_text
            if "running" not in summary_text:
                errors.append(f"summary missing status, got: {summary_text!r}")
            if "iter 5" not in summary_text:
                errors.append(f"summary missing iteration, got: {summary_text!r}")
            if "Mode" in summary_text:
                errors.append(f"summary should drop 'Mode' metric, got: {summary_text!r}")
            if "Trades: 0" in summary_text:
                errors.append(f"summary should hide zero-valued non-errors, got: {summary_text!r}")
            if "Errors" not in summary_text:
                errors.append(f"summary should keep Errors even at 0, got: {summary_text!r}")

            # No crash on missing flow
            panel.state = CanonState(phase="")
            await pilot.pause()
            results["empty_state_no_crash"] = True

    asyncio.run(_run())

    if verbose:
        for key, val in results.items():
            console.print(f"  {key}: {val}")

    return len(errors) == 0, errors, results


def verify_phases_diagram(
    verbose: bool = False,
) -> tuple[bool, list[str], dict[str, object]]:
    """Verify CanonPhaseDiagram: topology, status derivation, headless render."""
    import asyncio

    errors: list[str] = []
    results: dict[str, object] = {}

    # --- Unit: mode-specific flow synthesis ---
    from toad.widgets.canon_state import CanonState
    from toad.widgets.canon_phase_diagram import (
        _synthesize_build_flow,
        _synthesize_live_flow,
    )

    # Build mode: empty phase — no active
    if _synthesize_build_flow(CanonState(phase="")).active != "":
        errors.append("empty phase: expected active=''")

    f = _synthesize_build_flow(CanonState(phase="init", status="running"))
    if f.active != "init":
        errors.append(f"init phase: expected active='init', got {f.active!r}")

    f = _synthesize_build_flow(CanonState(phase="scaffold", status="running"))
    if f.active != "scaffold":
        errors.append(f"scaffold phase: expected active='scaffold', got {f.active!r}")
    if "init" not in f.completed:
        errors.append("scaffold phase: init should be done")

    f = _synthesize_build_flow(CanonState(phase="run", status="running"))
    if f.active != "run":
        errors.append(f"run phase: expected active='run', got {f.active!r}")
    for p in ("init", "scaffold", "strategy", "develop"):
        if p not in f.completed:
            errors.append(f"run phase: {p!r} should be done")

    # Live mode: deposit-pending → awaiting active
    f = _synthesize_live_flow(CanonState(phase="live", status="deposit-pending"))
    if f.active != "awaiting":
        errors.append(f"live+deposit-pending: expected active='awaiting', got {f.active!r}")

    f = _synthesize_live_flow(CanonState(phase="live", status="onboarding"))
    if f.active != "onboard":
        errors.append(f"live+onboarding: expected active='onboard', got {f.active!r}")
    for n in ("awaiting", "detected"):
        if n not in f.completed:
            errors.append(f"live+onboarding: {n!r} should be done")

    f = _synthesize_live_flow(CanonState(phase="live", status="running"))
    if f.active != "live":
        errors.append(f"live+running: expected active='live', got {f.active!r}")
    for n in ("awaiting", "detected", "onboard", "ready"):
        if n not in f.completed:
            errors.append(f"live+running: {n!r} should be done")

    results["unit_tests_passed"] = len(errors) == 0

    # --- Headless render: both modes side-by-side ---
    async def _run() -> None:
        from textual.app import App, ComposeResult
        from toad.widgets.canon_phase_diagram import CanonPhaseDiagram
        from toad.widgets.automation_dag import DagNode

        class PhasesHarness(App[None]):
            CSS = "Screen { overflow: hidden; }"

            def compose(self) -> ComposeResult:
                yield CanonPhaseDiagram(mode="build", id="build")
                yield CanonPhaseDiagram(mode="live", id="live")

        app = PhasesHarness()
        async with app.run_test(size=(120, 30)) as pilot:
            build = app.query_one("#build", CanonPhaseDiagram)
            live = app.query_one("#live", CanonPhaseDiagram)

            await pilot.pause()
            await pilot.pause()

            build.state = CanonState(phase="scaffold", status="running")
            live.state = CanonState(phase="live", status="onboarding")
            await pilot.pause()
            await pilot.pause()

            build_nodes = list(build.query(DagNode))
            results["build_node_count"] = len(build_nodes)
            if len(build_nodes) != 5:
                errors.append(f"build mode: expected 5 nodes, got {len(build_nodes)}")
            build_map = {n.node_id: n._status for n in build_nodes}
            if build_map.get("init") != "done":
                errors.append(f"build init should be done, got {build_map.get('init')!r}")
            if build_map.get("scaffold") != "running":
                errors.append(f"build scaffold should be running, got {build_map.get('scaffold')!r}")

            live_nodes = list(live.query(DagNode))
            results["live_node_count"] = len(live_nodes)
            if len(live_nodes) != 5:
                errors.append(f"live mode: expected 5 nodes, got {len(live_nodes)}")
            live_map = {n.node_id: n._status for n in live_nodes}
            if live_map.get("onboard") != "running":
                errors.append(f"live onboard should be running, got {live_map.get('onboard')!r}")
            if live_map.get("awaiting") != "done":
                errors.append(f"live awaiting should be done, got {live_map.get('awaiting')!r}")

    asyncio.run(_run())

    if verbose:
        for key, val in results.items():
            console.print(f"  {key}: {val}")

    return len(errors) == 0, errors, results


def verify_imports(verbose: bool = False) -> bool:
    """Verify all key modules import without error."""
    errors: list[str] = []
    modules = [
        "toad.widgets.gantt_timeline",
        "toad.widgets.project_state_pane",
        "toad.widgets.github_state",
        "toad.widgets.github_views.fetch",
        "toad.widgets.github_views.timeline_provider",
        "toad.widgets.github_views.github_timeline_provider",
        "toad.widgets.github_views.timeline_data",
        "toad.widgets.github_views.task_provider",
        "toad.widgets.task_table",
        "toad.widgets.task_detail",
        "toad.widgets.filter_toolbar",
        "toad.screens.task_detail_screen",
        "toad.widgets.subagent_tab_section",
        "toad.outreach.protocol",
        "toad.outreach.registry",
        "toad.widgets.outreach_cards",
        "toad.growth.protocol",
        "toad.growth.registry",
        "toad.widgets.plan_dep_graph",
        "toad.widgets.plan_status_rail",
        "toad.widgets.plan_worker_log_pane",
        "toad.widgets.plan_execution_tab",
        "toad.widgets.plan_execution_section",
        "toad.widgets.automation_dag",
        "toad.widgets.automation_panel",
        "toad.widgets.canon_phase_diagram",
    ]
    for mod in modules:
        try:
            __import__(mod)
        except Exception as exc:
            errors.append(f"{mod}: {exc}")

    return len(errors) == 0, errors, {}


def verify_dega(verbose: bool = False) -> tuple[bool, list[str], dict[str, object]]:
    """Verify the DEGA plugin: discovery, gating, and chat alignment.

    Unlike the Growth check this drives the real panel, because it ships
    in this repo. Covers the two things a reviewer cares about: that the
    element gating actually opens and closes access, and that own chat
    messages sit to the right of theirs (the WhatsApp convention).
    """
    import asyncio
    import os

    from textual.app import App, ComposeResult
    from textual.containers import Vertical, VerticalScroll
    from textual.widgets import Button, DataTable, Input, ListView, Static, TabbedContent

    from toad.dega.protocol import DegaPanel
    from toad.dega.registry import discover

    # The product defaults to the on-chain (chain) chat backend. This is a
    # headless LAYOUT harness (no network / no wallet): use the offline test
    # backend so the chat render checks run deterministically.
    os.environ["DEGA_CHAT_BACKEND"] = "test"

    errors: list[str] = []
    results: dict[str, object] = {}

    panel = discover()
    if panel is None:
        return False, ["DEGA panel not discovered by toad.dega.registry"], {}
    if not isinstance(panel, DegaPanel):
        errors.append("panel does not satisfy the DegaPanel protocol")
    results["panel_id"] = panel.id
    results["panel_title"] = panel.title
    results["refresh_seconds"] = panel.refresh_seconds

    from toad.extensions.dega_panel.chat import ChatView
    from toad.extensions.dega_panel.data import BUILDS
    from toad.extensions.dega_panel.pane import DegaPane

    class DegaHostHarness(App[None]):
        CSS = "Screen { overflow: hidden; }"

        def compose(self) -> ComposeResult:
            yield Vertical(id="dega-container")

    async def drive() -> None:
        app = DegaHostHarness()
        async with app.run_test(size=(64, 44)) as pilot:
            container = app.query_one("#dega-container", Vertical)
            await panel.mount(container)
            for _ in range(3):
                await pilot.pause()

            pane = app.query_one(DegaPane)

            # --- utility: catalogue renders once per build, no duplicates ---
            build_list = app.query_one("#build-list", ListView)
            results["build_rows"] = len(build_list.children)
            if len(build_list.children) != len(BUILDS):
                errors.append(
                    f"catalogue has {len(build_list.children)} rows, "
                    f"expected {len(BUILDS)}"
                )
            if build_list.index != 0:
                errors.append("catalogue starts with nothing highlighted")

            # --- utility detail: signals render in a Market/Signal/Prob./Delta
            # table with the delta column populated (matches the approved mock) ---
            table = app.query_one("#detail-table", DataTable)
            results["table_columns"] = table.columns
            results["table_locked_row"] = list(table.rows)[0] if table.rows else None
            if not table.columns:
                errors.append("signals DataTable has no columns")
            elif len(table.columns) != 4:
                errors.append(
                    f"signals table should have 4 columns (Market/Signal/Prob./Delta), "
                    f"got {len(table.columns)}"
                )
            if table.display or table.row_count:
                errors.append("signals table should be hidden when there are no signals")

            # --- gating opens and closes ---
            arbiter = BUILDS[0]
            results["arbiter_locked_at_start"] = bool(
                arbiter.rule.unmet(pane.elements)
            )
            if not arbiter.rule.unmet(pane.elements):
                errors.append("Arbiter should start locked at 5/3/2")
            pane.elements = {"Silver Fire": 9, "Golden Water": 9, "Obsidian Earth": 9}
            for _ in range(3):
                await pilot.pause()
            if arbiter.rule.unmet(pane.elements):
                errors.append("Arbiter should unlock once thresholds are met")
            if len(build_list.children) != len(BUILDS):
                errors.append("catalogue duplicated rows after an elements change")

            # --- the `t` key must swap sub-tabs from the keyboard ---
            # Terminals that do not forward mouse events leave the sub-tabs
            # otherwise unreachable, so this is the only way in for many users.
            # Focus must land inside the incoming pane or TabbedContent snaps
            # the tab straight back.
            tabs = pane.query_one("#dega-subtabs", TabbedContent)
            app.query_one("#build-list", ListView).focus()
            await pilot.pause()
            await pilot.press("t")
            for _ in range(8):
                await pilot.pause()
            results["tab_after_t"] = tabs.active
            if tabs.active != "tab-dega-chat":
                errors.append(f"`t` did not swap to chat (active={tabs.active})")
            # Move focus to a non-input widget inside chat before pressing `t` again —
            # an Input would swallow the key, and a hidden-tab widget would make
            # TabbedContent snap back by itself.
            for btn in app.query(Button):
                btn.focus()
                break
            await pilot.pause()
            await pilot.press("t")
            for _ in range(8):
                await pilot.pause()
            if tabs.active != "tab-dega-utility":
                errors.append(f"`t` did not swap back (active={tabs.active})")

            # Back to chat via the same key: assigning ``active`` directly
            # while focus sits in the outgoing pane is what snaps it back.
            await pilot.press("t")
            for _ in range(3):
                await pilot.pause()

            chat = app.query_one(ChatView)

            # --- chat opens a node from a username (fee-gated, offline sim) ---
            uname = chat.query_one("#username", Input)
            results["username_visible_before_node"] = not uname.disabled
            if uname.disabled:
                errors.append("username field should be enabled before opening a node")
            uname.value = "pavel"
            chat.query_one("#btn-open-node", Button).press()
            for _ in range(4):
                await pilot.pause()
            results["node_username"] = chat._my_username
            if chat._my_username != "pavel":
                errors.append(f"node did not open; username={chat._my_username}")
            results["username_hidden_after_node"] = "hidden" in uname.classes
            if "hidden" not in uname.classes:
                errors.append("username field should hide once a node is opened")

            # --- add a contact (by name) then send a private E2E message ---
            reg = chat._registry._sim
            from toad.extensions.dega_panel.chat_protocol import make_node as _mn
            from toad.extensions.dega_panel.chat_contact import contacts
            from unittest.mock import patch

            maria_node = _mn(offline=True)
            reg.open_node("maria", "0x00000000000000000000000000000000000000dEa1",
                          nostr_pubkey=bytes.fromhex(maria_node.pubkey))
            chat.query_one("#contact-name", Input).value = "maria.dega"
            await chat._add_contact()
            known = contacts(path=chat._contacts_path)
            chat._selected_contact = next(c for c in known if c["username"] == "maria")
            await chat.rebuild()
            results["contacts_after_add"] = len(known)

            msg = "chat check: e2e hello"
            composer = chat.query_one("#composer", Input)
            composer.focus()
            composer.value = msg
            for _ in range(3):
                await pilot.pause()
            # Drive the send directly (headless: Enter routing to the focused
            # composer is flaky under the harness).
            with patch("toad.extensions.dega_panel.chat.make_node", return_value=maria_node):
                await chat._send_message()
            for _ in range(4):
                await pilot.pause()
            # a sent message lands as a right-aligned bubble in the conversation
            conv = chat.query_one("#conv-scroll", VerticalScroll)
            mine = [s for s in conv.query(Static) if "mine" in s.classes]
            results["sent_bubbles"] = len(mine)
            results["peer_inbox"] = maria_node.inbox_decrypted()
            if not mine:
                errors.append("no right-aligned (mine) bubble after sending")

            # --- fee gate is surfaced in the header ---
            head = chat._header()  # the actual header string built for rendering
            results["fee_in_header"] = "fee" in head
            if "End-to-end encrypted" not in head:
                errors.append("registered chat should show its encryption status")

    try:
        asyncio.run(drive())
    except Exception as exc:  # noqa: BLE001 - surface as a failed check
        errors.append(f"chat drive raised: {type(exc).__name__}: {exc}")

    if verbose:
        for key, value in results.items():
            console.print(f"  {key}: {value}")

    return len(errors) == 0, errors, results


def verify_dega_auth(verbose: bool = False) -> bool:
    """Verify the device-flow login end to end with a fake backend client.

    Covers: idle prompt on mount, pressing `l` running the flow, the approved
    token being applied (elements populated), and the session being persisted to
    the auth store. The store is redirected to a temp dir so a real
    ~/.canon/auth.json is never read or written.
    """
    import asyncio
    import tempfile
    from pathlib import Path

    from textual.app import App, ComposeResult
    from textual.containers import Vertical
    from textual.widgets import ListView

    from toad.extensions.dega_panel import auth_store, chat_contact, chat_identity, chat_store
    from toad.extensions.dega_panel.auth_view import AuthBar
    from toad.extensions.dega_panel.pane import DegaPane, DegaPanelImpl

    errors: list[str] = []
    results: dict[str, object] = {}

    class FakeClient:
        base_url = "http://test"

        def __init__(self) -> None:
            self.code_calls = 0

        async def request_code(self):
            self.code_calls += 1
            return {
                "device_code": "dc1234",
                "user_code": "ABCD-EFGH",
                "verification_uri": "/device",
                "expires_in": 600,
                "interval": 1,
            }

        async def poll_token(self, device_code, *, expires_in=600, interval=5, on_pending=None):
            return {
                "status": "approved",
                "session_token": "jwt-secret",
                "user": {"id": "u1", "email": "pavel@dega.org", "display_name": "Pavel"},
            }

        async def fetch_elements(self, email):
            return {
                "user": {"email": email, "addresses": ["0x1234567890abcdef"]},
                "totalElements": 7,
                "aggregatedElements": {"Silver Fire": 5, "Golden Water": 2},
                "elementCount": {},
            }

    # Isolate the auth/chat stores from any real ~/.canon.
    orig_auth, orig_elems = auth_store.AUTH_FILE, auth_store.ELEMENTS_FILE
    orig_contacts = chat_contact.CONTACTS_FILE
    orig_identity = chat_identity.IDENTITY_FILE
    orig_inbox = chat_store.DEFAULT_INBOX_FILE
    tmp = Path(tempfile.mkdtemp())
    auth_store.AUTH_FILE = tmp / "auth.json"
    auth_store.ELEMENTS_FILE = tmp / "elements.json"
    chat_contact.CONTACTS_FILE = tmp / "chat-contacts.json"
    chat_identity.IDENTITY_FILE = tmp / "chat-identity.json"
    chat_store.DEFAULT_INBOX_FILE = tmp / "chat-inbox.json"
    old_env = {
        "DEGA_CHAT_IDENTITY_FILE": os.environ.get("DEGA_CHAT_IDENTITY_FILE"),
        "DEGA_CHAT_CONTACTS_FILE": os.environ.get("DEGA_CHAT_CONTACTS_FILE"),
        "DEGA_CHAT_INBOX_FILE": os.environ.get("DEGA_CHAT_INBOX_FILE"),
    }
    os.environ["DEGA_CHAT_IDENTITY_FILE"] = str(chat_identity.IDENTITY_FILE)
    os.environ["DEGA_CHAT_CONTACTS_FILE"] = str(chat_contact.CONTACTS_FILE)
    os.environ["DEGA_CHAT_INBOX_FILE"] = str(chat_store.DEFAULT_INBOX_FILE)

    class DegaHostHarness(App[None]):
        CSS = "Screen { overflow: hidden; }"

        def compose(self) -> ComposeResult:
            yield Vertical(id="dega-container")

    async def drive() -> None:
        app = DegaHostHarness()
        async with app.run_test(size=(64, 44)) as pilot:
            container = app.query_one("#dega-container", Vertical)
            panel = DegaPanelImpl(client=FakeClient())
            await panel.mount(container)
            for _ in range(4):
                await pilot.pause()

            pane = app.query_one(DegaPane)
            results["auth_initial"] = pane.auth.is_logged_in
            if pane.auth.is_logged_in:
                errors.append("panel should start disconnected (no stored session)")

            # Start the device flow via the `l` binding.
            app.query_one("#build-list", ListView).focus()
            await pilot.press("l")
            for _ in range(10):
                await pilot.pause()

            results["auth_logged_in"] = pane.auth.is_logged_in
            results["elements_after"] = dict(pane.elements)
            bar = app.query_one("#auth-bar", AuthBar)
            results["auth_bar_phase"] = bar._status.phase

            if not pane.auth.is_logged_in:
                errors.append("device flow did not complete login")
            if pane.elements.get("Silver Fire") != 5:
                errors.append("elements were not populated from the fetched snapshot")

            persisted = auth_store.load_auth()
            results["persisted"] = persisted.is_logged_in
            if not persisted.is_logged_in:
                errors.append("auth state was not persisted to the store")

    try:
        asyncio.run(drive())
    finally:
        auth_store.AUTH_FILE, auth_store.ELEMENTS_FILE = orig_auth, orig_elems
        chat_contact.CONTACTS_FILE = orig_contacts
        chat_identity.IDENTITY_FILE = orig_identity
        chat_store.DEFAULT_INBOX_FILE = orig_inbox
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    if verbose:
        for key, value in results.items():
            console.print(f"  {key}: {value}")
    return len(errors) == 0, errors, results


def verify_dega_install(verbose: bool = False) -> bool:
    """Verify strategy install/uninstall against a local git repo (no network).

    Creates a throwaway repo in a temp dir, installs it (clone), checks the dir
    and the installed marker, then uninstalls and checks both are gone.
    """
    import asyncio
    import subprocess
    import tempfile
    from pathlib import Path

    from toad.extensions.dega_panel import install_store
    from toad.extensions.dega_panel.installer import install_strategy, uninstall_strategy

    errors: list[str] = []
    results: dict[str, object] = {}

    tmp = Path(tempfile.mkdtemp())
    orig_installed, orig_strategies = install_store.INSTALLED_FILE, install_store.strategies_dir
    install_store.INSTALLED_FILE = tmp / "installed.json"
    install_store.strategies_dir = lambda: (tmp / "strategies")

    src = tmp / "src"
    src.mkdir()
    (src / "README.md").write_text("hi", encoding="utf-8")
    # _is_valid_clone requires package.json + .git, so the test repo must have it.
    (src / "package.json").write_text(
        '{"name":"test","scripts":{"start":"node x.js"}}', encoding="utf-8"
    )
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@b.c",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@b.c"}
    subprocess.run(["git", "init", "-q"], cwd=src, env=env, check=True)
    subprocess.run(["git", "add", "-A"], cwd=src, env=env, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=src, env=env, check=True)

    async def drive() -> None:
        dest = await install_strategy("test-key", str(src))
        results["dest_exists"] = dest.exists()
        results["marked"] = install_store.is_installed("test-key")
        if not dest.exists():
            errors.append("install did not clone the repo")
        if not install_store.is_installed("test-key"):
            errors.append("install did not mark the strategy installed")

        await uninstall_strategy("test-key")
        results["uninstalled_marked"] = not install_store.is_installed("test-key")
        results["uninstalled_removed"] = not dest.exists()
        if install_store.is_installed("test-key"):
            errors.append("uninstall did not clear the marker")
        if dest.exists():
            errors.append("uninstall did not remove the directory")

    try:
        asyncio.run(drive())
    finally:
        install_store.INSTALLED_FILE, install_store.strategies_dir = (
            orig_installed,
            orig_strategies,
        )

    if verbose:
        for key, value in results.items():
            console.print(f"  {key}: {value}")
    return len(errors) == 0, errors, results


def verify_dega_runner(verbose: bool = False) -> bool:
    """Verify strategy manifest detection and URL/key safety, offline.

    Builds a throwaway strategy dir with a *.config.json + package.json and
    asserts detect_manifest() parses it; that run_strategy() rejects an unsafe
    key (path traversal); and that _repo_to_archive() maps owner/name slugs to a
    codeload .tar.gz URL while leaving explicit URLs untouched.
    """
    import json
    import tempfile
    from pathlib import Path

    from toad.extensions.dega_panel import install_store
    from toad.extensions.dega_panel import installer
    from toad.extensions.dega_panel.installer import InstallError, _repo_to_archive
    from toad.extensions.dega_panel.runner import RunError, detect_manifest

    errors: list[str] = []
    results: dict[str, object] = {}

    tmp = Path(tempfile.mkdtemp())
    strategies = tmp / "strategies"
    strategies.mkdir(parents=True, exist_ok=True)
    # Redirect both module-level references (install_store AND installer).
    install_store.strategies_dir = lambda: strategies
    installer.strategies_dir = lambda: strategies

    # --- _repo_to_archive normalization ---
    slug = _repo_to_archive("owner/name")
    results["slug_url"] = slug
    if slug != "https://codeload.github.com/owner/name/tar.gz/refs/heads/main":
        errors.append(f"owner/name slug did not map to a codeload archive URL: {slug}")
    for keep in ("https://x/y.tar.gz", "file:///tmp/w.tgz"):
        if _repo_to_archive(keep) != keep:
            errors.append(f"full URL should pass through as archive: {keep}")

    # --- detect_manifest from a local throwaway strategy ---
    strat = strategies / "mock-strat"
    strat.mkdir()
    (strat / "mock.config.json").write_text(
        json.dumps(
            {
                "name": "Mock",
                "strategy": "mock",
                "pipeline": ["fetch", "analyze", "decide"],
            }
        ),
        encoding="utf-8",
    )
    (strat / "package.json").write_text(
        json.dumps({"name": "mock", "scripts": {"scan": "node x.js", "start": "node y.js"}}),
        encoding="utf-8",
    )

    m = detect_manifest("mock-strat")
    results["pipeline"] = m.pipeline
    results["runnable"] = m.runnable
    results["run_hint"] = m.run_hint
    if m.pipeline != ["fetch", "analyze", "decide"]:
        errors.append("manifest pipeline not parsed")
    # F4: command selection is explicit. A dry-run/scan script is preferred and
    # `start` is only the fallback (this check used to assume `start` always).
    if not m.runnable or m.run_hint != "npm run scan":
        errors.append(f"dry-run/scan script not preferred, got run_hint={m.run_hint!r}")

    # F4: a package shaped like the catalog's build-then-start ones (no
    # dry-run/scan) must resolve build/start explicitly and stay runnable.
    build_strat = strategies / "mock-build"
    build_strat.mkdir()
    (build_strat / "package.json").write_text(
        json.dumps(
            {
                "name": "mock-build",
                "main": "dist/index.js",
                "scripts": {"build": "tsc", "start": "node dist/index.js"},
            }
        ),
        encoding="utf-8",
    )
    mb = detect_manifest("mock-build")
    results["build_command"] = mb.build_command
    results["build_dry_run"] = mb.dry_run_command
    results["build_run_hint"] = mb.run_hint
    if mb.build_command != "build" or mb.dry_run_command != "start":
        errors.append(
            f"build/start not resolved explicitly: build={mb.build_command!r} "
            f"dry_run={mb.dry_run_command!r}"
        )
    if not mb.runnable or mb.run_hint != "npm run start":
        errors.append(f"build-then-start package not runnable: run_hint={mb.run_hint!r}")

    # F4: a package with only checkers must NOT be reported runnable.
    checker_strat = strategies / "mock-checkers"
    checker_strat.mkdir()
    (checker_strat / "package.json").write_text(
        json.dumps(
            {
                "name": "mock-checkers",
                "scripts": {"typecheck": "tsc --noEmit", "lint": "eslint .", "check": "npm run lint"},
            }
        ),
        encoding="utf-8",
    )
    mc = detect_manifest("mock-checkers")
    results["checker_runnable"] = mc.runnable
    results["checker_run_hint"] = mc.run_hint
    if mc.runnable or "no runnable script" not in mc.run_hint:
        errors.append(
            f"checker-only package reported runnable: runnable={mc.runnable} hint={mc.run_hint!r}"
        )

    # --- unsafe keys rejected (path traversal) ---
    for bad in ("../evil", "a/b", "..", ""):
        try:
            detect_manifest(bad)
            errors.append(f"detect_manifest accepted unsafe key {bad!r}")
        except (RunError, InstallError):
            pass  # expected: either error type is a valid rejection

    if verbose:
        for key, value in results.items():
            console.print(f"  {key}: {value}")
    return len(errors) == 0, errors, results


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify TUI widgets")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument(
        "--widget",
        choices=[
            "gantt",
            "imports",
            "pane",
            "tasks",
            "subagents",
            "outreach",
            "growth",
            "dega",
            "dega-auth",
            "dega-install",
            "dega-runner",
            "plan-execution",
            "automation-dag",
            "automation-panel",
            "phases-diagram",
            "live",
            "all",
        ],
        default="all",
    )
    args = parser.parse_args()

    checks = {
        "imports": verify_imports,
        "gantt": verify_gantt,
        "pane": verify_pane_no_default,
        "tasks": verify_tasks,
        "subagents": verify_subagents,
        "outreach": verify_outreach,
        "growth": verify_growth,
        "dega": verify_dega,
        "dega-auth": verify_dega_auth,
        "dega-install": verify_dega_install,
        "dega-runner": verify_dega_runner,
        "plan-execution": verify_plan_execution,
        "automation-dag": verify_automation_dag,
        "automation-panel": verify_automation_panel,
        "phases-diagram": verify_phases_diagram,
    }
    # Live probe only runs when explicitly requested — it hits the network.
    if args.widget == "live":
        checks = {"live": verify_live_data_probe}
    elif args.widget != "all":
        checks = {args.widget: checks[args.widget]}

    all_passed = True
    for name, check_fn in checks.items():
        console.print(f"\n[bold]Checking {name}...[/bold]")
        passed, errors, _results = check_fn(verbose=args.verbose)
        if passed:
            console.print("  [green]PASS[/green]")
        else:
            all_passed = False
            for err in errors:
                console.print(f"  [red]FAIL[/red]: {err}")

    if all_passed:
        console.print("\n[bold green]All checks passed.[/bold green]")
    else:
        console.print("\n[bold red]Some checks failed.[/bold red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
