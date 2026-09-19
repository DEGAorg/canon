// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Test} from "forge-std/Test.sol";
import {ProofHelper} from "test/ProofHelper.sol";
import {DegaChatRegistry} from "DegaChatRegistry.sol";
import {IERC20} from "IERC20.sol";

import {MockDEGA} from "MockDEGA.sol";

contract DegaChatRegistryTest is ProofHelper {
    MockDEGA deg;
    DegaChatRegistry reg;
    address payer = address(0xA11CE);
    // a 32-byte (64 hex) Nostr pubkey stand-in
    bytes32 PUBKEY;

    function setUp() public {
        PUBKEY = bytes32(_pub(1));
        deg = new MockDEGA();
        reg = new DegaChatRegistry(IERC20(address(deg)), 0, 3, 30 days); // fee 0, max 3
        deg.mint(payer, 1_000_000_000e8);
    }

    function testOpenNodeFreeTierWithPubkey() public {
        reg.openNode("pavel", abi.encodePacked(PUBKEY), _proof(reg, "pavel", 1));
        assertEq(reg.nodeOwnerOf("pavel"), address(this));
        assertTrue(reg.isMemberOf("pavel", address(this)));
        assertEq(reg.memberCountOf("pavel"), 1);
        // pubkey stored + resolvable by bare and by "pavel.dega"
        assertEq(keccak256(reg.resolveNostrPubkey("pavel")), keccak256(abi.encodePacked(PUBKEY)));
        assertEq(
            keccak256(reg.resolveNostrPubkey("pavel.dega")), keccak256(abi.encodePacked(PUBKEY))
        );
        assertEq(keccak256(reg.resolveNostrPubkey("pavel")), keccak256(abi.encodePacked(PUBKEY)));
        assertTrue(reg.usernameTaken("pavel.dega"));
    }

    function testParametrizableFeeRequiresPayment() public {
        reg.setFee(5_000_000e8); // parametrizable fee
        assertEq(reg.fee(), 5_000_000e8);
        vm.prank(payer);
        deg.approve(address(reg), 5_000_000e8);
        vm.prank(payer);
        reg.openNode("carlos", abi.encodePacked(PUBKEY), _proof(reg, "carlos", 1));
        assertEq(reg.nodeOwnerOf("carlos"), payer);
        assertEq(deg.balanceOf(address(reg)), 0);
        assertEq(deg.totalSupply(), 1_000_000_000e8 - 5_000_000e8);
    }

    function testUsernameRejected() public {
        vm.expectRevert();
        reg.openNode(
            "este_nombre_es_demasiado_largo_para_15",
            abi.encodePacked(PUBKEY),
            _proof(reg, "este_nombre_es_demasiado_largo_para_15", 1)
        ); // >15 chars
    }

    function testUniqueUsername() public {
        reg.openNode("pavel", abi.encodePacked(PUBKEY), _proof(reg, "pavel", 1));
        // A different owner cannot take an already-registered username.
        vm.prank(address(0xABABA));
        vm.expectRevert(bytes("DegaChatRegistry: username taken"));
        reg.openNode("pavel", abi.encodePacked(PUBKEY), _proof(reg, "pavel", 1));
    }

    function testInviteRespectsDefaultCap() public {
        reg.setFee(0);
        reg.openNode("nodo", abi.encodePacked(PUBKEY), _proof(reg, "nodo", 1));
        reg.invite("nodo", address(0xB0B));
        reg.invite("nodo", address(0xC0C));
        vm.expectRevert(bytes("DegaChatRegistry: node full"));
        reg.invite("nodo", address(0xD0D)); // max 3 reached
    }

    function testOnlyOwnerInvites() public {
        reg.openNode("pavel", abi.encodePacked(PUBKEY), _proof(reg, "pavel", 1));
        vm.prank(address(0xBAD));
        vm.expectRevert(bytes("DegaChatRegistry: only node owner invites"));
        reg.invite("pavel", address(0xB0B));
    }

    function testBadPubkeyLengthRejected() public {
        // empty bytes allowed (compat), but non-32-byte is rejected
        vm.expectRevert(bytes("DegaChatRegistry: bad nostr pubkey"));
        reg.openNode("shortkey", hex"1234", bytes(""));
    }
}
