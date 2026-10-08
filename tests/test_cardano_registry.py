"""Behavioral tests at the Cardano companion process boundary."""

import json
import subprocess
from unittest.mock import patch

import pytest

from toad.extensions.dega_panel.cardano_registry import CardanoRegistry
from toad.extensions.dega_panel.cardano_runtime import CardanoWallet
from toad.extensions.dega_panel.registry_client import RegistryError

OWNER = "11" * 28
SECRET = "00" * 31 + "03"
KEY = "f9308a019258c31049344f85f89d5229b531c845836f99b08601f113bce036f9"
RECORD = {
    "name": "a.b",
    "owner": OWNER,
    "nostrKey": KEY,
    "openedMs": "1000",
    "expiresMs": "20000",
    "members": [OWNER],
}


@pytest.fixture
def registry(tmp_path):
    cli = tmp_path / "cli.js"
    cli.write_text("")
    deployment = tmp_path / "deployment.json"
    deployment.write_text(json.dumps({"network": "Preview", "policyId": "33" * 28}))
    return CardanoRegistry(deployment=str(deployment), cli=str(cli))


def reply(result, *, ok=True, code=0):
    envelope = {"ok": ok, "result" if ok else "error": result}
    return subprocess.CompletedProcess([], code, json.dumps(envelope), "SECRET STDERR")


def test_public_lookup_needs_no_wallet_and_uses_stdin(registry):
    with patch(
        "subprocess.run", return_value=reply({"record": RECORD, "checkedAtMs": "19999"})
    ) as run:
        assert registry.resolve_member(" a.b.dega ") == {
            "username": "a.b",
            "wallet": OWNER,
            "pubkey": bytes.fromhex(KEY),
        }
    request = json.loads(run.call_args.kwargs["input"])
    assert request["payload"]["name"] == "a.b"
    assert request["operation"] == "resolve"
    assert run.call_args.args[0] == ["node", registry.cli]
    assert run.call_args.kwargs["timeout"] == 120


def test_exact_expiry_hidden_but_name_permanently_reserved(registry):
    with patch("subprocess.run", return_value=reply({"record": RECORD, "checkedAtMs": "20000"})):
        assert registry.resolve_member("a.b") is None
        assert registry.username_taken("a.b")
        registration = registry.registration_of_owner(OWNER)
        assert not registration.active
        assert registration.expires_at == 20
        assert registration.opened_at == 1


@pytest.mark.parametrize("output", ["garbage", "[]", '{"ok":true,"result":[]}', "{}"])
def test_malformed_envelope_not_absence(registry, output):
    with patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0, output, "SECRET")):
        with pytest.raises(RegistryError, match="invalid response") as error:
            registry.resolve_member("a")
    assert "SECRET" not in str(error.value)


def test_provider_failure_not_absence(registry):
    with patch(
        "subprocess.run",
        return_value=reply({"code": "PROVIDER", "message": "Unavailable"}, ok=False, code=1),
    ):
        with pytest.raises(RegistryError, match="PROVIDER"):
            registry.resolve_member("a")


@pytest.mark.parametrize(
    "failure", [OSError("missing node"), subprocess.TimeoutExpired("node", 120)]
)
def test_process_failure_actionable(registry, failure):
    with patch("subprocess.run", side_effect=failure):
        with pytest.raises(RegistryError):
            registry.resolve_member("a")


@pytest.mark.parametrize(
    "field,value",
    [
        ("nostrKey", "ab"),
        ("owner", "bad"),
        ("expiresMs", "0"),
        ("members", []),
        ("members", [OWNER, OWNER]),
    ],
)
def test_malformed_record_rejected(registry, field, value):
    malformed = {**RECORD, field: value}
    with patch("subprocess.run", return_value=reply({"record": malformed, "checkedAtMs": "1000"})):
        with pytest.raises(RegistryError, match="malformed registration"):
            registry.resolve_member("a")


def test_unknown_network_configuration_rejected(tmp_path):
    cli, manifest = tmp_path / "cli.js", tmp_path / "manifest.json"
    cli.write_text("")
    manifest.write_text(json.dumps({"network": "Unknown", "policyId": "33" * 28}))
    with pytest.raises(RegistryError, match="Preview"):
        CardanoRegistry(deployment=str(manifest), cli=str(cli))


