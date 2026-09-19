"""Detect how an installed strategy runs, and launch it (dry-run by default).

Each strategy workflow ships a manifest (`*.config.json` with a `pipeline`,
`entry`, and — via package.json — runnable scripts). Canon reads that manifest to
know how to launch the strategy, then runs it as a subprocess in the strategy's
own directory. Live/real-money modes are never triggered automatically: only an
explicit, separately-confirmed flag does that.

There are two entry points:

- ``run_strategy`` — a simple **blocking** helper (used by the harness and by
  callers that want the exit code when the process finishes). It is not
  suitable for long-lived bots on its own.
- ``StrategyRunner`` — a **managed** runner for persistent strategy bots: it
  spawns the process, streams output to ``~/.canon/execution/<key>.log``
  (rotated) **and** to a callback, tracks ``state``/``pid``, and can be stopped.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import resource
import signal
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from toad.extensions.dega_panel.auth_store import CANON_DIR
from toad.extensions.dega_panel.installer import _safe_dest

# Cap for the stdout line buffer: a stream that never emits a newline must not
# grow the pending buffer without bound before EOF.
_MAX_PENDING_CHARS = 16_384


def _default_mem_limit_mb() -> int:
    """Virtual-memory cap for a strategy child (MB). Env override applies."""
    v = os.environ.get("DEGA_STRAT_MEM_MB", "").strip()
    if v:
        try:
            return int(v)
        except ValueError:
            pass
    return 6 * 1024


class RunError(Exception):
    """Raised when a strategy cannot be detected or launched."""


@dataclass
class StrategyManifest:
    """What we learn from an installed strategy's config + package.json."""

    key: str
    path: Path
    name: str = ""
    description: str = ""
    strategy: str = ""
    pipeline: list[str] = field(default_factory=list)
    scripts: dict[str, str] = field(default_factory=dict)
    runnable: bool = False
    run_hint: str = ""
    build_command: str = ""
    dry_run_command: str = ""
    live_command: str = ""

    @property
    def run_command(self) -> str:
        """The strategy's execution entrypoint.

        Never a build/checker script: only the scripts that actually execute the
        strategy count, so a package that ships just `build` or `typecheck` is
        not treated as runnable.
        """
        return self.dry_run_command or self.live_command


