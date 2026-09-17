"""Format orchestrator worker logs for the plan-execution worker pane.

The orchestrator engine pipes each worker's tmux pane to
``logs/worker-<id>.log`` via ``tmux pipe-pane``. With the agent shim
configured for ``--output-format stream-json --verbose`` (Claude),
that file is one JSON event per line — system init, assistant
messages, tool uses, tool results, the final result. With the older
``-p`` text mode it's a single summary line plus tmux ANSI teardown.

This module turns either form into a readable transcript. JSON events
become one-line summaries (``🔧 Read(path)``, ``📄 result preview``,
``🤖 assistant text``, ``✅ done``); anything that isn't valid JSON
passes through unchanged so the formatter is safe to deploy before
the shim flips, and stays useful for any non-streaming output (e.g.
``echo`` lines from the engine wrapper).

Chunks delivered by ``PlanExecutionModel`` are not line-aligned —
they're raw byte ranges from the file. The :class:`WorkerLogFormatter`
buffers a partial trailing line until the next chunk so we never split
a JSON object across two formatted outputs.
"""

from __future__ import annotations

import json
from typing import Any


__all__ = ["WorkerLogFormatter"]


_MAX_PREVIEW = 240


class WorkerLogFormatter:
    """Stateful, per-item formatter that converts raw log chunks to text.

    Use one instance per worker-pane attachment. ``feed(chunk)`` accepts
    arbitrary byte-aligned text and returns the rendered transcript
    fragment ready to write to the ``RichLog``. ``flush()`` emits any
    remaining unterminated line — call it when switching items so a
    trailing partial line isn't lost.
    """

    def __init__(self) -> None:
        self._buffer = ""

    def feed(self, chunk: str) -> str:
        self._buffer += chunk
        out: list[str] = []
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            rendered = _format_line(line)
            if rendered:
                out.append(rendered)
        if not out:
            return ""
        return "\n".join(out) + "\n"

    def flush(self) -> str:
        if not self._buffer:
            return ""
        line, self._buffer = self._buffer, ""
        rendered = _format_line(line)
        return f"{rendered}\n" if rendered else ""


def _format_line(line: str) -> str | None:
    """Render one log line. ``None`` means 'drop silently'."""
    stripped = line.strip()
    if not stripped:
        return None
    # JSON event lines start with `{` and end with `}` (full object on a line).
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            event = json.loads(stripped)
        except ValueError:
            return line  # malformed — show raw so issues are visible
        if isinstance(event, dict):
            return _render_event(event)
    return line  # plain text passes through unchanged


def _render_event(event: dict[str, Any]) -> str | None:
    event_type = event.get("type")
    if event_type == "system":
        if event.get("subtype") == "init":
            model = event.get("model") or "claude"
            return f"⚙ session start  ·  {model}"
        return None
    if event_type == "rate_limit_event":
        return None
    if event_type == "assistant":
        return _render_assistant(event)
    if event_type == "user":
        return _render_user(event)
    if event_type == "result":
        return _render_result(event)
    return None


def _render_assistant(event: dict[str, Any]) -> str | None:
    message = event.get("message")
    if not isinstance(message, dict):
        return None
    parts: list[str] = []
    for block in message.get("content", []) or []:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text":
            text = (block.get("text") or "").strip()
            if text:
                # Don't truncate — this is the actual assistant
                # conversation the user wants to read in the pane.
                parts.append(f"🤖 {text}")
        elif block_type == "thinking":
            text = (block.get("thinking") or "").strip()
            if text:
                parts.append(f"💭 {text}")
        elif block_type == "tool_use":
            name = block.get("name") or "?"
            summary = _summarize_tool_input(block.get("input"))
            parts.append(f"🔧 {name}({summary})")
    return "\n".join(parts) if parts else None


def _render_user(event: dict[str, Any]) -> str | None:
    message = event.get("message")
    if not isinstance(message, dict):
        return None
    for block in message.get("content", []) or []:
        if not isinstance(block, dict):
            continue
        if block.get("type") != "tool_result":
            continue
        content = block.get("content")
        text = _extract_tool_result_text(content)
        if not text:
            continue
        prefix = "⚠" if block.get("is_error") else "📄"
        return f"{prefix} {_truncate(text)}"
    return None


def _render_result(event: dict[str, Any]) -> str | None:
    text = (event.get("result") or "").strip()
    is_error = bool(event.get("is_error"))
    icon = "❌" if is_error else "✅"
    if not text:
        text = "error" if is_error else "done"
    # Don't truncate — the result is the agent's final, deliberate
    # output (summary, plan reply, etc.) and it's what the user is most
    # likely to want to read in full.
    return f"{icon} {text}"


def _extract_tool_result_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text")
                if isinstance(text, str):
                    chunks.append(text)
        return " ".join(chunks).strip()
    return ""


def _summarize_tool_input(inp: Any) -> str:
    """One-line preview of a tool's argument set.

    Picks the highest-signal field per known tool (path for Read/Edit,
    command for Bash, pattern for Grep, …) and falls back to a
    truncated key=value list for unknown tools.
    """
    if not isinstance(inp, dict):
        return _truncate(str(inp), 80)
    for key in ("file_path", "path", "notebook_path"):
        value = inp.get(key)
        if isinstance(value, str) and value:
            return value
    command = inp.get("command")
    if isinstance(command, str) and command:
        return _truncate(command, 80)
    for key in ("pattern", "query", "url"):
        value = inp.get(key)
        if isinstance(value, str) and value:
            return _truncate(value, 80)
    pairs = []
    for key, value in list(inp.items())[:2]:
        pairs.append(f"{key}={_truncate(str(value), 30)}")
    return ", ".join(pairs) if pairs else ""


def _truncate(text: str, limit: int = _MAX_PREVIEW) -> str:
    text = text.replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"
