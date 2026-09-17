// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Test} from "forge-std/Test.sol";
import {ProofHelper} from "test/ProofHelper.sol";
import {DegaChatRegistry} from "DegaChatRegistry.sol";
import {IERC20} from "IERC20.sol";
import {MockDEGA} from "MockDEGA.sol";

contract RegistrationExpiryTest is ProofHelper {
    MockDEGA token;
    DegaChatRegistry registry;
    bytes key;

    function setUp() public {
        key = _pub(1);
        vm.warp(1000);
        token = new MockDEGA();
        registry = new DegaChatRegistry(IERC20(address(token)), 10, 3, 100);
        token.mint(address(this), 1000);
        token.approve(address(registry), 1000);
        registry.openNode("alice", key, _proof(registry, "alice", 1));
        registry.invite("alice", address(22));
    }

    function testExpiryBoundaryAndRecovery() public {
        vm.warp(1099);
        assertTrue(registry.isActive("alice.dega"));
        vm.warp(1100);
        assertFalse(registry.isActive("alice"));
        assertEq(registry.resolveNostrPubkey("alice"), bytes(""));
        assertEq(registry.usernameForPubkey(key), "");
        assertEq(registry.usernameOfOwner(address(this)), "");
        assertEq(registry.nodeOwnerOf("alice"), address(0));
        assertFalse(registry.isMemberOf("alice", address(this)));
        assertEq(registry.memberCountOf("alice"), 0);
        vm.expectRevert("DegaChatRegistry: node inactive");
        registry.members("alice", 0);
        vm.expectRevert("DegaChatRegistry: node inactive");
        registry.invite("alice", address(33));
        assertTrue(registry.usernameTaken("alice.dega"));
        (string memory name, address owner,, uint256 expiry, uint256 count, bool active,) =
            registry.registrationOfOwner(address(this));
        assertEq(name, "alice");
        assertEq(owner, address(this));
        assertEq(expiry, 1100);
        assertEq(count, 2);
        assertFalse(active);
        registry.renewNode("alice.dega", 1100, 10, 100);
        assertEq(registry.resolveNostrPubkey("alice"), key);
        assertEq(registry.usernameForPubkey(key), "alice");
        assertEq(registry.usernameOfOwner(address(this)), "alice");
        assertTrue(registry.isMemberOf("alice", address(22)));
        assertEq(token.balanceOf(address(registry)), 0);
        assertEq(token.totalSupply(), 980);
    }

    function testEarlyAndLateRenewal() public {
        registry.renewNode("alice", 1100, 10, 100);
        (,,, uint256 expiry,,,) = registry.registrationOfOwner(address(this));
        assertEq(expiry, 1200);
        vm.warp(1300);
        registry.renewNode("alice", 1200, 10, 100);
        (,,, expiry,,,) = registry.registrationOfOwner(address(this));
        assertEq(expiry, 1400);
    }

    function testDynamicTermsDoNotChangeExistingExpiry() public {
        registry.setRegistrationTTL(200);
        registry.setFee(0);
        (,,, uint256 expiry,,,) = registry.registrationOfOwner(address(this));
        assertEq(expiry, 1100);
        registry.renewNode("alice", 1100, 0, 200);
        (,,, expiry,,,) = registry.registrationOfOwner(address(this));
        assertEq(expiry, 1300);
        assertEq(token.balanceOf(address(registry)), 0);
        assertEq(token.totalSupply(), 990);
    }

    function testStaleRenewalCannotChargeTwice() public {
        registry.renewNode("alice", 1100, 10, 100);
        vm.expectRevert("DegaChatRegistry: stale renewal");
        registry.renewNode("alice", 1100, 10, 100);
        assertEq(token.balanceOf(address(registry)), 0);
        assertEq(token.totalSupply(), 980);
    }

    function testChangedTermsRequireAnotherConfirmation() public {
        registry.setFee(11);
        vm.expectRevert("DegaChatRegistry: fee changed");
        registry.renewNode("alice", 1100, 10, 100);
        registry.setRegistrationTTL(99);
        vm.expectRevert("DegaChatRegistry: TTL changed");
        registry.renewNode("alice", 1100, 11, 100);
    }

    function testPaymentFailureRollsBackExpiry() public {
        token.approve(address(registry), 0);
        vm.expectRevert();
        registry.renewNode("alice", 1100, 10, 100);
        (,,, uint256 expiry,,,) = registry.registrationOfOwner(address(this));
        assertEq(expiry, 1100);
        assertEq(token.balanceOf(address(registry)), 0);
        assertEq(token.totalSupply(), 990);
    }

    function testUnauthorizedAndZeroDurationRejected() public {
        vm.prank(address(77));
        vm.expectRevert("DegaChatRegistry: only node owner renews");
        registry.renewNode("alice", 1100, 10, 100);
        vm.prank(address(77));
        vm.expectRevert("DegaChatRegistry: not owner");
        registry.setRegistrationTTL(10);
        vm.expectRevert("DegaChatRegistry: TTL must be positive");
        registry.setRegistrationTTL(0);
        vm.expectRevert("DegaChatRegistry: TTL must be positive");
        new DegaChatRegistry(IERC20(address(token)), 0, 10, 0);
    }

    function testExpiredNameAndPubkeyRemainReserved() public {
        registry.setFee(0);
        vm.warp(1200);
        vm.prank(address(77));
        vm.expectRevert("DegaChatRegistry: username taken");
        registry.openNode("alice", key, _proof(registry, "alice", 1));
        vm.prank(address(77));
        vm.expectRevert("DegaChatRegistry: pubkey taken");
        registry.openNode("bob", key, _proof(registry, "bob", 1));
    }

    function testFuzzExpiryAndRenewal(uint32 duration, uint32 elapsed) public {
        uint256 ttl = bound(duration, 1, 3650 days);
        registry.setRegistrationTTL(ttl);
        vm.warp(1000 + uint256(elapsed));
        assertEq(registry.isActive("alice"), elapsed < 100);
        registry.renewNode("alice", 1100, 10, ttl);
        (,,, uint256 expiry,,,) = registry.registrationOfOwner(address(this));
        assertEq(expiry, (block.timestamp > 1100 ? block.timestamp : 1100) + ttl);
    }
}

