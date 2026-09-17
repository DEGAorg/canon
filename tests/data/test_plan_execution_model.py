"""Pilot tests for ``toad.data.plan_execution_model.PlanExecutionModel``.

The model watches an orchestrator plan directory
(``.orchestrator/plans/<slug>/``) for changes to ``state.json`` and
per-item ``logs/<id>.log`` files, then posts Textual messages that the
existing plan-execution widgets handle:

- ``PlanExecutionTab.ItemStatusChanged`` when an item's ``status`` flips
- ``PlanWorkerLogPane.ItemLogAppended`` (delivered through the
  ``subscribe_log`` callback) when a log file grows
- ``PlanExecutionTab.PlanFinished`` when the plan reaches a terminal
  verdict

These pilot tests pin the public surface of the model. They use polling
mode (no real filesystem watcher thread) and a synchronous ``poll_now``
hook so behaviour is deterministic across platforms.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from toad.data.plan_execution_model import PlanExecutionModel
from toad.widgets.plan_execution_tab import PlanExecutionTab
from toad.widgets.plan_worker_log_pane import PlanWorkerLogPane


# ----------------------------------------------------------------------
# Test doubles
# ----------------------------------------------------------------------


@dataclass
class _Recorder:
    """Captures messages the model would post to a Textual widget."""

    messages: list[Any] = field(default_factory=list)

    def post_message(self, message: Any) -> bool:
        self.messages.append(message)
        return True


def _state_payload(
    *,
    items: Iterable[dict[str, Any]],
    verdict: str | None = None,
    issue_number: int | None = 42,
    slug: str = "20260427-test-plan",
    status: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "version": 1,
        "plan": slug,
        "issueNumber": issue_number,
        "items": list(items),
    }
    if verdict is not None:
        # Engine writes finalReview.result; the parameter is named ``verdict``
        # for readability in test bodies.
        payload["finalReview"] = {"result": verdict, "status": "done"}
        payload["status"] = status or "completed"
    elif status is not None:
        payload["status"] = status
    return payload


def _write_state(plan_dir: Path, payload: dict[str, Any]) -> None:
    (plan_dir / "state.json").write_text(json.dumps(payload), encoding="utf-8")


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------


@pytest.fixture
def plan_dir(tmp_path: Path) -> Path:
    """Create an orchestrator plan dir with a minimal ``state.json``."""
    pdir = tmp_path / ".orchestrator" / "plans" / "20260427-test-plan"
    (pdir / "logs").mkdir(parents=True)
    _write_state(
        pdir,
        _state_payload(
            items=[
                {
                    "id": 1,
                    "description": "alpha",
                    "deps": [],
                    "status": "running",
                },
                {
                    "id": 2,
                    "description": "beta",
                    "deps": [1],
                    "status": "queued",
                },
            ],
        ),
    )
    return pdir


# ----------------------------------------------------------------------
# Initial parse
# ----------------------------------------------------------------------


class TestInitialParse:
    """The model parses ``state.json`` on construction."""

    def test_exposes_slug_issue_items_and_verdict(self, plan_dir: Path) -> None:
        target = _Recorder()
        model = PlanExecutionModel(plan_dir, target=target, poll=True)

        assert model.slug == "20260427-test-plan"
        assert model.issue_number == 42
        assert [item.id for item in model.items] == [1, 2]
        assert [item.status for item in model.items] == ["running", "queued"]
        assert model.items[1].deps == (1,)
        assert model.verdict == "running"

    def test_no_messages_posted_on_construction(self, plan_dir: Path) -> None:
        """Initial parse populates state but emits nothing."""
        target = _Recorder()
        PlanExecutionModel(plan_dir, target=target, poll=True)
        assert target.messages == []


# ----------------------------------------------------------------------
# ItemStatusChanged
# ----------------------------------------------------------------------


class TestItemStatusChanged:
    """Status flips in ``state.json`` produce ``ItemStatusChanged``."""

    def test_emits_when_item_status_flips(self, plan_dir: Path) -> None:
        target = _Recorder()
        model = PlanExecutionModel(plan_dir, target=target, poll=True)
        model.start()
        try:
            _write_state(
                plan_dir,
                _state_payload(
                    items=[
                        {
                            "id": 1,
                            "description": "alpha",
                            "deps": [],
                            "status": "done",
                        },
                        {
                            "id": 2,
                            "description": "beta",
                            "deps": [1],
                            "status": "running",
                        },
                    ],
                ),
            )
            model.poll_now()
        finally:
            model.stop()

        flips = [
            (m.item_id, m.status)
            for m in target.messages
            if isinstance(m, PlanExecutionTab.ItemStatusChanged)
        ]
        assert (1, "done") in flips
        assert (2, "running") in flips

    def test_no_message_when_status_unchanged(self, plan_dir: Path) -> None:
        target = _Recorder()
        model = PlanExecutionModel(plan_dir, target=target, poll=True)
        model.start()
        try:
            # Re-write the same payload — nothing changed.
            _write_state(
                plan_dir,
                _state_payload(
                    items=[
                        {
                            "id": 1,
                            "description": "alpha",
                            "deps": [],
                            "status": "running",
                        },
                        {
                            "id": 2,
                            "description": "beta",
                            "deps": [1],
                            "status": "queued",
                        },
                    ],
                ),
            )
            model.poll_now()
        finally:
            model.stop()

        flips = [
            m
            for m in target.messages
            if isinstance(m, PlanExecutionTab.ItemStatusChanged)
        ]
        assert flips == []


# ----------------------------------------------------------------------
# ItemLogAppended
# ----------------------------------------------------------------------


class TestItemLogAppended:
    """New lines in ``logs/<id>.log`` reach ``subscribe_log`` callbacks."""

    def test_subscriber_receives_appended_text(self, plan_dir: Path) -> None:
        target = _Recorder()
        model = PlanExecutionModel(plan_dir, target=target, poll=True)
        received: list[str] = []
        unsubscribe = model.subscribe_log(1, received.append)
        model.start()
        try:
            log_path = plan_dir / "logs" / "1.log"
            log_path.write_text("first line\n", encoding="utf-8")
            model.poll_now()
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write("second line\n")
            model.poll_now()
        finally:
            unsubscribe()
            model.stop()

        joined = "".join(received)
        assert "first line" in joined
        assert "second line" in joined

    def test_unsubscribe_stops_delivery(self, plan_dir: Path) -> None:
        target = _Recorder()
        model = PlanExecutionModel(plan_dir, target=target, poll=True)
        received: list[str] = []
        unsubscribe = model.subscribe_log(1, received.append)
        model.start()
        try:
            log_path = plan_dir / "logs" / "1.log"
            log_path.write_text("before unsub\n", encoding="utf-8")
            model.poll_now()
            unsubscribe()
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write("after unsub\n")
            model.poll_now()
        finally:
            model.stop()

        joined = "".join(received)
        assert "before unsub" in joined
        assert "after unsub" not in joined

    def test_subscriber_reads_engine_worker_log(self, plan_dir: Path) -> None:
        """The orchestrator engine pipes the worker tmux pane to
        ``logs/worker-<id>.log``; the model must tail that file rather
        than the legacy ``logs/<id>.log`` path so the worker pane shows
        the live agent conversation, not just the final summary line.
        """
        target = _Recorder()
        model = PlanExecutionModel(plan_dir, target=target, poll=True)
        received: list[str] = []
        unsubscribe = model.subscribe_log(1, received.append)
        model.start()
        try:
            log_path = plan_dir / "logs" / "worker-1.log"
            log_path.write_text("agent: thinking…\n", encoding="utf-8")
            model.poll_now()
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write("tool_use: Read(plan.md)\n")
            model.poll_now()
        finally:
            unsubscribe()
            model.stop()

        joined = "".join(received)
        assert "thinking" in joined
        assert "Read(plan.md)" in joined

    def test_worker_log_supersedes_legacy_path(self, plan_dir: Path) -> None:
        """If a legacy ``logs/<id>.log`` was created first and the engine
        later writes ``logs/worker-<id>.log``, the model switches to the
        engine file from byte 0 — we must not skip the prefix of the new
        file because of bytes already consumed from the legacy one.
        """
        target = _Recorder()
        model = PlanExecutionModel(plan_dir, target=target, poll=True)
        received: list[str] = []
        unsubscribe = model.subscribe_log(1, received.append)
        model.start()
        try:
            (plan_dir / "logs" / "1.log").write_text(
                "legacy summary\n", encoding="utf-8"
            )
            model.poll_now()
            (plan_dir / "logs" / "worker-1.log").write_text(
                "fresh worker output\n", encoding="utf-8"
            )
            model.poll_now()
        finally:
            unsubscribe()
            model.stop()

        joined = "".join(received)
        assert "legacy summary" in joined
        assert "fresh worker output" in joined

    def test_subscribe_replays_existing_log_content(self, plan_dir: Path) -> None:
        """A fresh subscriber receives whatever is already on disk so
        switching away from an item and coming back doesn't wipe the
        worker pane. The on-disk log survives the navigation; the model
        must replay it on attach.
        """
        target = _Recorder()
        model = PlanExecutionModel(plan_dir, target=target, poll=True)
        model.start()
        log_path = plan_dir / "logs" / "worker-1.log"
        log_path.write_text("history line 1\nhistory line 2\n", encoding="utf-8")

        # First subscriber sees the existing file as a single replay chunk.
        first: list[str] = []
        unsubscribe_first = model.subscribe_log(1, first.append)
        try:
            assert "history line 1" in "".join(first)
            assert "history line 2" in "".join(first)
            # No extra delivery on poll because the snapshot synced position.
            model.poll_now()
            assert "".join(first).count("history line 1") == 1
        finally:
            unsubscribe_first()

        # New writes while no subscriber.
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write("offline append\n")

        # Re-attach (simulates navigating away and back to the item).
        second: list[str] = []
        unsubscribe_second = model.subscribe_log(1, second.append)
        try:
            joined = "".join(second)
            # Must see the full history *and* the offline append, exactly once.
            assert "history line 1" in joined
            assert "history line 2" in joined
            assert joined.count("offline append") == 1
            model.poll_now()
            # Polling after the snapshot must not re-deliver the gap.
            assert "".join(second).count("offline append") == 1
        finally:
            unsubscribe_second()
            model.stop()

    def test_log_pane_message_class_is_used(self, plan_dir: Path) -> None:
        """The log-append message class lives on ``PlanWorkerLogPane``.

        This is a regression pin — if the class is renamed or moved, the
        worker-log pane and the model both break together, so make the
        symbol's home explicit.
        """
        assert hasattr(PlanWorkerLogPane, "ItemLogAppended")


# ----------------------------------------------------------------------
# PlanFinished
# ----------------------------------------------------------------------


class TestPlanFinished:
    """A terminal verdict in ``state.json`` produces ``PlanFinished``."""

    def test_emits_when_verdict_set(self, plan_dir: Path) -> None:
        target = _Recorder()
        model = PlanExecutionModel(plan_dir, target=target, poll=True)
        model.start()
        try:
            _write_state(
                plan_dir,
                _state_payload(
                    items=[
                        {
                            "id": 1,
                            "description": "alpha",
                            "deps": [],
                            "status": "done",
                        },
                        {
                            "id": 2,
                            "description": "beta",
                            "deps": [1],
                            "status": "done",
                        },
                    ],
                    verdict="SHIP",
                ),
            )
            model.poll_now()
        finally:
            model.stop()

        finished = [
            m for m in target.messages if isinstance(m, PlanExecutionTab.PlanFinished)
        ]
        assert len(finished) == 1
        assert finished[0].verdict == "SHIP"
        assert model.verdict == "SHIP"

    def test_no_premature_finished_when_verdict_set_before_status(
        self, plan_dir: Path
    ) -> None:
        """Regression: the engine writes ``finalReview.result = "SHIP"``
        before setting ``status = "completed"``. The model must NOT fire
        ``PlanFinished`` until ``status`` is actually terminal —
        otherwise the tab badge freezes on "running" because the later
        poll (with ``status = "completed"``) is suppressed by the
        ``_finished_emitted`` guard.
        """
        done_items = [
            {"id": 1, "description": "alpha", "deps": [], "status": "done"},
            {"id": 2, "description": "beta", "deps": [1], "status": "done"},
        ]
        target = _Recorder()
        model = PlanExecutionModel(plan_dir, target=target, poll=True)
        model.start()
        try:
            # Step 1: engine writes finalReview.result but status is
            # still "running" (review just finished, verify not started).
            payload_review_done = _state_payload(items=done_items)
            payload_review_done["finalReview"] = {
                "result": "SHIP",
                "status": "done",
            }
            # status stays default (no "status" key → model treats as "running")
            payload_review_done.pop("status", None)
            _write_state(plan_dir, payload_review_done)
            model.poll_now()

            premature = [
                m
                for m in target.messages
                if isinstance(m, PlanExecutionTab.PlanFinished)
            ]
            assert premature == [], (
                "PlanFinished must not fire before status is terminal"
            )
            assert model.verdict == "SHIP"
            assert model.phase == "Running"

            # Step 2: engine sets status = "verifying".
            payload_verifying = dict(payload_review_done)
            payload_verifying["status"] = "verifying"
            payload_verifying["verification"] = {
                "status": "running",
                "uncheckedCount": 2,
            }
            _write_state(plan_dir, payload_verifying)
            model.poll_now()

            still_premature = [
                m
                for m in target.messages
                if isinstance(m, PlanExecutionTab.PlanFinished)
            ]
            assert still_premature == [], (
                "PlanFinished must not fire during verification"
            )
            assert model.phase == "Verify"

            # Step 3: engine writes status = "completed".
            payload_completed = _state_payload(
                items=done_items, verdict="SHIP"
            )
            payload_completed["verification"] = {
                "status": "passed",
                "uncheckedCount": 0,
            }
            _write_state(plan_dir, payload_completed)
            model.poll_now()

            finished = [
                m
                for m in target.messages
                if isinstance(m, PlanExecutionTab.PlanFinished)
            ]
            assert len(finished) == 1
            assert finished[0].verdict == "SHIP"
            assert model.phase == "Done"
            assert model.status == "completed"
        finally:
            model.stop()

    def test_emits_at_most_once_per_terminal_verdict(self, plan_dir: Path) -> None:
        target = _Recorder()
        model = PlanExecutionModel(plan_dir, target=target, poll=True)
        model.start()
        try:
            payload = _state_payload(
                items=[
                    {
                        "id": 1,
                        "description": "alpha",
                        "deps": [],
                        "status": "done",
                    },
                    {
                        "id": 2,
                        "description": "beta",
                        "deps": [1],
                        "status": "done",
                    },
                ],
                verdict="SHIP",
            )
            _write_state(plan_dir, payload)
            model.poll_now()
            # A second poll without any state change must not re-emit.
            model.poll_now()
        finally:
            model.stop()

        finished = [
            m for m in target.messages if isinstance(m, PlanExecutionTab.PlanFinished)
        ]
        assert len(finished) == 1
