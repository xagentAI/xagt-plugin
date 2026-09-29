// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {DeployAgentonomyUSDCExecutor} from "../script/DeployAgentonomyUSDCExecutor.s.sol";

interface Vm {
    function expectRevert(bytes calldata revertData) external;
}

contract DeployAgentonomyUSDCExecutorHarness is DeployAgentonomyUSDCExecutor {
    function approvedUsdc(uint256 chainId) external pure returns (address) {
        return _approvedUsdc(chainId);
    }
}

contract DeployAgentonomyUSDCExecutorTest {
    Vm internal constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));

    uint256 internal constant BASE_CHAIN_ID = 8453;
    uint256 internal constant POLYGON_CHAIN_ID = 137;
    uint256 internal constant BASE_SEPOLIA_CHAIN_ID = 84532;
    uint256 internal constant POLYGON_AMOY_CHAIN_ID = 80002;
    address internal constant BASE_USDC = 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913;
    address internal constant POLYGON_USDC = 0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359;
    address internal constant BASE_SEPOLIA_USDC = 0x036CbD53842c5426634e7929541eC2318f3dCF7e;
    address internal constant POLYGON_AMOY_USDC = 0x41E94Eb019C0762f9Bfcf9Fb1E58725BfB0e7582;

    DeployAgentonomyUSDCExecutorHarness internal harness;

    function setUp() public {
        harness = new DeployAgentonomyUSDCExecutorHarness();
    }

    function test_allowlistAcceptsExactlyTheFourApprovedPairs() public view {
        assertEq(harness.approvedUsdc(BASE_CHAIN_ID), BASE_USDC);
        assertEq(harness.approvedUsdc(POLYGON_CHAIN_ID), POLYGON_USDC);
        assertEq(harness.approvedUsdc(BASE_SEPOLIA_CHAIN_ID), BASE_SEPOLIA_USDC);
        assertEq(harness.approvedUsdc(POLYGON_AMOY_CHAIN_ID), POLYGON_AMOY_USDC);
    }

    function test_allowlistRejectsUnsupportedChain() public {
        vm.expectRevert(abi.encodeWithSelector(DeployAgentonomyUSDCExecutor.WrongChain.selector, uint256(1)));
        harness.approvedUsdc(1);
    }

    function assertEq(address left, address right) internal pure {
        if (left != right) revert("assertion failed");
    }
}
