from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any
import random

if TYPE_CHECKING:
    from toad.widgets.plan_execution_tab import (
        PlanExecutionModel as PlanExecutionModelProtocol,
    )

from textual import on
from textual.app import ComposeResult
from textual import getters
from textual.binding import Binding
from textual.command import Hit, Hits, Provider, DiscoveryHit
from textual.content import Content
from textual.events import ScreenResume
from textual.screen import Screen
from textual.css.query import NoMatches
from textual.reactive import var, reactive
from textual.widgets import Footer, OptionList, DirectoryTree, Tree
from textual import containers
from textual.widget import Widget


from toad.app import ToadApp
from toad import messages
from toad.agent_schema import Agent
from toad.acp import messages as acp_messages

from toad.widgets.plan import Plan
from toad.widgets.throbber import Throbber
from toad.widgets.conversation import Conversation
from toad.widgets.project_directory_tree import ProjectDirectoryTree
from toad.widgets.automation_panel import AutomationPanel
from toad.widgets.canon_state import CanonState, CanonStateWidget
from toad.widgets.project_state_pane import ProjectStatePane


# Right-pane width bounds. Char-step keybindings clamp to [40, 100];
# percentage values from canon-ctl clamp to [20%, 80%].
PANE_WIDTH_DEFAULT = "50%"
PANE_WIDTH_MIN_CHARS = 40
PANE_WIDTH_MAX_CHARS = 100
PANE_WIDTH_STEP_CHARS = 5
PANE_WIDTH_MIN_PCT = 20
PANE_WIDTH_MAX_PCT = 80


def _parse_percentage(width: str) -> int:
    """Validate ``width`` as a percentage string in the allowed range."""
    if not width.endswith("%"):
        raise ValueError(
            f"width must be a percentage like '40%', got {width!r}"
        )
    try:
        pct = int(width[:-1])
    except ValueError as exc:
        raise ValueError(f"invalid percentage: {width!r}") from exc
    if not PANE_WIDTH_MIN_PCT <= pct <= PANE_WIDTH_MAX_PCT:
        raise ValueError(
            f"width must be between {PANE_WIDTH_MIN_PCT}% "
            f"and {PANE_WIDTH_MAX_PCT}%, got {pct}%"
        )
    return pct


class ModeProvider(Provider):
    async def search(self, query: str) -> Hits:
        """Search for Python files."""
        matcher = self.matcher(query)

        screen = self.screen
        assert isinstance(screen, MainScreen)

        for mode in sorted(
            screen.conversation.modes.values(), key=lambda mode: mode.name
        ):
            command = mode.name
            score = matcher.match(command)
            if score > 0:
                yield Hit(
                    score,
                    matcher.highlight(command),
                    partial(screen.conversation.set_mode, mode.id),
                    help=mode.description,
                )

    async def discover(self) -> Hits:
        screen = self.screen
        assert isinstance(screen, MainScreen)

        for mode in sorted(
            screen.conversation.modes.values(), key=lambda mode: mode.name
        ):
            yield DiscoveryHit(
                mode.name,
                partial(screen.conversation.set_mode, mode.id),
                help=mode.description,
            )


