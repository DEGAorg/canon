// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Script, console2} from "forge-std/Script.sol";
import {DegaChatRegistry} from "DegaChatRegistry.sol";
import {MockDEGA} from "MockDEGA.sol";
import {IERC20} from "IERC20.sol";

/// @notice TESTNET deployment: deploys a mintable MockDEGA + the chat registry.
///
/// The real $DEGA token only exists on Ethereum **mainnet** (18 decimals).
/// To exercise the chat fee flow on a testnet (Sepolia/Holesky) we first deploy
/// a `MockDEGA` (mintable, same 18-decimal scale) and a `DegaChatRegistry`
/// pointing at it. Set INITIAL_FEE_WEEGA=0 for the free tier; no test tokens are needed
/// to open a node initially; `setFee` on-chain later enables the fee path.
///
/// Usage (testnet for Sepolia):
///
///     forge script script/DeployTestnet.s.sol:DeployTestnet \
///       --rpc-url $SEPOLIA_RPC --broadcast --private-key $PK \
///       --sig "run()"
///
/// After the broadcast, look at:
///   - `MockDEGA` address  -> mint test $DEGA with the mock's `mint` if a nonzero fee is wanted
///   - `DegaChatRegistry` address -> the chat nodes' home
///
/// **Never run on mainnet** — use `Deploy.s.sol` there with the real token
/// 0x97aeE01ed2aabAd9F54692f94461AE761D225f17.
contract DeployTestnet is Script {
    function run() external {
        uint256 pk = vm.envUint("PRIVATE_KEY");
        uint256 initialFeeWeega = vm.envUint("INITIAL_FEE_WEEGA");
        uint256 maxUsersPerNode = vm.envOr("MAX_USERS_PER_NODE", uint256(10));
        uint256 ttl = vm.envUint("REGISTRATION_TTL_SECONDS");
        vm.startBroadcast(pk);

        MockDEGA mock = new MockDEGA();
        DegaChatRegistry reg =
            new DegaChatRegistry(IERC20(address(mock)), initialFeeWeega, maxUsersPerNode, ttl);

        vm.stopBroadcast();
        console2.log("  registrationTTL    :", ttl);

        console2.log("MockDEGA deployed at     :", address(mock));
        console2.log("DegaChatRegistry deployed:", address(reg));
        console2.log("  degaToken (mock)   :", address(mock));
        console2.log("  fee (weega)        :", initialFeeWeega);
        console2.log("  maxUsersPerNode    :", maxUsersPerNode);
        console2.log("");
        console2.log("To test the fee path, mint + approve:");
        console2.log(
            "  cast send <MOCKDEGA> \"mint(address,uint256)\" $YOU 1000000000000000000000 --rpc-url $SEPOLIA_RPC --private-key $PK"
        );
        console2.log(
            "  cast send <MOCKDEGA> \"approve(address,uint256)\" <REGISTRY> 1000000000000000000000 --rpc-url $SEPOLIA_RPC --private-key $PK"
        );
        console2.log("  then registry.setFee(<N>) by the registry owner.");
    }
}
