// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

interface Vm {
    struct Log {
        bytes32[] topics;
        bytes data;
        address emitter;
    }

    function addr(uint256 privateKey) external returns (address);
    function chainId(uint256 newChainId) external;
    function etch(address who, bytes calldata code) external;
    function expectEmit(bool checkTopic1, bool checkTopic2, bool checkTopic3, bool checkData) external;
    function expectRevert() external;
    function expectRevert(bytes4 selector) external;
    function expectRevert(bytes calldata revertData) external;
    function getRecordedLogs() external returns (Log[] memory);
    function prank(address sender) external;
    function recordLogs() external;
    function sign(uint256 privateKey, bytes32 digest) external returns (uint8 v, bytes32 r, bytes32 s);
    function startPrank(address sender) external;
    function stopPrank() external;
    function warp(uint256 newTimestamp) external;
}

interface IERC20Test {
    function allowance(address owner, address spender) external view returns (uint256);
    function balanceOf(address account) external view returns (uint256);
    function approve(address spender, uint256 amount) external returns (bool);
    function mint(address account, uint256 amount) external;
}

import {AgentonomyUSDCExecutor} from "../src/AgentonomyUSDCExecutor.sol";
import {MockBaseUSDC} from "./mocks/MockBaseUSDC.sol";

interface IExecutorMarkers {
    function usedCapabilityHashes(bytes32 capabilityHash) external view returns (bool);
    function usedNonces(address owner, uint256 nonce) external view returns (bool);
}

contract StateCheckingToken {
    IExecutorMarkers internal immutable executor;
    bytes32 internal immutable capabilityHash;
    address internal immutable executionOwner;
    uint256 internal immutable nonce;

    constructor(address executorAddress, bytes32 capabilityHashValue, address ownerValue, uint256 nonceValue) {
        executor = IExecutorMarkers(executorAddress);
        capabilityHash = capabilityHashValue;
        executionOwner = ownerValue;
        nonce = nonceValue;
    }

    function transferFrom(address, address, uint256) external view returns (bool) {
        return executor.usedCapabilityHashes(capabilityHash) && executor.usedNonces(executionOwner, nonce);
    }
}

