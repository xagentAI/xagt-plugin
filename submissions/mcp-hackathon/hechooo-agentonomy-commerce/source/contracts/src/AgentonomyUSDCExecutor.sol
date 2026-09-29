// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

/// @title Agentonomy USDC Executor
/// @notice Executes one Core-authorized USDC transfer per capability and owner nonce.
/// @dev This contract is intentionally not upgradeable and has no arbitrary-call surface.
contract AgentonomyUSDCExecutor {
    string public constant EIP712_NAME = "Agentonomy USDC Executor";
    string public constant EIP712_VERSION = "1";

    bytes32 public constant EIP712_DOMAIN_TYPEHASH =
        keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)");
    bytes32 public constant EXECUTION_TYPEHASH = keccak256(
        "Execution(bytes32 capabilityHash,bytes32 reservationHash,address owner,address payee,address token,uint256 amount,uint256 nonce,uint256 deadline,uint256 signerEpoch,address relayer)"
    );

    uint256 private constant _SECP256K1_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141;
    uint256 private constant _SECP256K1_HALF_N = 0x7FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF5D576E7357A4501DDFE92F46681B20A0;
    uint256 private constant _NOT_ENTERED = 1;
    uint256 private constant _ENTERED = 2;

    struct Execution {
        bytes32 capabilityHash;
        bytes32 reservationHash;
        address owner;
        address payee;
        address token;
        uint256 amount;
        uint256 nonce;
        uint256 deadline;
        uint256 signerEpoch;
        address relayer;
    }

    error WrongChain(uint256 chainId);
    error InvalidAdmin();
    error InvalidSigner();
    error InvalidCapabilityHash();
    error InvalidReservationHash();
    error InvalidOwner();
    error InvalidPayee();
    error InvalidToken();
    error InvalidAmount();
    error InvalidSignerEpoch();
    error InvalidRelayer();
    error InvalidSignature();
    error CapabilityAlreadyUsed();
    error NonceAlreadyUsed();
    error SignatureExpired();
    error NotOwner();
    error NotPendingOwner();
    error PausedError();
    error AlreadyPaused();
    error AlreadyUnpaused();
    error TokenNoCode();
    error TokenCallFailed();
    error TokenMalformedReturn();
    error TokenReturnedFalse();
    error ReentrancyGuardReentered();

    event PaymentExecuted(
        bytes32 indexed capabilityHash,
        bytes32 indexed reservationHash,
        address indexed owner,
        address payee,
        address token,
        uint256 amount,
        uint256 nonce,
        uint256 deadline,
        address signer,
        uint256 signerEpoch,
        address relayer
    );
    event ExecutionSignerRotated(
        address indexed previousSigner,
        address indexed newSigner,
        address indexed operator,
        uint256 previousEpoch,
        uint256 newEpoch
    );
    event Paused(address indexed account);
    event Unpaused(address indexed account);
    event OwnershipTransferStarted(address indexed previousOwner, address indexed newOwner);
    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);

    address public owner;
    address public pendingOwner;
    address public executionSigner;
    uint256 public signerEpoch;
    uint256 public immutable EXECUTION_CHAIN_ID;
    address public immutable USDC;
    bytes32 public immutable DOMAIN_SEPARATOR;
    bool public paused;

    mapping(bytes32 capabilityHash => bool used) public usedCapabilityHashes;
    mapping(address ownerAddress => mapping(uint256 nonce => bool used)) public usedNonces;

    uint256 private _reentrancyStatus = _NOT_ENTERED;

    constructor(address admin, address kmsExecutionSigner) {
        EXECUTION_CHAIN_ID = block.chainid;
        USDC = _approvedUsdc(EXECUTION_CHAIN_ID);
        if (admin == address(0)) revert InvalidAdmin();
        if (kmsExecutionSigner == address(0)) revert InvalidSigner();
        if (_codeSize(USDC) == 0) revert TokenNoCode();

        owner = admin;
        executionSigner = kmsExecutionSigner;
        signerEpoch = 1;
        DOMAIN_SEPARATOR = keccak256(
            abi.encode(
                EIP712_DOMAIN_TYPEHASH,
                keccak256(bytes(EIP712_NAME)),
                keccak256(bytes(EIP712_VERSION)),
                EXECUTION_CHAIN_ID,
                address(this)
            )
        );
        emit OwnershipTransferred(address(0), admin);
    }

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    modifier whenNotPaused() {
        if (paused) revert PausedError();
        _;
    }

    modifier nonReentrant() {
        if (_reentrancyStatus == _ENTERED) revert ReentrancyGuardReentered();
        _reentrancyStatus = _ENTERED;
        _;
        _reentrancyStatus = _NOT_ENTERED;
    }

    function hashExecution(Execution calldata execution) public view returns (bytes32) {
        return _digest(execution);
    }

    function execute(Execution calldata execution, bytes calldata signature)
        external
        whenNotPaused
        nonReentrant
        returns (bytes32 digest)
    {
        if (execution.capabilityHash == bytes32(0)) {
            revert InvalidCapabilityHash();
        }
        if (execution.reservationHash == bytes32(0)) {
            revert InvalidReservationHash();
        }
        if (execution.owner == address(0)) revert InvalidOwner();
        if (execution.payee == address(0)) revert InvalidPayee();
        if (execution.token != USDC) revert InvalidToken();
        if (execution.amount == 0) revert InvalidAmount();
        if (execution.signerEpoch != signerEpoch) revert InvalidSignerEpoch();
        if (execution.relayer == address(0) || msg.sender != execution.relayer) {
            revert InvalidRelayer();
        }
        if (block.timestamp >= execution.deadline) revert SignatureExpired();
        if (usedCapabilityHashes[execution.capabilityHash]) {
            revert CapabilityAlreadyUsed();
        }
        if (usedNonces[execution.owner][execution.nonce]) {
            revert NonceAlreadyUsed();
        }

        digest = _digest(execution);
        address recovered = _recover(digest, signature);
        if (recovered != executionSigner) revert InvalidSigner();

        // Consume before the external call. A failed call reverts this state too.
        usedCapabilityHashes[execution.capabilityHash] = true;
        usedNonces[execution.owner][execution.nonce] = true;
        _safeTransferFrom(execution.owner, execution.payee, execution.amount);

        emit PaymentExecuted(
            execution.capabilityHash,
            execution.reservationHash,
            execution.owner,
            execution.payee,
            execution.token,
            execution.amount,
            execution.nonce,
            execution.deadline,
            recovered,
            execution.signerEpoch,
            execution.relayer
        );
    }

    function pause() external onlyOwner {
        if (paused) revert AlreadyPaused();
        paused = true;
        emit Paused(msg.sender);
    }

    function unpause() external onlyOwner {
        if (!paused) revert AlreadyUnpaused();
        paused = false;
        emit Unpaused(msg.sender);
    }

    function rotateExecutionSigner(address newSigner) external onlyOwner {
        if (newSigner == address(0)) revert InvalidSigner();
        address previousSigner = executionSigner;
        uint256 previousEpoch = signerEpoch;
        executionSigner = newSigner;
        signerEpoch = previousEpoch + 1;
        emit ExecutionSignerRotated(previousSigner, newSigner, msg.sender, previousEpoch, signerEpoch);
    }

    function transferOwnership(address newOwner) external onlyOwner {
        if (newOwner == address(0)) revert InvalidAdmin();
        pendingOwner = newOwner;
        emit OwnershipTransferStarted(owner, newOwner);
    }

    function acceptOwnership() external {
        if (msg.sender != pendingOwner) revert NotPendingOwner();
        address previousOwner = owner;
        owner = msg.sender;
        pendingOwner = address(0);
        emit OwnershipTransferred(previousOwner, msg.sender);
    }

    function _digest(Execution calldata execution) internal view returns (bytes32) {
        bytes32 structHash = keccak256(
            abi.encode(
                EXECUTION_TYPEHASH,
                execution.capabilityHash,
                execution.reservationHash,
                execution.owner,
                execution.payee,
                execution.token,
                execution.amount,
                execution.nonce,
                execution.deadline,
                execution.signerEpoch,
                execution.relayer
            )
        );
        return keccak256(abi.encodePacked("\x19\x01", DOMAIN_SEPARATOR, structHash));
    }

    function _recover(bytes32 digest, bytes calldata signature) internal pure returns (address recovered) {
        if (signature.length != 65) revert InvalidSignature();

        bytes32 r;
        bytes32 s;
        uint8 v;
        assembly {
            r := calldataload(signature.offset)
            s := calldataload(add(signature.offset, 32))
            v := byte(0, calldataload(add(signature.offset, 64)))
        }
        if (v != 27 && v != 28) revert InvalidSignature();
        if (uint256(r) == 0 || uint256(r) >= _SECP256K1_N) {
            revert InvalidSignature();
        }
        if (uint256(s) == 0 || uint256(s) > _SECP256K1_HALF_N) {
            revert InvalidSignature();
        }

        recovered = ecrecover(digest, v, r, s);
        if (recovered == address(0)) revert InvalidSignature();
    }

    function _safeTransferFrom(address from, address to, uint256 amount) internal {
        address token = USDC;
        if (_codeSize(token) == 0) revert TokenNoCode();

        bytes memory callData =
            abi.encodeWithSelector(bytes4(keccak256("transferFrom(address,address,uint256)")), from, to, amount);
        bool success;
        uint256 returnSize;
        uint256 returnValue;
        assembly {
            let output := mload(0x40)
            success := call(gas(), token, 0, add(callData, 32), mload(callData), output, 32)
            returnSize := returndatasize()
            if success {
                returnValue := mload(output)
            }
        }
        if (!success) revert TokenCallFailed();
        if (returnSize != 32) revert TokenMalformedReturn();
        if (returnValue != 1) revert TokenReturnedFalse();
    }

    function _approvedUsdc(uint256 chainId) internal pure returns (address token) {
        if (chainId == 8453) return 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913;
        if (chainId == 137) return 0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359;
        if (chainId == 84532) return 0x036CbD53842c5426634e7929541eC2318f3dCF7e;
        if (chainId == 80002) return 0x41E94Eb019C0762f9Bfcf9Fb1E58725BfB0e7582;
        revert WrongChain(chainId);
    }

    function _codeSize(address account) internal view returns (uint256 size) {
        assembly {
            size := extcodesize(account)
        }
    }
}
