"""Public distribution metadata and update destination."""
from unittest.mock import Mock

from click.testing import CliRunner

from toad import get_version
from toad.cli import update


def test_version_uses_installed_distribution(monkeypatch):
    lookup = Mock(return_value="0.7.25")
    monkeypatch.setattr("importlib.metadata.version", lookup)
    assert get_version() == "0.7.25"
    lookup.assert_called_once_with("canon-app")


def test_update_installs_public_repository(monkeypatch):
    import subprocess

    run = Mock()
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/uv")
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr("toad.cli._read_installed_version", lambda: "0.7.25")
    result = CliRunner().invoke(update, [])
    assert result.exit_code == 0, result.output
    run.assert_called_once_with(
        ["uv", "tool", "install", "canon-app @ git+https://github.com/DEGAorg/canon.git@main",
         "--force", "--reinstall"],
        check=True,
    )
