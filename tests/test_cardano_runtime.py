"""Automatic wallet startup, public configuration and chain-selection behavior."""

import asyncio
import json
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from textual.screen import Screen
from textual.widgets import Button, Collapsible, Input, Select, Static

from toad.extensions.dega_panel import auth_store, cardano_config, cardano_runtime
from toad.extensions.dega_panel.cardano_registry import CardanoRegistry
from toad.extensions.dega_panel.cardano_runtime import CardanoWallet, ensure_cardano_wallet
from toad.extensions.dega_panel.chat import ChatView, default_registry_backend
from toad.extensions.dega_panel.registry_client import RegistryError
from tests.test_cardano_registry import OWNER, RECORD
from tests.test_chat_ui import ChatApp


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(auth_store, "CANON_DIR", tmp_path)
    monkeypatch.setattr("toad.extensions.dega_panel.registry_client._DEGA_CHAT_ENV",
                        tmp_path / "dega-chat.env")
    for key in ("CANON_CARDANO_DEPLOYMENT", "CANON_CARDANO_WALLET", "CANON_CARDANO_NETWORK",
                "DEGA_CHAT_BACKEND"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("CANON_CARDANO_CONFIG", str(tmp_path / "cardano/config.json"))
    cli = tmp_path / "cardano/runtime/dist/cli.js"
    cli.parent.mkdir(parents=True)
    cli.write_text("")
    monkeypatch.setenv("CANON_CARDANO_CLI", str(cli))
    return tmp_path


@pytest.fixture
def public_process(monkeypatch):
    result = {"network": "Mainnet", "address": "addr1publicfunding", "owner": OWNER}
    process = Mock(return_value=subprocess.CompletedProcess(
        [], 0, json.dumps({"ok": True, "result": result}), ""))
    monkeypatch.setattr(cardano_runtime.subprocess, "run", process)
    return process


def test_startup_reuses_configured_wallet_without_deployment_or_provider(isolated, public_process):
    path = cardano_config.config_path()
    existing = isolated / "existing-demo-wallet"
    path.write_text(json.dumps({"network": "Mainnet", "walletPath": str(existing)}))
    first, second = ensure_cardano_wallet(), ensure_cardano_wallet()
    assert first == second == CardanoWallet("Mainnet", "addr1publicfunding", OWNER)
    for call in public_process.call_args_list:
        request = json.loads(call.kwargs["input"])
        assert request == {"operation": "wallet.ensure", "network": "Mainnet",
                           "walletPath": str(existing), "payload": {}}
        assert call.kwargs["timeout"] == 30
    assert json.loads(path.read_text())["walletPath"] == str(existing)


def test_default_config_and_installed_runtime_do_not_depend_on_cwd(
    isolated, public_process, monkeypatch,
):
    monkeypatch.delenv("CANON_CARDANO_CLI")
    elsewhere = isolated / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    wallet = ensure_cardano_wallet()
    assert wallet.address == "addr1publicfunding"
    saved = json.loads(cardano_config.config_path().read_text())
    assert saved["walletPath"] == str(isolated / "cardano/wallets/mainnet")
    assert cardano_config.config_path().stat().st_mode & 0o777 == 0o600
    assert public_process.call_args.args[0][1] == str(isolated / "cardano/runtime/dist/cli.js")


def test_missing_runtime_is_actionable_without_wallet_or_network(isolated, monkeypatch):
    monkeypatch.setenv("CANON_CARDANO_CLI", str(isolated / "missing.js"))
    process = Mock(side_effect=AssertionError("No process should run"))
    monkeypatch.setattr(cardano_runtime.subprocess, "run", process)
    with pytest.raises(RegistryError, match="python -m toad.cardano_install"):
        ensure_cardano_wallet()
    assert not cardano_config.config_path().exists()


@pytest.mark.parametrize("content", ["not-json", "[]", '{"network":"Unknown"}'])
def test_corrupt_config_fails_without_replacement(isolated, content, public_process):
    path = cardano_config.config_path()
    path.write_text(content)
    with pytest.raises(RegistryError, match="Invalid Cardano configuration"):
        ensure_cardano_wallet()
    assert path.read_text() == content
    public_process.assert_not_called()


def test_chain_selection_persists_without_replacing_wallet(isolated, public_process):
    ensure_cardano_wallet()
    before = cardano_config.load_cardano_config()
    cardano_config.save_registration_backend("cardano")
    assert default_registry_backend() == "cardano"
    after = cardano_config.load_cardano_config()
    assert (after.wallet_path, after.network, after.deployment) == (
        before.wallet_path, before.network, before.deployment)


@pytest.mark.asyncio
async def test_actual_app_mount_automatically_ensures_wallet(isolated, public_process, monkeypatch):
    from toad.app import ToadApp

    for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"):
        monkeypatch.setenv(name, str(isolated / name))
    monkeypatch.setattr(ToadApp, "on_load", AsyncMock())
    for method in ("capture_event", "set_process_title", "run_version_check",
                   "update_show_sessions", "update_terminal_title"):
        monkeypatch.setattr(ToadApp, method, Mock())
    monkeypatch.setattr("toad.socket_controller.start_socket_server", AsyncMock(return_value=None))
    app = ToadApp(mode="startup-test", project_dir=str(isolated))
    app.__dict__["anon_id"] = "isolated-test"
    app.add_mode("startup-test", Screen)
    async with app.run_test() as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.cardano_wallet == CardanoWallet("Mainnet", "addr1publicfunding", OWNER)
        assert app.cardano_wallet_error is None
    assert json.loads(public_process.call_args.kwargs["input"])["operation"] == "wallet.ensure"


@pytest.mark.asyncio
async def test_mounted_chain_selector_preserves_identity_and_funding_without_registry(
    isolated, public_process, monkeypatch,
):
    app = ChatApp(isolated)
    async with app.run_test(size=(100, 50)) as pilot:
        view = app.query_one(ChatView)
        monkeypatch.setattr(view, "_start_inbox_poll", lambda: None)
        previous = view._registry
        identity = view._me.pubkey
        view._offline = False
        view._selected_contact = {"pubkey": "aa" * 32}
        view.query_one("#composer", Input).value = "saved draft"
        view.query_one("#account-details", Collapsible).collapsed = False
        selector = view.query_one("#registration-chain", Select)
        selector.disabled = False
        selector.value = "cardano"
        await pilot.pause()
        chain_workers = [worker for worker in app.workers if worker.group == "registration-chain"]
        if chain_workers:
            await app.workers.wait_for_complete(chain_workers)
        await pilot.pause()
        assert view._registry_backend == "cardano"
        assert view._me.pubkey == identity
        assert view._drafts["aa" * 32] == "saved draft"
        assert view._wallet() == "addr1publicfunding"
        assert view.query_one("#retry-cardano-wallet", Button).display
        profile = str(view.query_one("#profile", Static).render())
        assert profile.count("addr1publicfunding") == 1
        assert not view.query("#cardano-wallet")
        assert "not deployed" in view._registry_error
        assert view.query_one("#btn-open-node", Button).disabled
        assert default_registry_backend() == "cardano"
        monkeypatch.setattr("toad.extensions.dega_panel.chat.RegistryClient", lambda **_: previous)
        selector.value = "chain"
        await pilot.pause()
        chain_workers = [worker for worker in app.workers if worker.group == "registration-chain"]
        if chain_workers:
            await app.workers.wait_for_complete(chain_workers)
        await pilot.pause()
        assert view._registry is previous
        assert view._me.pubkey == identity
        assert default_registry_backend() == "chain"
        assert not view.query("#cardano-wallet")
        assert not view.query_one("#retry-cardano-wallet", Button).display
        view.set_cardano_wallet(None, "Cardano setup unavailable")
        await pilot.pause()
        assert not view.query("#cardano-wallet")
        assert not view.query_one("#retry-cardano-wallet", Button).display
        view._offline = True


def test_passive_snapshot_reuses_one_request_and_expires_at_exact_millisecond(isolated, monkeypatch):
    deployment = isolated / "deployment.json"
    deployment.write_text(json.dumps({"network": "Mainnet", "policyId": "33" * 28}))
    registry = CardanoRegistry(deployment=str(deployment))
    registry._wallet_descriptor = CardanoWallet("Mainnet", "addr1publicfunding", OWNER)
    now = [0.0]
    monkeypatch.setattr("toad.extensions.dega_panel.cardano_registry.time.monotonic", lambda: now[0])
    status = {"record": {**RECORD, "expiresMs": "20999"}, "checkedAtMs": "20998",
              "feeAmount": "50", "ttlMs": "1000", "stateRef": "state#0", "maxUsers": 10}
    call = Mock(return_value=status)
    monkeypatch.setattr(registry, "_call", call)
    assert registry.state_snapshot()["funding_address"] == "addr1publicfunding"
    assert registry.registration_status().active
    now[0] = 0.001
    assert not registry.registration_status().active
    assert not registry.state_snapshot()["my_nodes"]
    call.assert_called_once_with("status", {"owner": OWNER})
    now[0] = 180.0
    registry.state_snapshot()
    assert call.call_count == 2


@pytest.mark.asyncio
async def test_stale_snapshot_cannot_overwrite_new_chain(isolated, monkeypatch):
    from threading import Event

    app = ChatApp(isolated)
    release, started = Event(), Event()

    def old_snapshot():
        started.set()
        release.wait(timeout=5)
        return {"sender": "old-chain"}

    async with app.run_test() as pilot:
        view = app.query_one(ChatView)
        view._chat_ready = True
        view._registry = SimpleNamespace(state_snapshot=old_snapshot)
        refresh = asyncio.create_task(view._refresh_snapshot_cache())
        await asyncio.to_thread(started.wait, 2)
        view._registry_generation += 1
        view._snapshot_cache = {"sender": "new-chain"}
        release.set()
        await refresh
        await pilot.pause()
        assert view._snapshot_cache == {"sender": "new-chain"}


def test_concurrent_startup_publishes_complete_public_config(isolated, public_process):
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=6) as pool:
        wallets = list(pool.map(lambda _: ensure_cardano_wallet(), range(12)))
    assert all(wallet == wallets[0] for wallet in wallets)
    saved = json.loads(cardano_config.config_path().read_text())
    assert saved["network"] == "Mainnet"
    assert saved["walletPath"] == str(isolated / "cardano/wallets/mainnet")


