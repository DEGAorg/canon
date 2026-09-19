# Nostr registration ownership

Registration remains a direct wallet-to-registry transaction. Canon signs an EIP-712
Registration(wallet, username, nostrPubkey) message using the active local Nostr
secp256k1 secret. The domain binds chain ID, registry address, name DegaChatRegistry,
and version 1. Username is canonicalized identically to registration.

The proof carries the full public key's Y coordinate and a standard 65-byte ECDSA
signature. The registry checks the point lies on secp256k1, hashes its full public
key to an Ethereum address, and checks standard ecrecover against that address.
Both valid Y parities are accepted: Nostr's x-only identity represents either
secret d or n-d. Signatures must use canonical low S and v=27/28.

The wallet, username, chain, and registry bindings prevent front-running or replay
by another account, chain, or deployment. Each wallet and key can register only
once, even after expiry. There is no deletion or replacement, so no extra nonce
is required. Renewal uses the registered wallet and does not replace the key.

No backend approval, new cryptography library, or private-key transmission is
introduced. The existing eth-account/eth-keys stack signs locally. Missing or
mismatched local signing identity fails before token approval. Registration now
requires a Nostr identity; empty keys are rejected. The ABI changes and requires
a new registry deployment coordinated with the client release. Fee burning and
TTL behavior are unchanged.

References: EIP-712 https://eips.ethereum.org/EIPS/eip-712;
Solidity ecrecover https://docs.soliditylang.org/en/latest/units-and-global-variables.html;
BIP-340 x-only keys https://github.com/bitcoin/bips/blob/master/bip-0340.mediawiki.
