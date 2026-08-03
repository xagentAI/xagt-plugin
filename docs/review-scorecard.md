# MCP Hackathon review scorecard

Scoring starts only after all automated and manual hard gates pass. A high score cannot compensate for an unreachable API, missing source, unverifiable deployment, malicious code, secret exposure, unauthorized data use, or false ownership claims.

## Hard gates

- The pull request changes exactly one project directory under `submissions/`.
- `submission.json`, `SUBMISSION.md`, complete `source/`, and `verification/README.md` are present.
- The public GitHub repository contains the declared 40-character commit.
- The live health check reports `status: ok|healthy` and the exact review commit.
- The live `/.well-known/xagent-verification.json` reports the project slug and exact review commit.
- Source and verification evidence are reproducible in an isolated review environment.
- Baseline secret, malicious-code, licensing, ownership, and data-use checks pass.

## Quality score (100 points)

| Area | Weight | Reviewer question |
| --- | ---: | --- |
| Real agent/user value | 30 | Does this capability complete a meaningful real-world task better than a prompt-only demo? |
| Demonstrated capability quality | 25 | Do live results, error behavior, limits, and evidence show reliable usefulness? |
| Engineering and maintainability | 20 | Is the source understandable, reproducible, tested, observable, and maintainable? |
| MCP productization readiness | 15 | Are tool boundaries, inputs, outputs, authorization, errors, and side effects clear? |
| Adoption and operating potential | 10 | Can the team operate, support, and improve the capability after the event? |

Each reviewer records evidence, not only a number. Two reviewers score independently. A material difference of 15 or more total points requires reconciliation. The program notice defines any selection threshold and tie-break process.

## Fraud and abuse review

Reviewers may request a short live challenge, repository ownership proof, service log excerpt with sensitive data removed, or a new deployment proof tied to a fresh commit. Plagiarism, undisclosed copied work, fake deployment evidence, purchased engagement, identity manipulation, or coordinated scoring abuse results in rejection and may disqualify related entries.