def test_mutation_confirmation_discards_inflight_old_status(isolated, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    deployment = isolated / "deployment.json"
    deployment.write_text(json.dumps({"network": "Mainnet", "policyId": "33" * 28}))
    registry = CardanoRegistry(deployment=str(deployment))
    registry._wallet_descriptor = CardanoWallet("Mainnet", "addr1publicfunding", OWNER)
    started, release = Event(), Event()

    def provider(operation, payload):
        if operation != "status":
            return {"status": "confirmed", "txHash": "aa" * 32}
        started.set()
        release.wait(timeout=5)
        return {"record": None, "checkedAtMs": "1000", "feeAmount": "50",
                "ttlMs": "1000", "stateRef": "state#0", "maxUsers": 10}

    monkeypatch.setattr(registry, "_call", provider)
    with ThreadPoolExecutor(max_workers=1) as pool:
        old = pool.submit(registry.state_snapshot)
        assert started.wait(timeout=2)
        try:
            registry._confirmed("register", {})
        finally:
            release.set()
        with pytest.raises(RegistryError, match="changed during lookup"):
            old.result()
    assert registry._status_cache is None


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["ensure_chat_ready", "_resume_node"])
async def test_old_chain_cannot_mark_new_chain_ready_or_restore_old_registration(
    isolated, monkeypatch, operation,
):
    from threading import Event
    from toad.extensions.dega_panel.registration import Registration

    started, release = Event(), Event()

    def old_result():
        started.set()
        release.wait(timeout=5)
        if operation == "ensure_chat_ready":
            return {"sender": "old"}
        return Registration("old", "owner", 0, 100, 1, True, 10)

    app = ChatApp(isolated)
    async with app.run_test():
        view = app.query_one(ChatView)
        view._offline = False
        view._registry = SimpleNamespace(state_snapshot=old_result, registration_status=old_result)
        monkeypatch.setattr(view, "_restore_direct_history", AsyncMock())
        task = asyncio.create_task(getattr(view, operation)())
        assert await asyncio.to_thread(started.wait, 2)
        view._registry_generation += 1
        view._registry = None
        view._snapshot_cache = {"sender": "new"}
        view._chat_ready = False
        release.set()
        await task
        assert not view._chat_ready
        assert view._registration is None
        assert view._snapshot_cache == {"sender": "new"}
        view._offline = True


def test_saved_chain_choice_overrides_legacy_file_but_not_explicit_environment(
    isolated, monkeypatch,
):
    (isolated / "dega-chat.env").write_text("DEGA_CHAT_BACKEND=chain\n")
    cardano_config.save_registration_backend("cardano")
    assert default_registry_backend() == "cardano"
    monkeypatch.setenv("DEGA_CHAT_BACKEND", "test")
    assert default_registry_backend() == "test"