def test_submission_waits_for_confirmation(registry):
    submitted = {"txHash": "ab" * 32, "status": "submitted"}
    with patch.object(registry, "_call", side_effect=[
        submitted, submitted, {**submitted, "status": "confirmed"},
    ]) as call, patch("toad.extensions.dega_panel.cardano_registry.time.sleep") as sleep:
        result = registry._confirmed("register", {"name": "a"})
    assert result == {"status": "ok", "confirmed": True, "tx_hash": "ab" * 32}
    assert [item.args[0] for item in call.call_args_list] == ["register", "retry", "retry"]
    assert sleep.call_count == 2


def test_unconfirmed_submission_remains_pending_without_failure(registry):
    with patch.object(registry, "_call", return_value={
        "txHash": "ab" * 32, "status": "submitted",
    }) as call, patch("toad.extensions.dega_panel.cardano_registry.time.sleep"):
        result = registry._confirmed("register", {})
    assert result == {"status": "pending", "confirmed": False, "tx_hash": "ab" * 32}
    assert call.call_count == 9


def test_confirmation_rejects_another_transaction(registry):
    with patch.object(registry, "_call", side_effect=[
        {"txHash": "ab" * 32, "status": "submitted"},
        {"txHash": "cd" * 32, "status": "confirmed"},
    ]), patch("toad.extensions.dega_panel.cardano_registry.time.sleep"):
        with pytest.raises(RegistryError, match="different transaction"):
            registry._confirmed("register", {})


@pytest.mark.parametrize("code", [
    "PROVIDER_RATE_LIMIT", "PROVIDER_UNAVAILABLE", "STALE_CHAIN_TIP",
    "SUBMISSION_FAILED", "TRANSACTION_TIMING",
])
def test_confirmation_recovers_transient_provider_error(registry, code):
    from toad.extensions.dega_panel.cardano_runtime import CardanoOperationError

    with patch.object(registry, "_call", side_effect=[
        {"txHash": "ab" * 32, "status": "submitted"},
        CardanoOperationError(code, "wait"),
        {"txHash": "ab" * 32, "status": "confirmed"},
    ]), patch("toad.extensions.dega_panel.cardano_registry.time.sleep"):
        assert registry._confirmed("register", {})["confirmed"]


def test_registration_secret_only_in_local_stdin(registry):
    with patch.object(
        registry,
        "_call",
        side_effect=[
            {"pending": None},
            {"stateRef": "ref", "feeAmount": "100", "ttlMs": "1000", "maxUsers": "10"},
            {"txHash": "ab" * 32, "status": "confirmed"},
        ],
    ) as call:
        result = registry.open_node("a", nostr_secret=SECRET, nostr_pubkey=KEY)
    assert result["confirmed"]
    assert call.call_args.args[1]["nostrSecret"] == SECRET
    assert call.call_args.args[1]["stateRef"] == "ref"


@pytest.mark.parametrize(
    "operation,result",
    [
        ("status", {}),
        ("status", {"feeAmount": "-1", "ttlMs": "1", "maxUsers": 10, "stateRef": "x"}),
        ("wallet.status", {"owner": "bad"}),
        ("register", {"status": "confirmed"}),
        ("renew", {"status": "confirmed", "txHash": "abc"}),
    ],
)
def test_malformed_successful_operation(registry, operation, result):
    with patch("subprocess.run", return_value=reply(result)):
        with pytest.raises(RegistryError, match="invalid response"):
            registry._call(operation)


