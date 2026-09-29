# Local Commerce acceptance

The demo is deterministic service procurement through a real MCP connection:

1. The demo owner creates a fresh in-memory test wallet, signs a 1.00 USDC
   Spending Grant and supplies simulated allowance evidence to Core.
2. The Agent lists services through `clink_node`, then selects an order-analysis
   service priced at 0.30 USDC.
3. Marketplace locks the input and quote. Core validates identity, authorization,
   policy and the budget, reserves funds and verifies simulated settlement.
4. The merchant checks the Core receipt and returns order counts, totals and
   category totals. Marketplace returns and retains a retrievable result.
5. Repeating the same preview execution returns the existing purchase. The
   settlement count and consumed budget do not increase.

The owner setup is demo bootstrapping, not an Agent tool granting itself funds.
Agent-facing schemas do not accept a user identity, signature, transaction hash
or a replacement spending authorization.

```sh
make PYTHON=.venv/bin/python demo
make PYTHON=.venv/bin/python test-commerce
```

`demo` prints JSON evidence. The test suite also exercises insufficient budget,
revoked authorization and paid-but-undelivered replay behavior. The latter is a
safe terminal state in the imported implementation: retries do not charge again,
but automatic redelivery is not implemented or claimed.

## Connect an MCP client

Use the absolute paths of this checkout and its Python interpreter:

```json
{
  "mcpServers": {
    "clink_node": {
      "command": "/absolute/path/agentonomy-commerce/.venv/bin/python",
      "args": ["-m", "examples.commerce.node"],
      "cwd": "/absolute/path/agentonomy-commerce"
    }
  }
}
```

Suggested prompt:

> Find the cheaper order-analysis service. Preview and execute a purchase for
> orders 12.50/books, 7.25/food and 2.50/books. Return the purchased result, purchase
> id and remaining authorized budget. Read the existing purchase if a result is
> uncertain; do not create another purchase to recover a paid delivery failure.

## What is real and what is simulated

Real: the Node MCP gateway and routing, cryptographic grant verification, Core
policy/reservation/accounting, Marketplace purchase transitions and idempotency,
merchant receipt verification, and delivery of computed order-analysis results.

Simulated: the blockchain RPC and transaction inclusion, external risk assessment,
the provider directory admission and the local merchant transport. The supplied
values are demonstration data, not live market data.

No external network call is required. Each demo/MCP process lifetime has fresh
local state and a fresh test mandate; it is not a persistent production wallet.
A live-chain rehearsal requires separate wallet consent and environment setup.

The result mailbox is transient. Retrieve the result in the same demo session;
restarting the demo creates a fresh rehearsal and is not a result archive.
