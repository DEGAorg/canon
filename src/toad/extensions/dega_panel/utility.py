"""Utility sub-tab: element-gated catalogue of absorbed strategy workflows.

Laid out vertically because the right pane is narrow: catalogue on top,
detail for the highlighted build below.
"""

from __future__ import annotations

import re
from typing import ClassVar

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Label, ListItem, ListView, Static
from toad.extensions.dega_panel.data import (
    BUILDS,
    BUILDS_BY_KEY,
    PHASES,
    Build,
)
from toad.extensions.dega_panel.install_store import is_installed
from toad.extensions.dega_panel.installer import install_strategy, uninstall_strategy
from toad.extensions.dega_panel.runner import RunError, StrategyRunner, detect_manifest
from toad.extensions.dega_panel.access_grants import activate_access, ensure_access
from toad.extensions.dega_panel.scanner import describe, scan_severity, scan_strategy
from toad.extensions.dega_panel.strategy_access import (
    StrategyAccessError,
    backend_download_archive,
    backend_eligibility,
)


class _AccessConfirm(ModalScreen[bool]):
    """Explicit consent before permanently spending elements."""

    DEFAULT_CSS = """
    _AccessConfirm { align: center middle; }
    _AccessConfirm Vertical { width: 64; height: auto; padding: 1 2; background: $panel; }
    _AccessConfirm Label { width: 1fr; height: auto; }
    """

    def __init__(self, terms: str, *, use_slot: bool = False) -> None:
        super().__init__()
        self.terms = terms
        self.use_slot = use_slot

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Activate timed access?")
            yield Label(self.terms, markup=False)
            yield Label(
                "This selection is fixed and uses one purchased slot. No Element is consumed."
                if self.use_slot else
                "The cheapest affordable option is consumed permanently. "
                "All selections share a timer starting now. Selections are fixed."
            )
            yield Button("Cancel", id="cancel")
            yield Button("Use purchased slot" if self.use_slot else "Consume and activate",
                         id="activate", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "activate")


class _RunConfirm(ModalScreen[bool]):
    """Confirmation before executing third-party strategy code.

    npm run (and the deps install) executes code from a cloned third-party repo.
    This modal shows the origin and what will run, and requires an explicit
    "Run" click — the whole point of the adversarial review finding.
    """

    DEFAULT_CSS = """
    _RunConfirm { align: center middle; }
    _RunConfirm #box {
        width: 60; height: auto; padding: 1 2;
        border: round $accent; background: $surface;
    }
    _RunConfirm #box Label { width: 100%; }
    _RunConfirm #actions { width: 100%; height: auto; layout: horizontal; align-horizontal: right; padding-top: 1; }
    _RunConfirm #actions Button { margin-left: 1; }
    """

    def __init__(self, name: str, script: str, repo) -> None:
        super().__init__()
        self._name = name
        self._script = script
        self._repo = repo

    def compose(self) -> ComposeResult:
        with Vertical(id="box"):
            yield Label("[b]Run third-party strategy?[/]", classes="title")
            yield Label(
                f"\"{self._name}\" will execute code from a cloned third-party "
                f"repository:\n[dim]{self._repo}[/]\n\n[dim]It will run:[/] "
                f"[b]{self._script}[/]\n\nThis can run arbitrary commands on "
                f"your machine. Only continue if you trust this repo."
            )
            with Vertical(id="actions"):
                yield Button("Cancel", id="cancel")
                yield Button("Run", variant="error", id="run")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "run")


