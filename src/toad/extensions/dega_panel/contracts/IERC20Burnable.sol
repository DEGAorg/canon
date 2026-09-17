// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @notice Allowance-authorized burning, as provided by DEGA's ERC20Burnable.
interface IERC20Burnable {
    function burnFrom(address account, uint256 amount) external;
}
