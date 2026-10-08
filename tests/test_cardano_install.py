"""Installation uses packaged sources and never modifies wallet/configuration files."""

from pathlib import Path
import subprocess
import tomllib
from unittest.mock import Mock
import zipfile

import pytest

from toad import cardano_install as installer


@pytest.fixture
def source(tmp_path: Path) -> Path:
    directory = tmp_path / "client"
    directory.mkdir()
    for name in ("package.json", "package-lock.json", "tsconfig.json"):
        (directory / name).write_text("{}")
    (directory / "src").mkdir()
    (directory / "src" / "cli.ts").write_text("export {};")
    (directory / ".env").write_text("not shipped")
    (directory / "test").mkdir()
    (directory / "test" / "wallet.json").write_text("private")
    return directory


@pytest.fixture
def processes(monkeypatch: pytest.MonkeyPatch) -> Mock:
    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        cwd = Path(str(kwargs["cwd"]))
        if command[-1] == "--version":
            return subprocess.CompletedProcess(command, 0, "v26.1.0\n", "")
        if command[1:] == ["run", "build"]:
            (cwd / "dist").mkdir()
            (cwd / "dist" / "cli.js").write_text("built")
        if command[-1].endswith("cli.js"):
            assert kwargs["input"] == "{}\n"
            return subprocess.CompletedProcess(
                command,
                1,
                '{"ok":false,"error":{"code":"INVALID_REQUEST"}}\n',
                "",
            )
        return subprocess.CompletedProcess(command, 0, "", "")

    mock = Mock(side_effect=run)
    monkeypatch.setattr(installer.subprocess, "run", mock)
    monkeypatch.setattr(installer.shutil, "which", lambda executable: f"/tools/{executable}")
    return mock


def test_installs_and_reuses_runtime_preserving_wallet(
    source: Path,
    tmp_path: Path,
    processes: Mock,
) -> None:
    root = tmp_path / "cardano"
    root.mkdir()
    (root / "config.json").write_text("configuration")
    (root / "wallet").mkdir()
    (root / "wallet" / "seed.json").write_text("wallet bytes")
    cli = installer.install_runtime(source=source, root=root)
    assert cli == root / "runtime" / "dist" / "cli.js"
    assert cli.read_text() == "built"
    assert not (root / "runtime" / ".env").exists()
    assert not (root / "runtime" / "test").exists()
    assert (root / "config.json").read_text() == "configuration"
    assert (root / "wallet" / "seed.json").read_text() == "wallet bytes"
    assert installer.install_runtime(source=source, root=root) == cli
    npm_calls = [
        call.args[0] for call in processes.call_args_list if call.args[0][0] == "/tools/npm"
    ]
    assert npm_calls == [
        ["/tools/npm", "ci", "--include=dev", "--ignore-scripts", "--no-audit", "--no-fund"],
        ["/tools/npm", "run", "build"],
    ]
    assert not list(root.glob(".runtime-stage-*"))


def test_source_change_rebuilds(source: Path, tmp_path: Path, processes: Mock) -> None:
    root = tmp_path / "cardano"
    installer.install_runtime(source=source, root=root)
    (source / "src" / "cli.ts").write_text("export const version = 2;")
    installer.install_runtime(source=source, root=root)
    assert (root / "runtime" / "src" / "cli.ts").read_text() == "export const version = 2;"
    assert sum(call.args[0][1] == "ci" for call in processes.call_args_list) == 2


