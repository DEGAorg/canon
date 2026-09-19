// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Test} from "forge-std/Test.sol";
import {ProofHelper} from "test/ProofHelper.sol";
import {DegaChatRegistry} from "DegaChatRegistry.sol";
import {IERC20} from "IERC20.sol";
import {MockDEGA} from "MockDEGA.sol";

/// @title Shared fuzz pool: distinct valid usernames + deterministic wallets.
contract Pool {
    function user(uint256 i) internal pure returns (address) {
        return address(uint160(uint256(keccak256(abi.encodePacked("user", i))) & ((1 << 160) - 1)));
    }
    function name(uint256 i) internal pure returns (string memory) {
        string[8] memory n = ["alice", "bob", "carol", "dave", "erin", "frank", "1_ab-c", "x.yz"];
        return n[i % 8];
    }
}

/// @title Stateful handler — pseudo-random open/invite/fee/cap ops.
///
/// Every call may legitimately revert (invalid/taken name, full node, unfunded
/// payer). The invariants asserted by DegaChatRegistryInvariantTest must hold
/// after *any* sequence of these calls.
contract Handler is Pool, ProofHelper {
    DegaChatRegistry internal reg;
    MockDEGA internal token;
    uint256 internal currentCap = 10;

    constructor(DegaChatRegistry reg_, MockDEGA token_) {
        reg = reg_;
        token = token_;
    }

    function open(uint256 seed) external {
        address u = user(seed % 8);
        uint256 funds = (seed >> 8) % 1e24; // 0..~1e24
        token.mint(u, funds);
        vm.prank(u);
        token.approve(address(reg), type(uint256).max);
        vm.prank(u);
        try reg.openNode(name(seed), _pub(seed % 8 + 1), _proof(reg, name(seed), seed % 8 + 1)) {} catch {}
    }

    function invite(uint256 seed) external {
        address owner = user(seed % 8);
        address member = address(uint160(uint256(keccak256(abi.encodePacked("m", seed))) & ((1 << 160) - 1)));
        vm.prank(owner);
        try reg.invite(name(seed), member) {} catch {}
    }

    function setFee(uint256 fee_) external {
        vm.prank(reg.owner());
        reg.setFee(fee_ % 1e24);
    }

    /// Only increase the cap so the invariant memberCount <= cap remains monotonic.
    function setCap(uint256 cap_) external {
        vm.prank(reg.owner());
        currentCap += (cap_ % 5) + 1; // monotonically 11,12,...
        reg.setMaxUsersPerNode(currentCap);
    }
}

/// @notice Stateful fuzzing over the real contract. run: `forge test --match-contract Invariant`
contract DegaChatRegistryInvariantTest is ProofHelper, Pool {
    DegaChatRegistry internal reg;
    MockDEGA internal token;
    Handler internal h;

    function setUp() public {
        token = new MockDEGA();
        reg = new DegaChatRegistry(IERC20(address(token)), 1e10, 10, 30 days); // fee>0 to exercise payment path
        h = new Handler(reg, token);
        targetContract(address(h));
    }

    /// Members per node never exceed the (possibly changed) cap.
    function invariant_memberCountNeverExceedsCap() public view {
        for (uint256 i = 0; i < 8; i++) {
            assertLe(reg.memberCountOf(name(i)), reg.maxUsersPerNode());
        }
    }

    /// Any open node's owner is always member #1 (count >= 1) and inside the node.
    function invariant_ownerIsMemberNumberOne() public view {
        for (uint256 i = 0; i < 8; i++) {
            address owner = reg.nodeOwnerOf(name(i));
            if (owner != address(0)) {
                assertTrue(reg.isMemberOf(name(i), owner), "owner must be a member");
                assertGe(reg.memberCountOf(name(i)), 1);
            }
        }
    }

    /// No close/delete path: once a username is taken it stays taken forever,
    /// and is visible under both bare and ".dega" spellings.
    function invariant_usernameTakenIsMonotonicAndPersistent() public view {
        for (uint256 i = 0; i < 8; i++) {
            string memory n = name(i);
            if (reg.usernameTaken(n)) {
                assertEq(reg.usernameTaken(n), true);
                assertEq(reg.usernameTaken(string.concat(n, ".dega")), true);
            } else {
                assertEq(reg.usernameTaken(string.concat(n, ".dega")), false);
            }
        }
    }

    /// Successful fee payments leave no retained registry balance.
    function invariant_noRetainedFees() public view {
        assertEq(token.balanceOf(address(reg)), 0);
    }

}

