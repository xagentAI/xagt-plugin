# ADR 0002: Separate current and historical hackathon records

## Status

Accepted — 2026-08-03

## Context

The repository already contains 19 preserved submissions from the May 2026 X-Agent × OKX Agentic Wallet Hackathon. Its archived projects use top-level `submissions/<participant-id>-<project>/` directories. Reusing that namespace for the new MCP Hackathon would make historical records look like current entries and would allow a new submission workflow to touch archive paths.

## Decision

Keep every historical directory at its existing path to preserve evidence and inbound links. Place all new MCP Hackathon entries under `submissions/mcp-hackathon/<team>-<project>/`.

The pull-request workflow triggers only for the MCP namespace, and the trusted validator rejects changes outside exactly one project directory inside that namespace. The root README presents the MCP Hackathon as the current program and links to a dedicated archive page containing the previous program's rules and submission index.

## Alternatives considered

- **Move historical projects into an archive directory.** Rejected because it would break existing paths and create a large, unnecessary historical rewrite.
- **Reuse the top-level submission namespace.** Rejected because old and new contracts would be ambiguous and the current automation could accidentally process archive changes.
- **Use a separate repository.** Rejected for now because the official code and PR history already live here, and a dedicated namespace provides sufficient separation with less operational overhead.

## Consequences

- Historical links and code snapshots stay stable.
- New submission paths are longer but unambiguous.
- CLI output, templates, validation, sealing, and documentation must all use the MCP namespace.
- A later program should receive its own namespace rather than reuse the MCP directory.

## Rollback

The namespace can be replaced before the first MCP submission is accepted by updating the CLI, workflow, validator, templates, and docs together. After an accepted submission exists, the path is part of the permanent program record and should not be rewritten.
