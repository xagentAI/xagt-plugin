// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

contract MockBaseUSDC {
    enum Mode {
        Success,
        False,
        Malformed,
        Reverting,
        Reentrant
    }

    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;
    address public executor;
    Mode public mode;
    bytes public reentryData;
    bool public reentryAttempted;
    bool public reentrySucceeded;

    function configure(address executorAddress, Mode newMode) external {
        executor = executorAddress;
        mode = newMode;
        reentryAttempted = false;
        reentrySucceeded = false;
    }

    function setReentry(bytes calldata data) external {
        reentryData = data;
    }

    function mint(address account, uint256 amount) external {
        balanceOf[account] += amount;
    }

    function approve(address spender, uint256 amount) external returns (bool) {
        allowance[msg.sender][spender] = amount;
        return true;
    }

    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        require(msg.sender == executor, "not executor");
        if (mode == Mode.Reverting) revert("mock revert");
        if (mode == Mode.False) return false;
        if (mode == Mode.Malformed) {
            assembly {
                mstore(0, 1)
                return(0, 1)
            }
        }
        if (mode == Mode.Reentrant) {
            reentryAttempted = true;
            (reentrySucceeded,) = executor.call(reentryData);
        }
        require(allowance[from][msg.sender] >= amount, "allowance");
        allowance[from][msg.sender] -= amount;
        balanceOf[from] -= amount;
        balanceOf[to] += amount;
        return true;
    }
}
