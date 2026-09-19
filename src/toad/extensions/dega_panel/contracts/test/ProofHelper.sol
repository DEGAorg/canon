// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Test} from "forge-std/Test.sol";
import {Vm, VmSafe} from "forge-std/Vm.sol";
import {DegaChatRegistry} from "DegaChatRegistry.sol";

abstract contract ProofHelper is Test {
    function _pub(uint256 secret) internal returns (bytes memory) {
        uint256 x = vm.createWallet(secret).publicKeyX;
        return abi.encodePacked(x);
    }

    function _proof(DegaChatRegistry registry, string memory name, uint256 secret)
        internal
        returns (bytes memory)
    {
        (VmSafe.CallerMode mode, address sender,) = vm.readCallers();
        if (mode == VmSafe.CallerMode.None) sender = address(this);
        return _proofFor(registry, name, secret, sender);
    }

    function _proofFor(
        DegaChatRegistry registry,
        string memory name,
        uint256 secret,
        address wallet
    ) internal returns (bytes memory) {
        Vm.Wallet memory identity = vm.createWallet(secret);
        uint256 x = identity.publicKeyX;
        uint256 y = identity.publicKeyY;
        bytes32 domain = keccak256(
            abi.encode(
                keccak256(
                    "EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
                ),
                keccak256("DegaChatRegistry"),
                keccak256("1"),
                block.chainid,
                address(registry)
            )
        );
        bytes32 data = keccak256(
            abi.encode(
                keccak256("Registration(address wallet,string username,bytes32 nostrPubkey)"),
                wallet,
                keccak256(bytes(name)),
                bytes32(x)
            )
        );
        (uint8 v, bytes32 r, bytes32 s) =
            vm.sign(secret, keccak256(abi.encodePacked(hex"1901", domain, data)));
        return abi.encodePacked(y, r, s, v);
    }
}
