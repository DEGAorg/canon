// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Test} from "forge-std/Test.sol";
import {ProofHelper} from "test/ProofHelper.sol";
import {DegaChatRegistry} from "DegaChatRegistry.sol";
import {IERC20} from "IERC20.sol";
import {IERC20Burnable} from "IERC20Burnable.sol";
import {MockDEGA} from "MockDEGA.sol";

contract FeeBurnTest is ProofHelper {
    MockDEGA token;
    DegaChatRegistry registry;
    bytes key;

    event FeeBurned(address indexed payer, uint256 amount);

    function setUp() public {
        key = _pub(1);
        token = new MockDEGA();
        registry = new DegaChatRegistry(token, 10, 10, 100);
        token.mint(address(this), 1000);
        token.approve(address(registry), 1000);
    }

    function testRegistrationAndRenewalBurnCurrentFee() public {
        vm.expectEmit(true, false, false, true, address(registry));
        emit FeeBurned(address(this), 10);
        registry.openNode("alice", key, _proof(registry, "alice", 1));
        assertEq(token.totalSupply(), 990);
        assertEq(token.balanceOf(address(this)), 990);
        assertEq(token.balanceOf(address(registry)), 0);
        (,,, uint256 expiry,,,) = registry.registrationOfOwner(address(this));
        registry.setFee(25);
        registry.renewNode("alice", expiry, 25, 100);
        assertEq(token.totalSupply(), 965);
        assertEq(token.balanceOf(address(this)), 965);
        assertEq(token.balanceOf(address(registry)), 0);
    }

    function testInsufficientAllowanceRollsBackRegistration() public {
        token.approve(address(registry), 9);
        vm.expectRevert(bytes("MockDEGA: insufficient allowance"));
        registry.openNode("alice", key, _proof(registry, "alice", 1));
        assertFalse(registry.usernameTaken("alice"));
        assertEq(token.totalSupply(), 1000);
        assertEq(token.allowance(address(this), address(registry)), 9);
    }

    function testInsufficientBalanceRollsBackRegistration() public {
        registry.setFee(1001);
        token.approve(address(registry), 1001);
        vm.expectRevert(bytes("MockDEGA: insufficient balance"));
        registry.openNode("alice", key, _proof(registry, "alice", 1));
        assertFalse(registry.usernameTaken("alice"));
        assertEq(token.allowance(address(this), address(registry)), 1001);
    }

    function testInfiniteAllowanceIsPreserved() public {
        token.approve(address(registry), type(uint256).max);
        registry.openNode("alice", key, _proof(registry, "alice", 1));
        assertEq(token.allowance(address(this), address(registry)), type(uint256).max);
    }

    function testFeeDoesNotTransferTokensToRegistry() public {
        vm.mockCallRevert(
            address(token), abi.encodePacked(IERC20.transferFrom.selector), "transfer called"
        );
        registry.openNode("alice", key, _proof(registry, "alice", 1));
        (,,, uint256 expiry,,,) = registry.registrationOfOwner(address(this));
        registry.renewNode("alice", expiry, 10, 100);
        assertEq(token.totalSupply(), 980);
        assertEq(token.allowance(address(this), address(registry)), 980);
    }

    function testRevertingBurnRollsBackRegistration() public {
        vm.mockCallRevert(
            address(token),
            abi.encodeCall(IERC20Burnable.burnFrom, (address(this), 10)),
            "burn failed"
        );
        vm.expectRevert(bytes("burn failed"));
        registry.openNode("alice", key, _proof(registry, "alice", 1));
        assertFalse(registry.usernameTaken("alice"));
        assertEq(registry.usernameOfOwner(address(this)), "");
        assertEq(registry.usernameForPubkey(key), "");
        assertEq(token.balanceOf(address(this)), 1000);
        assertEq(token.balanceOf(address(registry)), 0);
        assertEq(token.allowance(address(this), address(registry)), 1000);
        assertEq(token.totalSupply(), 1000);
        vm.clearMockedCalls();
        registry.openNode("alice", key, _proof(registry, "alice", 1));
        assertTrue(registry.isActive("alice"));
    }

    function testRevertingBurnRollsBackRenewal() public {
        registry.openNode("alice", key, _proof(registry, "alice", 1));
        (,,, uint256 expiry,,,) = registry.registrationOfOwner(address(this));
        vm.mockCallRevert(
            address(token),
            abi.encodeCall(IERC20Burnable.burnFrom, (address(this), 10)),
            "burn failed"
        );
        vm.expectRevert(bytes("burn failed"));
        registry.renewNode("alice", expiry, 10, 100);
        (,,, uint256 afterExpiry,,,) = registry.registrationOfOwner(address(this));
        assertEq(afterExpiry, expiry);
        assertEq(token.balanceOf(address(this)), 990);
        assertEq(token.allowance(address(this), address(registry)), 990);
        assertEq(token.balanceOf(address(registry)), 0);
        assertEq(token.totalSupply(), 990);
    }

    function testZeroFeeSkipsTokenCalls() public {
        registry.setFee(0);
        vm.mockCallRevert(
            address(token), abi.encodePacked(IERC20Burnable.burnFrom.selector), "burn called"
        );
        vm.mockCallRevert(
            address(token), abi.encodePacked(IERC20.transferFrom.selector), "transfer called"
        );
        registry.openNode("alice", key, _proof(registry, "alice", 1));
        (,,, uint256 expiry,,,) = registry.registrationOfOwner(address(this));
        registry.renewNode("alice", expiry, 0, 100);
        assertEq(token.totalSupply(), 1000);
    }

    function testUnsolicitedDepositIsNotBurnedWithFee() public {
        token.transfer(address(registry), 50);
        registry.openNode("alice", key, _proof(registry, "alice", 1));
        assertEq(token.balanceOf(address(registry)), 50);
        assertEq(token.totalSupply(), 990);
    }
}

contract MainnetFeeBurnTest is ProofHelper {
    function testRealDegaRegistrationAndRenewal() public {
        string memory rpc = vm.envOr("DEGA_MAINNET_RPC", string(""));
        if (bytes(rpc).length == 0) {
            vm.skip(true);
            return;
        }
        vm.createSelectFork(rpc);
        address dega = 0x97aeE01ed2aabAd9F54692f94461AE761D225f17;
        IERC20 token = IERC20(dega);
        uint256 fee = 6_719_270 * 1e18;
        DegaChatRegistry registry = new DegaChatRegistry(token, fee, 10, 365 days);
        deal(dega, address(this), fee * 2, true);
        (bool ok, bytes memory result) = dega.staticcall(abi.encodeWithSignature("totalSupply()"));
        assertTrue(ok);
        uint256 supply = abi.decode(result, (uint256));
        token.approve(address(registry), fee * 2);
        registry.openNode("burntest", _pub(1), _proof(registry, "burntest", 1));
        (,,, uint256 expiry,,,) = registry.registrationOfOwner(address(this));
        registry.renewNode("burntest", expiry, fee, 365 days);
        assertEq(token.balanceOf(address(this)), 0);
        assertEq(token.balanceOf(address(registry)), 0);
        (, result) = dega.staticcall(abi.encodeWithSignature("totalSupply()"));
        assertEq(abi.decode(result, (uint256)), supply - fee * 2);
        assertTrue(registry.isActive("burntest"));
    }
}
