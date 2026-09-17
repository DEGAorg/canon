"""Focused async test for hardened StrategyRunner behaviour.

- normal completion -> on_line "exited cleanly", state exited, no error
- run_timeout -> on_line "timed out ...", strategy killed, error set

Run: uv run python tools/test_runner_hardening.py
"""
from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path

from toad.extensions.dega_panel.runner import StrategyRunner

SH = shutil.which("sh")


async def spawn(runner: StrategyRunner, cmd: str) -> asyncio.Task:
    sh: str = shutil.which("sh") or "/bin/sh"
    proc = await asyncio.create_subprocess_exec(
        sh, "-c", cmd, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT, preexec_fn=runner._preexec_limits()
    )
    runner._proc = proc
    runner.pid = proc.pid
    runner.state = "running"
    task = asyncio.create_task(runner._drain())
    return task


async def main() -> None:
    out = []

    # 1) normal short command completes cleanly
    lines: list[str] = []
    with tempfile.TemporaryDirectory() as d:
        r = StrategyRunner("_t", on_line=lines.append, log_dir=Path(d))
        await spawn(r, "printf ok; exit 0")
        for _ in range(40):
            if r.state != "running":
                break
            await asyncio.sleep(0.02)
        out.append(f"clean  state={r.state} rc={r.exit_code} err={r.error!r} lines={lines!r}")

    # 2) run_timeout kills a long sleep and reports the reason
    lines2: list[str] = []
    with tempfile.TemporaryDirectory() as d:
        r2 = StrategyRunner("_t", on_line=lines2.append, log_dir=Path(d),
                            run_timeout=0.4)
        drain = await spawn(r2, "sleep 30")
        r2._watchdog = asyncio.create_task(r2._timeout_watch(0.4))
        await asyncio.wait_for(drain, timeout=5)
        out.append(f"timeout state={r2.state} rc={r2.exit_code} err={r2.error!r} lines={lines2!r}")

    print("RESULTS")
    for line in out:
        print(line)


if __name__ == "__main__":
    asyncio.run(main())