# Sepolia burnFrom registry — 2026-09-17

> Historical testnet evidence; current defaults use the [production registry](contracts.md).

Source commit: `2b00cb2` (PR #16).

- Chain: Sepolia, 11155111.
- Registry: `0x2D69074C1ceCe968529CdC08162B31700F7Aed4A`.
- MockDEGA: `0x4D55b1B62EdF27a8154F7bD810a3EcCEd6326896` (18 decimals).
- Fee: 1 MockDEGA (`1000000000000000000` raw).
- Registration TTL: 31,536,000 seconds (365 days).
- Node cap: 10.

The previous MockDEGA does not expose burnFrom, so this deployment uses a new
mock. Existing token balances and registrations stay on the previous contracts.
The client ABI is unchanged from the ownership-proof release (PR #14).

Validation: 41 unit/fuzz/mainnet-fork tests and four invariant tests passed.
The fork test exercised registration and renewal against the real mainnet DEGA
at `0x97aeE01ed2aabAd9F54692f94461AE761D225f17`. No mainnet transactions were sent.
Live Sepolia registration and renewal tests are left to the user.

Registry deployment transaction:
`0x00cac468cab70fe96020744b0a794e973448b82f8e93a2cc7797ecd0161324d2`

Mock deployment transaction:
`0x50e1f79ac98bd4ee4e914480bfb8dd5706038f20eb3422666dac7c40993ccd4a`

Explicit testnet configuration (token is read from the registry):

```dotenv
DEGA_CHAT_BACKEND=chain
DEGA_CHAT_RPC=https://ethereum-sepolia-rpc.publicnode.com
DEGA_CHAT_REGISTRY=0x2D69074C1ceCe968529CdC08162B31700F7Aed4A
```

Restart Canon, approve the new registry to spend the new mock token, then register.

Deployment receipts and runtime bytecode were verified against the compiled build.
The configured testing wallet `0x92f961c10a199C79fA05A17aAF57181968cf742d`
received 100 new MockDEGA for manual testing.