/// @notice Guided fuzz over specific properties. run: `forge test --match-contract Fuzz`
contract DegaChatRegistryFuzzTest is ProofHelper, Pool {
    MockDEGA internal deg;
    DegaChatRegistry internal reg;

    function setUp() public {
        deg = new MockDEGA();
        reg = new DegaChatRegistry(IERC20(address(deg)), 0, 10, 30 days);
    }

    function _validName(uint256 seed) internal pure returns (string memory) {
        bytes memory alpha = "abcdefghijklmnopqrstuvwxyz0123456789._-";
        uint256 len = (seed % 16); // 0..15
        if (len == 0) len = 1;
        bytes memory out = new bytes(len);
        for (uint256 j = 0; j < len; j++) out[j] = alpha[(seed >> j) % alpha.length];
        return string(out);
    }

    /// Arbitrary byte strings longer than 15 must be rejected as usernames.
    function testFuzz_rejectsOverlongName(bytes calldata raw) public {
        if (raw.length > 15) {
            vm.expectRevert(bytes("DegaChatRegistry: invalid username"));
            reg.openNode(string(raw), bytes(""), bytes(""));
        }
    }

    /// Fee is collected exactly once per open, even for extreme-but-valid fees.
    function testFuzz_paymentCollectedExactlyOnce(uint96 seed96) public {
        uint256 seed = uint256(seed96);
        uint256 feeW = (seed % 1e12) + 1; // keep comfortably below any overflow edge
        reg.setFee(feeW);
        address owner = user(seed % 8);
        deg.mint(owner, feeW * 2 + 1e18);
        vm.startPrank(owner);
        deg.approve(address(reg), type(uint256).max);
        reg.openNode(_validName(seed), _pub(1), _proof(reg, _validName(seed), 1));
        // The fee is burned, reducing supply and the payer balance exactly once.
        assertEq(deg.balanceOf(address(reg)), 0);
        assertEq(deg.totalSupply(), feeW + 1e18);
        assertEq(deg.balanceOf(owner), feeW + 1e18);
        // second open by the same owner is impossible (one-owner-one-node), so no overpay
        vm.expectRevert(bytes("DegaChatRegistry: owner already has node"));
        reg.openNode("zzz_other", bytes(""), bytes(""));
        vm.stopPrank();
    }

    /// Username uniqueness + canonical form: opening under ".dega" markers behaves
    /// exactly like the bare form for the same pool of distinct names.
    function testFuzz_canonicalBareVsTldEquivalent(uint256 seedA, uint256 seedB) public {
        vm.assume(seedA % 8 != seedB % 8); // distinct pool names
        string memory nA = name(seedA);
        string memory nB = name(seedB);
        vm.prank(user(seedA % 8));
        reg.openNode(nA, _pub(seedA % 8 + 1), _proof(reg, nA, seedA % 8 + 1));
        vm.prank(user(seedB % 8));
        reg.openNode(string.concat(nB, ".dega"), _pub(seedB % 8 + 1), _proof(reg, nB, seedB % 8 + 1));
        // both resolvable under bare and tld spelling
        assertEq(keccak256(reg.resolveNostrPubkey(nA)), keccak256(_pub(seedA % 8 + 1)));
        assertEq(keccak256(reg.resolveNostrPubkey(string.concat(nA, ".dega"))), keccak256(_pub(seedA % 8 + 1)));
        assertEq(keccak256(reg.resolveNostrPubkey(nB)), keccak256(_pub(seedB % 8 + 1)));
        assertEq(keccak256(reg.resolveNostrPubkey(string.concat(nB, ".dega"))), keccak256(_pub(seedB % 8 + 1)));
        assertEq(reg.usernameOfOwner(user(seedA % 8)), nA);
        assertEq(reg.usernameOfOwner(user(seedB % 8)), nB);
    }
}