contract CallbackToken is IERC20 {
    DegaChatRegistry registry;
    bool public reentered;
    uint8 public constant override decimals = 18;

    function configure(DegaChatRegistry target, bytes calldata pubkey, bytes calldata proof)
        external
    {
        registry = target;
        target.openNode("callback", pubkey, proof);
    }

    function renew() external {
        (,,, uint256 expiry,,,) = registry.registrationOfOwner(address(this));
        registry.renewNode("callback", expiry, 1, 100);
    }

    function balanceOf(address) external pure returns (uint256) {
        return 100;
    }

    function allowance(address, address) external pure returns (uint256) {
        return 100;
    }

    function approve(address, uint256) external pure returns (bool) {
        return true;
    }

    function transfer(address, uint256) external pure returns (bool) {
        return true;
    }

    function burnFrom(address, uint256) external {
        _tryReenter();
    }

    function transferFrom(address, address, uint256) external returns (bool) {
        _tryReenter();
        return true;
    }

    function _tryReenter() private {
        (,,, uint256 expiry,,,) = registry.registrationOfOwner(address(this));
        try registry.renewNode("callback", expiry, 1, 100) {
            reentered = true;
        } catch {}
    }
}

contract RenewalReentrancyTest is ProofHelper {
    function testFeeCallbackCannotRenewAgain() public {
        CallbackToken token = new CallbackToken();
        DegaChatRegistry registry = new DegaChatRegistry(token, 0, 3, 100);
        token.configure(registry, _pub(1), _proofFor(registry, "callback", 1, address(token)));
        registry.setFee(1);
        token.renew();
        assertFalse(token.reentered());
        (,,, uint256 expiry,,,) = registry.registrationOfOwner(address(token));
        assertEq(expiry, block.timestamp + 200);
    }
}
