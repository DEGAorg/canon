"""Install Canon's packaged Cardano companion without touching wallet state."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import logging
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Iterator

_LOG = logging.getLogger(__name__)
_MANIFESTS = ("package.json", "package-lock.json", "tsconfig.json")
_MARKER = ".canon-source-sha256"


class InstallError(RuntimeError):
    """An actionable companion installation failure."""


def packaged_source() -> Path:
    """Find the bundled client sources or a source checkout's client directory."""
    package = Path(__file__).parent / "extensions" / "dega_panel" / "cardano_client"
    if package.is_dir():
        return package
    checkout = Path(__file__).resolve().parents[2] / "cardano" / "client"
    if checkout.is_dir():
        return checkout
    raise InstallError("Cardano sources are missing; reinstall the complete canon-app package.")


def _run(
    command: list[str], *, cwd: Path, input_text: str | None = None
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            input=input_text,
            text=True,
            capture_output=True,
            timeout=600,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise InstallError(
            f"Could not run {command[0]}: {error}. Check Node.js/npm installation."
        ) from error


def _tools(source: Path) -> tuple[str, str, str]:
    node, npm = shutil.which("node"), shutil.which("npm")
    if node is None or npm is None:
        raise InstallError(
            "Install Node.js >=26 with npm, then run python -m toad.cardano_install."
        )
    result = _run([node, "--version"], cwd=source)
    version = result.stdout.strip()
    match = re.fullmatch(r"v(\d+)\.\d+\.\d+", version)
    if result.returncode or match is None or int(match.group(1)) < 26:
        raise InstallError("Node.js >=26 is required; update Node.js and rerun the installer.")
    return node, npm, version


def _source_files(source: Path) -> list[Path]:
    manifests = [source / name for name in _MANIFESTS]
    sources = sorted((source / "src").rglob("*.ts"))
    if not sources or any(not path.is_file() for path in manifests):
        raise InstallError(
            "Incomplete Cardano sources; package.json, lockfile, tsconfig and src are required."
        )
    paths = manifests + sources
    if any(
        path.is_symlink() or not path.resolve().is_relative_to(source.resolve()) for path in paths
    ):
        raise InstallError(
            "Cardano package sources must be regular files within the source directory."
        )
    return paths


def _fingerprint(source: Path, files: list[Path], node_version: str) -> str:
    digest = hashlib.sha256(node_version.encode())
    for path in files:
        digest.update(str(path.relative_to(source)).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _verify(node: str, runtime: Path) -> None:
    cli = runtime / "dist" / "cli.js"
    if not cli.is_file():
        raise InstallError("Cardano build did not produce dist/cli.js; reinstall the companion.")
    result = _run([node, str(cli)], cwd=runtime, input_text="{}\n")
    try:
        response = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise InstallError(
            "Cardano CLI verification returned invalid JSON; rebuild the companion."
        ) from error
    if (
        result.returncode != 1
        or not isinstance(response, dict)
        or response.get("ok") is not False
        or not isinstance(response.get("error"), dict)
        or response["error"].get("code") != "INVALID_REQUEST"
    ):
        raise InstallError("Cardano CLI failed its offline protocol check; rebuild the companion.")


@contextmanager
def _installation_lock(parent: Path) -> Iterator[None]:
    with (parent / ".runtime-install.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _publish(staged: Path, runtime: Path) -> None:
    backup = staged.parent / "previous-runtime"
    if runtime.exists():
        runtime.rename(backup)
    try:
        staged.rename(runtime)
    except OSError:
        if backup.exists():
            try:
                backup.rename(runtime)
            except OSError as error:
                raise InstallError(
                    f"Runtime replacement failed; restore the previous runtime from {backup}."
                ) from error
        raise


def _build(source: Path, files: list[Path], stage: Path, tools: tuple[str, str, str]) -> None:
    node, npm, _ = tools
    stage.mkdir()
    for path in files:
        target = stage / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    commands = [
        [npm, "ci", "--include=dev", "--ignore-scripts", "--no-audit", "--no-fund"],
        [npm, "run", "build"],
    ]
    for command in commands:
        result = _run(command, cwd=stage)
        if result.returncode:
            operation = "dependency installation" if command[1] == "ci" else "TypeScript build"
            raise InstallError(
                f"Cardano {operation} failed (exit {result.returncode}); "
                "check npm registry access, disk space and the pinned source package, then retry."
            )
    _verify(node, stage)


def install_runtime(*, source: Path | None = None, root: Path | None = None) -> Path:
    """Build and install the companion, preserving a working runtime on failure.

    Args:
        source: Packaged client sources; discovered automatically when omitted.
        root: Cardano data directory; defaults to ~/.canon/cardano.

    Returns:
        Absolute path to the installed CLI. Wallets and configuration are never read.

    Raises:
        InstallError: Missing tools, invalid sources, or failed build/protocol check.
    """
    source = (source or packaged_source()).resolve()
    files = _source_files(source)
    tools = _tools(source)
    fingerprint = _fingerprint(source, files, tools[2])
    parent = (root or Path.home() / ".canon" / "cardano").absolute()
    parent.mkdir(parents=True, exist_ok=True)
    runtime = parent / "runtime"
    with _installation_lock(parent):
        if runtime.is_symlink() or (runtime.exists() and not runtime.is_dir()):
            raise InstallError("Cardano runtime must be a directory, not a symlink or file.")
        marker = runtime / _MARKER
        if marker.is_file() and marker.read_text() == fingerprint:
            try:
                _verify(tools[0], runtime)
                return runtime / "dist" / "cli.js"
            except InstallError:
                _LOG.info("Rebuilding failed Cardano runtime", extra={"runtime": str(runtime)})
        temporary = Path(tempfile.mkdtemp(prefix=".runtime-stage-", dir=parent))
        published = False
        try:
            stage = temporary / "runtime"
            _build(source, files, stage, tools)
            (stage / _MARKER).write_text(fingerprint)
            _publish(stage, runtime)
            published = True
        finally:
            if published or not (temporary / "previous-runtime").exists():
                shutil.rmtree(temporary)
    return runtime / "dist" / "cli.js"


def main() -> None:
    """Install the companion explicitly for pip users or the Canon installer."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="Use a local companion source directory")
    parser.add_argument(
        "--root", type=Path, help="Cardano data directory (default ~/.canon/cardano)"
    )
    options = parser.parse_args()
    try:
        cli = install_runtime(source=options.source, root=options.root)
    except (InstallError, OSError) as error:
        parser.exit(1, f"Cardano companion installation failed: {error}\n")
    parser.exit(0, f"Cardano companion installed: {cli}\n")


if __name__ == "__main__":
    main()