def test_renewal_uses_one_snapshot_and_invalidates_old_quote(registry):
    registry._wallet_descriptor = CardanoWallet("Preview", "addr_test1public", OWNER)
    first = {"record": RECORD, "checkedAtMs": "1000"}
    changed = {**RECORD, "expiresMs": "29999"}
    quote_data = {
        "record": changed,
        "checkedAtMs": "1500",
        "feeAmount": "50",
        "ttlMs": "1001",
        "stateRef": "test#0",
    }
    with patch.object(
        registry, "_call", side_effect=[first, {"pending": None}, quote_data]
    ):
        quote = registry.renewal_quote()
    assert quote.registration.expires_at == 29
    with patch.object(
        registry, "_call", return_value={"status": "confirmed", "txHash": "ab" * 32}
    ) as call:
        registry.renew_node(quote)
    assert call.call_args.args[1]["expectedExpiryMs"] == "29999"
    assert call.call_args.args[1]["expectedTtlMs"] == "1001"
    with patch.object(
        registry, "_call", side_effect=[first, {"pending": None}, quote_data]
    ):
        replacement = registry.renewal_quote()
    assert replacement == quote
    assert replacement is not quote
    with pytest.raises(RegistryError, match="Refresh"):
        registry.renew_node(quote)


def test_pending_renewal_rechecks_saved_transaction_without_buying_term(registry):
    registry._wallet_descriptor = CardanoWallet("Preview", "addr_test1public", OWNER)
    pending = {"pending": {"operation": "renew", "name": "a.b", "policyId": registry.registry}}
    with patch.object(
        registry,
        "_call",
        side_effect=[
            {"record": RECORD, "checkedAtMs": "1000"},
            pending,
        ],
    ):
        quote = registry.renewal_quote()
    assert quote.pending
    with patch.object(
        registry,
        "_call",
        side_effect=[
            pending,
            {"status": "confirmed", "txHash": "ab" * 32},
        ],
    ) as call:
        assert registry.renew_node(quote)["confirmed"]
    assert call.call_args.args == ("retry", {})


def test_pending_other_operation_cannot_be_reported_as_registration(registry):
    pending = {"pending": {"operation": "renew", "name": "a.b", "policyId": registry.registry}}
    with patch.object(registry, "_call", return_value=pending) as call:
        with pytest.raises(RegistryError, match="pending operation"):
            registry.open_node("a.b", nostr_secret=SECRET, nostr_pubkey=KEY)
    assert call.call_count == 1


def test_registration_retry_cannot_confirm_another_nostr_identity(registry):
    pending = {
        "pending": {
            "operation": "register",
            "name": "a.b",
            "policyId": registry.registry,
            "nostrKey": "44" * 32,
        }
    }
    with patch.object(registry, "_call", return_value=pending) as call:
        with pytest.raises(RegistryError, match="another Nostr identity"):
            registry.open_node("a.b", nostr_secret=SECRET, nostr_pubkey=KEY)
    assert call.call_count == 1


def test_wrong_supplied_public_key_rejected_before_process(registry):
    with patch.object(registry, "_call") as call:
        with pytest.raises(RegistryError, match="does not match"):
            registry.open_node("a.b", nostr_secret=SECRET, nostr_pubkey="44" * 32)
    call.assert_not_called()


@pytest.mark.parametrize("network", ["Preview", "Mainnet"])
def test_supported_network_is_explicit_at_process_boundary(tmp_path, network):
    cli = tmp_path / "cli.js"
    cli.write_text("")
    manifest = tmp_path / "deployment.json"
    manifest.write_text(json.dumps({"network": network, "policyId": "33" * 28}))
    bridge = CardanoRegistry(deployment=str(manifest), cli=str(cli))
    with patch(
        "subprocess.run", return_value=reply({"record": None, "checkedAtMs": "1000"})
    ) as run:
        assert bridge.resolve_member("unused") is None
    request = json.loads(run.call_args.kwargs["input"])
    assert request["network"] == network
    assert "walletPath" not in request


@pytest.fixture
def pending_registration(registry):
    return {"pending": {"operation": "register", "name": "a.b",
                        "policyId": registry.registry, "nostrKey": KEY}}


def test_companion_error_code_is_preserved_at_process_boundary(registry):
    from toad.extensions.dega_panel.cardano_runtime import CardanoOperationError

    error = {"code": "PENDING_EXPIRED", "message": "Archived safely; original state is unspent",
             "details": {"maxFee": "50", "expectedTtlMs": "1000"}}
    with patch("subprocess.run", return_value=reply(error, ok=False, code=1)):
        with pytest.raises(CardanoOperationError) as caught:
            registry._call("retry")
    assert caught.value.code == "PENDING_EXPIRED"
    assert caught.value.details == {"maxFee": "50", "expectedTtlMs": "1000"}
    assert "Archived safely" in str(caught.value)
    assert "SECRET STDERR" not in str(caught.value)


