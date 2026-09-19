"""PRs DataTable — open pull requests with review decision and CI status."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from textual.app import ComposeResult
from textual.widgets import DataTable, Static
from textual.widget import Widget

from toad.widgets.github_views.fetch import (
    GitHubAuthError,
    GitHubFetchError,
    RepoInfo,
    fetch_prs,
)

log = logging.getLogger(__name__)

REVIEW_DISPLAY: dict[str, str] = {
    "APPROVED": "Approved",
    "CHANGES_REQUESTED": "Changes",
    "REVIEW_REQUIRED": "Pending",
}


def _review_label(decision: str | None) -> str:
    """Map reviewDecision to a short display label."""
    if not decision:
        return "None"
    return REVIEW_DISPLAY.get(decision, decision)


def _ci_status(rollup: list[dict] | None) -> str:
    """Summarise statusCheckRollup into a single CI label.

    Returns one of: Passing, Failing, Pending, Mixed, or — (no checks).
    """
    if not rollup:
        return "—"

    states: set[str] = set()
    for check in rollup:
        conclusion = (check.get("conclusion") or "").upper()
        status = (check.get("status") or "").upper()
        if conclusion == "SUCCESS":
            states.add("pass")
        elif conclusion in ("FAILURE", "ERROR", "CANCELLED", "TIMED_OUT"):
            states.add("fail")
        elif status in ("IN_PROGRESS", "QUEUED", "PENDING", "WAITING"):
            states.add("pending")
        else:
            states.add("pending")

    if states == {"pass"}:
        return "Passing"
    if "fail" in states and "pass" not in states:
        return "Failing"
    if states == {"pending"}:
        return "Pending"
    if "fail" in states:
        return "Mixed"
    return "Pending"


def _friendly_age(iso_ts: str) -> str:
    """Convert ISO timestamp to a short relative age string."""
    try:
        dt = datetime.fromisoformat(iso_ts)
        now = datetime.now(timezone.utc)
        diff = now - dt
        seconds = diff.total_seconds()
        if seconds < 60:
            return "now"
        if seconds < 3600:
            mins = int(seconds // 60)
            return f"{mins}m"
        if seconds < 86400:
            hours = int(seconds // 3600)
            return f"{hours}h"
        days = int(seconds // 86400)
        return f"{days}d"
    except Exception:
        return "?"


class PRsView(Widget):
    """DataTable of open pull requests with review and CI columns."""

    DEFAULT_CSS = """
    PRsView {
        height: auto;
    }
    PRsView DataTable {
        height: auto;
        max-height: 20;
    }
    PRsView .error-message {
        color: $error;
        padding: 1;
    }
    """

    def compose(self) -> ComposeResult:
        table = DataTable(id="prs-table", cursor_type="row")
        table.add_columns("#", "Title", "Author", "Review", "CI", "Age")
        yield table

    async def load(self, repo: RepoInfo) -> None:
        """Fetch PRs and populate the table."""
        table = self.query_one("#prs-table", DataTable)
        table.clear()

        # Remove any previous error message
        for widget in self.query(".error-message"):
            widget.remove()

        try:
            prs = await fetch_prs(repo)
        except GitHubAuthError:
            await self.mount(
                Static(
                    "Not authenticated — run: gh auth login",
                    classes="error-message",
                )
            )
            return
        except GitHubFetchError as exc:
            log.warning("Failed to fetch PRs: %s", exc)
            await self.mount(Static(str(exc), classes="error-message"))
            return

        for pr in prs:
            number = str(pr.get("number", ""))
            title = pr.get("title", "")
            author = (pr.get("author") or {}).get("login", "")
            review = _review_label(pr.get("reviewDecision"))
            ci = _ci_status(pr.get("statusCheckRollup"))
            age = _friendly_age(pr.get("updatedAt", ""))

            table.add_row(number, title, author, review, ci, age)