class _LiveConfirm(ModalScreen[bool]):
    """Second, explicit confirmation before a LIVE (real-funds) strategy run.

    ``npm run -- --live`` places real orders with the funded wallet. This modal
    is shown AFTER the normal ``_RunConfirm`` and requires a deliberate extra
    click, so a live run can never happen from a single unintended action.
    """

    DEFAULT_CSS = """
    _LiveConfirm { align: center middle; }
    _LiveConfirm #box {
        width: 64; height: auto; padding: 1 2;
        border: round $error; background: $surface;
    }
    _LiveConfirm #box Label { width: 100%; }
    _LiveConfirm #actions { width: 100%; height: auto; layout: horizontal; align-horizontal: right; padding-top: 1; }
    _LiveConfirm #actions Button { margin-left: 1; }
    """

    def __init__(self, name: str, script: str, wallet: str = "funded wallet") -> None:
        super().__init__()
        self._name = name
        self._script = script
        self._wallet = wallet

    def compose(self) -> ComposeResult:
        with Vertical(id="box"):
            yield Label("[b]⚠ LIVE — REAL FUNDS[/]", classes="title")
            yield Label(
                f'You are about to run "{self._name}" in [b]LIVE[/] mode:\n'
                f"[dim]{self._script} --live[/]\n\n"
                f"This will [b][red]place real orders with the funded wallet[/][/] "
                f"({self._wallet}). This is not a dry run — actual positions and "
                f"transactions may be opened.\n\nType [b]LIVE[/] to confirm:"
            )
            yield Input(placeholder="type LIVE", id="confirm-word", password=True)
            with Vertical(id="actions"):
                yield Button("Cancel", id="cancel")
                yield Button("Activate live", variant="error", id="confirm")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.value.strip().upper() == "LIVE":
            self.dismiss(True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm":
            word = self.query_one("#confirm-word", Input).value.strip().upper()
            if word == "LIVE":
                self.dismiss(True)
                return
            self.notify("Type LIVE to confirm", severity="warning")
        elif event.button.id == "cancel":
            self.dismiss(False)


class BuildRow(ListItem):
    """One build in the catalogue. Locked builds stay visible on purpose."""

    def __init__(self, build: Build, unmet: list[str]) -> None:
        super().__init__()
        self.build = build
        self.unmet = unmet

    def compose(self) -> ComposeResult:
        b = self.build
        crown = " [yellow]*[/]" if b.winner else ""
        inst = "[green]● installed[/]" if is_installed(b.key) else "[dim]○ not installed[/]"
        head = f"[b]{b.name}[/]{crown}  [dim]{b.score:.2f}[/]  {inst}"
        body = f"{head}\n[dim]Select to check access[/]"
        yield Static(body, classes="build-body")


class UtilityView(Vertical):
    """Catalogue plus detail. Reads holdings from the owning pane."""

    DEFAULT_CSS = """
    UtilityView { height: 1fr; }
    /* The catalogue is a short fixed list, so let it size to content and
       give the leftover rows to the detail. max-height keeps it from
       swallowing the pane if the catalogue ever grows. */
    UtilityView #build-list {
        height: auto;
        max-height: 50%;
        background: transparent;
        border: none;
    }
    UtilityView ListItem {
        padding: 0 1;
        background: transparent;
    }
    UtilityView ListItem.--highlight { background: $boost; }
    UtilityView .build-body { height: auto; }
    UtilityView #build-detail {
        height: 1fr;
        border-top: solid $panel-lighten-2;
        padding: 1 1 0 1;
    }
    UtilityView #detail-head { height: auto; padding-bottom: 1; }
    UtilityView #detail-rule { height: auto; padding-bottom: 1; }
    /* Let the predictions table grow to its rows instead of being pinned to
       1fr: pinned, it clips its rows at the pane edge (only the header shows).
       Auto height makes the parent #build-detail (a VerticalScroll) scroll to
       reveal every row, so the end of the predictions is always reachable. */
    UtilityView #detail-table { height: auto; }
    UtilityView #op-status {
        height: auto;
        padding: 0 1 1 1;
        background: $boost;
        border: round $accent;
        color: $text;
    }
    UtilityView #op-status:empty { display: none; }
    UtilityView #phase-key { height: auto; padding: 1 0 0 0; }
    """

    def __init__(self, pane) -> None:
        super().__init__()
        self._pane = pane
        self._selected: str = BUILDS[0].key
        self.runner_lines: list[str] = []
        self._access: dict[str, dict] = {}
        # key -> StrategyRunner for each active strategy process (robust, stoppable)
        self._runners: dict[str, StrategyRunner] = {}

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("i", "install_toggle", "Install/Uninstall", show=False),
        Binding("a", "activate_access", "Activate access", show=False),
        Binding("r", "run_strategy", "Run", show=False),
        Binding("L", "run_live", "Run live", show=False),
        Binding("x", "stop_strategy", "Stop", show=False),
    ]

    def action_run_strategy(self) -> None:
        """Launch the highlighted installed strategy (dry-run by default)."""
        b = BUILDS_BY_KEY[self._selected]
        if not is_installed(b.key):
            self.notify(f"{b.name} is not installed — press i to install first", severity="warning")
            return
        self.run_worker(
            self._run(b.key, b.name),
            name=f"dega-run-{b.key}",
            exclusive=True,
        )

    def action_run_live(self) -> None:
        """Launch the highlighted installed strategy in LIVE (real funds) mode.

        Chains the normal third-party run confirmation AND a dedicated LIVE
        double-confirmation before any real-order execution happens.
        """
        b = BUILDS_BY_KEY[self._selected]
        if not is_installed(b.key):
            self.notify(f"{b.name} is not installed — press i to install first", severity="warning")
            return
        self.run_worker(
            self._run(b.key, b.name, live=True),
            name=f"dega-live-{b.key}",
            exclusive=True,
        )

    def action_stop_strategy(self) -> None:
        """Stop the currently-highlighted strategy's running process."""
        b = BUILDS_BY_KEY[self._selected]
        runner = self._runners.get(b.key)
        if runner is None or not runner.running:
            self.notify(f"{b.name} is not running", severity="warning")
            return
        self.run_worker(self._stop(b.key, b.name))

    async def _stop(self, key: str, name: str) -> None:
        runner = self._runners.get(key)
        if runner is None:
            return
        await runner.stop()
        self.set_op_status(f"{name}: stopped", severity="warn")
        self.notify(f"{name}: stopped")
        self.runner_lines.append(f"{name}: stopped")

    async def _run(self, key: str, name: str, *, live: bool = False) -> None:
        def status(s: str, notify: bool = False) -> None:
            # Lifecycle state, shown once on the persistent status line.
            self.set_op_status(f"{name}: {s}", severity=("warn" if live else "normal"))
            if notify:
                self.notify(f"{name}: {s}")

        # on_line for the bot's raw stdout: it must NEVER touch the toast/status
        # path. A live strategy emits hundreds of lines per second (tickers,
        # \\r spinners), and notify()+repaint per line floods the Textual event
        # loop, freezing the terminal. We only tag and buffer the tail so the
        # signals table can parse it; the full raw feed goes to the rotated log
        # on disk in runner.py.
        def on_stream(line: str) -> None:
            self._note_line(f"{name}: {line}")

        try:
            manifest = detect_manifest(key)
            if manifest.pipeline:
                status(f"pipeline {','.join(manifest.pipeline)} — {manifest.run_hint}")
            # Running executes THIRD-PARTY code from the cloned repo. Get explicit
            # consent first, showing what will run.
            self.set_op_status(f"{name}: waiting for confirmation…", severity="warn")
            resp = await self.app.push_screen_wait(
                _RunConfirm(name=name, script=manifest.run_hint, repo=manifest.path)
            )
            if not resp:
                self.set_op_status(f"{name}: cancelled", severity="warn")
                return
            if live:
                # Real funds: an explicit second, word-typed confirmation.
                live_resp = await self.app.push_screen_wait(
                    _LiveConfirm(name=name, script=manifest.run_hint)
                )
                if not live_resp:
                    self.set_op_status(f"{name}: live cancelled", severity="warn")
                    return
            # Non-blocking managed runner: tracks state, log and can be stopped
            # with the 'x' key instead of blocking the worker until exit.
            runner = StrategyRunner(key)
            runner.on_line = on_stream
            self._runners[key] = runner
            await runner.start(confirmed=True, live=live, live_confirm=live)
            # One stable "Running" line — NOT repainted per bot output line, so
            # the screen reads cleanly while the strategy streams in background.
            self.set_op_status(f"{name}: running (pid {runner.pid}) — press x to stop", severity="ok")
            self.notify(f"{name}: running (pid {runner.pid})")
            # Return so the worker frees; the runner keeps running in background.
            return
        except (RunError, StrategyAccessError) as exc:
            self.set_op_status(f"{name}: {exc}", severity="error")
            self.notify(f"{name}: {exc}", severity="error")

    # Cap the in-memory signal buffer: a long-lived bot cannot grow runner_lines
    # without bound (the raw feed already lands in the rotated execution log).
    _MAX_RUNNER_LINES = 500

    def _note_line(self, line: str) -> None:
        """Append a line to the signal buffer, bounded to the last N."""
        self.runner_lines.append(line)
        if len(self.runner_lines) > self._MAX_RUNNER_LINES:
            del self.runner_lines[: len(self.runner_lines) - self._MAX_RUNNER_LINES]

    def action_install_toggle(self) -> None:
        """Install or uninstall the highlighted strategy (git clone locally)."""
        self.run_worker(self._toggle(self._selected))

    async def _toggle(self, key: str) -> None:
        b = BUILDS_BY_KEY[key]

        def status(s: str) -> None:
            self.set_op_status(f"{b.name}: {s}")
            self.notify(f"{b.name}: {s}")
            self.runner_lines.append(s)

        try:
            self.set_op_status(f"{b.name}: starting…", severity="normal")
            if is_installed(key):
                await uninstall_strategy(key, on_status=status)
                self.set_op_status(f"{b.name}: uninstalled", severity="ok")
            else:
                if not await self._activate(key):
                    return
                async def fetcher(tmp):
                    await backend_download_archive(key, tmp)
                dest = await install_strategy(key, b.repo, on_status=status, fetcher=fetcher)
                # Client requirement: review downloaded code for anything
                # malicious before we ever consider running it. Non-blocking
                # AND isolated: a scanner failure must never abort an install
                # that already succeeded, so it has its own try/except.
                try:
                    scan = scan_strategy(dest, key=key)
                    self.set_op_status(
                        f"{b.name}: {describe(scan)}", severity=scan_severity(scan)
                    )
                    status("security scan: " + describe(scan))
                except Exception as sexc:  # noqa: BLE001 - scan is best-effort
                    self.set_op_status(f"{b.name}: installed (scan failed: {sexc})", severity="warn")
            await self.rebuild()
        except Exception as exc:  # noqa: BLE001 - surface install failures
            self.set_op_status(f"{b.name}: error — {exc}", severity="error")
            self.notify(f"{b.name}: {exc}", severity="error")

    @on(Button.Pressed, "#activate-access")
    def action_activate_access(self) -> None:
        self.run_worker(self._activate(self._selected), group="activation", exclusive=True)

    async def _activate(self, key: str) -> bool:
        decision = await backend_eligibility(key)
        if decision is None:
            self.set_op_status("Sign in and connect to check access", severity="error")
            return False
        self._access[key] = decision
        if decision.get("state") == "active":
            try:
                await ensure_access(key)
            except StrategyAccessError as exc:
                self.set_op_status(str(exc), severity="error")
                return False
            self.refresh_detail()
            return True
        if decision.get("state") != "activation_required":
            self.set_op_status("No affordable access option or archive unavailable", severity="warn")
            self.refresh_detail()
            return False
        options = decision.get("alternatives", [])
        slot = decision.get("slotOffer")
        terms = ([f"{slot['remaining']} purchased slots available. Select {key}. "
                  f"Access ends {slot['expiresAt']}; selecting now does not reset the timer."]
                 if slot else [])
        for option in options:
            if option.get("deficits"):
                continue
            cost = " + ".join(f"{r['count']} {r['elementType']}" for r in option["allOf"])
            count = option.get("strategyCount", 1)
            scope = ("all strategies" if option["scope"] == "all_strategies" else
                     f"{count} strategy selections, starting with {key}")
            terms.append(f"{cost}: {option['durationSeconds'] / 86400:g} "
                         f"{'day' if option['durationSeconds'] == 86400 else 'days'}, {scope}")
        accepted = await self.app.push_screen_wait(_AccessConfirm("\n".join(terms), use_slot=bool(slot)))
        if not accepted:
            return False
        try:
            grant = await activate_access(key, purchase_id=slot["purchaseId"] if slot else None)
        except Exception as exc:
            self.set_op_status(str(exc), severity="error")
            return False
        self.set_op_status(f"Access active until {grant.expiresAt}", severity="ok")
        self._access[key] = {"state": "active", "grant": {"expiresAt": grant.expiresAt}}
        self.refresh_detail()
        return True

    def compose(self) -> ComposeResult:
        yield ListView(id="build-list")
        with VerticalScroll(id="build-detail"):
            yield Static(id="op-status")
            yield Static(id="detail-head")
            yield Static(id="detail-rule")
            yield Button("Check availability", id="activate-access", variant="primary")
            yield DataTable(id="detail-table", zebra_stripes=True)

    def set_op_status(self, text: str | None, *, severity: str = "normal") -> None:
        """Persistent in-pane feedback for install/run, replacing the toast.

        The old code only called notify(), whose message vanishes quickly and
        is easy to miss. This draws the latest status line inside the detail
        pane so it stays visible until the next operation or a rebuild."""
        box = self.query_one("#op-status", Static)
        if not text:
            box.update("")
            return
        color = {"normal": "", "ok": "green", "warn": "yellow", "error": "red"}[severity]
        marked = f"[{color}]{text}[/]" if color else text
        box.update(marked)

    async def on_mount(self) -> None:
        await self.rebuild()

    async def rebuild(self) -> None:
        """Repaint the catalogue from current holdings. Five rows, so cheap."""
        lst = self.query_one("#build-list", ListView)
        keep = lst.index
        # clear() is awaitable: appending without awaiting it races the removal
        # and leaves the old rows behind.
        await lst.clear()
        for b in BUILDS:
            lst.append(BuildRow(b, ["Check access"]))
        # index starts as None: without this nothing is highlighted while the
        # detail pane already shows a build, and the first arrow key is wasted.
        lst.index = keep if keep is not None else 0
        self.refresh_detail()

    def refresh_detail(self) -> None:
        b = BUILDS_BY_KEY[self._selected]
        decision = self._access.get(b.key, {})
        state = decision.get("state", "checking")
        state_label = {
            "active": "Access active", "activation_required": "Ready to activate",
            "insufficient_elements": "Not enough elements", "unavailable": "Unable to check access",
        }.get(state, "Checking availability…")
        slot = decision.get("slotOffer")
        if slot:
            state_label = f"{slot['remaining']} purchased slots available"
        button = self.query_one("#activate-access", Button)
        button.label = {
            "active": "Refresh access",
            "activation_required": "Activate access",
            "unavailable": "Retry",
        }.get(state, "Check availability")
        if slot:
            button.label = "Use purchased slot"

        self.query_one("#detail-head", Static).update(
            f"[b]{b.name}[/]  [dim]#{b.submission_id}[/]\n"
            f"[dim]{b.summary}[/]"
        )

        marks = []
        for i, phase in enumerate(PHASES, start=1):
            if i < b.phase:
                marks.append(f"[green]{phase}[/]")
            elif i == b.phase:
                marks.append(f"[reverse b] {phase} [/]")
            else:
                marks.append(f"[dim]{phase}[/]")
        note = (
            "\n[yellow]Reaching «live» needs a funded wallet, which lives "
            "in canon-cli.[/]"
            if b.phase >= 5
            else ""
        )
        descriptions = []
        for option in decision.get("alternatives", []):
            cost = " + ".join(f"{r['count']} {r['elementType']}" for r in option["allOf"])
            missing = ", ".join(f"{r['count']} {r['elementType']}" for r in option["deficits"])
            descriptions.append(f"{cost} — {option['durationSeconds'] / 86400:g} days"
                                + (f" (missing {missing})" if missing else " (available)"))
        access_text = " OR \n".join(descriptions)
        counts = ""
        if "ownedElements" in decision:
            counts = (f"Owned: {decision['ownedElements']} · "
                      f"Available to spend: {decision['availableElements']}\n")
        grant = decision.get("grant")
        if grant:
            access_text = f"Access until {grant['expiresAt']}"
        self.query_one("#detail-rule", Static).update(
            f"{state_label}\n{counts}{access_text}\n" + " ".join(marks) + note
        )

        table = self.query_one("#detail-table", DataTable)
        # Columns are created here: a repaint can arrive before on_mount runs.
        if not table.columns:
            table.add_columns("Market", "Signal", "Prob.", "Delta")
        table.clear()
        own_lines = [ln for ln in self.runner_lines if ln.startswith(f"{b.name}:")]
        live_signals = self._parse_signal_lines(own_lines[-50:]) if state == "active" else []
        table.display = bool(live_signals)
        for market, signal, prob, delta in live_signals:
            table.add_row(market, signal, prob, delta)

    def _parse_signal_lines(self, lines: list[str]) -> list[tuple[str, str, str, str]]:
        """Parse runner log lines into (market, signal, prob, delta) rows.

        Pure function so it can be unit-tested headless. Returns [] when no
        recognised signal lines are present.
        """
        rows: list[tuple[str, str, str, str]] = []

        injury_re = re.compile(
            r"INJURY SIGNAL:\s*([^(]+?)\s*\(([^)]+)\)\s*->\s*([^|]+?)\s*\|\s*"
            r"Impact:\s*([0-9.]+)%"
        )
        momentum_re = re.compile(
            r'MOMENTUM LAG:\s*"([^"]+)"\s*moved\s*([0-9.]+)¢'
        )
        executed_re = re.compile(
            r"EXECUTED \(dry-run\):\s*([^|]+?)\s*\|\s*Market:\s*([^|]*)"
        )

        for line in lines:
            line = line.strip()
            m = injury_re.search(line)
            if m:
                player, team, status, impact = m.groups()
                rows.append(
                    (
                        f"{player.strip()} ({team}) -> {status.strip()}".strip(),
                        "Injury",
                        impact,
                        "",
                    )
                )
                continue
            m = momentum_re.search(line)
            if m:
                market, moved = m.groups()
                rows.append((market.strip(), "Momentum", moved, ""))
                continue
            m = executed_re.search(line)
            if m:
                action, market = m.groups()
                rows.append((market.strip(), action.strip().title(), "", ""))
        return rows

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if isinstance(event.item, BuildRow):
            self._selected = event.item.build.key
            self.refresh_detail()
            self.run_worker(self._refresh_access(self._selected), group="eligibility", exclusive=True)

    async def _refresh_access(self, key: str) -> None:
        decision = await backend_eligibility(key)
        self._access[key] = decision or {"state": "unavailable"}
        if key == self._selected:
            self.refresh_detail()
