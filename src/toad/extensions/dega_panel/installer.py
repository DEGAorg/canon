"""Install / uninstall strategy workflows locally.

Workflows ship as ``.tar.gz`` archives delivered by the authenticated DEGA
agents backend (gated by the user's element holdings). The archive is
extracted into ~/.canon/strategies/<key>, then the caller runs the security
scan on the extracted tree before anything runs. Installation is the only
network moment besides login. A local directory source remains for dev /
headless harness (no network). Extraction rejects path traversal and symlinks.
"""

from __future__ import annotations

import re
import shutil
import tarfile
from pathlib import Path
from typing import Awaitable, Callable

from toad.extensions.dega_panel.install_store import (
    mark_installed,
    mark_uninstalled,
    strategies_dir,
)


class InstallError(Exception):
    """Raised when an archive operation fails."""


# A safe strategy key: letters, digits, dash, underscore. No path separators or
# '..', so `strategies_dir() / key` can never escape ~/.canon/strategies.
_SAFE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")

# (GitHub-archive branch list and _repo_to_archive were removed: strategy tars
# are delivered via the backend, never downloaded from a public repo URL.)


def _safe_dest(key: str) -> Path:
    """Resolve the install dir for ``key``, rejecting anything path-unsafe."""
    if not key or not _SAFE_KEY.match(key):
        raise InstallError(f"unsafe strategy key: {key!r}")
    base = strategies_dir().resolve()
    dest = (base / key).resolve()
    # Defense in depth: the resolved path must stay inside the strategies dir.
    if dest.parent != base:
        raise InstallError(f"strategy key escapes the strategies dir: {key!r}")
    return dest


def _is_valid_strategy(dest: Path) -> bool:
    """A download is valid if it holds a runnable or manifest-carrying tree."""
    if not dest.is_dir():
        return False
    return (dest / "package.json").exists() or bool(list(dest.glob("*.config.json")))


def _safe_member(dest: Path, member: tarfile.TarInfo) -> bool:
    """Reject path traversal / absolute paths / symlinks / hardlinks in the tar."""
    if member.islnk() or member.issym():
        return False
    name = member.name
    # resolve() catches '..' escapes and the parent check is a second net.
    if name.startswith("/") or ".." in Path(name).parts:
        return False
    resolved = (dest / name).resolve()
    return resolved.is_relative_to(dest.resolve())


def _extract(dest_tar: Path, dest: Path) -> None:
    """Extract a downloaded tarball safely (no traversal, no symlinks)."""
    with tarfile.open(dest_tar, "r:gz") as tf:
        # Validation pass first, then a filtered extract.
        members = tf.getmembers()
        if not members:
            raise InstallError("archive is empty")
        top = members[0].name.split("/", 1)[0]  # GitHub wraps in one top dir
        for member in members:
            if not _safe_member(dest, member):
                raise InstallError(
                    f"unsafe archive member: {member.name!r} (traversal/symlink blocked)"
                )
        tf.extractall(dest, members=members, filter="data")
    # Move the single wrapped top-level directory out (owner-name-hash).
    inner = dest / top
    if (dest / top).is_dir() and list(dest.iterdir()) == [inner]:
        for child in inner.iterdir():
            shutil.move(str(child), str(dest / child.name))
        shutil.rmtree(inner, ignore_errors=True)


async def install_strategy(
    key: str, repo: str, *, on_status: Callable[[str], None] | None = None,
    fetcher: Callable[[Path], Awaitable[None]] | None = None,
) -> Path:
    """Install ``key`` into ~/.canon/strategies/<key> and mark it installed.

    The strategy tars live in the backend repo (delivered via the authenticated
    agents backend, gated by the user's holdings). This function supports
    exactly two sources:

    - **backend delivery** (``fetcher`` given): the fetcher writes the archive
      bytes to a temp path (used when the panel is signed in). Extraction and
      the security scan are identical whether bytes come from the backend or a
      local dir.
    - **local directory** (dev/testing / headless harness): the tree is copied
      verbatim with no network.

    There is intentionally NO public GitHub/codeload fallback: strategy archives
    are no longer downloaded from a repository URL.
    """
    dest = _safe_dest(key)
    if dest.exists() and _is_valid_strategy(dest):
        mark_installed(key)
        if on_status:
            on_status("already installed")
        return dest
    if dest.exists():  # partial/corrupt prior attempt -> clean slate
        shutil.rmtree(dest, ignore_errors=True)

    local_dir = Path(repo) if (isinstance(repo, str) and Path(repo).is_dir()) else None
    if local_dir is not None:
        if on_status:
            on_status("copying local source…")
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copytree(local_dir, dest, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".git"))
        if not _is_valid_strategy(dest):
            raise InstallError(f"local source {repo!r} did not produce a valid workflow")
        mark_installed(key)
        if on_status:
            on_status("installed")
        return dest

    if fetcher is None:
        raise InstallError(
            "strategy delivery requires a session — sign in to download it via "
            "the backend (no public repository)"
        )

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_tar = dest.with_suffix(".tar.gz.tmp")

    # Authenticated backend delivery: the fetcher writes the archive bytes to
    # tmp_tar. A denial raises (the backend's verdict is authoritative) so the
    # caller surfaces it and does not fall back to a public URL.
    if on_status:
        on_status("downloading via DEGA backend…")
    try:
        await fetcher(tmp_tar)
    except Exception:
        if tmp_tar.exists():
            tmp_tar.unlink(missing_ok=True)
        raise
    try:
        dest.mkdir(parents=True, exist_ok=True)
        _extract(tmp_tar, dest)
        tmp_tar.unlink(missing_ok=True)
    except Exception:
        if tmp_tar.exists():
            tmp_tar.unlink(missing_ok=True)
        raise
    if not _is_valid_strategy(dest):
        raise InstallError("backend download did not produce a valid workflow")
    mark_installed(key)
    if on_status:
        on_status("installed")
    return dest


async def uninstall_strategy(key: str, *, on_status: Callable[[str], None] | None = None) -> None:
    """Remove the local install and the installed marker."""
    dest = _safe_dest(key)
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    mark_uninstalled(key)
    if on_status:
        on_status("uninstalled")