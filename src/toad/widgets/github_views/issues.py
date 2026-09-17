"""Issues DataTable grouped by label."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import DataTable, Label, Static

from toad.widgets.github_views.fetch import (
    GitHubAuthError,
    GitHubFetchError,
    RepoInfo,
    fetch_issues,
)

log = logging.getLogger(__name__)


def _label_names(issue: dict[str, Any]) -> list[str]:
    """Extract label name strings from an issue dict."""
    labels = issue.get("labels") or []
    return [lbl["name"] for lbl in labels if "name" in lbl]


def _group_by_label(
    issues: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Group issues by label. Issues with no labels go under 'unlabeled'."""
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for issue in issues:
        names = _label_names(issue)
        if not names:
            groups["unlabeled"].append(issue)
        else:
            for name in names:
                groups[name].append(issue)
    return dict(sorted(groups.items()))


def _format_date(iso_str: str) -> str:
    """Shorten ISO timestamp to YYYY-MM-DD."""
    return iso_str[:10] if iso_str else ""


def _author_login(issue: dict[str, Any]) -> str:
    """Extract author login from issue dict."""
    author = issue.get("author") or {}
    return author.get("login", "")


class IssuesView(VerticalScroll):
    """Open issues grouped by label, each group in its own DataTable."""

    DEFAULT_CSS = """
    IssuesView {
        height: 1fr;
        padding: 0 1;

        .issues-label-header {
            text-style: bold;
            color: $accent;
            margin: 1 0 0 0;
        }

        .issues-error {
            color: $error;
            text-style: italic;
            margin: 1 0;
        }

        .issues-empty {
            color: $text-muted;
            text-style: italic;
            margin: 1 0;
        }

        DataTable {
            height: auto;
            max-height: 20;
            margin: 0 0 1 0;
        }
    }
    """

    def __init__(
        self,
        repo: RepoInfo | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._repo = repo
        self._issues: list[dict[str, Any]] = []

    def compose(self) -> ComposeResult:
        yield Static("Loading issues...", id="issues-status")

    async def on_mount(self) -> None:
        await self.fetch_and_render()

    async def fetch_and_render(self) -> None:
        """Fetch issues and rebuild the widget tree."""
        status = self.query_one("#issues-status", Static)
        if self._repo is None:
            status.update("No repo configured")
            return

        try:
            self._issues = await fetch_issues(self._repo)
        except GitHubAuthError:
            status.update("Not authenticated — run: gh auth login")
            status.add_class("issues-error")
            return
        except GitHubFetchError as exc:
            log.warning("Failed to fetch issues: %s", exc)
            status.update(f"Fetch error: {exc}")
            status.add_class("issues-error")
            return

        await status.remove()
        self._render_groups()

    def _render_groups(self) -> None:
        """Build label-grouped DataTables from fetched issues."""
        if not self._issues:
            self.mount(Static("No open issues", classes="issues-empty"))
            return

        groups = _group_by_label(self._issues)
        for label, issues in groups.items():
            header = Label(f" {label} ({len(issues)})", classes="issues-label-header")
            self.mount(header)

            table = DataTable(zebra_stripes=True)
            table.add_columns("#", "Title", "Author", "Updated")
            for issue in issues:
                table.add_row(
                    str(issue.get("number", "")),
                    _truncate(issue.get("title", ""), 50),
                    _author_login(issue),
                    _format_date(issue.get("updatedAt", "")),
                )
            self.mount(table)

    async def refresh_data(self) -> None:
        """Re-fetch and re-render issues."""
        for child in list(self.children):
            await child.remove()
        self.mount(Static("Loading issues...", id="issues-status"))
        await self.fetch_and_render()


def _truncate(text: str, max_len: int) -> str:
    """Truncate text with ellipsis if needed."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "\u2026"
