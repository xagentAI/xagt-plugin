// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {AgentonomyUSDCExecutor} from "../src/AgentonomyUSDCExecutor.sol";

interface Vm {
    function envAddress(string calldata key) external returns (address);
    function startBroadcast() external;
    function stopBroadcast() external;
}

contract DeployAgentonomyUSDCExecutor {
    Vm internal constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));

    error WrongChain(uint256 chainId);
    error MissingAddress(string key);
    error InvalidDeployedToken(address expected, address actual);

    event ExecutorDeployed(address indexed executor, address indexed admin, address indexed executionSigner);

    function run() external returns (AgentonomyUSDCExecutor deployed) {
        address expectedUsdc = _approvedUsdc(block.chainid);
        address admin = vm.envAddress("CLINK_EXECUTOR_ADMIN");
        address executionSigner = vm.envAddress("CLINK_EXECUTION_SIGNER");
        if (admin == address(0)) revert MissingAddress("CLINK_EXECUTOR_ADMIN");
        if (executionSigner == address(0)) {
            revert MissingAddress("CLINK_EXECUTION_SIGNER");
        }

        vm.startBroadcast();
        deployed = new AgentonomyUSDCExecutor(admin, executionSigner);
        vm.stopBroadcast();

        if (deployed.USDC() != expectedUsdc) {
            revert InvalidDeployedToken(expectedUsdc, deployed.USDC());
        }
        emit ExecutorDeployed(address(deployed), admin, executionSigner);
    }

    function _approvedUsdc(uint256 chainId) internal pure returns (address token) {
        if (chainId == 8453) return 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913;
        if (chainId == 137) return 0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359;
        if (chainId == 84532) return 0x036CbD53842c5426634e7929541eC2318f3dCF7e;
        if (chainId == 80002) return 0x41E94Eb019C0762f9Bfcf9Fb1E58725BfB0e7582;
        revert WrongChain(chainId);
    }
}