class MainScreen(Screen, can_focus=False):
    AUTO_FOCUS = "Conversation Prompt TextArea"

    CSS_PATH = "main.tcss"

    COMMANDS = {ModeProvider}

    SESSION_NAVIGATION_GROUP = Binding.Group(description="Sessions")
    BINDINGS = [
        Binding("ctrl+b,f20", "show_sidebar", "Sidebar"),
        Binding("ctrl+g", "toggle_project_state", "Project Status"),
        Binding("ctrl+h", "go_home", "Home"),
        Binding("comma", "narrow_pane", "Narrow pane", show=False),
        Binding("full_stop", "widen_pane", "Widen pane", show=False),
        Binding(
            "ctrl+left_square_bracket",
            "session_previous",
            "Previous session",
            group=SESSION_NAVIGATION_GROUP,
        ),
        Binding(
            "ctrl+right_square_bracket",
            "session_next",
            "Next session",
            group=SESSION_NAVIGATION_GROUP,
        ),
    ]

    BINDING_GROUP_TITLE = "Screen"
    busy_count = var(0)
    throbber: getters.query_one[Throbber] = getters.query_one("#throbber")
    conversation = getters.query_one(Conversation)
    project_directory_tree = getters.query_one("#project_directory_tree")

    column = reactive(False)
    column_width = reactive(100)
    scrollbar = reactive("")
    split_enabled: reactive[bool] = reactive(False)
    pane_width: reactive[str] = reactive(PANE_WIDTH_DEFAULT, init=False)
    project_path: var[Path] = var(Path("./").expanduser().absolute())

    app = getters.app(ToadApp)

    def __init__(
        self,
        project_path: Path,
        agent: Agent | None = None,
        agent_session_id: str | None = None,
        agent_session_title: str | None = None,
        session_pk: int | None = None,
        initial_prompt: str | None = None,
    ) -> None:
        super().__init__()
        self.set_reactive(MainScreen.project_path, project_path)
        self._agent = agent
        self._agent_session_id = agent_session_id
        self._agent_session_title = agent_session_title
        self._session_pk = session_pk
        self._initial_prompt = initial_prompt

    def watch_title(self, title: str) -> None:
        self.app.update_terminal_title()

    def get_loading_widget(self) -> Widget:
        throbber = self.app.settings.get("ui.throbber", str)
        if throbber == "status":
            from toad.app import STATUS_MESSAGES
            from toad.widgets.future_text import FutureText

            messages = STATUS_MESSAGES.copy()
            random.shuffle(messages)
            return FutureText([Content(msg) for msg in messages])
        return super().get_loading_widget()

    def _on_screen_resume(self, event: ScreenResume) -> None:
        self.conversation

    def compose(self) -> ComposeResult:
        with containers.Horizontal(id="main-split"):
            with containers.Center():
                yield Conversation(
                    self.project_path,
                    self._agent,
                    self._agent_session_id,
                    self._session_pk,
                    initial_prompt=self._initial_prompt,
                ).data_bind(
                    project_path=MainScreen.project_path,
                    column=MainScreen.column,
                )
            yield ProjectStatePane(
                project_path=self.project_path,
                id="project_state_pane",
            )
        yield Footer()

    def run_prompt(self, prompt: str) -> None:
        self.conversation

    def update_node_styles(self, animate: bool = True) -> None:
        self.conversation.update_node_styles(animate=animate)
        self.query_one(Footer).update_node_styles(animate=animate)

    def action_session_previous(self) -> None:
        if self.screen.id is not None:
            self.post_message(messages.SessionNavigate(self.screen.id, -1))

    def action_session_next(self) -> None:
        if self.screen.id is not None:
            self.post_message(messages.SessionNavigate(self.screen.id, +1))

    @on(messages.ProjectDirectoryUpdated)
    async def on_project_directory_update(self) -> None:
        await self.query_one(ProjectDirectoryTree).reload()

    @on(DirectoryTree.FileSelected, "ProjectDirectoryTree")
    def on_project_directory_tree_selected(self, event: Tree.NodeSelected):
        if (data := event.node.data) is not None:
            self.conversation.insert_path_into_prompt(data.path)

    @on(acp_messages.Plan)
    async def on_acp_plan(self, message: acp_messages.Plan):
        message.stop()
        entries = [
            Plan.Entry(
                Content(entry["content"]),
                entry.get("priority", "medium"),
                entry.get("status", "pending"),
            )
            for entry in message.entries
        ]
        self.query_one(Plan).entries = entries

    @on(messages.SessionUpdate)
    async def on_session_update(self, event: messages.SessionUpdate) -> None:
        # TODO: May not be required
        if event.name is not None:
            self._agent_session_title = event.name
        if self.id is not None:
            self.app.session_tracker.update_session(
                self.id,
                title=event.name,
                subtitle=event.subtitle,
                path=event.path,
                state=event.state,
            )

    @on(messages.SessionClose)
    async def on_session_close(self, event: messages.SessionClose) -> None:

        if self.id is None:
            return
        current_mode = self.id
        session_tracker = self.app.session_tracker

        session_count = session_tracker.session_count

        if session_count <= 1:
            session_tracker.close_session(current_mode)
            await self.app.switch_mode("store")

        else:
            if new_mode := self.app.session_tracker.session_cursor_move(
                current_mode, -1
            ):
                await self.app.switch_mode(new_mode)
            session_tracker.close_session(current_mode)

        self.app.call_later(self.app.remove_mode, current_mode)

    def on_mount(self) -> None:
        import gc

        gc.freeze()
        for tree in self.query("#project_directory_tree").results(DirectoryTree):
            tree.data_bind(path=MainScreen.project_path)
        for tree in self.query(DirectoryTree):
            tree.guide_depth = 3

        pane = self.query_one("#project_state_pane", ProjectStatePane)
        pane.configure_plan_execution(self._make_plan_execution_factory(pane))
        saved_width = (
            self.app.settings.get("ui.pane_width", str) or PANE_WIDTH_DEFAULT
        )
        pane.styles.width = saved_width
        # Bypass the watcher on the initial load so we don't immediately
        # re-persist the value we just read.
        self.set_reactive(MainScreen.pane_width, saved_width)

    def _make_plan_execution_factory(
        self, target: ProjectStatePane
    ) -> Callable[[str], "PlanExecutionModelProtocol | None"]:
        """Build the factory passed to ``ProjectStatePane.configure_plan_execution``.

        The factory resolves ``.orchestrator/plans/<slug>/`` under the
        current project path and constructs a live
        :class:`PlanExecutionModel` rooted at it. Messages from the
        model bubble up through the section to the active tab.
        """
        from typing import cast

        from toad.data.plan_execution_model import PlanExecutionModel

        def factory(slug: str) -> "PlanExecutionModelProtocol | None":
            plan_dir = self.project_path / ".orchestrator" / "plans" / slug
            if not plan_dir.is_dir():
                return None
            model = PlanExecutionModel(plan_dir, target=target)
            model.start()
            return cast("PlanExecutionModelProtocol", model)

        return factory

    @on(OptionList.OptionHighlighted)
    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        if event.option.id is not None:
            self.conversation.prompt.suggest(event.option.id)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        return True

    def action_show_sidebar(self) -> None:
        """Legacy keybinding — now opens the Context section in the right pane."""
        self.split_enabled = True
        pane = self.query_one("#project_state_pane", ProjectStatePane)
        pane.show_section("section-context")
        pane.activate_tab("tab-plan")
        try:
            pane.query_one(Plan).focus()
        except Exception:
            pass

    def action_toggle_project_state(self) -> None:
        """Toggle the right-side project state pane.

        Opens the DEGA section by default.
        """
        if self.split_enabled:
            pane = self.query_one("#project_state_pane", ProjectStatePane)
            pane.hide_all_sections()
        else:
            self.split_enabled = True
            pane = self.query_one("#project_state_pane", ProjectStatePane)
            pane.show_single_section("section-dega")

    def action_refresh_timeline(self) -> None:
        """Re-fetch timeline data from gist."""
        pane = self.query_one("#project_state_pane", ProjectStatePane)
        pane.refresh_timeline()

    def _show_section_tab(self, section_id: str, tab_id: str) -> None:
        """Open pane, show a section, and activate a tab."""
        self.split_enabled = True
        pane = self.query_one("#project_state_pane", ProjectStatePane)
        pane.show_section(section_id)
        pane.activate_tab(tab_id)

    async def _forward_canon_state(self, state: "CanonState") -> None:
        """Forward canon state to the AutomationPanel reactive attribute."""
        pane = self.query_one("#project_state_pane", ProjectStatePane)
        for panel in pane.query(AutomationPanel):
            panel.state = state

    def action_show_planning(self) -> None:
        """Open pane and show Planning section (Board tab)."""
        self._show_section_tab("section-planning", "tab-tasks")

    def action_show_github(self) -> None:
        """Open pane and show the Plans tab inside Planning."""
        self._show_section_tab("section-planning", "tab-gh-plans")

    def action_show_timeline(self) -> None:
        """Open pane and show Timeline tab inside Planning."""
        self._show_section_tab("section-planning", "tab-timeline")

    def action_show_automation(self) -> None:
        """Open pane and show Automation section."""
        self._show_section_tab("section-state", "tab-automation")

    # Backward-compat: older canon-start.md scripts in claude-code-config
    # still call screen.show_state / screen.hide_state. Forward to the
    # new automation actions so the panel opens correctly until those
    # scripts are updated.
    def action_show_state(self) -> None:
        """Alias of show_automation for older canon-start.md scripts."""
        self.action_show_automation()

    def action_show_outreach(self) -> None:
        """Open pane and show Outreach section.

        No-op when the private rpa_outreach extension is not installed —
        the section isn't mounted so ``show_section`` silently returns.
        """
        self._show_section_tab("section-outreach", "tab-outreach")

    def action_show_growth(self) -> None:
        """Open pane and show Growth section.

        No-op when the private dega_growth extension is not installed —
        the section isn't mounted so ``show_section`` silently returns.
        """
        self._show_section_tab("section-growth", "tab-growth")

    def action_show_dega(self) -> None:
        """Open pane and show the DEGA section.

        No-op when the dega_panel extension is not installed — the section
        isn't mounted so ``show_section`` silently returns.
        """
        self._show_section_tab("section-dega", "tab-dega")

    def _hide_section(self, section_id: str) -> None:
        """Hide a section by ID."""
        pane = self.query_one("#project_state_pane", ProjectStatePane)
        pane.hide_section(section_id)

    def action_hide_planning(self) -> None:
        """Hide the Planning section."""
        self._hide_section("section-planning")

    def action_hide_github(self) -> None:
        """Hide Planning section (GitHub is a tab inside it)."""
        self._hide_section("section-planning")

    def action_hide_timeline(self) -> None:
        """Hide Planning section (Timeline is a tab inside it)."""
        self._hide_section("section-planning")

    def action_hide_automation(self) -> None:
        """Hide the Automation section."""
        self._hide_section("section-state")

    def action_hide_state(self) -> None:
        """Alias of hide_automation for older canon-start.md scripts."""
        self.action_hide_automation()

    def action_hide_outreach(self) -> None:
        """Hide the Outreach section."""
        self._hide_section("section-outreach")

    def action_hide_dega(self) -> None:
        """Hide the DEGA section."""
        self._hide_section("section-dega")

    def action_hide_growth(self) -> None:
        """Hide the Growth section."""
        self._hide_section("section-growth")

    # ------------------------------------------------------------------
    # Canon auto-show logic
    # ------------------------------------------------------------------

    @on(CanonStateWidget.CanonStateDetected)
    def _on_canon_detected(
        self,
        _event: CanonStateWidget.CanonStateDetected,
    ) -> None:
        """Forward canon state data without auto-showing the pane."""
        _event.stop()
        canon = self.query_one("#canon-state", CanonStateWidget)
        self.call_later(self._forward_canon_state, canon.state)

    @on(CanonStateWidget.CanonStateUpdated)
    async def _on_canon_updated(
        self,
        event: CanonStateWidget.CanonStateUpdated,
    ) -> None:
        """Auto-switch between Builder and Automation on phase change."""
        event.stop()
        await self._forward_canon_state(event.state)

    def watch_split_enabled(self, enabled: bool) -> None:
        """Show/hide the project state pane."""
        pane = self.query_one("#project_state_pane", ProjectStatePane)
        pane.display = enabled

    @on(ProjectStatePane.AllSectionsHidden)
    def on_all_sections_hidden(
        self, message: ProjectStatePane.AllSectionsHidden
    ) -> None:
        """Auto-close pane when both sections are toggled off."""
        message.stop()
        self.split_enabled = False

    @on(acp_messages.OpenPanel)
    def on_acp_open_panel(self, message: acp_messages.OpenPanel) -> None:
        """Agent requests opening a panel.

        The panel ID is looked up in ``PANEL_ROUTES`` (declared in
        ``project_state_pane``). Optional ``message.context`` may carry
        ``filters`` — a dict applied to the panel after it opens (see
        the ``canon-panel-routing`` skill).

        Alias IDs like ``plans`` / ``prs`` route to the Board tab with the
        matching type chip pre-activated.
        """
        from toad.widgets.project_state_pane import (
            PANEL_ROUTES,
            PANEL_TYPE_PRESETS,
        )

        message.stop()
        panel_id = message.panel_id
        if panel_id == "project_state":
            self.split_enabled = True
            return
        mapping = PANEL_ROUTES.get(panel_id)
        if not mapping:
            return
        self._show_section_tab(*mapping)
        # Combine explicit filters from context with the alias's type preset.
        combined_filters: dict[str, Any] = {}
        preset_type = PANEL_TYPE_PRESETS.get(panel_id)
        if preset_type:
            combined_filters["type"] = preset_type
        if message.context:
            ctx_filters = message.context.get("filters")
            if isinstance(ctx_filters, dict):
                combined_filters.update(ctx_filters)
        if combined_filters and mapping[1] == "tab-tasks":
            pane = self.query_one("#project_state_pane", ProjectStatePane)
            pane.apply_task_filters(combined_filters)

    @on(acp_messages.ClosePanel)
    def on_acp_close_panel(self, message: acp_messages.ClosePanel) -> None:
        """Agent requests closing a panel."""
        from toad.widgets.project_state_pane import PANEL_ROUTES

        message.stop()
        panel_id = message.panel_id
        if panel_id == "project_state":
            pane = self.query_one("#project_state_pane", ProjectStatePane)
            pane.hide_all_sections()
            return
        mapping = PANEL_ROUTES.get(panel_id)
        if mapping:
            pane = self.query_one("#project_state_pane", ProjectStatePane)
            pane.hide_section(mapping[0])

    # ------------------------------------------------------------------
    # Subagent tab actions (driven by the socket controller)
    # ------------------------------------------------------------------

    def _default_subagent_factory(
        self, name: str, objective: str
    ) -> tuple[Widget, Any]:
        """Build a ``(Conversation, Agent)`` pair for a new subagent tab.

        The subagent reuses the Conductor's agent descriptor (``self._agent``)
        so it picks up the same `claude-code-acp` binary/config. Item 6 hooks
        the agent's ``done`` signal back into Conductor's session.
        """
        from toad.acp.agent import Agent as AcpAgent

        conversation = Conversation(
            self.project_path,
            self._agent,
            None,
            None,
            initial_prompt=objective,
        )
        agent: Any
        if self._agent is not None:
            agent = AcpAgent(self.project_path, self._agent, None, None)
        else:
            agent = None
        return conversation, agent

    def _get_subagent_section(self):
        pane = self.query_one("#project_state_pane", ProjectStatePane)
        return pane.ensure_subagent_section(self._default_subagent_factory)

    async def action_open_subagent_tab(
        self, name: str, objective: dict[str, Any]
    ) -> str:
        """Open a subagent tab.

        ``objective`` is the structured payload validated by the socket layer
        (guaranteed to contain a string ``objective`` key). Returns the
        resolved unique tab name.
        """
        import asyncio

        from toad.acp.agent import watch_subagent_completion

        self.split_enabled = True
        section = self._get_subagent_section()
        objective_text = str(objective["objective"])
        resolved = section.open_tab(name, objective_text)
        self._show_section_tab(section.SECTION_ID, section._tab_id(resolved))

        subagent = section.get_agent(resolved)
        conductor = getattr(self.conversation, "agent", None)
        if subagent is not None and conductor is not None and hasattr(
            subagent, "done_event"
        ):
            asyncio.create_task(
                watch_subagent_completion(subagent, conductor, resolved)
            )
        return resolved

    async def action_close_subagent_tab(self, name: str) -> None:
        """Close a subagent tab by name."""
        pane = self.query_one("#project_state_pane", ProjectStatePane)
        if pane._subagent_section is None:
            return
        pane._subagent_section.close_tab(name)

    def subagent_status(self) -> dict[str, Any]:
        """Return the list of open subagent tabs and their count."""
        pane = self.query_one("#project_state_pane", ProjectStatePane)
        section = pane._subagent_section
        names = list(section.tab_names) if section is not None else []
        return {"tabs": names, "count": len(names)}

    def action_focus_prompt(self) -> None:
        self.conversation.focus_prompt()

    async def action_go_home(self) -> None:
        """Clear default agent and return to agent picker."""
        self.app.settings.set("agent.default_agent", "")
        await self.app.save_settings()
        await self.app.switch_mode("store")


    def watch_pane_width(self, width: str) -> None:
        """Apply the right-pane width and persist it to user settings."""
        try:
            pane = self.query_one("#project_state_pane", ProjectStatePane)
        except NoMatches:
            return
        pane.styles.width = width
        self.app.settings.set("ui.pane_width", width)
        self.app.call_later(self.app.save_settings)

    def _current_pane_chars(self) -> int:
        """Return the right pane's current rendered width in cells.

        Falls back to the midpoint of the allowed range when the pane
        hasn't been laid out yet (e.g. width keybinding pressed before
        the pane has ever been opened).
        """
        try:
            pane = self.query_one("#project_state_pane", ProjectStatePane)
        except NoMatches:
            return (PANE_WIDTH_MIN_CHARS + PANE_WIDTH_MAX_CHARS) // 2
        rendered = pane.size.width
        if rendered > 0:
            return rendered
        return (PANE_WIDTH_MIN_CHARS + PANE_WIDTH_MAX_CHARS) // 2

    def _clamp_chars(self, chars: int) -> int:
        return max(min(chars, PANE_WIDTH_MAX_CHARS), PANE_WIDTH_MIN_CHARS)

    def action_widen_pane(self) -> None:
        """Increase the right pane width by one step (clamped)."""
        new_chars = self._clamp_chars(
            self._current_pane_chars() + PANE_WIDTH_STEP_CHARS
        )
        self.pane_width = str(new_chars)

    def action_narrow_pane(self) -> None:
        """Decrease the right pane width by one step (clamped)."""
        new_chars = self._clamp_chars(
            self._current_pane_chars() - PANE_WIDTH_STEP_CHARS
        )
        self.pane_width = str(new_chars)

    def action_set_pane_width(self, width: str) -> str:
        """Set the right pane width to a percentage like ``"40%"``.

        Raises ``ValueError`` if ``width`` is not in ``20%``–``80%``.
        Returns the applied width so the socket layer can echo it.
        """
        _parse_percentage(width)
        self.pane_width = width
        return width

    def action_get_pane_width(self) -> str:
        """Return the current right-pane width string."""
        return self.pane_width

    def watch_column(self, column: bool) -> None:
        self.conversation.styles.max_width = (
            max(10, self.column_width) if column else None
        )

    def watch_column_width(self, column_width: int) -> None:
        self.conversation.styles.max_width = (
            max(10, column_width) if self.column else None
        )

    def watch_scrollbar(self, old_scrollbar: str, scrollbar: str) -> None:
        if old_scrollbar:
            self.conversation.remove_class(f"-scrollbar-{old_scrollbar}")
        if scrollbar:
            self.conversation.add_class(f"-scrollbar-{scrollbar}")
