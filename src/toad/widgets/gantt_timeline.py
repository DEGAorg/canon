"""Gantt Timeline — renders a Gantt chart from TimelineData model."""

from __future__ import annotations

import logging
import math
from datetime import date

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import ScrollableContainer
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from toad.widgets.github_views.timeline_data import (
    MilestoneGroup,
    TimelineData,
    TimelineItem,
)
from toad.widgets.github_views.timeline_provider import ItemStatus, Priority

log = logging.getLogger(__name__)

# Palette
DONE_STYLE = "green"
ACTIVE_STYLE = "yellow"
PENDING_STYLE = "bright_black"
GATE_STYLE = "bold yellow"
TODAY_STYLE = "bold green"
AXIS_STYLE = "bright_black"
GROUP_STYLE = "bold cyan"
DUE_STYLE = "bold magenta"

# Layout
LABEL_WIDTH = 22
CHARS_PER_WEEK = 10
BAR_CHAR = "\u2588"  # █
BAR_DIM = "\u2591"  # ░
TODAY_CHAR = "\u2502"  # │
DIAMOND = "\u25c6"  # ◆


def compute_track_width(
    total_days: int,
    chars_per_week: int = CHARS_PER_WEEK,
) -> int:
    """Compute track width from timeline span using fixed chars per week.

    Returns:
        Character width = ceil(total_days / 7) * chars_per_week,
        with a minimum of chars_per_week (one week).
    """
    if total_days <= 0:
        return chars_per_week
    weeks = math.ceil(total_days / 7)
    return max(chars_per_week, weeks * chars_per_week)


# Priority → style suffix
_PRIORITY_BORDER: dict[Priority, str] = {
    Priority.P1: "bold red",
    Priority.P2: "bold yellow",
    Priority.P3: "",
    Priority.P4: "dim",
}


def _item_bar_style(item: TimelineItem) -> str:
    """Return bar style based on status."""
    if item.status is ItemStatus.DONE:
        return DONE_STYLE
    if item.status is ItemStatus.IN_PROGRESS:
        return ACTIVE_STYLE
    return PENDING_STYLE


def _status_indicator(status: ItemStatus) -> str:
    """Return a status prefix character."""
    if status is ItemStatus.DONE:
        return "\u2713 "  # ✓
    if status is ItemStatus.IN_PROGRESS:
        return "\u25b6 "  # ▶
    return "  "


def compute_bar_position(
    start_day: int,
    days: int,
    total_days: int,
    track_width: int,
) -> tuple[int, int]:
    """Compute character offset and width for a Gantt bar.

    Returns:
        (offset, width) in characters.
    """
    if total_days <= 0 or track_width <= 0:
        return (0, 0)
    offset = int((start_day / total_days) * track_width)
    width = max(1, int((days / total_days) * track_width))
    offset = min(offset, track_width - 1)
    width = min(width, track_width - offset)
    return (offset, width)