def _find_config(path: Path) -> dict | None:
    """Return the first top-level *.config.json parsed, or None."""
    for cfg in sorted(path.glob("*.config.json")):
        try:
            return json.loads(cfg.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
    return None


def detect_manifest(key: str) -> StrategyManifest:
    """Read the installed strategy's manifest so the UI knows how to run it."""
    path = _safe_dest(key)
    if not path.exists():
        raise RunError(f"strategy {key!r} is not installed")

    manifest = StrategyManifest(key=key, path=path)

    cfg = _find_config(path)
    if cfg:
        manifest.name = cfg.get("name", key)
        manifest.description = cfg.get("description", "")
        manifest.strategy = cfg.get("strategy", "")
        manifest.pipeline = list(cfg.get("pipeline", []) or [])

    pkg_file = path / "package.json"
    if pkg_file.exists():
        try:
            pkg = json.loads(pkg_file.read_text(encoding="utf-8"))
            manifest.scripts = pkg.get("scripts", {}) or {}
            if not manifest.name:
                manifest.name = pkg.get("name", key)
        except (ValueError, OSError):
            pass

    def _pick_command(*candidates: str) -> str:
        for candidate in candidates:
            if candidate in manifest.scripts:
                return candidate
        return ""

    # Explicit command selection (F4): `build`/`compile` is only ever a PRE-step
    # and never the strategy entrypoint. `serve`/`server`/`dev` are the accepted
    # stand-ins when a package ships no start/scan (e.g. the dashboard builds).
    manifest.build_command = _pick_command("build", "compile")
    manifest.dry_run_command = _pick_command(
        "dry-run", "start:dry-run", "start:dry", "scan", "start", "serve", "server", "dev"
    )
    manifest.live_command = (
        _pick_command("live", "start:live", "start") or manifest.dry_run_command
    )

    if manifest.run_command:
        manifest.runnable = True
        manifest.run_hint = f"npm run {manifest.run_command}"
    elif manifest.scripts:
        # Scripts exist but none executes the strategy (only checkers). Say so
        # instead of marking it runnable and "running" a checker.
        manifest.runnable = False
        manifest.run_hint = (
            "no runnable script in package.json "
            f"(found: {', '.join(sorted(manifest.scripts))})"
        )
    else:
        manifest.runnable = False
        manifest.run_hint = "no runnable script found in package.json"

    return manifest


def _build_command(manifest: StrategyManifest, chosen: str, live_confirm: bool) -> list[str]:
    """Run dedicated live scripts as declared; pass --live to generic scripts."""
    cmd = ["npm", "run", chosen]
    if live_confirm and chosen not in ("live", "start:live"):
        cmd += ["--", "--live"]
    return cmd


def _needs_build_output(manifest: StrategyManifest, chosen: str) -> bool:
    """True when the run command points at a compiled artifact.

    Strategies whose `start` runs the TypeScript sources directly through a
    runner (`tsx src/index.ts`, `ts-node src/index.ts`) work even if the build
    step fails, so a build failure must not block them. Only commands that
    reference a build output directory depend on it.
    """
    body = str(manifest.scripts.get(chosen, ""))
    return bool(re.search(r"(^|[\s\"'])(dist|build|out)/", body))


# ---------------------------------------------------------------------------
# Managed (persistent) runner
# ---------------------------------------------------------------------------

def _log_path(key: str) -> Path:
    """Where strategy logs live: ~/.canon/execution/<key>.log (rotated)."""
    d = CANON_DIR / "execution"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{key}.log"


def _setsid() -> None:
    """Preexec: detach the child into its own session/process-group so we can
    signal the WHOLE tree (target + its node/npm grandchildren), not just the
    direct child. Without this, killing `npm` orphans the `node` it spawned,
    which keeps the stdout pipe open and hangs the drain loop."""
    try:
        os.setsid()
    except OSError:
        pass


def kill_tree(pid: int, sig: int) -> None:
    """Send ``sig`` to the process group led by ``pid`` (the child ran setsid,
    so pgid == child pid). Falls back to signalling the single pid."""
    try:
        os.killpg(pid, sig)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            pass


def _rotate(log: Path, max_bytes: int = 2 * 1024 * 1024, keep: int = 3) -> None:
    """Rotate a log file when it exceeds ``max_bytes``, keeping ``keep`` old."""
    if not log.exists() or log.stat().st_size < max_bytes:
        return
    try:
        for i in range(keep, 0, -1):  # shift .1 -> .2, .2 -> .3 ...
            # keep-1 is the highest kept suffix we shift into
            dst = log.with_suffix(f".log.{i}")
            src = log.with_suffix(f".log.{i-1}") if i > 1 else log
            if src.exists():
                if dst.exists():
                    dst.unlink()
                src.rename(dst)
        # after rotation, rewrite the primary
        tmp = log.with_suffix(".log.tmp")
        tmp.write_text("", encoding="utf-8")
        tmp.replace(log)
    except OSError:
        pass


class StrategyRunner:
    """Tracks and manages one long-lived strategy subprocess.

    ``on_line`` receives each stdout line (after being appended to the log).
    ``state`` is one of: "idle", "installing", "running", "exited", "stopped",
    "error". ``exit_code``/``error`` describe how it ended.
    """

    def __init__(
        self,
        key: str,
        *,
        on_line: Callable[[str], None] | None = None,
        log_dir: Path | None = None,
        run_timeout: float | None = None,
        mem_limit_mb: int | None = None,
        cpu_limit_sec: float | None = None,
    ) -> None:
        self.key = key
        self.on_line = on_line
        # ``log_dir`` is a DIRECTORY; the log file is <log_dir>/<key>.log (same
        # shape as the default ~/.canon/execution/<key>.log).
        base = Path(log_dir) if log_dir is not None else Path(_log_path(key)).parent
        self.log = base / f"{key}.log"
        self.state = "idle"
        self.pid: int | None = None
        self.exit_code: int | None = None
        self.error: str | None = None
        self.started_at: float | None = None
        self.stopped_at: float | None = None
        self._proc: asyncio.subprocess.Process | None = None
        # Hardening knobs: bound a strategy subprocess so a runaway cannot starve
        # (OOM-thrash) or hang the host/UI. run_timeout is a wall-clock opt-in
        # (None = no limit, since long-lived bots run indefinitely by design);
        # mem_limit_mb bounds child virtual memory so an over-allocating strategy
        # dies on its OWN limit instead of triggering the global OOM killer (which
        # can pick the TUI as a victim and freeze the box).
        self.run_timeout: float | None = run_timeout
        self._mem_limit_mb: int | None = (
            mem_limit_mb if mem_limit_mb is not None else _default_mem_limit_mb()
        )
        self._cpu_limit_sec: float | None = cpu_limit_sec
        self._stop_reason: str | None = None
        self._watchdog: asyncio.Task | None = None

    # --- resource limits ----------------------------------------------------

    def _preexec_limits(self) -> Callable[[], None] | None:
        """Build a preexec_fn that applies rlimits to the child, or None if the
        platform forbids it. Any single failure is swallowed so a limit that the
        kernel rejects never blocks the strategy from launching."""

        def _mb(limit_mb: int) -> int:
            return limit_mb * 1024 * 1024

        def _apply() -> None:
            _setsid()  # own session/process-group so we can killpg the whole tree
            try:
                resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
            except (ValueError, OSError):
                pass
            if self._mem_limit_mb is not None:
                try:
                    lim: int = _mb(self._mem_limit_mb)
                    resource.setrlimit(resource.RLIMIT_AS, (lim, lim))
                except (ValueError, OSError):
                    pass
            if self._cpu_limit_sec is not None:
                try:
                    cpu: int = max(1, int(self._cpu_limit_sec))
                    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
                except (ValueError, OSError):
                    pass

        return _apply

    async def _timeout_watch(self, seconds: float) -> None:
        """Wall-clock watchdog: kill the strategy if it outlives ``seconds``."""
        await asyncio.sleep(seconds)
        proc = self._proc
        if (
            proc is None
            or proc.returncode is not None
            or self.state != "running"
        ):
            return  # already finished / stopped
        await self.stop(reason=f"timed out after {seconds:.0f}s")

    # --- lifecycle ---------------------------------------------------------
    async def start(
        self,
        *,
        script: str | None = None,
        live: bool = False,
        confirmed: bool = False,
        live_confirm: bool = False,
    ) -> "StrategyRunner":
        """Launch the strategy, returning immediately (does not block)."""
        if not confirmed:
            raise RunError(
                "refusing to run a third-party strategy without explicit confirmation"
            )
        if live and not live_confirm:
            raise RunError("live mode requires explicit live_confirm; it is never on by default")

        from toad.extensions.dega_panel.access_grants import ensure_access

        await ensure_access(self.key)
        manifest = detect_manifest(self.key)
        if not manifest.runnable:
            raise RunError(f"{self.key!r} has no runnable script: {manifest.run_hint}")

        if not (manifest.path / "node_modules").exists() and (manifest.path / "package.json").exists():
            self.state = "installing"
            self._log("installing dependencies (npm install --ignore-scripts)…")
            code = await _run_generic(
                ["npm", "install", "--ignore-scripts"], manifest.path, self._log, timeout=300
            )
            if code != 0:
                self.state = "error"
                self.error = f"npm install failed (exit {code})"
                return self

        if script:
            chosen = script
        elif live_confirm and manifest.live_command:
            chosen = manifest.live_command
        else:
            chosen = manifest.run_command
        if not chosen:
            self.state = "error"
            self.error = f"{self.key!r} has no runnable script: {manifest.run_hint}"
            return self
        if chosen not in manifest.scripts:
            self.state = "error"
            self.error = f"script {chosen!r} not in package.json scripts"
            return self

        # Some packages ship TypeScript and fail at start without a compiled
        # entrypoint (e.g. a missing dist/index.js). Run the build step first
        # when the package declares one and it is not the command we are about
        # to run.
        if manifest.build_command and manifest.build_command != chosen:
            self.state = "building"
            self._log(f"building first: npm run {manifest.build_command}")
            code = await _run_generic(
                ["npm", "run", manifest.build_command], manifest.path, self._log, timeout=600
            )
            if code != 0:
                if _needs_build_output(manifest, chosen):
                    self.state = "error"
                    self.error = f"build failed (exit {code})"
                    return self
                self._log(
                    f"build failed (exit {code}); continuing — {chosen} runs the sources directly"
                )

        cmd = _build_command(manifest, chosen, live_confirm)
        if live_confirm:
            self._log("LIVE mode — real funds / real orders will be used")
        self._log(f"$ {' '.join(cmd)}  (cwd={manifest.path.name})")

        await ensure_access(self.key)
        self.state = "running"
        self.started_at = time.time()
        preexec_fn = self._preexec_limits()
        self._proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(manifest.path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            preexec_fn=preexec_fn,
        )
        self.pid = self._proc.pid
        # Drain in the background so `start` returns immediately.
        asyncio.create_task(self._drain())
        if self.run_timeout is not None:
            self._watchdog = asyncio.create_task(
                self._timeout_watch(self.run_timeout)
            )
        return self

    async def _drain(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            # Read in bounded chunks (read(n)) so a line longer than the
            # stream's internal limit (~64KB) can never raise, and flush the
            # buffer once it grows past the cap so a stream that never emits a
            # newline cannot accumulate unbounded memory.
            pending = ""
            eof = False
            while not eof:
                raw = await proc.stdout.read(16_384)
                if not raw:
                    eof = True
                else:
                    pending += raw.decode(errors="replace")
                *lines, pending = pending.split("\n")
                for line in lines:
                    self._emit_bounded(line)
                if len(pending) >= _MAX_PENDING_CHARS:
                    self._emit_bounded(pending)
                    pending = ""
                if eof and pending:
                    self._emit_bounded(pending)
            self.exit_code = await proc.wait()
        except asyncio.CancelledError:
            self.state = "stopped"
            raise
        finally:
            self.stopped_at = time.time()
            if self.state != "stopped":
                self._report_exit()

    def _emit_bounded(self, text: str) -> None:
        text = text.rstrip("\r")
        for start in range(0, len(text), 16_384):
            self._log(text[start : start + 16_384])

    def _report_exit(self) -> None:
        """Set the final state/error and surface the exit reason on the feed."""
        if self._watchdog is not None and not self._watchdog.done():
            self._watchdog.cancel()
        if self.state == "running":
            self.state = "exited"
        if self._stop_reason:
            self.error = self._stop_reason
            line = f"process {self._stop_reason}"
        else:
            rc = self.exit_code
            if rc is None:
                line = "process exited (no exit code)"
            elif rc < 0:
                self.error = f"killed by signal {-rc} (likely OOM — too much memory)"
                line = f"process killed by signal {-rc} (likely OOM)"
            elif rc == 0:
                line = "process exited cleanly"
            else:
                self.error = f"exited with code {rc}"
                line = f"process exited with code {rc}"
        if self.on_line:
            self.on_line(line)

    async def stop(self, *, reason: str = "stopped") -> None:
        """Stop the running strategy (SIGTERM, then SIGKILL after a grace).

        A caller-provided ``reason`` (e.g. \".timed out.\") is recorded and surfaced
        when the process actually exits.
        """
        self._stop_reason = reason
        self.state = "stopped"
        self.stopped_at = time.time()
        proc = self._proc
        if proc is None or proc.returncode is not None:
            return
        try:
            kill_tree(proc.pid, signal.SIGTERM)
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            kill_tree(proc.pid, signal.SIGKILL)
            await proc.wait()

    @property
    def running(self) -> bool:
        return self.state == "running"

    @property
    def elapsed(self) -> float | None:
        if self.started_at is None:
            return None
        end = self.stopped_at or time.time()
        return end - self.started_at

    def _log(self, line: str) -> None:
        _rotate(self.log)
        self.log.parent.mkdir(parents=True, exist_ok=True)
        with self.log.open("a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {line}\n")
        if self.on_line:
            self.on_line(line)


# ---------------------------------------------------------------------------
# Blocking helper (harness / one-shot)
# ---------------------------------------------------------------------------

async def _run_generic(
    cmd: list[str],
    cwd: Path,
    on_line: Callable[[str], None] | None,
    *,
    timeout: float | None = None,
) -> int:
    """Run a subprocess, streaming stdout, with an optional hard timeout."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        preexec_fn=_setsid,
    )
    assert proc.stdout is not None
    stdout = proc.stdout

    async def _drain() -> int:
        # Bounded reads: a single line larger than the stream's internal
        # limit can never raise here.
        pending = ""
        eof = False
        while not eof:
            raw = await stdout.read(16_384)
            if not raw:
                eof = True
            else:
                pending += raw.decode(errors="replace")
            *lines, pending = pending.split("\n")
            for line in lines:
                if on_line:
                    on_line(line.rstrip("\r"))
            if len(pending) >= _MAX_PENDING_CHARS:
                if on_line:
                    on_line(pending.rstrip("\r"))
                pending = ""
            if eof and pending and on_line:
                on_line(pending.rstrip("\r"))
        return await proc.wait()

    if timeout is None:
        return await _drain()
    try:
        return await asyncio.wait_for(_drain(), timeout=timeout)
    except asyncio.TimeoutError:
        kill_tree(proc.pid, signal.SIGKILL)
        await proc.wait()
        raise RunError(f"command timed out after {timeout}s: {' '.join(cmd)}")


async def ensure_deps(
    manifest: StrategyManifest, *, on_line: Callable[[str], None] | None = None
) -> None:
    """Install node deps if package.json exists and node_modules is missing."""
    if not (manifest.path / "package.json").exists():
        return
    if (manifest.path / "node_modules").exists():
        return
    if on_line:
        on_line("installing dependencies (npm install --ignore-scripts)…")
    code = await _run_generic(
        ["npm", "install", "--ignore-scripts"], manifest.path, on_line, timeout=300
    )
    if code != 0:
        raise RunError(f"npm install failed (exit {code})")


async def run_strategy(
    key: str,
    *,
    script: str | None = None,
    live: bool = False,
    confirmed: bool = False,
    live_confirm: bool = False,
    on_line: Callable[[str], None] | None = None,
) -> int:
    """Blocking convenience wrapper: run to completion and return the exit code.

    Retained for the headless harness and one-shot callers. For long-lived bots
    prefer ``StrategyRunner`` (non-blocking, stop-able, rotated logging).
    """
    if not confirmed:
        raise RunError(
            "refusing to run a third-party strategy without explicit confirmation"
        )
    if live and not live_confirm:
        raise RunError("live mode requires explicit live_confirm; it is never on by default")

    from toad.extensions.dega_panel.access_grants import ensure_access

    await ensure_access(key)
    manifest = detect_manifest(key)
    if not manifest.runnable:
        raise RunError(f"{key!r} has no runnable script: {manifest.run_hint}")

    await ensure_deps(manifest, on_line=on_line)

    if script:
        chosen = script
    elif live_confirm and manifest.live_command:
        chosen = manifest.live_command
    else:
        chosen = manifest.run_command
    if not chosen:
        raise RunError(f"{key!r} has no runnable script: {manifest.run_hint}")
    if chosen not in manifest.scripts:
        raise RunError(f"script {chosen!r} not in package.json scripts")

    # Compile first when the package declares a build step and we are about to
    # run something else (packages that ship TypeScript fail without dist/).
    if manifest.build_command and manifest.build_command != chosen:
        if on_line:
            on_line(f"building first: npm run {manifest.build_command}")
        code = await _run_generic(
            ["npm", "run", manifest.build_command], manifest.path, on_line, timeout=600
        )
        if code != 0:
            if _needs_build_output(manifest, chosen):
                raise RunError(f"build failed (exit {code})")
            if on_line:
                on_line(
                    f"build failed (exit {code}); continuing — {chosen} runs the sources directly"
                )

    cmd = _build_command(manifest, chosen, live_confirm)
    if live_confirm and on_line:
        on_line("LIVE mode — real funds / real orders will be used")
    if on_line:
        on_line(f"$ {' '.join(cmd)}  (cwd={manifest.path.name})")
    await ensure_access(key)
    return await _run_generic(cmd, manifest.path, on_line)