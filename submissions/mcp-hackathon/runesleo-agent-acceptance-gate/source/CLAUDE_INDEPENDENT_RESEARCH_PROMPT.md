# Claude Independent Research Prompt

Purpose: let Claude independently re-evaluate the OKX.AI / Agent commerce opportunity without being anchored by the current Codex-built product.

Use this tomorrow in a fresh Claude thread.

## Phase 1: Blind market research

Do **not** read `/Users/zhangxu/Projects/agent-acceptance-gate` yet.

Start from first principles and current market evidence.

Research:

1. What will the OKX.AI / agent-commerce / A2A / A2MCP market likely become?
2. In a world where agents hire agents, call tools, spend budgets, deliver work, release escrow, and dispute outcomes, which services are naturally high-frequency?
3. Which services have the largest market capacity or highest willingness to pay?
4. Which services are likely to be platform-owned vs third-party ASP opportunities?
5. What should a one-person company build first if the target is meaningful revenue, not just a hackathon demo?

Required sources:

- OKX.AI official docs: ASP, A2MCP, A2A, Evaluator, ASP registration.
- OKX / X Layer hackathon announcement and Star_OKX $1M OPC tweet.
- Agentic payments: x402, AP2, UCP, OKX Payment SDK.
- MCP ecosystem: tool directories, MCP adoption, MCP security/market research.
- Agent marketplaces: RentAHuman or similar task/escrow systems.
- Agent eval / observability / QA companies: LangSmith, Braintrust, HoneyHive, Arize.

Output format:

```text
1. Market structure map
2. High-frequency service demand map
3. Highest-revenue opportunity ranking
4. Risks / platform-owned areas
5. Recommended wedge for Leo
6. 7-day execution plan
7. Kill criteria
```

Important:

- Do not assume `Agent Acceptance Gate` is correct.
- Do not optimize for what Codex already built.
- If the best answer is unrelated to acceptance/verification, say so.
- Separate "strategically interesting" from "currently demanded."

## Phase 2: Compare against Codex repo

Only after Phase 1 is complete, read:

```text
/Users/zhangxu/Projects/agent-acceptance-gate
```

Then compare:

1. Where does the existing repo match your independent market thesis?
2. Where is it overfit to Codex's assumptions?
3. What should be kept?
4. What should be renamed, pivoted, or killed?
5. What is the next concrete step if Leo wants to pursue the strongest opportunity?

Output format:

```text
Claude independent conclusion:

Keep:
Change:
Kill:
New direction:
Next 24h:
Next 7d:
Hard gates:
```

## Hard gates

Do not do any of these without explicit Leo approval:

- OKX.AI account / Agentic Wallet login;
- API key / credential setup;
- wallet address / funding / signing / transaction / staking;
- payment middleware / x402 / OKX Payment SDK integration;
- ASP listing submission;
- GitHub remote creation or public repo;
- push / deploy / production endpoint;
- leolabs public publish.

Read-only web research and local notes are allowed.