def render_date_axis(
    data: TimelineData,
    track_width: int,
) -> list[Text]:
    """Build date axis rows: dates on top, gate markers below."""
    total_days = data.total_days
    start = data.start_date

    # Row 1: date tick marks
    date_track = [" "] * track_width
    tick_interval = max(7, total_days // max(1, track_width // 10))
    for day in range(0, total_days, tick_interval):
        pos = int((day / total_days) * track_width)
        if pos + 6 >= track_width:
            break
        d = date.fromordinal(start.toordinal() + day)
        label = d.strftime("%b %d")
        if all(
            date_track[pos + i] == " "
            for i in range(len(label))
            if pos + i < track_width
        ):
            for i, ch in enumerate(label):
                idx = pos + i
                if idx < track_width:
                    date_track[idx] = ch

    date_line = Text(" " * LABEL_WIDTH)
    date_line.append("".join(date_track), style=f"bold {AXIS_STYLE}")

    # Row 2: gate markers
    gate_track = [" "] * track_width
    for gate in data.gates:
        pos = (
            int((gate.day / total_days) * track_width)
            if total_days > 0
            else 0
        )
        pos = min(pos, track_width - 1)
        tag = f"{DIAMOND}{gate.label}"
        for i, ch in enumerate(tag):
            idx = pos + i
            if idx < track_width:
                gate_track[idx] = ch

    gate_str = "".join(gate_track)
    gate_text = Text(gate_str, style=AXIS_STYLE)
    for gate in data.gates:
        pos = (
            int((gate.day / total_days) * track_width)
            if total_days > 0
            else 0
        )
        pos = min(pos, track_width - 1)
        tag = f"{DIAMOND}{gate.label}"
        end = min(pos + len(tag), track_width)
        gate_text.stylize(GATE_STYLE, pos, end)

    gate_line = Text(" " * LABEL_WIDTH)
    gate_line.append_text(gate_text)

    return [date_line, gate_line]


def render_today_row(
    data: TimelineData,
    track_width: int,
) -> Text | None:
    """Build a today-marker row if today falls within the timeline range."""
    today = date.today()
    day_offset = (today - data.start_date).days
    if day_offset < 0 or day_offset >= data.total_days:
        return None

    pos = int((day_offset / data.total_days) * track_width)
    pos = min(pos, track_width - 1)

    label_part = Text("TODAY".ljust(LABEL_WIDTH), style=TODAY_STYLE)
    track = Text(
        " " * pos + TODAY_CHAR + " " * (track_width - pos - 1),
        style=TODAY_STYLE,
    )
    label_part.append_text(track)
    return label_part


def render_bar_row(
    item: TimelineItem,
    total_days: int,
    track_width: int,
) -> Text:
    """Render one Gantt bar row: [status] [label] [positioned bar]."""
    indicator = _status_indicator(item.status)
    raw_label = item.title
    label_str = (indicator + raw_label)[: LABEL_WIDTH - 1].ljust(
        LABEL_WIDTH
    )
    style = _item_bar_style(item)

    offset, width = compute_bar_position(
        item.start_day,
        item.days,
        total_days,
        track_width,
    )

    done = item.status is ItemStatus.DONE
    char = BAR_CHAR if done else BAR_DIM

    # Priority styling on the label
    priority_style = ""
    if item.priority and item.priority in _PRIORITY_BORDER:
        priority_style = _PRIORITY_BORDER[item.priority]
    label_style = priority_style or (f"dim {style}" if done else style)

    # Risk items get underlined bars
    bar_style = f"underline {style}" if item.risk_labels else style

    line = Text(label_str, style=label_style)
    line.append(" " * offset)
    line.append(char * width, style=bar_style)

    remaining = track_width - offset - width
    if remaining > 0:
        line.append(" " * remaining)

    return line


def render_group_header(
    group: MilestoneGroup,
    data: TimelineData,
    track_width: int,
) -> Text:
    """Render a milestone group header with optional due-date marker."""
    title = f"\u2501\u2501 {group.title} "
    header = Text(
        title[: LABEL_WIDTH - 1].ljust(LABEL_WIDTH), style=GROUP_STYLE
    )

    track_chars = ["\u2500"] * track_width
    if group.due_date:
        day_offset = (group.due_date - data.start_date).days
        if 0 <= day_offset < data.total_days:
            pos = int((day_offset / data.total_days) * track_width)
            pos = min(pos, track_width - 1)
            due_label = f"{DIAMOND}{group.due_date.strftime('%b %d')}"
            for i, ch in enumerate(due_label):
                idx = pos + i
                if idx < track_width:
                    track_chars[idx] = ch

    track = Text("".join(track_chars), style=AXIS_STYLE)
    if group.due_date:
        day_offset = (group.due_date - data.start_date).days
        if 0 <= day_offset < data.total_days:
            pos = int((day_offset / data.total_days) * track_width)
            pos = min(pos, track_width - 1)
            due_label = f"{DIAMOND}{group.due_date.strftime('%b %d')}"
            end = min(pos + len(due_label), track_width)
            track.stylize(DUE_STYLE, pos, end)

    header.append_text(track)
    return header


def render_gantt(
    data: TimelineData,
    track_width: int = 60,
) -> list[Text]:
    """Render the full Gantt chart as a list of Rich Text lines."""
    lines: list[Text] = []

    # Date axis (dates + gate markers = 2 rows)
    lines.extend(render_date_axis(data, track_width))

    # Separator
    sep = Text(" " * LABEL_WIDTH, style=AXIS_STYLE)
    sep.append("\u2500" * track_width, style=AXIS_STYLE)
    lines.append(sep)

    # Today marker
    today_line = render_today_row(data, track_width)
    if today_line:
        lines.append(today_line)

    # Milestone groups with headers
    for group in data.groups:
        lines.append(render_group_header(group, data, track_width))
        for item in group.items:
            lines.append(
                render_bar_row(item, data.total_days, track_width)
            )

    return lines


class GanttTimeline(Widget):
    """Gantt chart with fixed-width-per-week bars and 2D scrolling.

    The chart content may be wider than the viewport (horizontal
    scroll) and taller than the viewport (vertical scroll).  Both
    axes are handled by a single ``ScrollableContainer``.
    """

    DEFAULT_CSS = """
    GanttTimeline {
        height: 1fr;
    }
    GanttTimeline #gantt-scroll {
        overflow-x: auto;
        overflow-y: auto;
    }
    GanttTimeline #gantt-content {
        height: auto;
    }
    """

    timeline_data: reactive[TimelineData | None] = reactive(None)

    def compose(self) -> ComposeResult:
        with ScrollableContainer(id="gantt-scroll"):
            yield Static("", id="gantt-content")

    def watch_timeline_data(self) -> None:
        """Re-render when data changes."""
        self._render_chart()

    def on_resize(self) -> None:
        """Re-render on terminal resize."""
        if self.timeline_data:
            self._render_chart()

    def _render_chart(self) -> None:
        """Render the Gantt chart into this widget."""
        if not self.timeline_data:
            try:
                self.query_one("#gantt-content", Static).update(
                    "No timeline data"
                )
            except Exception:
                pass
            return

        data = self.timeline_data
        track_width = compute_track_width(data.total_days)
        lines = render_gantt(data, track_width)

        content = self.query_one("#gantt-content", Static)
        # Force the content to be wide enough for horizontal scroll
        total_width = LABEL_WIDTH + track_width + 2
        content.styles.min_width = total_width
        content.update(Text("\n").join(lines))

        self._scroll_to_today(data, track_width)

    def _scroll_to_today(
        self,
        data: TimelineData,
        track_width: int,
    ) -> None:
        """Auto-scroll so the today marker is visible."""
        today = date.today()
        day_offset = (today - data.start_date).days
        if day_offset < 0 or day_offset >= data.total_days:
            return
        pos = LABEL_WIDTH + int(
            (day_offset / data.total_days) * track_width
        )
        scroll = self.query_one("#gantt-scroll", ScrollableContainer)

        def _do_scroll() -> None:
            visible_w = scroll.size.width
            target_x = max(0, pos - visible_w // 2)
            scroll.scroll_to(x=target_x, animate=False)

        self.call_after_refresh(_do_scroll)
