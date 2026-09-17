// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Script, console2} from "forge-std/Script.sol";
import {DegaChatRegistry} from "DegaChatRegistry.sol";
import {IERC20} from "IERC20.sol";

/// @notice One-shot deployment of the chat node registry.
///
/// Deploy with the $DEGA token address, an initial (parametrizable) fee and the
/// per-node cap:
///
///     forge script script/Deploy.s.sol:DeployChatRegistry \
///       --rpc-url $RPC --broadcast --private-key $PK \
///       --sig "run(address,uint256,uint256,uint256)" \
///       $DEGA_TOKEN_ADDRESS $INITIAL_FEE_WEEGA $MAX_USERS_PER_NODE $REGISTRATION_TTL_SECONDS
///
/// A zero fee deploys the free tier (good for staging/demos); `setFee` on-chain
/// later changes it without a redeploy — the fee is parametrizable at runtime.
contract DeployChatRegistry is Script {
    // virtual: override in a deployment-specific script for prod vectors.
    function run(
        address degaToken,
        uint256 initialFeeWeega,
        uint256 maxUsersPerNode,
        uint256 registrationTTL
    ) external {
        uint256 pk = vm.envUint("PRIVATE_KEY");
        vm.startBroadcast(pk);
        DegaChatRegistry reg = new DegaChatRegistry(
            IERC20(degaToken), initialFeeWeega, maxUsersPerNode, registrationTTL
        );
        vm.stopBroadcast();
        console2.log("  registrationTTL  :", registrationTTL);
        console2.log("DegaChatRegistry deployed at:", address(reg));
        console2.log("  degaToken        :", degaToken);
        console2.log("  initialFee (weega):", initialFeeWeega);
        console2.log("  maxUsersPerNode  :", maxUsersPerNode);
    }
}
