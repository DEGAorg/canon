"""Controller sockets must be private to the current OS user."""

import asyncio
import json
import stat
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from toad import socket_controller as controller


@pytest.mark.asyncio
async def test_private_socket_accepts_commands(monkeypatch):
    directory = Path(tempfile.mkdtemp(prefix="ctl-", dir="/tmp"))
    directory.chmod(0o755)
    monkeypatch.setattr(controller, "SOCKET_DIR", directory)
    app = SimpleNamespace(log=Mock())
    server = await controller.start_socket_server(app)
    try:
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700
        assert stat.S_IMODE(controller._socket_path().stat().st_mode) == 0o600
        reader, writer = await asyncio.open_unix_connection(controller._socket_path())
        writer.write(b'{"cmd":"ping"}\n')
        await writer.drain()
        assert json.loads(await reader.readline())["ok"] is True
        writer.close()
        await writer.wait_closed()
    finally:
        await controller.stop_socket_server(server)
    assert not controller._socket_path().exists()
    directory.rmdir()


@pytest.mark.asyncio
@pytest.mark.parametrize("symlink", [False, True])
async def test_refuses_non_socket_path(tmp_path, monkeypatch, symlink):
    monkeypatch.setattr(controller, "SOCKET_DIR", tmp_path)
    target = tmp_path / "keep"
    target.write_text("preserve")
    path = controller._socket_path()
    if symlink:
        path.symlink_to(target)
    else:
        path.write_text("preserve")
    with pytest.raises(PermissionError):
        await controller.start_socket_server(SimpleNamespace(log=Mock()))
    assert target.read_text() == "preserve"
    assert path.read_text() == "preserve"


@pytest.mark.asyncio
async def test_refuses_symlink_directory(tmp_path, monkeypatch):
    directory = tmp_path / "sockets"
    directory.symlink_to(tmp_path, target_is_directory=True)
    monkeypatch.setattr(controller, "SOCKET_DIR", directory)
    with pytest.raises(PermissionError):
        await controller.start_socket_server(SimpleNamespace(log=Mock()))
