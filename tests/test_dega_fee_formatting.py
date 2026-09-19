from __future__ import annotations

from toad.extensions.dega_panel.chat_protocol import fee_display, format_dega_amount
from toad.extensions.dega_panel.registry_client import RegistryClient


def test_format_dega_amount_uses_8_decimals() -> None:
    assert format_dega_amount(1) == "0.00000001"
    assert format_dega_amount(123456789) == "1.23457"


def test_format_dega_amount_honors_token_decimals() -> None:
    # 18-decimal token: 1e18 base units == 1 $DEGA.
    assert format_dega_amount(10**18, decimals=18) == "1"
    assert format_dega_amount(15 * 10**17, decimals=18) == "1.5"
    # 6-decimal token.
    assert format_dega_amount(1_500_000, decimals=6) == "1.5"


def test_format_dega_amount_never_uses_scientific_notation() -> None:
    """A tiny fee must render as 0.00000000005, not 5e-11, in the UI."""
    for weega in (1, 5, 1000000, 50000000):
        for decimals in (6, 8, 18):
            out = format_dega_amount(weega, decimals=decimals)
            assert "e" not in out.lower(), out
            assert out
    assert format_dega_amount(50000000, decimals=18) == "0.00000000005"
    assert format_dega_amount(50000000, decimals=8) == "0.5"
    assert format_dega_amount(0) == "0"


class _UnknownScaleChain:
    """Chain-like backend whose token scale cannot be read from the contract."""

    def __init__(self, fee_weega: int = 50000000) -> None:
        self._fee = fee_weega
        self._sender = "0x" + "ab" * 20
        self._registry = "0x" + "cd" * 20

    def fee(self) -> int:
        return self._fee

    def token_decimals(self) -> None:
        return None  # contract unreadable

    def max_users_per_node(self) -> int:
        return 10

    def username_of_owner(self, _owner: str) -> str:
        return ""


def test_failed_contract_read_retries_and_caches_verified_scale(monkeypatch):
    from unittest.mock import Mock
    from toad.extensions.dega_panel.registry_client import ChainRegistry

    chain = ChainRegistry(private_key="11" * 32)
    token = Mock()
    monkeypatch.setattr(chain._w3.eth, "contract", Mock(return_value=token))
    read = Mock(side_effect=["", "0x" + "ab" * 20, None, "0x" + "ab" * 20, 6])
    monkeypatch.setattr(chain, "_view", read)
    assert chain.token_decimals() is None  # registry lookup failed
    assert chain.token_decimals() is None  # token lookup failed
    assert fee_display(50000000, None) == "50000000 weega (token scale unavailable)"
    assert chain.token_decimals() == 6
    assert chain.token_decimals() == 6
    assert read.call_count == 5  # successful response is cached


def test_zero_token_decimals_are_cached(monkeypatch):
    from unittest.mock import Mock
    from toad.extensions.dega_panel.registry_client import ChainRegistry

    chain = ChainRegistry(private_key="11" * 32)
    monkeypatch.setattr(chain._w3.eth, "contract", Mock())
    read = Mock(side_effect=["0x" + "ab" * 20, 0])
    monkeypatch.setattr(chain, "_view", read)
    assert chain.token_decimals() == 0
    assert chain.token_decimals() == 0
    assert read.call_count == 2


def test_backend_reporting_unknown_scale_never_mis_scales() -> None:
    """UI safety net: a backend that reports an unknown scale shows base units."""
    reg = RegistryClient(backend="test")
    reg._chain = _UnknownScaleChain()  # type: ignore[assignment]

    snap = reg.state_snapshot()
    assert reg.fee_decimals() is None
    assert snap["fee_decimals"] is None
    # Base units, flagged - not "0.5" (which assumed 8 decimals).
    assert reg.fee_degas() == "50000000 weega"
    assert fee_display(snap["fee_weega"], snap["fee_decimals"]) == (
        "50000000 weega (token scale unavailable)"
    )


def test_fee_display_uses_contract_scale_when_known() -> None:
    assert fee_display(50000000, 18) == "0.00000000005 $DEGA"
    assert fee_display(250000000, 8) == "2.5 $DEGA"
    assert fee_display(0, 18) == "0 $DEGA"


def test_registry_fee_degas_uses_shared_formatter() -> None:
    reg = RegistryClient(backend="test", fee_weega=250000000)
    assert reg.fee_degas() == "2.5"


def test_snapshot_carries_fee_decimals_for_the_ui() -> None:
    """The UI renders from the cached snapshot, so decimals must travel with it."""
    reg = RegistryClient(backend="test", fee_weega=50000000)
    snap = reg.state_snapshot()
    assert snap["fee_decimals"] == 8
    assert snap["fee_weega"] == 50000000


def test_ui_amount_uses_snapshot_decimals() -> None:
    """18-decimal token: the UI amount must match the on-chain scale, not 1e8."""
    reg = RegistryClient(backend="test", fee_weega=50000000)
    snap = reg.state_snapshot()
    snap["fee_decimals"] = 18  # what ChainRegistry returns on Sepolia
    shown = format_dega_amount(snap["fee_weega"], decimals=snap["fee_decimals"])
    assert shown == "0.00000000005"
    assert reg.fee_decimals() == 8  # test backend keeps the default
