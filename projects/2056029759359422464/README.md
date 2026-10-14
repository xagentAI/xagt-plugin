# Wallet Whisperer

**Participant ID:** `2056029759359422464`
**Submitted via:** `xagt-plugin@0.4.0`
**Submitted at:** 2026-05-18T01:43:43.085Z

> Read any wallet's trading personality. Narrate their best and worst trades. Mirror their style with explicit per-trade confirmation.

## Live demo

**https://wallet-whisperer.onrender.com**

Zero signup, no wallet connect. Paste any address (the page has a sample chip) and watch each OKX skill light up live on the left as the data streams in.

## Repo

https://github.com/Temitope15/wallet-whisperer

## Demo video

_Walkthrough of all three surfaces — published in the [GitHub repo README](https://github.com/Temitope15/wallet-whisperer#try-it-now)._

## Description

Wallet Whisperer is an OKX OnchainOS agent that turns any wallet address into a one-screen trading persona: style (scalper / day trader / swing / position / hodl), sizing pattern, sector tilt, behavioural tells (Top-Catcher, Tactical Re-entry, Capitulator, Revenge Trader, FOMO Sizer, Stop-Loss Disciplined), edge metrics, and a verdict — distilled from 90 days of DEX history.

It narrates the wallet's best and worst trades and, optionally, mirrors its in-character new trades on the user's own wallet. Every candidate goes through `okx-security` and waits for an explicit `execute` reply in the agent host before any swap runs. Persona inference is fully deterministic — same input, same output. The LLM only writes a single verdict sentence at the bottom of the card.

## OKX skills used

| Skill | Operation | Used for |
|---|---|---|
| `okx-agentic-wallet` | `wallet status` | Pre-flight: confirm the session is logged in |
| `okx-dex-market` | `portfolio-overview` | Win rate, realised PnL, buy / sell counts, market-cap tilt |
| `okx-dex-market` | `portfolio-recent-pnl` | Per-token PnL, hold times, best / worst trade selection |
| `okx-dex-market` | `portfolio-dex-history` | (Skill mode) FIFO inventory pagination |
| `okx-tracker` | `activities` | Mirror: live poll of the source wallet's new buys |
| `okx-security` | `token-scan` | Mandatory honeypot / mint / washtrade check per mirror candidate |
| `okx-wallet-portfolio` | `total-value` | Mirror: size candidates against the user's portfolio cap |
| `okx-dex-swap` | `swap` | Mirror: execute after user types `execute` |
| `okx-strategy` | `create-limit` | Mirror: auto stop-loss when the source persona is Stop-Loss Disciplined |

All on-chain writes go through the TEE-managed Agentic Wallet via `onchainos swap swap`. All reads use the documented Market API on the user's free 1M-call / month tier. No third-party data sources.

## Three surfaces, one engine

| Surface | Install | Mirror support |
|---|---|---|
| **Hosted web app** | nothing to install — open the URL above | Setup wizard + live preview poll; hands off the prompt to the agent host |
| **Terminal CLI** | `npm install -g .` from `cli/` | `mirror` subcommand prints handoff instructions |
| **Agent skill** (Claude Code, Cursor, Codex, OpenCode, Windsurf, AgentSkills) | `wallet-whisperer init <host>` (one command, idempotent, supports six hosts) | Full mirror loop with per-trade `execute` confirmation |

## Key features

- **Deterministic persona inference** across six dimensions, computed in `cli/lib/persona.js`. Two runs on the same data produce the same card.
- **Live OKX skills sidebar** in the web app: each `onchainos` call streams its start / completion over SSE, with a pulsing blue ring + live-ms ticker while running, and a green check + final timing when done. Nothing mocked.
- **One-line skill install** into six agent hosts: `wallet-whisperer init claude` (or `cursor`, `codex`, `opencode`, `windsurf`, `agents`). Idempotent. Falls back to downloading the skill from GitHub if the local repo isn't present.
- **Style-filtered mirroring.** Out-of-character trades (rugs, hacks, revenge entries) are auto-skipped. The skill is the safety net naïve copy-trade bots lack.
- **No auto-broadcast.** Every mirror candidate surfaces as a confirmation card and waits for the user to type `execute`.
- **Drift detection.** The source persona is re-profiled every 7 days; style shift or score below threshold auto-pauses the mirror.

## Architecture

```
                         ┌───────────────────────────┐
                         │   onchainos CLI (OKX)     │
                         │  market · tracker ·       │
                         │  security · swap · etc.   │
                         └─────────────┬─────────────┘
                                       │
                          ┌────────────┴────────────┐
                          │   cli/lib/onchainos.js  │
                          └────────────┬────────────┘
                                       │
                       ┌───────────────┴───────────────┐
                       │     cli/lib/persona.js        │
                       │  deterministic inference      │
                       └───────────────┬───────────────┘
                                       │
            ┌──────────────────────────┼──────────────────────────┐
            ▼                          ▼                          ▼
   ┌─────────────────┐       ┌───────────────────┐      ┌──────────────────┐
   │   Terminal CLI  │       │  Web server (SSE) │      │   Agent skill    │
   │  + render lib   │       │ live skills view  │      │ skills/SKILL.md  │
   └─────────────────┘       └───────────────────┘      └──────────────────┘
```

## Stack

- Node 20 (zero runtime dependencies in the web server)
- OKX OnchainOS CLI (`onchainos` v3.3.3, sha256-pinned in the Dockerfile)
- Server-Sent Events for live skill telemetry
- Tailwind CSS (via CDN), Instrument Serif + Poppins + JetBrains Mono
- Docker + Render for the hosted deployment

## Hackathon

Build with XAgent × OKX (May 2026) — Builder track.
