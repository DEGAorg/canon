// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {IERC20} from "./IERC20.sol";

/// @notice Mintable $DEGA stand-in for TESTNET deployments only.
///
/// The real $DEGA token lives on Ethereum **mainnet** at
/// 0x97aeE01ed2aabAd9F54692f94461AE761D225f17 (18 decimals, no minting by us).
/// On a testnet there is no real asset, so this contract gives the chat an
/// ERC-20 to collect the fee while validating the whole flow on Sepolia/Holesky
/// etc. It is a drop-in `IERC20` (same 18-decimal scale) so `DegaChatRegistry`
/// needs no changes. **Never deploy this to mainnet.**
contract MockDEGA is IERC20 {
    string public name = "Mock DEGA";
    string public symbol = "DEGA";
    uint8 public constant override decimals = 18;

    mapping(address => uint256) public override balanceOf;
    mapping(address => mapping(address => uint256)) public override allowance;
    uint256 public totalSupply;

    /// Mint test tokens to an address (caller can be anyone — it's a testnet mock).
    function mint(address to, uint256 amount) external {
        totalSupply += amount;
        balanceOf[to] += amount;
    }

    function burnFrom(address account, uint256 amount) external {
        uint256 approved = allowance[account][msg.sender];
        require(approved >= amount, "MockDEGA: insufficient allowance");
        require(balanceOf[account] >= amount, "MockDEGA: insufficient balance");
        if (approved != type(uint256).max) {
            allowance[account][msg.sender] = approved - amount;
        }
        balanceOf[account] -= amount;
        totalSupply -= amount;
    }

    function transfer(address to, uint256 amount) external override returns (bool) {
        require(balanceOf[msg.sender] >= amount, "MockDEGA: insufficient balance");
        balanceOf[msg.sender] -= amount;
        balanceOf[to] += amount;
        return true;
    }

    function approve(address spender, uint256 amount) external override returns (bool) {
        allowance[msg.sender][spender] = amount;
        return true;
    }

    function transferFrom(address from, address to, uint256 amount)
        external
        override
        returns (bool)
    {
        require(balanceOf[from] >= amount, "MockDEGA: insufficient balance");
        require(allowance[from][msg.sender] >= amount, "MockDEGA: insufficient allowance");
        balanceOf[from] -= amount;
        balanceOf[to] += amount;
        allowance[from][msg.sender] -= amount;
        return true;
    }
}
