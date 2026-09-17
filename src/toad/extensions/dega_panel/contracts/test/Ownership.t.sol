// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {ProofHelper} from "test/ProofHelper.sol";
import {DegaChatRegistry} from "DegaChatRegistry.sol";
import {MockDEGA} from "MockDEGA.sol";

contract NostrOwnershipTest is ProofHelper {
    DegaChatRegistry registry;
    uint256 constant ORDER = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141;
    uint256 constant FIELD = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F;

    function setUp() public {
        registry = new DegaChatRegistry(new MockDEGA(), 0, 10, 365 days);
    }

    function testBothNostrParitiesProveSameIdentity() public {
        bytes memory pubkey = _pub(1);
        assertEq(pubkey, _pub(ORDER - 1));
        registry.openNode("alice.dega", pubkey, _proof(registry, "alice", ORDER - 1));
        assertEq(registry.usernameForPubkey(pubkey), "alice");
        vm.prank(address(2));
        vm.expectRevert("DegaChatRegistry: pubkey taken");
        registry.openNode("bob", pubkey, _proof(registry, "bob", 1));
    }

    function testVictimKeyCannotBeRegisteredByAttacker() public {
        vm.expectRevert("DegaChatRegistry: bad point");
        registry.openNode("victim", _pub(1), _proof(registry, "victim", 2));
        assertFalse(registry.usernameTaken("victim"));
    }

    function testAttackerSignatureWithVictimFullPointFails() public {
        bytes memory proof = _proof(registry, "victim", 2);
        uint256 victimY = vm.createWallet(1).publicKeyY;
        assembly {
            mstore(add(proof, 32), victimY)
        }
        vm.expectRevert("DegaChatRegistry: invalid ownership proof");
        registry.openNode("victim", _pub(1), proof);
    }

    function testFuzzValidIdentityProof(uint256 secret) public {
        secret = bound(secret, 1, ORDER - 1);
        bytes memory pubkey = _pub(secret);
        registry.openNode("alice", pubkey, _proof(registry, "alice", secret));
        assertEq(registry.resolveNostrPubkey("alice"), pubkey);
    }

    function testCopiedProofBoundToWalletAndUsername() public {
        bytes memory proof = _proof(registry, "alice", 1);
        vm.prank(address(2));
        vm.expectRevert("DegaChatRegistry: invalid ownership proof");
        registry.openNode("alice", _pub(1), proof);
        vm.expectRevert("DegaChatRegistry: invalid ownership proof");
        registry.openNode("bob", _pub(1), proof);
        registry.openNode("alice", _pub(1), proof);
        vm.expectRevert("DegaChatRegistry: owner already has node");
        registry.openNode("alice", _pub(1), proof);
    }

    function testProofBoundToChainAndRegistry() public {
        bytes memory proof = _proof(registry, "alice", 1);
        uint256 originalChain = block.chainid;
        vm.chainId(originalChain + 1);
        vm.expectRevert("DegaChatRegistry: invalid ownership proof");
        registry.openNode("alice", _pub(1), proof);
        vm.chainId(originalChain);
        DegaChatRegistry other = new DegaChatRegistry(new MockDEGA(), 0, 10, 365 days);
        vm.expectRevert("DegaChatRegistry: invalid ownership proof");
        other.openNode("alice", _pub(1), proof);
    }

    function testMissingProofAndOldSelectorRejected() public {
        vm.expectRevert("DegaChatRegistry: bad proof length");
        registry.openNode("alice", _pub(1), bytes(""));
        (bool ok,) = address(registry).call(
            abi.encodeWithSignature("openNode(string,bytes)", "alice", _pub(1))
        );
        assertFalse(ok);
        vm.expectRevert("DegaChatRegistry: bad nostr pubkey");
        registry.openNode("alice", bytes(""), bytes(""));
    }

    function testRejectsInvalidPointAndCoordinates() public {
        bytes memory proof = _proof(registry, "alice", 1);
        assembly {
            mstore(add(proof, 32), FIELD)
        }
        vm.expectRevert("DegaChatRegistry: bad point");
        registry.openNode("alice", _pub(1), proof);
        vm.expectRevert("DegaChatRegistry: bad point");
        registry.openNode("alice", abi.encodePacked(FIELD), _proof(registry, "alice", 1));
        vm.expectRevert("DegaChatRegistry: bad point");
        registry.openNode("alice", abi.encodePacked(uint256(0)), _proof(registry, "alice", 1));
    }

    function testValidPointWithWrongParityFails() public {
        bytes memory proof = _proof(registry, "alice", 1);
        uint256 alternate = vm.createWallet(ORDER - 1).publicKeyY;
        assembly {
            mstore(add(proof, 32), alternate)
        }
        vm.expectRevert("DegaChatRegistry: invalid ownership proof");
        registry.openNode("alice", _pub(1), proof);
    }

    function testRejectsZeroAndOutOfRangeR() public {
        bytes memory proof = _proof(registry, "alice", 1);
        assembly {
            mstore(add(proof, 64), 0)
        }
        vm.expectRevert("DegaChatRegistry: invalid ownership proof");
        registry.openNode("alice", _pub(1), proof);
        uint256 order = ORDER;
        assembly {
            mstore(add(proof, 64), order)
        }
        vm.expectRevert("DegaChatRegistry: invalid ownership proof");
        registry.openNode("alice", _pub(1), proof);
    }

    function testRejectsHighSZeroSAndBadV() public {
        bytes memory proof = _proof(registry, "alice", 1);
        uint256 highS = ORDER - 1;
        assembly {
            mstore(add(proof, 96), highS)
        }
        vm.expectRevert("DegaChatRegistry: bad signature");
        registry.openNode("alice", _pub(1), proof);
        assembly {
            mstore(add(proof, 96), 0)
        }
        vm.expectRevert("DegaChatRegistry: bad signature");
        registry.openNode("alice", _pub(1), proof);
        proof = _proof(registry, "alice", 1);
        proof[96] = bytes1(uint8(1));
        vm.expectRevert("DegaChatRegistry: bad signature");
        registry.openNode("alice", _pub(1), proof);
    }
}