@pytest.mark.parametrize("error", [
    {"code": None, "message": "expired"},
    {"code": "PENDING_EXPIRED", "message": None},
    {"code": "", "message": "expired"},
])
def test_malformed_companion_error_cannot_trigger_recovery(registry, error):
    from toad.extensions.dega_panel.cardano_runtime import CardanoOperationError

    with patch("subprocess.run", return_value=reply(error, ok=False, code=1)):
        with pytest.raises(RegistryError, match="invalid response") as caught:
            registry._call("retry")
    assert not isinstance(caught.value, CardanoOperationError)


def test_verified_expired_registration_rebuilds_same_intent_once(registry, pending_registration):
    terms = {"stateRef": "fresh#2", "feeAmount": "1512340000",
             "ttlMs": "31536000000", "maxUsers": 10}
    expired = {"code": "PENDING_EXPIRED", "message": "Expired journal archived safely",
               "details": {"maxFee": "1512340000", "expectedTtlMs": "31536000000"}}
    with patch("subprocess.run", side_effect=[
        reply(pending_registration), reply(expired, ok=False, code=1), reply(terms),
        reply({"status": "confirmed", "txHash": "ab" * 32}),
    ]) as process:
        result = registry.open_node(" a.b.dega ", nostr_secret=SECRET, nostr_pubkey=KEY)
    assert result["confirmed"]
    requests = [json.loads(call.kwargs["input"]) for call in process.call_args_list]
    assert [request["operation"] for request in requests] == [
        "pending.status", "retry", "status", "register",
    ]
    assert requests[-1]["payload"] == {
        "name": "a.b", "nostrSecret": SECRET, "nostrKey": KEY,
        "stateRef": "fresh#2", "maxFee": "1512340000", "expectedTtlMs": "31536000000",
    }


@pytest.mark.parametrize("code", ["PROVIDER", "PENDING_CONFLICT", "PENDING_UNKNOWN"])
def test_other_retry_failures_do_not_rebuild(registry, pending_registration, code):
    from toad.extensions.dega_panel.cardano_runtime import CardanoOperationError

    error = CardanoOperationError(code, "Retry cannot be reconciled")
    with patch.object(registry, "_call", side_effect=[pending_registration, error]) as call:
        with pytest.raises(CardanoOperationError) as caught:
            registry.open_node("a.b", nostr_secret=SECRET, nostr_pubkey=KEY)
    assert caught.value is error
    assert [item.args[0] for item in call.call_args_list] == ["pending.status", "retry"]


def test_error_text_alone_never_authorizes_rebuild(registry, pending_registration):
    with patch.object(registry, "_call", side_effect=[
        pending_registration, RegistryError("PENDING_EXPIRED"),
    ]) as call:
        with pytest.raises(RegistryError, match="PENDING_EXPIRED"):
            registry.open_node("a.b", nostr_secret=SECRET, nostr_pubkey=KEY)
    assert call.call_count == 2


def test_expired_error_from_fresh_registration_does_not_loop(registry, pending_registration):
    from toad.extensions.dega_panel.cardano_runtime import CardanoOperationError

    expired = CardanoOperationError("PENDING_EXPIRED", "Expired",
                                    details={"maxFee": "50", "expectedTtlMs": "1000"})
    terms = {"stateRef": "fresh#2", "feeAmount": "50", "ttlMs": "1000"}
    with patch.object(registry, "_call", side_effect=[
        pending_registration, expired, terms, expired,
    ]) as call:
        with pytest.raises(CardanoOperationError):
            registry.open_node("a.b", nostr_secret=SECRET, nostr_pubkey=KEY)
    assert [item.args[0] for item in call.call_args_list] == [
        "pending.status", "retry", "status", "register",
    ]


