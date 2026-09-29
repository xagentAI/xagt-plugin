# Agentonomy USDC Executor

`AgentonomyUSDCExecutor` is a narrow, non-upgradeable USDC payment executor.
It accepts only a current KMS execution-authority signature over the fixed
EIP-712 `Execution` struct and calls only the deployment's canonical USDC
`transferFrom(owner, payee, amount)` function.

Each deployment permanently binds its immutable `EXECUTION_CHAIN_ID` getter to
the current chain and its immutable `USDC` getter to the corresponding Circle
USDC contract:

| Chain | Chain ID | USDC |
|---|---:|---|
| Base | `8453` | `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913` |
| Polygon | `137` | `0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359` |
| Base Sepolia | `84532` | `0x036CbD53842c5426634e7929541eC2318f3dCF7e` |
| Polygon Amoy | `80002` | `0x41E94Eb019C0762f9Bfcf9Fb1E58725BfB0e7582` |

The EIP-712 domain name is `Agentonomy USDC Executor`, version `1`.

Each capability hash and each `(owner, nonce)` pair is single-use. The
execution signer is separate from the gas-relayer account. Every execution
authorization also carries the monotonically increasing signer epoch. An admin
can pause, unpause, rotate the execution signer, and transfer ownership through
a two-step handoff. Every signer rotation advances the epoch, so signed
executions from any prior signer epoch remain invalid and are never resurrected;
rotation does not re-sign or replace them.

The implementation intentionally has no proxy, upgrade, batch, fee, swap,
rescue, permit, arbitrary-call, or generic-role functionality. The low-level
token call requires deployed code, a successful call, and exactly one ABI bool
returning `true`. State markers are written before the token interaction and
roll back if that interaction fails.

## Build and test

From this directory:

```bash
forge fmt --check
forge test -vvv
```

The test suite uses a tiny local `Vm` interface and `vm.etch` to install a
hostile mock token at the canonical address. It does not import `forge-std`,
OpenZeppelin, or any external Solidity dependency.

## Deployment

The deployment script reads only public addresses from the environment and
selects the allowlisted USDC address from the current chain:

```bash
export CLINK_EXECUTOR_ADMIN=0x...
export CLINK_EXECUTION_SIGNER=0x...
forge script script/DeployAgentonomyUSDCExecutor.s.sol:DeployAgentonomyUSDCExecutor \
  --rpc-url "$RPC_URL" \
  --broadcast
```

The broadcast key is supplied by Foundry's account/private-key mechanism; no
private key is embedded in the script. The script fails closed unless the
current chain is one of the four allowlisted chain/token pairs and both
addresses are nonzero. The constructor also requires deployed code at the
allowlisted USDC address.
