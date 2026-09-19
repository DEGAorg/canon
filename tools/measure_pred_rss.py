"""Bounded, safe measurement of prediction-edge peak RSS.

Spawns `npm run start` in the strategy dir under a per-process virtual-mem cap
(ulimit -v) and a wall-clock timeout so it cannot OOM the host nor run forever.
Sums RSS across the spawned process group and prints the peak.

Run: uv run python tools/measure_pred_rss.py
"""
from __future__ import annotations

import os
import re
import signal
import subprocess
import time
from pathlib import Path

STRAT = Path.home() / ".canon/strategies/prediction-edge"
VIRT_CAP_MB = 3000
WALL_TIMEOUT = 45.0


def rss_of(pid: int) -> int:
    try:
        st = Path(f"/proc/{pid}/status").read_text()
    except OSError:
        return 0
    m = re.search(r"^VmRSS:\s+(\d+)", st, re.M)
    return int(m.group(1)) if m else 0


def group_rss(pgid: int) -> int:
    total = 0
    for tgt in Path("/proc").iterdir():
        if not tgt.name.isdigit():
            continue
        try:
            st = (tgt / "stat").read_text()
        except OSError:
            continue
        rp = st.rfind(")")
        fields = st[rp + 2:].split()
        if len(fields) >= 2 and fields[1].isdigit() and int(fields[1]) == pgid:
            total += rss_of(int(tgt.name))
    return total


def main() -> None:
    if not (STRAT / "node_modules").exists():
        print("node_modules missing — cannot measure, skipping")
        return
    shell = f"ulimit -v $(( {VIRT_CAP_MB} * 1024 )); exec npm run start"
    p = subprocess.Popen(
        ["/bin/bash", "-c", shell], cwd=str(STRAT),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    pgid = os.getpgid(p.pid)
    peak = 0
    t0 = time.monotonic()
    reason = ""
    try:
        while True:
            if p.poll() is not None:
                reason = f"exited code={p.returncode}"
                break
            if time.monotonic() - t0 > WALL_TIMEOUT:
                os.killpg(pgid, signal.SIGKILL)
                p.wait()
                reason = f"wall timeout {WALL_TIMEOUT}s"
                break
            peak = max(peak, group_rss(pgid))
            time.sleep(0.2)
    except KeyboardInterrupt:
        os.killpg(pgid, signal.SIGKILL)
        p.wait()
        reason = "interrupted"
    print(f"RESULT peak_group_rss={peak/1024:.0f} MB  end={reason}")


if __name__ == "__main__":
    main()