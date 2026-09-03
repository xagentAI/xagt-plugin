# Architecture

```
Agent -> POST /v1/sessions (scope+pagination_type+strategy)
  -> POST /v1/sessions/{id}/observe per page (cursor/offset/page/single)
  -> POST /v1/sessions/{id}/failure on errors
  -> POST /v1/sessions/{id}/verify {claim} -> PROVEN/UNPROVEN/CONDITIONAL
  -> GET /v1/sessions/{id}/certificate (SHA-256 evidence digest)
```

Modules (`backend/app/services/`): `scope` (canonical hash), `pagination`
(chain/loop/gap/exhaustion), `obligations` (per-type requirements + reason codes),
`verifier` (pure deterministic verdict), `certificates`, `claim_parser`
(regex; LLM hook reserved). Storage: SQLite/SQLAlchemy, one `sessions` table.
