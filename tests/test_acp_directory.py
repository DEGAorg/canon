"""ACP launches preserve the requested project directory without parser warnings."""
from unittest.mock import Mock
import warnings

import pytest
from click.testing import CliRunner

from toad.cli import acp


@pytest.mark.parametrize("mode", ["positional", "option", "both", "default"])
def test_acp_project_directory(tmp_path, monkeypatch, mode):
    app = Mock()
    monkeypatch.setattr("toad.cli.ToadApp", app)
    monkeypatch.chdir(tmp_path)
    chosen = tmp_path / "chosen"
    chosen.mkdir()
    args = ["agent-command"]
    if mode in ("positional", "both"):
        args.append("." if mode == "both" else str(chosen))
    if mode in ("option", "both"):
        args.extend(["--project-dir", str(chosen)])
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        result = CliRunner().invoke(acp, args)
    assert result.exit_code == 0, result.output
    assert app.call_args.kwargs["project_dir"] == ("." if mode == "default" else str(chosen))
    app.return_value.run.assert_called_once()


def test_acp_rejects_missing_directory(tmp_path, monkeypatch):
    app = Mock()
    monkeypatch.setattr("toad.cli.ToadApp", app)
    result = CliRunner().invoke(acp, ["agent-command", str(tmp_path / "missing")])
    assert result.exit_code != 0
    app.assert_not_called()
