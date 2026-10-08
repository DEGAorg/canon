"""Cross-language JSON boundary checks against the built local companion."""

import json
from pathlib import Path

import pytest

from toad.extensions.dega_panel.cardano_registry import CardanoRegistry

CLI = Path(__file__).resolve().parents[1] / "cardano/client/dist/cli.js"
pytestmark = pytest.mark.skipif(
    not CLI.is_file(), reason="Build cardano/client for integration tests"
)


@pytest.mark.parametrize("network,prefix", [("Preview", "addr_test1"), ("Mainnet", "addr1")])
def test_real_companion_wallet_and_pending_boundary(tmp_path, network, prefix):
    manifest = tmp_path / "deployment.json"
    manifest.write_text(json.dumps({"network": network, "policyId": "33" * 28}))
    wallet = tmp_path / "wallet"
    bridge = CardanoRegistry(deployment=str(manifest), cli=str(CLI), wallet_path=str(wallet))
    assert bridge._call("pending.status") == {"pending": None}
    assert not wallet.exists()
    public = bridge.wallet()
    assert public.network == network
    assert public.address.startswith(prefix)
    assert bridge._sender == public.owner
    reopened = CardanoRegistry(deployment=str(manifest), cli=str(CLI), wallet_path=str(wallet))
    assert reopened.wallet() == public
    assert wallet.joinpath("cardano.json").stat().st_mode & 0o777 == 0o600
    assert wallet.joinpath("nostr.json").stat().st_mode & 0o777 == 0o600
