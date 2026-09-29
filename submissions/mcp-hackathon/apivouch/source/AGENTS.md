# Repository Instructions

## Purpose

Ship the focused API-verification agent used for the XAgent hackathon, separate from the long-term SKLab platform.

## Read before editing

- `backend/app/` for API and MCP behavior
- `backend/tests/` and `examples/` for verified flows
- `scripts/verify_hackathon.py` for the submission gate

## Working rules

- Work only inside this repository unless the user explicitly requests a coordinated cross-repository change.
- Read `README.md`, the package manifest, and the relevant CI workflow before changing behavior.
- Preserve unrelated user changes. Do not rewrite or delete work merely to make a patch cleaner.
- Never commit credentials, tokens, client data, local state, caches, build output, or generated secrets.
- Do not describe a configured, mocked, or importable integration as successfully executed.
- When behavior or a public contract changes, update tests and user-facing documentation in the same change.
- Preserve content-addressed evidence receipts and deterministic offline verification.
- Keep live API results, simulated responses, and fallback behavior explicitly distinguishable.
- MCP tool schemas and HTTP response models are public contracts; change them deliberately and test both paths.

## Verification

- `python -m ruff check backend/app backend/tests examples scripts`
- `python -m pytest -q`
- `python scripts/verify_hackathon.py`
- `node --check frontend/app.js`
- `docker build -t apivouch:verify .`

If an environment-dependent check cannot run, state exactly what was skipped and
why. Do not replace a missing check with a claim of success.

## Completion checklist

- The smallest correct change is implemented within this repository's scope.
- New or changed behavior has focused tests.
- Public interfaces, examples, and limitations are documented.
- Security and credential boundaries still hold.
- `git diff --check` passes and the working tree contains no unintended files.