@pytest.mark.parametrize("failure", ["ci", "build", "verify"])
def test_failure_preserves_working_runtime(
    source: Path,
    tmp_path: Path,
    processes: Mock,
    failure: str,
) -> None:
    root = tmp_path / "cardano"
    cli = installer.install_runtime(source=source, root=root)
    original = processes.side_effect
    (source / "src" / "cli.ts").write_text("changed source")

    def fail(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        failing = (
            failure == "ci"
            and command[1] == "ci"
            or failure == "build"
            and command[1:] == ["run", "build"]
            or failure == "verify"
            and command[-1].endswith("cli.js")
        )
        if failing:
            return subprocess.CompletedProcess(command, 2, "not JSON", "failure")
        return original(command, **kwargs)

    processes.side_effect = fail
    with pytest.raises(installer.InstallError):
        installer.install_runtime(source=source, root=root)
    assert cli.read_text() == "built"
    assert (root / "runtime" / "src" / "cli.ts").read_text() == "export {};"
    assert not list(root.glob(".runtime-stage-*"))


def test_missing_node_is_actionable(
    source: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(installer.shutil, "which", lambda _: None)
    with pytest.raises(installer.InstallError, match="Node.js >=26 with npm"):
        installer.install_runtime(source=source, root=tmp_path / "cardano")


@pytest.mark.parametrize("version", ["v25.9.0", "invalid"])
def test_old_or_invalid_node_rejected(
    source: Path,
    tmp_path: Path,
    processes: Mock,
    version: str,
) -> None:
    processes.side_effect = None
    processes.return_value = subprocess.CompletedProcess([], 0, version, "")
    with pytest.raises(installer.InstallError, match="Node.js >=26"):
        installer.install_runtime(source=source, root=tmp_path / "cardano")


def test_missing_lockfile_rejected(source: Path, tmp_path: Path) -> None:
    (source / "package-lock.json").unlink()
    with pytest.raises(installer.InstallError, match="Incomplete Cardano sources"):
        installer.install_runtime(source=source, root=tmp_path / "cardano")


def test_publish_failure_restores_old_runtime(
    source: Path,
    tmp_path: Path,
    processes: Mock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "cardano"
    cli = installer.install_runtime(source=source, root=root)
    (source / "src" / "cli.ts").write_text("changed")
    rename = Path.rename

    def fail_publish(path: Path, target: Path) -> Path:
        if path.name == "runtime" and path.parent.name.startswith(".runtime-stage-"):
            raise OSError("failed publication")
        return rename(path, target)

    monkeypatch.setattr(Path, "rename", fail_publish)
    with pytest.raises(OSError, match="failed publication"):
        installer.install_runtime(source=source, root=root)
    assert cli.read_text() == "built"
    assert (root / "runtime" / "src" / "cli.ts").read_text() == "export {};"


def test_source_symlink_rejected(source: Path, tmp_path: Path) -> None:
    (source / "src" / "secret.ts").symlink_to(source / ".env")
    with pytest.raises(installer.InstallError, match="regular files"):
        installer.install_runtime(source=source, root=tmp_path / "cardano")


def test_wheel_contains_only_explicit_client_sources(tmp_path: Path) -> None:
    builder = pytest.importorskip("hatchling.builders.wheel")
    root = Path(__file__).resolve().parents[1]
    config = tomllib.loads((root / "pyproject.toml").read_text())
    includes = config["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    assert all(Path(path).suffix in {".json", ".ts"} for path in includes)
    benchmark_sources = {
        "cardano/client/src/mpf-benchmark.ts",
        "cardano/client/src/mpf-fixture.ts",
    }
    expected_sources = {
        str(path.relative_to(root)) for path in (root / "cardano" / "client" / "src").rglob("*.ts")
    } - benchmark_sources
    assert benchmark_sources.isdisjoint(includes)
    assert {path for path in includes if path.endswith(".ts")} == expected_sources
    artifact = next(builder.WheelBuilder(str(root)).build(directory=str(tmp_path)))
    with zipfile.ZipFile(artifact) as wheel:
        entries = set(wheel.namelist())
    prefix = "toad/extensions/dega_panel/cardano_client/"
    client_entries = {entry for entry in entries if entry.startswith(prefix)}
    assert client_entries == set(includes.values())
    assert prefix + "package-lock.json" in entries
    assert prefix + "src/cli.ts" in entries
    assert "toad/cardano_install.py" in entries


def test_failed_rollback_keeps_recoverable_backup(
    source: Path,
    tmp_path: Path,
    processes: Mock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "cardano"
    installer.install_runtime(source=source, root=root)
    (source / "src" / "cli.ts").write_text("changed")
    rename = Path.rename

    def fail_after_backup(path: Path, target: Path) -> Path:
        if path.parent.name.startswith(".runtime-stage-"):
            raise OSError("filesystem unavailable")
        return rename(path, target)

    monkeypatch.setattr(Path, "rename", fail_after_backup)
    with pytest.raises(installer.InstallError, match="restore the previous runtime from"):
        installer.install_runtime(source=source, root=root)
    backups = list(root.glob(".runtime-stage-*/previous-runtime/dist/cli.js"))
    assert len(backups) == 1
    assert backups[0].read_text() == "built"


def test_process_timeout_is_actionable(
    source: Path,
    tmp_path: Path,
    processes: Mock,
) -> None:
    processes.side_effect = subprocess.TimeoutExpired("node", 600)
    with pytest.raises(installer.InstallError, match="Check Node.js/npm installation"):
        installer.install_runtime(source=source, root=tmp_path / "cardano")


def test_runtime_symlink_rejected(
    source: Path,
    tmp_path: Path,
    processes: Mock,
) -> None:
    root = tmp_path / "cardano"
    root.mkdir()
    (root / "runtime").symlink_to(source)
    with pytest.raises(installer.InstallError, match="not a symlink"):
        installer.install_runtime(source=source, root=root)
    assert (source / "src" / "cli.ts").read_text() == "export {};"


def test_missing_built_cli_rebuilds(
    source: Path,
    tmp_path: Path,
    processes: Mock,
) -> None:
    root = tmp_path / "cardano"
    cli = installer.install_runtime(source=source, root=root)
    cli.unlink()
    assert installer.install_runtime(source=source, root=root).is_file()
    assert sum(call.args[0][1] == "ci" for call in processes.call_args_list) == 2