contract AgentonomyUSDCExecutorTest {
    Vm internal constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));

    uint256 internal constant ADMIN_KEY = 0xA11CE;
    uint256 internal constant SIGNER_KEY = 0xB0B;
    uint256 internal constant NEW_SIGNER_KEY = 0xC0DE;
    uint256 internal constant OWNER_KEY = 0xDAD;
    uint256 internal constant ATTACKER_KEY = 0xBAD;

    uint256 internal constant AMOUNT = 1_250_000;
    uint256 internal constant DEADLINE = 1_000_000;
    uint256 internal constant CHAIN_ID = 8453;
    uint256 internal constant POLYGON_CHAIN_ID = 137;
    uint256 internal constant BASE_SEPOLIA_CHAIN_ID = 84532;
    uint256 internal constant POLYGON_AMOY_CHAIN_ID = 80002;
    bytes32 internal constant DIGEST_FIXTURE_SALT = keccak256("agentonomy-usdc-executor-python-parity");
    uint256 internal constant SECP256K1_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141;
    uint256 internal constant SECP256K1_HALF_N = 0x7FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF5D576E7357A4501DDFE92F46681B20A0;
    address internal constant CANONICAL_USDC = 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913;
    address internal constant POLYGON_USDC = 0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359;
    address internal constant BASE_SEPOLIA_USDC = 0x036CbD53842c5426634e7929541eC2318f3dCF7e;
    address internal constant POLYGON_AMOY_USDC = 0x41E94Eb019C0762f9Bfcf9Fb1E58725BfB0e7582;
    address internal constant DIGEST_FIXTURE_EXECUTOR = 0xD290aaCF3E0DbF6bBEBA9D900C6bcdcBDb05a182;

    address internal admin;
    address internal signer;
    address internal newSigner;
    address internal ownerAccount;
    address internal attacker;
    address internal payee = address(0xBEEF);
    AgentonomyUSDCExecutor internal executor;
    MockBaseUSDC internal token;

    struct LegacyExecution {
        bytes32 capabilityHash;
        bytes32 reservationHash;
        address owner;
        address payee;
        address token;
        uint256 amount;
        uint256 nonce;
        uint256 deadline;
        uint256 signerEpoch;
    }

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

    function setUp() public {
        vm.chainId(CHAIN_ID);
        admin = vm.addr(ADMIN_KEY);
        signer = vm.addr(SIGNER_KEY);
        newSigner = vm.addr(NEW_SIGNER_KEY);
        ownerAccount = vm.addr(OWNER_KEY);
        attacker = vm.addr(ATTACKER_KEY);

        token = new MockBaseUSDC();
        vm.etch(CANONICAL_USDC, address(token).code);
        executor = new AgentonomyUSDCExecutor(admin, signer);
        MockBaseUSDC(CANONICAL_USDC).configure(address(executor), MockBaseUSDC.Mode.Success);
        IERC20Test(CANONICAL_USDC).mint(ownerAccount, AMOUNT * 10);
        vm.prank(ownerAccount);
        IERC20Test(CANONICAL_USDC).approve(address(executor), type(uint256).max);
    }

    function test_executeTransfersExactAmountAndEmitsCompleteEvent() public {
        AgentonomyUSDCExecutor.Execution memory execution = _execution(1, 1, payee, AMOUNT, DEADLINE);
        bytes memory signature = _signature(SIGNER_KEY, execution);

        vm.recordLogs();
        executor.execute(execution, signature);

        assertEq(IERC20Test(CANONICAL_USDC).balanceOf(payee), AMOUNT);
        assertTrue(executor.usedCapabilityHashes(execution.capabilityHash));
        assertTrue(executor.usedNonces(execution.owner, execution.nonce));
        _assertPaymentEvent(vm.getRecordedLogs(), execution, signer, address(this));
    }

    function test_executeRejectsWrongCallerAndZeroSignedRelayer() public {
        AgentonomyUSDCExecutor.Execution memory execution = _execution(23, 23, payee, AMOUNT, DEADLINE);
        bytes memory signature = _signature(SIGNER_KEY, execution);

        vm.prank(attacker);
        vm.expectRevert(AgentonomyUSDCExecutor.InvalidRelayer.selector);
        executor.execute(execution, signature);

        execution.relayer = address(0);
        signature = _signature(SIGNER_KEY, execution);
        vm.expectRevert(AgentonomyUSDCExecutor.InvalidRelayer.selector);
        executor.execute(execution, signature);
    }

    function test_executeRejectsMutatedSignedRelayer() public {
        AgentonomyUSDCExecutor.Execution memory execution = _execution(24, 24, payee, AMOUNT, DEADLINE);
        bytes memory signature = _signature(SIGNER_KEY, execution);

        execution.relayer = attacker;
        vm.prank(attacker);
        vm.expectRevert(AgentonomyUSDCExecutor.InvalidSigner.selector);
        executor.execute(execution, signature);
    }

    function test_executeRejectsAtExactDeadline() public {
        AgentonomyUSDCExecutor.Execution memory execution = _execution(25, 25, payee, AMOUNT, DEADLINE);
        bytes memory signature = _signature(SIGNER_KEY, execution);

        vm.warp(DEADLINE);
        vm.expectRevert(AgentonomyUSDCExecutor.SignatureExpired.selector);
        executor.execute(execution, signature);
    }

    function test_constructorRejectsWrongChain() public {
        vm.chainId(1);
        vm.expectRevert(abi.encodeWithSelector(AgentonomyUSDCExecutor.WrongChain.selector, uint256(1)));
        new AgentonomyUSDCExecutor(admin, signer);
    }

    function test_supportedChainTokenPairsAreBoundImmutably() public {
        uint256[4] memory chainIds = [CHAIN_ID, POLYGON_CHAIN_ID, BASE_SEPOLIA_CHAIN_ID, POLYGON_AMOY_CHAIN_ID];
        address[4] memory tokenAddresses = [CANONICAL_USDC, POLYGON_USDC, BASE_SEPOLIA_USDC, POLYGON_AMOY_USDC];

        for (uint256 index; index < chainIds.length; index++) {
            vm.chainId(chainIds[index]);
            vm.etch(tokenAddresses[index], address(token).code);

            AgentonomyUSDCExecutor deployed = new AgentonomyUSDCExecutor(admin, signer);

            assertEq(deployed.EXECUTION_CHAIN_ID(), chainIds[index]);
            assertEq(deployed.USDC(), tokenAddresses[index]);
        }

        vm.chainId(CHAIN_ID);
    }

    function test_executeWorksForEachSupportedChainTokenPair() public {
        uint256[4] memory chainIds = [CHAIN_ID, POLYGON_CHAIN_ID, BASE_SEPOLIA_CHAIN_ID, POLYGON_AMOY_CHAIN_ID];
        address[4] memory tokenAddresses = [CANONICAL_USDC, POLYGON_USDC, BASE_SEPOLIA_USDC, POLYGON_AMOY_USDC];

        for (uint256 index; index < chainIds.length; index++) {
            vm.chainId(chainIds[index]);
            vm.etch(tokenAddresses[index], address(token).code);
            executor = new AgentonomyUSDCExecutor(admin, signer);
            MockBaseUSDC(tokenAddresses[index]).configure(address(executor), MockBaseUSDC.Mode.Success);
            IERC20Test(tokenAddresses[index]).mint(ownerAccount, AMOUNT);
            vm.prank(ownerAccount);
            IERC20Test(tokenAddresses[index]).approve(address(executor), type(uint256).max);

            AgentonomyUSDCExecutor.Execution memory execution = AgentonomyUSDCExecutor.Execution({
                capabilityHash: bytes32(index + 100),
                reservationHash: bytes32(index + 1100),
                owner: ownerAccount,
                payee: payee,
                token: tokenAddresses[index],
                amount: AMOUNT,
                nonce: index + 100,
                deadline: DEADLINE,
                signerEpoch: executor.signerEpoch(),
                relayer: address(this)
            });
            uint256 beforeBalance = IERC20Test(tokenAddresses[index]).balanceOf(payee);

            executor.execute(execution, _signature(SIGNER_KEY, execution));

            assertEq(IERC20Test(tokenAddresses[index]).balanceOf(payee), beforeBalance + AMOUNT);
        }

        vm.chainId(CHAIN_ID);
    }

    function test_hashExecutionMatchesFacilitatorDigestFixture() public {
        AgentonomyUSDCExecutor fixture = new AgentonomyUSDCExecutor{salt: DIGEST_FIXTURE_SALT}(admin, signer);
        assertEq(address(fixture), DIGEST_FIXTURE_EXECUTOR);

        AgentonomyUSDCExecutor.Execution memory execution = AgentonomyUSDCExecutor.Execution({
            capabilityHash: 0x1111111111111111111111111111111111111111111111111111111111111111,
            reservationHash: 0x2222222222222222222222222222222222222222222222222222222222222222,
            owner: 0x3333333333333333333333333333333333333333,
            payee: 0x4444444444444444444444444444444444444444,
            token: CANONICAL_USDC,
            amount: 1_250_000,
            nonce: 7,
            deadline: 1_700_000_000,
            signerEpoch: 3,
            relayer: 0x5555555555555555555555555555555555555555
        });

        assertEq(fixture.EXECUTION_CHAIN_ID(), CHAIN_ID);
        assertEq(fixture.USDC(), CANONICAL_USDC);
        assertEq(fixture.DOMAIN_SEPARATOR(), 0xce47a2de22c2ebf0c7d7561981f6409eb675f3cb1e83e1d4b3b0b9ea7102e30e);
        assertEq(fixture.hashExecution(execution), 0x18bdf69c696d3376992b946974135bb28b41fee3d59e98f107ba5e5979be8e02);
    }

    function test_executeSelectorBindsRelayerTupleAndRejectsLegacyCalldata() public {
        bytes4 currentSelector = AgentonomyUSDCExecutor.execute.selector;
        bytes4 expectedSelector = bytes4(
            keccak256(
                "execute((bytes32,bytes32,address,address,address,uint256,uint256,uint256,uint256,address),bytes)"
            )
        );
        bytes4 legacySelector = bytes4(
            keccak256("execute((bytes32,bytes32,address,address,address,uint256,uint256,uint256,uint256),bytes)")
        );

        assertEq(uint256(uint32(currentSelector)), uint256(uint32(expectedSelector)));
        assertEq(uint256(uint32(currentSelector)), uint256(uint32(0x9472102f)));
        assertFalse(currentSelector == legacySelector);

        AgentonomyUSDCExecutor.Execution memory execution = _execution(26, 26, payee, AMOUNT, DEADLINE);
        LegacyExecution memory legacy = LegacyExecution({
            capabilityHash: execution.capabilityHash,
            reservationHash: execution.reservationHash,
            owner: execution.owner,
            payee: execution.payee,
            token: execution.token,
            amount: execution.amount,
            nonce: execution.nonce,
            deadline: execution.deadline,
            signerEpoch: execution.signerEpoch
        });
        (bool accepted,) =
            address(executor).call(abi.encodeWithSelector(legacySelector, legacy, _signature(SIGNER_KEY, execution)));
        assertFalse(accepted);
    }

    function test_constructorRejectsZeroAdminAndSigner() public {
        vm.expectRevert(AgentonomyUSDCExecutor.InvalidAdmin.selector);
        new AgentonomyUSDCExecutor(address(0), signer);

        vm.expectRevert(AgentonomyUSDCExecutor.InvalidSigner.selector);
        new AgentonomyUSDCExecutor(admin, address(0));
    }

    function test_executeRejectsZeroAndMutatedScopeValues() public {
        AgentonomyUSDCExecutor.Execution memory execution = _execution(2, 2, payee, AMOUNT, DEADLINE);
        bytes memory signature = _signature(SIGNER_KEY, execution);

        execution.capabilityHash = bytes32(0);
        vm.expectRevert(AgentonomyUSDCExecutor.InvalidCapabilityHash.selector);
        executor.execute(execution, signature);

        execution = _execution(2, 2, payee, AMOUNT, DEADLINE);
        execution.reservationHash = bytes32(0);
        signature = _signature(SIGNER_KEY, execution);
        vm.expectRevert(AgentonomyUSDCExecutor.InvalidReservationHash.selector);
        executor.execute(execution, signature);

        execution = _execution(3, 3, payee, AMOUNT, DEADLINE);
        execution.owner = address(0);
        signature = _signature(SIGNER_KEY, execution);
        vm.expectRevert(AgentonomyUSDCExecutor.InvalidOwner.selector);
        executor.execute(execution, signature);

        execution = _execution(4, 4, address(0), AMOUNT, DEADLINE);
        signature = _signature(SIGNER_KEY, execution);
        vm.expectRevert(AgentonomyUSDCExecutor.InvalidPayee.selector);
        executor.execute(execution, signature);

        execution = _execution(5, 5, payee, AMOUNT, DEADLINE);
        execution.token = address(0x1234);
        signature = _signature(SIGNER_KEY, execution);
        vm.expectRevert(AgentonomyUSDCExecutor.InvalidToken.selector);
        executor.execute(execution, signature);

        execution = _execution(6, 6, payee, 0, DEADLINE);
        signature = _signature(SIGNER_KEY, execution);
        vm.expectRevert(AgentonomyUSDCExecutor.InvalidAmount.selector);
        executor.execute(execution, signature);
    }

    function test_executeRejectsInvalidHighSWrongSignerAndTruncatedSignatures() public {
        AgentonomyUSDCExecutor.Execution memory execution = _execution(7, 7, payee, AMOUNT, DEADLINE);

        bytes memory truncated = new bytes(64);
        vm.expectRevert(AgentonomyUSDCExecutor.InvalidSignature.selector);
        executor.execute(execution, truncated);

        bytes memory wrongSigner = _signature(ATTACKER_KEY, execution);
        vm.expectRevert(AgentonomyUSDCExecutor.InvalidSigner.selector);
        executor.execute(execution, wrongSigner);

        bytes32 r;
        bytes32 s;
        uint8 v;
        AgentonomyUSDCExecutor.Execution memory highSExecution = _execution(8, 8, payee, AMOUNT, DEADLINE);
        bytes memory highS = _signature(SIGNER_KEY, highSExecution);
        assembly {
            r := mload(add(highS, 32))
            s := mload(add(highS, 64))
            v := byte(0, mload(add(highS, 96)))
        }
        if (uint256(s) <= SECP256K1_HALF_N) {
            s = bytes32(SECP256K1_N - uint256(s));
            v = v == 27 ? 28 : 27;
        }
        highS = abi.encodePacked(r, s, v);
        vm.expectRevert(AgentonomyUSDCExecutor.InvalidSignature.selector);
        executor.execute(highSExecution, highS);

        bytes memory invalidV = abi.encodePacked(r, bytes32(uint256(1)), uint8(0));
        vm.expectRevert(AgentonomyUSDCExecutor.InvalidSignature.selector);
        executor.execute(highSExecution, invalidV);
    }

    function test_capabilityReplayAndOwnerNonceReplayAreRejected() public {
        AgentonomyUSDCExecutor.Execution memory first = _execution(9, 9, payee, AMOUNT, DEADLINE);
        executor.execute(first, _signature(SIGNER_KEY, first));

        bytes memory replaySignature = _signature(SIGNER_KEY, first);
        vm.expectRevert(AgentonomyUSDCExecutor.CapabilityAlreadyUsed.selector);
        executor.execute(first, replaySignature);

        AgentonomyUSDCExecutor.Execution memory second = _execution(10, 9, payee, AMOUNT, DEADLINE);
        bytes memory nonceReplaySignature = _signature(SIGNER_KEY, second);
        vm.expectRevert(AgentonomyUSDCExecutor.NonceAlreadyUsed.selector);
        executor.execute(second, nonceReplaySignature);
    }

    function test_signatureMutationOfPayeeTokenOwnerAmountReservationAndDeadlineFails() public {
        AgentonomyUSDCExecutor.Execution memory original = _execution(11, 11, payee, AMOUNT, DEADLINE);
        bytes memory signature = _signature(SIGNER_KEY, original);

        AgentonomyUSDCExecutor.Execution memory changed = _execution(11, 11, payee, AMOUNT, DEADLINE);
        changed.payee = address(0xCAFE);
        _assertInvalidSigner(changed, signature);
        changed = _execution(11, 11, payee, AMOUNT, DEADLINE);
        changed.token = address(0x1234);
        vm.expectRevert(AgentonomyUSDCExecutor.InvalidToken.selector);
        executor.execute(changed, signature);
        changed = _execution(11, 11, payee, AMOUNT, DEADLINE);
        changed.owner = attacker;
        _assertInvalidSigner(changed, signature);
        changed = _execution(11, 11, payee, AMOUNT, DEADLINE);
        changed.amount = AMOUNT + 1;
        _assertInvalidSigner(changed, signature);
        changed = _execution(11, 11, payee, AMOUNT, DEADLINE);
        changed.reservationHash = bytes32(uint256(12));
        _assertInvalidSigner(changed, signature);
        changed = _execution(11, 11, payee, AMOUNT, DEADLINE);
        changed.deadline = DEADLINE + 1;
        _assertInvalidSigner(changed, signature);
    }

    function test_expiredExecutionIsRejected() public {
        AgentonomyUSDCExecutor.Execution memory execution = _execution(12, 12, payee, AMOUNT, DEADLINE);
        bytes memory signature = _signature(SIGNER_KEY, execution);
        vm.warp(DEADLINE + 1);
        vm.expectRevert(AgentonomyUSDCExecutor.SignatureExpired.selector);
        executor.execute(execution, signature);
    }

    function test_pauseUnpauseAndNonOwnerControls() public {
        vm.prank(attacker);
        vm.expectRevert(AgentonomyUSDCExecutor.NotOwner.selector);
        executor.pause();

        vm.expectEmit(true, false, false, false);
        emit Paused(admin);
        vm.prank(admin);
        executor.pause();

        AgentonomyUSDCExecutor.Execution memory execution = _execution(13, 13, payee, AMOUNT, DEADLINE);
        bytes memory signature = _signature(SIGNER_KEY, execution);
        vm.expectRevert(AgentonomyUSDCExecutor.PausedError.selector);
        executor.execute(execution, signature);

        vm.prank(attacker);
        vm.expectRevert(AgentonomyUSDCExecutor.NotOwner.selector);
        executor.unpause();
        vm.expectEmit(true, false, false, false);
        emit Unpaused(admin);
        vm.prank(admin);
        executor.unpause();
        executor.execute(execution, signature);
    }

    function test_twoStepOwnershipTransferAndControls() public {
        address nextAdmin = address(0xABCD);
        vm.prank(attacker);
        vm.expectRevert(AgentonomyUSDCExecutor.NotOwner.selector);
        executor.transferOwnership(nextAdmin);

        vm.expectEmit(true, true, false, false);
        emit OwnershipTransferStarted(admin, nextAdmin);
        vm.prank(admin);
        executor.transferOwnership(nextAdmin);

        vm.prank(attacker);
        vm.expectRevert(AgentonomyUSDCExecutor.NotPendingOwner.selector);
        executor.acceptOwnership();

        vm.expectEmit(true, true, false, false);
        emit OwnershipTransferred(admin, nextAdmin);
        vm.prank(nextAdmin);
        executor.acceptOwnership();

        vm.prank(admin);
        vm.expectRevert(AgentonomyUSDCExecutor.NotOwner.selector);
        executor.pause();
        vm.prank(nextAdmin);
        executor.pause();
    }

    function test_signerRotationImmediatelyInvalidatesOldPendingSignature() public {
        AgentonomyUSDCExecutor.Execution memory execution = _execution(14, 14, payee, AMOUNT, DEADLINE);
        bytes memory oldSignature = _signature(SIGNER_KEY, execution);

        vm.expectEmit(true, true, true, false);
        emit ExecutionSignerRotated(signer, newSigner, admin, 1, 2);
        vm.prank(admin);
        executor.rotateExecutionSigner(newSigner);

        vm.expectRevert(AgentonomyUSDCExecutor.InvalidSignerEpoch.selector);
        executor.execute(execution, oldSignature);

        execution.signerEpoch = executor.signerEpoch();
        executor.execute(execution, _signature(NEW_SIGNER_KEY, execution));
    }

    function test_signerRotationNeverRevalidatesOldSignerEpochSignature() public {
        AgentonomyUSDCExecutor.Execution memory execution = _execution(21, 21, payee, AMOUNT, DEADLINE);
        bytes memory oldSignature = _signature(SIGNER_KEY, execution);

        vm.prank(admin);
        executor.rotateExecutionSigner(newSigner);
        vm.prank(admin);
        executor.rotateExecutionSigner(signer);

        vm.expectRevert(AgentonomyUSDCExecutor.InvalidSignerEpoch.selector);
        executor.execute(execution, oldSignature);
    }

    function test_nonOwnerCannotRotateSigner() public {
        vm.prank(attacker);
        vm.expectRevert(AgentonomyUSDCExecutor.NotOwner.selector);
        executor.rotateExecutionSigner(newSigner);
    }

    function test_falseMalformedRevertingAndNoCodeTokenFail() public {
        AgentonomyUSDCExecutor.Execution memory falseExecution = _execution(15, 15, payee, AMOUNT, DEADLINE);
        bytes memory falseSignature = _signature(SIGNER_KEY, falseExecution);
        AgentonomyUSDCExecutor.Execution memory malformedExecution = _execution(16, 16, payee, AMOUNT, DEADLINE);
        bytes memory malformedSignature = _signature(SIGNER_KEY, malformedExecution);
        AgentonomyUSDCExecutor.Execution memory revertingExecution = _execution(17, 17, payee, AMOUNT, DEADLINE);
        bytes memory revertingSignature = _signature(SIGNER_KEY, revertingExecution);
        AgentonomyUSDCExecutor.Execution memory noCodeExecution = _execution(18, 18, payee, AMOUNT, DEADLINE);
        bytes memory noCodeSignature = _signature(SIGNER_KEY, noCodeExecution);

        MockBaseUSDC(CANONICAL_USDC).configure(address(executor), MockBaseUSDC.Mode.False);
        vm.expectRevert(AgentonomyUSDCExecutor.TokenReturnedFalse.selector);
        executor.execute(falseExecution, falseSignature);

        MockBaseUSDC(CANONICAL_USDC).configure(address(executor), MockBaseUSDC.Mode.Malformed);
        vm.expectRevert(AgentonomyUSDCExecutor.TokenMalformedReturn.selector);
        executor.execute(malformedExecution, malformedSignature);

        MockBaseUSDC(CANONICAL_USDC).configure(address(executor), MockBaseUSDC.Mode.Reverting);
        vm.expectRevert(AgentonomyUSDCExecutor.TokenCallFailed.selector);
        executor.execute(revertingExecution, revertingSignature);

        vm.etch(CANONICAL_USDC, bytes(""));
        vm.expectRevert(AgentonomyUSDCExecutor.TokenNoCode.selector);
        executor.execute(noCodeExecution, noCodeSignature);
    }

    function test_reentrantTokenCannotEnterExecutor() public {
        AgentonomyUSDCExecutor.Execution memory execution = _execution(19, 19, payee, AMOUNT, DEADLINE);
        bytes memory signature = _signature(SIGNER_KEY, execution);
        MockBaseUSDC mock = MockBaseUSDC(CANONICAL_USDC);
        mock.configure(address(executor), MockBaseUSDC.Mode.Reentrant);
        mock.setReentry(abi.encodeWithSelector(AgentonomyUSDCExecutor.execute.selector, execution, signature));

        executor.execute(execution, signature);
        assertTrue(mock.reentryAttempted());
        assertFalse(mock.reentrySucceeded());
        assertEq(IERC20Test(address(mock)).balanceOf(payee), AMOUNT);
    }

    function test_stateMarkersAreSetBeforeTokenInteraction() public {
        AgentonomyUSDCExecutor.Execution memory execution = _execution(22, 22, payee, AMOUNT, DEADLINE);
        StateCheckingToken observer =
            new StateCheckingToken(address(executor), execution.capabilityHash, execution.owner, execution.nonce);
        vm.etch(CANONICAL_USDC, address(observer).code);

        executor.execute(execution, _signature(SIGNER_KEY, execution));

        assertTrue(executor.usedCapabilityHashes(execution.capabilityHash));
        assertTrue(executor.usedNonces(execution.owner, execution.nonce));
    }

    function test_failedTokenCallRevertsConsumedMarkers() public {
        AgentonomyUSDCExecutor.Execution memory execution = _execution(20, 20, payee, AMOUNT, DEADLINE);
        bytes memory signature = _signature(SIGNER_KEY, execution);
        MockBaseUSDC(CANONICAL_USDC).configure(address(executor), MockBaseUSDC.Mode.False);
        vm.expectRevert(AgentonomyUSDCExecutor.TokenReturnedFalse.selector);
        executor.execute(execution, signature);

        assertFalse(executor.usedCapabilityHashes(execution.capabilityHash));
        assertFalse(executor.usedNonces(execution.owner, execution.nonce));
    }

    function test_canonicalUsdcAddressAndCodeAreRequired() public {
        assertEq(executor.USDC(), 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913);
        uint256 size;
        address tokenAddress = executor.USDC();
        assembly {
            size := extcodesize(tokenAddress)
        }
        assertTrue(size > 0);
    }

    function _execution(uint256 capability, uint256 nonce, address destination, uint256 amount, uint256 deadline)
        internal
        view
        returns (AgentonomyUSDCExecutor.Execution memory execution)
    {
        execution = AgentonomyUSDCExecutor.Execution({
            capabilityHash: bytes32(capability),
            reservationHash: bytes32(capability + 1000),
            owner: ownerAccount,
            payee: destination,
            token: executor.USDC(),
            amount: amount,
            nonce: nonce,
            deadline: deadline,
            signerEpoch: executor.signerEpoch(),
            relayer: address(this)
        });
    }

    function _signature(uint256 privateKey, AgentonomyUSDCExecutor.Execution memory execution)
        internal
        returns (bytes memory signature)
    {
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(privateKey, executor.hashExecution(execution));
        signature = abi.encodePacked(r, s, v);
    }

    function _assertInvalidSigner(AgentonomyUSDCExecutor.Execution memory execution, bytes memory signature) internal {
        vm.expectRevert(AgentonomyUSDCExecutor.InvalidSigner.selector);
        executor.execute(execution, signature);
    }

    function _assertPaymentEvent(
        Vm.Log[] memory logs,
        AgentonomyUSDCExecutor.Execution memory execution,
        address eventSigner,
        address relayer
    ) internal view {
        bytes32 expectedTopic = keccak256(
            "PaymentExecuted(bytes32,bytes32,address,address,address,uint256,uint256,uint256,address,uint256,address)"
        );
        bool found;
        for (uint256 index; index < logs.length; index++) {
            if (
                logs[index].emitter == address(executor) && logs[index].topics.length == 4
                    && logs[index].topics[0] == expectedTopic
            ) {
                found = true;
                assertEq(logs[index].topics[1], execution.capabilityHash);
                assertEq(logs[index].topics[2], execution.reservationHash);
                assertEq(address(uint160(uint256(logs[index].topics[3]))), execution.owner);
                (
                    address eventPayee,
                    address eventToken,
                    uint256 eventAmount,
                    uint256 eventNonce,
                    uint256 eventDeadline,
                    address eventSignerValue,
                    uint256 eventSignerEpoch,
                    address eventRelayer
                ) = abi.decode(
                    logs[index].data, (address, address, uint256, uint256, uint256, address, uint256, address)
                );
                assertEq(eventPayee, execution.payee);
                assertEq(eventToken, execution.token);
                assertEq(eventAmount, execution.amount);
                assertEq(eventNonce, execution.nonce);
                assertEq(eventDeadline, execution.deadline);
                assertEq(eventSignerValue, eventSigner);
                assertEq(eventSignerEpoch, execution.signerEpoch);
                assertEq(eventRelayer, relayer);
            }
        }
        assertTrue(found);
    }

    event Paused(address indexed account);
    event Unpaused(address indexed account);
    event OwnershipTransferStarted(address indexed previousOwner, address indexed newOwner);
    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);
    event ExecutionSignerRotated(
        address indexed previousSigner,
        address indexed newSigner,
        address indexed operator,
        uint256 previousEpoch,
        uint256 newEpoch
    );

    function assertTrue(bool condition) internal pure {
        require(condition, "assertion failed");
    }

    function assertFalse(bool condition) internal pure {
        require(!condition, "assertion failed");
    }

    function assertEq(uint256 left, uint256 right) internal pure {
        require(left == right, "uint256 assertion failed");
    }

    function assertEq(address left, address right) internal pure {
        require(left == right, "address assertion failed");
    }

    function assertEq(bytes32 left, bytes32 right) internal pure {
        require(left == right, "bytes32 assertion failed");
    }
}
