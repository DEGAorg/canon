# Atomic registration fee burning

Status: Approved. User authorized implementation of direct allowance-authorized burning on 2026-09-17.

DEGAorg/ERC20 contracts/DegaToken.sol inherits OpenZeppelin ERC20Burnable. The
registry calls burnFrom(payer, fee) directly against the payer's approved balance. Registration and renewal share this path and the existing reentrancy guard.
Zero-fee operations do not call the token. Failed burn reverts all
registration/renewal state, allowance, balances and emitted logs in the transaction.
Only the current fee is burned; unsolicited token deposits are untouched.

Remove withdrawFees and FeesWithdrawn. Emit FeeBurned(payer, amount) after a
successful burn. No permissionless deferred burn endpoint or new approval is needed.
The existing wallet allowance is still required for burnFrom. Constructor,
registration/renewal arguments, fee units and TTL behavior remain unchanged.

Acceptance: totalSupply and payer balance decrease by the fee; registry fee balance
remains zero; renewal burns again; zero fees skip burning; failed burn rolls back
new registration and renewal; token callbacks cannot reenter. Verify compatibility
with the actual mainnet token on an isolated fork. Deploy to Sepolia for user testing; do not deploy mainnet.

Token source reviewed: DEGAorg/ERC20 commit
`2b9a2c330df5c45a81d236d0172f76f900982ff8`, contracts/DegaToken.sol.
