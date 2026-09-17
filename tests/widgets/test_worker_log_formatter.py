"""Tests for the worker-log NDJSON formatter."""

from __future__ import annotations

import json

from toad.widgets.worker_log_formatter import WorkerLogFormatter


def _line(payload: dict) -> str:
    return json.dumps(payload) + "\n"


class TestStreamJsonRendering:
    def test_assistant_text_block(self) -> None:
        f = WorkerLogFormatter()
        rendered = f.feed(
            _line(
                {
                    "type": "assistant",
                    "message": {
                        "content": [{"type": "text", "text": "Reading the plan."}]
                    },
                }
            )
        )
        assert "🤖 Reading the plan." in rendered

    def test_tool_use_uses_path_when_present(self) -> None:
        f = WorkerLogFormatter()
        rendered = f.feed(
            _line(
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "Read",
                                "input": {"file_path": "src/toad/foo.py"},
                            }
                        ]
                    },
                }
            )
        )
        assert "🔧 Read(src/toad/foo.py)" in rendered

    def test_tool_use_command_for_bash(self) -> None:
        f = WorkerLogFormatter()
        rendered = f.feed(
            _line(
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {"command": "uv run pytest -q"},
                            }
                        ]
                    },
                }
            )
        )
        assert "🔧 Bash(uv run pytest -q)" in rendered

    def test_tool_result_emits_paper_icon(self) -> None:
        f = WorkerLogFormatter()
        rendered = f.feed(
            _line(
                {
                    "type": "user",
                    "message": {
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "x",
                                "content": [
                                    {"type": "text", "text": "hello world"}
                                ],
                            }
                        ]
                    },
                }
            )
        )
        assert "📄 hello world" in rendered

    def test_tool_result_error_uses_warning(self) -> None:
        f = WorkerLogFormatter()
        rendered = f.feed(
            _line(
                {
                    "type": "user",
                    "message": {
                        "content": [
                            {
                                "type": "tool_result",
                                "is_error": True,
                                "content": "boom",
                            }
                        ]
                    },
                }
            )
        )
        assert "⚠ boom" in rendered

    def test_result_event_success(self) -> None:
        f = WorkerLogFormatter()
        rendered = f.feed(
            _line({"type": "result", "is_error": False, "result": "Item 1 complete."})
        )
        assert "✅ Item 1 complete." in rendered

    def test_result_event_error(self) -> None:
        f = WorkerLogFormatter()
        rendered = f.feed(_line({"type": "result", "is_error": True, "result": "boom"}))
        assert rendered.startswith("❌ boom")

    def test_system_init_emits_session_marker(self) -> None:
        f = WorkerLogFormatter()
        rendered = f.feed(
            _line(
                {
                    "type": "system",
                    "subtype": "init",
                    "model": "claude-opus-4-7[1m]",
                }
            )
        )
        assert "session start" in rendered
        assert "claude-opus-4-7[1m]" in rendered

    def test_rate_limit_event_dropped(self) -> None:
        f = WorkerLogFormatter()
        rendered = f.feed(_line({"type": "rate_limit_event", "rate_limit_info": {}}))
        assert rendered == ""


class TestPassThrough:
    def test_plain_text_passes_through(self) -> None:
        f = WorkerLogFormatter()
        rendered = f.feed("--- worker 1 exited ---\n")
        assert "--- worker 1 exited ---" in rendered

    def test_malformed_json_passes_through(self) -> None:
        """A line that looks like JSON but doesn't parse should still
        appear so the user sees real engine output instead of silence."""
        f = WorkerLogFormatter()
        rendered = f.feed("{not actually json}\n")
        assert "{not actually json}" in rendered

    def test_blank_line_dropped(self) -> None:
        f = WorkerLogFormatter()
        assert f.feed("\n\n") == ""


class TestBuffering:
    def test_partial_line_buffered_until_newline(self) -> None:
        """Chunks from `_scan_logs` are byte ranges, not line-aligned —
        a JSON event split across two `feed()` calls must not get
        rendered as two malformed halves."""
        f = WorkerLogFormatter()
        line = _line({"type": "result", "result": "ok"})
        head, tail = line[:20], line[20:]
        assert f.feed(head) == ""
        rendered = f.feed(tail)
        assert "✅ ok" in rendered

    def test_multiple_events_in_one_chunk(self) -> None:
        f = WorkerLogFormatter()
        bulk = _line(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "a"}]},
            }
        ) + _line({"type": "result", "result": "b"})
        rendered = f.feed(bulk)
        assert "🤖 a" in rendered
        assert "✅ b" in rendered

    def test_flush_emits_unterminated_tail(self) -> None:
        f = WorkerLogFormatter()
        f.feed("trailing without newline")
        flushed = f.flush()
        assert "trailing without newline" in flushed
