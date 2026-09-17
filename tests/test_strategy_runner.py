from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from toad.extensions.dega_panel import runner as runner_mod
from toad.extensions.dega_panel.runner import StrategyRunner


class _FakeStream:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = list(chunks)

    async def read(self, n: int) -> bytes:
        await asyncio.sleep(0)
        if not self._chunks:
            return b""
        head = self._chunks.pop(0)
        return head[:n] if len(head) > n else head


class _FakeProc:
    def __init__(self, chunks: list[bytes]) -> None:
        self.stdout = _FakeStream(chunks)
        self.returncode = None
        self.pid = 4321

    async def wait(self) -> int:
        self.returncode = 0
        return 0


def _chunks_oversized() -> list[bytes]:
    """200KB single line (3x the stream's internal limit) then a normal line."""
    return [b"a" * 200_000 + b"\n", b"done\n"]


@pytest.mark.asyncio
async def test_strategy_runner_drains_oversized_stdout_and_finishes(
    tmp_path: Path,
) -> None:
    runner = StrategyRunner("demo", log_dir=tmp_path)
    runner._proc = _FakeProc(_chunks_oversized())  # type: ignore[assignment]
    runner.state = "running"

    await runner._drain()

    assert runner.state == "exited"
    assert runner.exit_code == 0
    assert runner.stopped_at is not None
    assert runner.log.exists()
    text = runner.log.read_text(encoding="utf-8")
    assert "done" in text
    # The oversized line was drained completely (200k a's across bounded emits).
    assert "a" * 1000 in text


@pytest.mark.asyncio
async def test_strategy_runner_emits_unterminated_tail(
    tmp_path: Path,
) -> None:
    runner = StrategyRunner("demo", log_dir=tmp_path)
    runner._proc = _FakeProc([b"no trailing newline"])  # type: ignore[assignment]
    runner.state = "running"

    await runner._drain()

    text = runner.log.read_text(encoding="utf-8")
    assert "no trailing newline" in text


@pytest.mark.asyncio
async def test_strategy_runner_flushes_buffer_without_newlines(
    tmp_path: Path,
) -> None:
    """A continuous stream with no newline must not accumulate until EOF."""
    runner = StrategyRunner("demo", log_dir=tmp_path)
    # 40 chunks of 4 KB with no newline: 160 KB total, well past the 16 KB cap.
    chunks = [b"x" * 4096 for _ in range(40)]
    lines: list[str] = []
    runner.on_line = lines.append
    runner._proc = _FakeProc(chunks + [b"\n"])  # type: ignore[assignment]
    runner.state = "running"

    await runner._drain()

    assert runner.state == "exited"
    payload = [ln for ln in lines if ln and set(ln) == {"x"}]
    # The buffer was flushed progressively, not once at EOF: several emits.
    assert len(payload) > 3, f"expected progressive flushes, got {len(payload)}"
    assert sum(len(ln) for ln in payload) == 40 * 4096


@pytest.mark.asyncio
async def test_run_generic_drain_flushes_without_newlines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_run_generic has its own drain: same bounded reads and progressive flush."""
    chunks = [b"y" * 4096 for _ in range(40)] + [b"\n"]
    proc = _FakeProc(chunks)

    async def fake_exec(*_args, **_kwargs):
        return proc

    monkeypatch.setattr(runner_mod.asyncio, "create_subprocess_exec", fake_exec)

    lines: list[str] = []
    code = await runner_mod._run_generic(["echo"], tmp_path, lines.append)

    assert code == 0
    payload = [ln for ln in lines if ln and set(ln) == {"y"}]
    assert len(payload) > 3, f"expected progressive flushes, got {len(payload)}"
    assert sum(len(ln) for ln in payload) == 40 * 4096
