# sandboxed.sh

**Participant ID:** `2054407797725990912`
**Submitted via:** `xagt-plugin@0.4.0`
**Submitted at:** 2026-05-14T03:23:43.892Z

## Description

sandboxed.sh is the safe runtime for autonomous on-chain AI agents.

## Why it fits Build with XAgent x OKX

sandboxed.sh is an existing shipped product for running autonomous coding agents
inside isolated Linux workspaces. For the hackathon, it adds a focused
read-only OKX security skill integration: agents can pre-flight token, dApp,
transaction, signature, and approval risk without signing, broadcasting, or
exposing wallet secrets to the model.

Featured hackathon work:

- OKX integration PR: https://github.com/Th0rgal/sandboxed.sh/pull/431
- Screenshot: https://raw.githubusercontent.com/Th0rgal/sandboxed.sh/hackathon/okx-integration/screenshots/okx-security-report.png
- Demo shot list: https://github.com/Th0rgal/sandboxed.sh/blob/hackathon/okx-integration/DEMO.md

The OKX skill is installed through sandboxed.sh's Git-backed Library and synced
into Claude Code, OpenCode, and Amp mission environments through shared
injection logic. The entry is intentionally read-only: the safety boundary is
the product, not a missing feature.

## Repo

https://github.com/Th0rgal/sandboxed.sh

## Deployed URL

https://sandboxed.sh

## Hackathon

Build with XAgent × OKX (May 2026)
