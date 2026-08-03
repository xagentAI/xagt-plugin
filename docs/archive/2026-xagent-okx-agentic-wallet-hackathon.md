# Archive: X-Agent × OKX Agentic Wallet Hackathon

> Historical record. This program is closed and is not the current MCP Hackathon submission contract.

## Program snapshot

| Field | Archived value |
| --- | --- |
| Program | X-Agent × OKX Agentic Wallet Hackathon |
| Kickoff | May 11, 2026 |
| Submission activity | May 13–18, 2026 |
| Prize pool announced | 6,000 USDT |
| Original submission repository | `xagent-labs/xagt-plugin` |
| Archive created | May 31, 2026 |
| Preserved submission records | 19 |

The program asked participants to build an X-Agent plugin or product using X-Agent identity, the X-Agent plugin setup flow, OKX Agentic Wallet capabilities, and OKX skills. The original public description presented the repository as the X-Agent plugin marketplace and OKX Agentic Wallet hackathon submission hub.

For an exact, unedited record, see the [`original README snapshot at the final pre-MCP commit`](https://github.com/xagentAI/xagt-plugin/blob/a3fde4c790fe9f9a136e77f23e61925ab0c93997/README.md). The sections below summarize that snapshot and connect it to the preserved project files.

## Original participation model

Participants installed the plugin and registered through X-Agent:

```bash
npx @xagt/agent-plugin@latest setup --target all
```

The setup flow opened a browser for sign-in, created the participant identity, and installed the OKX skill suite into supported agent runtimes. The original program supported Cursor, Claude Code, and AgentSkills-compatible runtimes.

The program separated four responsibilities:

| Layer | Original owner | Role in the program |
| --- | --- | --- |
| Identity | X-Agent | Registered participants and identified submissions. |
| Wallet and writes | OKX Agentic Wallet | Wallet connection, signing, swaps, transfers, and gas-bearing actions. |
| Intelligence | Agent runtime and OKX skills | Routed user intent to market, DeFi, security, wallet, and trading capabilities. |
| Product | Participant | Built the experience, workflow, business logic, and user interface. |

## Original eligibility rules

A qualifying entry was required to:

- register through `xagt-plugin setup --target all` or `xagt-plugin login`;
- use at least one OKX skill;
- publish a public GitHub repository containing the project source;
- provide a one-line description of the product; and
- submit under the participant ID assigned by X-Agent.

A deployed demo and demo video or GIF were encouraged but optional. Each participant ID owned one folder under the original `projects/` layout. Before the deadline, a participant could open another PR to update that entry.

These are historical rules only. The current MCP Hackathon does not require a participant ID, a prescribed OKX skill, a predefined product category, or an MCP server at entry.

## Original submission flow

The original CLI command was:

```bash
xagt-plugin submit
```

It collected the project name, one-line description, public GitHub repository, and optional deployed URL. It then opened GitHub with a proposed file at:

```text
projects/<participant-id>/README.md
```

The participant completed the GitHub pull request, and judges merged accepted records. This historical workflow relied heavily on an external source repository; the later archive process copied source into the official repository whenever the external repository was still available.

## What has been preserved

The complete archive index is [`submissions/INDEX.md`](../../submissions/INDEX.md). Each preserved entry remains under:

```text
submissions/<participant-id>-<project-slug>/
├── META.md            # original PR, author, source link, and PR body
├── pr-submission/     # files submitted in the original PR
└── source/            # copied source snapshot, when available
```

The archive contains `19` participant submission records. The source repositories for three entries were already unavailable when archival was performed; those entries retain their PR evidence and are explicitly marked as source unavailable. The archive does not silently claim that missing source was recovered.

Historical directory names and records remain stable so prior links and evidence continue to work. New MCP Hackathon projects must use `submissions/mcp-hackathon/<team>-<project>/` and must not modify a historical entry.

## Why this archive matters

The archive preserves the activity description, eligibility model, participant records, original PR evidence, and source snapshots that were obtainable at archive time. It provides an auditable distinction between what was submitted, what was preserved, and what could no longer be recovered.

For the active program, return to the [repository README](../../README.md) or read the [X-Agent MCP Hackathon rules](../mcp-hackathon.md).
