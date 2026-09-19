// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "IERC20.sol";
import "IERC20Burnable.sol";

/// @title DegaChatRegistry
/// @notice Node registry + fee gate for the DEGA/Canon P2P chat.
///
/// Registrations expire after a configurable duration and can be renewed by
/// their owner for the current DEGA fee. Expired names remain reserved.
contract DegaChatRegistry {
    IERC20 public immutable degaToken;

    address public owner;
    uint256 public registrationTTL;
    bool private entered;
    uint256 public fee; // fee in wei of $DEGA (0 => free tier)

    uint256 public constant MAX_USERNAME = 15;
    uint256 public maxUsersPerNode; // configurable, owner only

    struct Node {
        address nodeOwner; // wallet that paid the fee
        uint256 openedAt;
        uint256 expiresAt;
        uint32 memberCount; // nodeOwner + invited members
    }

    // username ("alice.dega" without the TLD) -> node
    mapping(string => Node) private _nodes;
    // username -> Nostr public key (32 bytes / 64 hex) for E2E identity + search
    mapping(string => bytes) private _nostrPubkeyOf;
    // Nostr public key -> username (bare) for reverse lookup when an inbound DM
    // only carries the sender's pubkey, so you can show their name even if you
    // have never invited/resolved them.
    mapping(bytes => string) private _usernameByPubkey;
    // username bytes32 -> exists (cheap uniqueness check in allowed list)
    mapping(string => bool) private isUsernameRegistered;
    // wallet -> username (bare) for the owner's single node
    mapping(address => string) private ownerUsername;
    // node username -> invited member addresses (unique)
    mapping(string => address[]) private _members;
    mapping(string => mapping(address => bool)) private _isMember;

    // successful fee payments, to let the TUI verify without trusting its input
    event NodeOpened(
        string indexed username,
        address indexed nodeOwner,
        bytes nostrPubkey,
        uint256 feePaid,
        uint256 at,
        uint256 expiresAt
    );
    event MemberInvited(string indexed username, address indexed member);
    event FeeBurned(address indexed payer, uint256 amount);
    event FeeUpdated(uint256 newFee);
    event RegistrationTTLUpdated(uint256 duration);
    event NodeRenewed(
        string indexed username,
        address indexed nodeOwner,
        uint256 previousExpiry,
        uint256 expiresAt,
        uint256 feePaid
    );

    modifier onlyOwner() {
        require(msg.sender == owner, "DegaChatRegistry: not owner");
        _;
    }

    modifier nonReentrant() {
        require(!entered, "DegaChatRegistry: reentrant call");
        entered = true;
        _;
        entered = false;
    }

    constructor(IERC20 token_, uint256 fee_, uint256 maxUsersPerNode_, uint256 ttl_) {
        require(address(token_) != address(0), "DegaChatRegistry: bad token");
        require(ttl_ > 0, "DegaChatRegistry: TTL must be positive");
        require(maxUsersPerNode_ >= 1, "DegaChatRegistry: cap must be >= 1");
        registrationTTL = ttl_;
        owner = msg.sender;
        degaToken = token_;
        fee = fee_;
        maxUsersPerNode = maxUsersPerNode_;
    }

    /// Set the node-opening fee (DEGA only). 0 unlocks the free tier for demos.
    function setFee(uint256 newFee) external onlyOwner {
        fee = newFee;
        emit FeeUpdated(newFee);
    }

    function setRegistrationTTL(uint256 duration) external onlyOwner {
        require(duration > 0, "DegaChatRegistry: TTL must be positive");
        registrationTTL = duration;
        emit RegistrationTTLUpdated(duration);
    }

    function isActive(string memory name) public view returns (bool) {
        Node storage n = _nodes[canonical(name)];
        return n.nodeOwner != address(0) && block.timestamp < n.expiresAt;
    }

    /// Administrative recovery retains expired identities; not a discovery query.
    function registrationOfOwner(address wallet)
        external
        view
        returns (
            string memory username,
            address nodeOwner,
            uint256 openedAt,
            uint256 expiresAt,
            uint256 memberCount,
            bool active,
            uint256 checkedAt
        )
    {
        username = ownerUsername[wallet];
        Node storage n = _nodes[username];
        return (
            username,
            n.nodeOwner,
            n.openedAt,
            n.expiresAt,
            n.memberCount,
            isActive(username),
            block.timestamp
        );
    }

    /// Configurable cap of users allowed inside a single node (owner included).
    function setMaxUsersPerNode(uint256 cap) external onlyOwner {
        require(cap >= 1, "DegaChatRegistry: cap must be >= 1");
        maxUsersPerNode = cap;
    }

    /// Resolve a chat username to its Nostr public key (for E2E + directed DM).
    /// ``name`` may be bare ("carlos") or full "carlos.dega" — the TLD is the
    /// same (`MAX_USERNAME` only bounds the bare name), so both resolve.
    function resolveNostrPubkey(string memory name) public view returns (bytes memory) {
        return isActive(name) ? _nostrPubkeyOf[canonical(name)] : bytes("");
    }

    /// Search helper: is this username registered (node open)?
    function usernameTaken(string memory name) public view returns (bool) {
        return isUsernameRegistered[canonical(name)];
    }

    /// Reverse lookup: given a Nostr public key (32 bytes), return the bare
    /// username ("" if the pubkey has never opened a node). Lets a recipient of
    /// an inbound DM resolve the sender's name even when not previously invited.
    function usernameForPubkey(bytes memory pubkey) public view returns (string memory) {
        string memory name = _usernameByPubkey[pubkey];
        return isActive(name) ? name : "";
    }

    /// Lookup the one username already owned by a wallet (empty string if none).
    function usernameOfOwner(address ownerAddr) public view returns (string memory) {
        string memory name = ownerUsername[ownerAddr];
        return isActive(name) ? name : "";
    }

    /// Normalize a queried name (bare or with ".dega" TLD) to the bare form.
    function canonical(string memory name) internal pure returns (string memory) {
        bytes memory b = bytes(name);
        bytes memory tld = bytes(".dega");
        // strip trailing ".dega" if present
        if (b.length > tld.length) {
            uint256 start = b.length - tld.length;
            bool isTld = true;
            for (uint256 i = 0; i < tld.length; i++) {
                if (b[start + i] != tld[i]) {
                    isTld = false;
                    break;
                }
            }
            if (isTld) {
                bytes memory bare = new bytes(start);
                for (uint256 i = 0; i < start; i++) {
                    bare[i] = b[i];
                }
                return string(bare);
            }
        }
        return name;
    }

    /// Validate a chat username: 1..15 chars, alnum + '.' + '_' + '-'.
    function _validateUsername(string memory name) internal pure returns (bool) {
        bytes memory b = bytes(name);
        if (b.length == 0 || b.length > MAX_USERNAME) return false;
        for (uint256 i = 0; i < b.length; i++) {
            bytes1 c = b[i];
            bool ok = (c >= "0" && c <= "9") || (c >= "a" && c <= "z") || (c >= "A" && c <= "Z")
                || c == "." || c == "_" || c == "-";
            if (!ok) return false;
        }
        return true;
    }

    uint256 private constant FIELD =
        0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F;
    uint256 private constant HALF_ORDER =
        0x7FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF5D576E7357A4501DDFE92F46681B20A0;
    bytes32 private constant DOMAIN_TYPE = keccak256(
        "EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
    );
    bytes32 private constant REGISTRATION_TYPE =
        keccak256("Registration(address wallet,string username,bytes32 nostrPubkey)");

    /// Wallet, network and deployment binding prevent copied proofs from being reused.
    function registrationDigest(address wallet, string memory username, bytes32 nostrPubkey)
        public
        view
        returns (bytes32)
    {
        bytes32 domain = keccak256(
            abi.encode(
                DOMAIN_TYPE,
                keccak256("DegaChatRegistry"),
                keccak256("1"),
                block.chainid,
                address(this)
            )
        );
        bytes32 registration = keccak256(
            abi.encode(
                REGISTRATION_TYPE, wallet, keccak256(bytes(canonical(username))), nostrPubkey
            )
        );
        return keccak256(abi.encodePacked(hex"1901", domain, registration));
    }

    /// Standard ECDSA proves possession of the secret behind an x-only Nostr key.
    function _verifyNostrProof(string memory name, bytes calldata pubkey, bytes calldata proof)
        internal
        view
    {
        require(pubkey.length == 32, "DegaChatRegistry: bad nostr pubkey");
        require(proof.length == 97, "DegaChatRegistry: bad proof length");
        uint256 x = uint256(bytes32(pubkey));
        uint256 y = uint256(bytes32(proof[:32]));
        require(x < FIELD && y < FIELD, "DegaChatRegistry: bad point");
        require(
            mulmod(y, y, FIELD) == addmod(mulmod(mulmod(x, x, FIELD), x, FIELD), 7, FIELD),
            "DegaChatRegistry: bad point"
        );
        bytes32 r = bytes32(proof[32:64]);
        bytes32 s = bytes32(proof[64:96]);
        uint8 v = uint8(proof[96]);
        require(v == 27 || v == 28, "DegaChatRegistry: bad signature");
        require(uint256(s) > 0 && uint256(s) <= HALF_ORDER, "DegaChatRegistry: bad signature");
        address expected = address(uint160(uint256(keccak256(abi.encodePacked(x, y)))));
        address recovered =
            ecrecover(registrationDigest(msg.sender, name, bytes32(pubkey)), v, r, s);
        require(
            recovered != address(0) && recovered == expected,
            "DegaChatRegistry: invalid ownership proof"
        );
    }

    /// Open a chat node. Burns `fee` in $DEGA (burnFrom), or fee==0 (free).
    /// Registers the owner's Nostr public key as the E2E identity for this
    /// username, so others can resolve `name.dega` -> pubkey to invite/DM them.
    function openNode(string calldata username, bytes calldata nostrPubkey, bytes calldata proof)
        external
        nonReentrant
    {
        string memory canonName = canonical(username);
        require(_validateUsername(canonName), "DegaChatRegistry: invalid username");
        require(
            bytes(ownerUsername[msg.sender]).length == 0, "DegaChatRegistry: owner already has node"
        );
        require(!isUsernameRegistered[canonName], "DegaChatRegistry: username taken");
        _verifyNostrProof(canonName, nostrPubkey, proof);
        require(bytes(_usernameByPubkey[nostrPubkey]).length == 0, "DegaChatRegistry: pubkey taken");

        Node storage n = _nodes[canonName];
        n.nodeOwner = msg.sender;
        n.openedAt = block.timestamp;
        n.expiresAt = block.timestamp + registrationTTL;
        n.memberCount = 1; // the owner is member #1

        isUsernameRegistered[canonName] = true;
        ownerUsername[msg.sender] = canonName;
        _isMember[canonName][msg.sender] = true;
        _members[canonName].push(msg.sender);
        _nostrPubkeyOf[canonName] = nostrPubkey;
        _usernameByPubkey[nostrPubkey] = canonName;

        _burnFee();
        emit NodeOpened(canonName, msg.sender, nostrPubkey, fee, block.timestamp, n.expiresAt);
    }

    /// Optimistic concurrency prevents charging twice for the same renewal.
    function renewNode(
        string calldata username,
        uint256 expectedExpiresAt,
        uint256 maxFee,
        uint256 expectedTTL
    ) external nonReentrant {
        string memory name = canonical(username);
        Node storage n = _nodes[name];
        require(n.nodeOwner == msg.sender, "DegaChatRegistry: only node owner renews");
        require(n.expiresAt == expectedExpiresAt, "DegaChatRegistry: stale renewal");
        require(fee <= maxFee, "DegaChatRegistry: fee changed");
        require(registrationTTL == expectedTTL, "DegaChatRegistry: TTL changed");
        uint256 previousExpiry = n.expiresAt;
        uint256 start = previousExpiry > block.timestamp ? previousExpiry : block.timestamp;
        n.expiresAt = start + registrationTTL;
        _burnFee();
        emit NodeRenewed(name, msg.sender, previousExpiry, n.expiresAt, fee);
    }

    function _burnFee() internal {
        if (fee > 0) {
            IERC20Burnable(address(degaToken)).burnFrom(msg.sender, fee);
            emit FeeBurned(msg.sender, fee);
        }
    }

    /// Node owner invites a member (caps total users at maxUsersPerNode).
    function invite(string calldata username, address member) external {
        string memory canonName = canonical(username);
        Node storage n = _nodes[canonName];
        require(isActive(canonName), "DegaChatRegistry: node inactive");
        require(msg.sender == n.nodeOwner, "DegaChatRegistry: only node owner invites");
        require(member != address(0) && member != n.nodeOwner, "DegaChatRegistry: bad member");
        require(!_isMember[canonName][member], "DegaChatRegistry: already member");
        require(n.memberCount < maxUsersPerNode, "DegaChatRegistry: node full");

        _isMember[canonName][member] = true;
        _members[canonName].push(member);
        n.memberCount += 1;

        emit MemberInvited(canonName, member);
    }

    /// Membership check the TUI uses before enabling the composer.
    function isMemberOf(string calldata username, address who) external view returns (bool) {
        return isActive(username) && _isMember[canonical(username)][who];
    }

    function nodeOwnerOf(string calldata username) external view returns (address) {
        return isActive(username) ? _nodes[canonical(username)].nodeOwner : address(0);
    }

    function memberCountOf(string calldata username) external view returns (uint256) {
        return isActive(username) ? _members[canonical(username)].length : 0;
    }

    function members(string calldata username, uint256 index) external view returns (address) {
        require(isActive(username), "DegaChatRegistry: node inactive");
        return _members[canonical(username)][index];
    }
}