def test_expired_pending_renewal_requires_new_quote_instead_of_repricing(registry):
    from toad.extensions.dega_panel.cardano_runtime import CardanoOperationError
    from toad.extensions.dega_panel.registration import Registration, RenewalQuote

    quote = RenewalQuote(Registration("a.b", OWNER, 1, 20, 1, False, 21), 0, 0, 8, pending=True)
    registry._quotes[id(quote)] = (quote, {})
    pending = {"pending": {"operation": "renew", "name": "a.b", "policyId": registry.registry}}
    error = CardanoOperationError("PENDING_EXPIRED", "Expired; request a fresh renewal quote")
    with patch.object(registry, "_call", side_effect=[pending, error]) as call:
        with pytest.raises(CardanoOperationError) as caught:
            registry.renew_node(quote)
    assert caught.value is error
    assert [item.args[0] for item in call.call_args_list] == ["pending.status", "retry"]


@pytest.mark.parametrize("details", [
    {}, {"maxFee": "50"}, {"maxFee": 50, "expectedTtlMs": "1000"},
    {"maxFee": "-1", "expectedTtlMs": "1000"},
    {"maxFee": "50", "expectedTtlMs": "0"},
])
def test_invalid_expiry_terms_rejected_at_boundary(registry, details):
    error = {"code": "PENDING_EXPIRED", "message": "Expired", "details": details}
    with patch("subprocess.run", return_value=reply(error, ok=False, code=1)):
        with pytest.raises(RegistryError, match="invalid response"):
            registry._call("retry")


def test_missing_expired_terms_does_not_rebuild(registry, pending_registration):
    from toad.extensions.dega_panel.cardano_runtime import CardanoOperationError

    expired = CardanoOperationError("PENDING_EXPIRED", "Expired")
    with patch.object(registry, "_call", side_effect=[pending_registration, expired]) as call:
        with pytest.raises(RegistryError, match="terms unavailable"):
            registry.open_node("a.b", nostr_secret=SECRET, nostr_pubkey=KEY)
    assert call.call_count == 2


@pytest.mark.parametrize("fee,ttl", [("51", "1000"), ("50", "1001"), ("49", "999")])
def test_changed_expired_registration_terms_require_new_review(
    registry, pending_registration, fee, ttl,
):
    from toad.extensions.dega_panel.cardano_runtime import CardanoOperationError

    expired = CardanoOperationError("PENDING_EXPIRED", "Expired",
                                    details={"maxFee": "50", "expectedTtlMs": "1000"})
    terms = {"feeAmount": fee, "ttlMs": ttl, "stateRef": "fresh#2"}
    with patch.object(registry, "_call", side_effect=[pending_registration, expired, terms]) as call:
        with pytest.raises(CardanoOperationError) as caught:
            registry.open_node("a.b", nostr_secret=SECRET, nostr_pubkey=KEY)
    assert caught.value.code == "TERMS_CHANGED"
    assert [item.args[0] for item in call.call_args_list] == ["pending.status", "retry", "status"]


def test_rebuild_after_fee_decrease_keeps_original_maximum(registry, pending_registration):
    from toad.extensions.dega_panel.cardano_runtime import CardanoOperationError

    expired = CardanoOperationError("PENDING_EXPIRED", "Expired",
                                    details={"maxFee": "50", "expectedTtlMs": "1000"})
    terms = {"feeAmount": "49", "ttlMs": "1000", "stateRef": "fresh#2"}
    with patch.object(registry, "_call", side_effect=[
        pending_registration, expired, terms, {"status": "confirmed", "txHash": "ab" * 32},
    ]) as call:
        assert registry.open_node("a.b", nostr_secret=SECRET, nostr_pubkey=KEY)["confirmed"]
    payload = call.call_args.args[1]
    assert payload["maxFee"] == "50"
    assert payload["expectedTtlMs"] == "1000"
    assert payload["stateRef"] == "fresh#2"


def test_confirmation_preserves_terminal_error(registry):
    from toad.extensions.dega_panel.cardano_runtime import CardanoOperationError

    with patch.object(registry, "_call", side_effect=[
        {"txHash": "ab" * 32, "status": "submitted"},
        CardanoOperationError("PENDING_CONFLICT", "State consumed"),
    ]), patch("toad.extensions.dega_panel.cardano_registry.time.sleep"):
        with pytest.raises(CardanoOperationError, match="State consumed"):
            registry._confirmed("register", {})
