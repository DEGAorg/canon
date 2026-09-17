"""Real Anvil transactions for the TTL registry and Canon's chain adapter.

Run `forge build --root src/toad/extensions/dega_panel/contracts` first.
"""

import json
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest
from eth_account import Account
from nostr_sdk import Keys
from web3 import Web3

from toad.extensions.dega_panel import registration_renewal, registry_client
from toad.extensions.dega_panel.registry_client import ChainRegistry, RegistryError

CONTRACTS = Path(__file__).parents[1] / "src/toad/extensions/dega_panel/contracts"


@pytest.fixture
def chain(tmp_path, monkeypatch):
    if not shutil.which("anvil"):
        pytest.skip("Anvil required for real chain tests")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    process = subprocess.Popen(
        ["anvil", "--port", str(port), "--silent"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        rpc = f"http://127.0.0.1:{port}"
        web3 = Web3(Web3.HTTPProvider(rpc))
        for _ in range(100):
            if web3.is_connected():
                break
            time.sleep(0.05)
        assert web3.is_connected(), "Anvil did not start"
        owner = web3.eth.accounts[0]

        def deploy(name, *args):
            artifact = json.loads((CONTRACTS / "out" / f"{name}.sol" / f"{name}.json").read_text())
            factory = web3.eth.contract(
                abi=artifact["abi"], bytecode=artifact["bytecode"]["object"]
            )
            tx = factory.constructor(*args).transact({"from": owner})
            receipt = web3.eth.wait_for_transaction_receipt(tx)
            return web3.eth.contract(address=receipt.contractAddress, abi=artifact["abi"])

        token = deploy("MockDEGA")
        registry = deploy("DegaChatRegistry", token.address, 10, 3, 100)
        wallet = Account.create()
        web3.eth.wait_for_transaction_receipt(
            web3.eth.send_transaction(
                {
                    "from": owner,
                    "to": wallet.address,
                    "value": Web3.to_wei(1, "ether"),
                }
            )
        )
        token.functions.mint(wallet.address, 1000).transact({"from": owner})
        monkeypatch.setattr(registration_renewal, "CANON_DIR", tmp_path)
        monkeypatch.setattr(registry_client, "_DEGA_CHAT_ENV", tmp_path / "absent.env")
        client = ChainRegistry(rpc=rpc, registry=registry.address, private_key=wallet.key.hex())
        identity = Keys.generate()
        client.open_node(
            "alice", identity.public_key().to_hex(),
            nostr_secret=identity.secret_key().to_hex(),
        )
        yield client, web3, token, registry, owner
    finally:
        process.terminate()
        process.communicate(timeout=10)


def test_register_expire_renew_and_recover_after_restart(chain):
    client, web3, token, registry, _ = chain
    initial = client.registration_of_owner(client._sender)
    assert initial.active
    assert initial.expires_at == initial.opened_at + 100
    assert client.resolve_member("alice")["wallet"] == client._sender
    assert token.functions.balanceOf(registry.address).call() == 0
    assert token.functions.totalSupply().call() == 990
    web3.provider.make_request("evm_setNextBlockTimestamp", [initial.expires_at])
    web3.provider.make_request("evm_mine", [])
    assert client.resolve_member("alice") == {}
    assert client.username_of_owner(client._sender) == ""
    recovered = ChainRegistry(rpc=client._rpc, registry=registry.address, private_key=client._pk)
    assert recovered.registration_of_owner(client._sender).username == "alice"
    assert recovered.renew_node(recovered.renewal_quote())["confirmed"]
    final = recovered.registration_of_owner(client._sender)
    assert final.active and final.expires_at > initial.expires_at
    assert recovered.resolve_member("alice")["wallet"] == client._sender
    assert token.functions.balanceOf(registry.address).call() == 0
    assert token.functions.totalSupply().call() == 980


def test_timeout_retry_reuses_signed_transaction_even_after_restart(chain, monkeypatch):
    client, web3, token, registry, _ = chain
    quote = client.renewal_quote()
    wait = web3.eth.wait_for_transaction_receipt
    # Only renewal confirmation fails: approve succeeds, then renewal is mined
    # but the RPC receipt call times out. Restore through a new client instance.
    original_receipt = registration_renewal._receipt

    def mined_but_timeout(chain_client, pending):
        web3.eth.send_raw_transaction(Web3.to_bytes(hexstr=pending.raw_transaction))
        wait(pending.tx_hash)
        raise TimeoutError("receipt connection lost")

    monkeypatch.setattr(registration_renewal, "_receipt", mined_but_timeout)
    with pytest.raises(RegistryError, match="Retry to check the same transaction"):
        client.renew_node(quote)
    assert token.functions.balanceOf(registry.address).call() == 0
    assert token.functions.totalSupply().call() == 980
    monkeypatch.setattr(registration_renewal, "_receipt", original_receipt)
    recovered = ChainRegistry(rpc=client._rpc, registry=registry.address, private_key=client._pk)
    result = recovered.renew_node(recovered.renewal_quote())
    assert result["confirmed"]
    assert token.functions.balanceOf(registry.address).call() == 0
    assert token.functions.totalSupply().call() == 980
    assert not registration_renewal._pending_path(recovered).exists()


def test_fee_and_duration_changes_do_not_silently_change_renewal(chain):
    client, _, token, registry, owner = chain
    quote = client.renewal_quote()
    registry.functions.setFee(11).transact({"from": owner})
    with pytest.raises(RegistryError, match="reverted"):
        client.renew_node(quote)
    assert client.registration_of_owner(client._sender).expires_at == quote.registration.expires_at
    assert token.functions.balanceOf(registry.address).call() == 0
    assert token.functions.totalSupply().call() == 990
    registry.functions.setFee(0).transact({"from": owner})
    registry.functions.setRegistrationTTL(200).transact({"from": owner})
    assert client.renew_node(client.renewal_quote())["confirmed"]
    assert (
        client.registration_of_owner(client._sender).expires_at
        == quote.registration.expires_at + 200
    )
    assert token.functions.balanceOf(registry.address).call() == 0
    assert token.functions.totalSupply().call() == 990


def test_replaced_pending_transaction_is_reported_without_renewal_charge(chain, monkeypatch):
    client, web3, token, registry, _ = chain
    original_receipt = registration_renewal._receipt

    def offline_before_broadcast(chain_client, pending):
        raise OSError("connection lost")

    monkeypatch.setattr(registration_renewal, "_receipt", offline_before_broadcast)
    with pytest.raises(RegistryError, match="Retry to check the same transaction"):
        client.renew_node(client.renewal_quote())
    path = registration_renewal._pending_path(client)
    pending = json.loads(path.read_text())
    replacement = client._account.sign_transaction(
        {
            "from": client._sender,
            "to": client._sender,
            "value": 0,
            "nonce": pending["nonce"],
            "gas": 21000,
            "gasPrice": web3.eth.gas_price,
            "chainId": web3.eth.chain_id,
        }
    )
    tx_hash = web3.eth.send_raw_transaction(replacement.raw_transaction)
    web3.eth.wait_for_transaction_receipt(tx_hash)
    monkeypatch.setattr(registration_renewal, "_receipt", original_receipt)
    with pytest.raises(RegistryError, match="transaction replaced"):
        client.renew_node(client.renewal_quote())
    assert not path.exists()
    assert token.functions.balanceOf(registry.address).call() == 0
    assert token.functions.totalSupply().call() == 990


def test_embedded_abi_matches_compiled_contract(chain):
    _, _, _, registry, _ = chain
    compiled = {(item["type"], item.get("name")): item for item in registry.abi}
    for item in registry_client._REGISTRY_ABI:
        actual = compiled[(item["type"], item["name"])]
        assert [i["type"] for i in item["inputs"]] == [i["type"] for i in actual["inputs"]]
        assert [o["type"] for o in item.get("outputs", [])] == [
            o["type"] for o in actual.get("outputs", [])
        ]


def test_python_typed_digest_matches_contract_and_rejects_copied_proof(chain):
    from eth_account.messages import encode_typed_data
    from eth_utils import keccak
    from toad.extensions.dega_panel.registration_proof import registration_proof

    _, web3, _, registry, owner = chain
    identity = Keys.generate()
    pubkey = bytes.fromhex(identity.public_key().to_hex())
    typed = encode_typed_data(
        domain_data={
            "name": "DegaChatRegistry", "version": "1",
            "chainId": web3.eth.chain_id, "verifyingContract": registry.address,
        },
        message_types={"Registration": [
            {"name": "wallet", "type": "address"},
            {"name": "username", "type": "string"},
            {"name": "nostrPubkey", "type": "bytes32"},
        ]},
        message_data={"wallet": owner, "username": "bob", "nostrPubkey": pubkey},
    )
    expected_digest = keccak(b"\x19" + typed.version + typed.header + typed.body)
    assert registry.functions.registrationDigest(owner, "bob.dega", pubkey).call() == expected_digest
    proof = registration_proof(
        identity.secret_key().to_hex(), pubkey, wallet=owner, username="bob",
        chain_id=web3.eth.chain_id, registry=registry.address,
    )
    assert Account.recover_message(typed, signature=proof[32:]) == Account.from_key(
        identity.secret_key().to_hex()
    ).address
    with pytest.raises(Exception, match="invalid ownership proof"):
        registry.functions.openNode("bob", pubkey, proof).call({"from": web3.eth.accounts[2]})
