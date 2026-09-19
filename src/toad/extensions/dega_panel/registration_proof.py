"""Local EIP-712 ownership proof for the active Nostr identity."""

from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_keys import keys


def registration_proof(
    secret_hex: str,
    pubkey: bytes,
    *,
    wallet: str,
    username: str,
    chain_id: int,
    registry: str,
) -> bytes:
    """Sign a registration bound to its wallet, name, chain, and contract.

    Raises:
        ValueError: The secret does not belong to the requested Nostr identity.
    """
    try:
        secret = bytes.fromhex(secret_hex.removeprefix("0x"))
    except ValueError:
        raise ValueError("Invalid local Nostr signing key") from None
    order = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
    if len(secret) != 32 or not 0 < int.from_bytes(secret, "big") < order:
        raise ValueError("Invalid local Nostr signing key")
    public = keys.PrivateKey(secret).public_key.to_bytes()
    if len(pubkey) != 32 or public[:32] != pubkey:
        raise ValueError("Active Nostr signing key does not match the registration identity")
    message = encode_typed_data(
        domain_data={
            "name": "DegaChatRegistry",
            "version": "1",
            "chainId": chain_id,
            "verifyingContract": registry,
        },
        message_types={
            "Registration": [
                {"name": "wallet", "type": "address"},
                {"name": "username", "type": "string"},
                {"name": "nostrPubkey", "type": "bytes32"},
            ]
        },
        message_data={"wallet": wallet, "username": username, "nostrPubkey": pubkey},
    )
    return public[32:] + bytes(Account.sign_message(message, private_key=secret).signature)
