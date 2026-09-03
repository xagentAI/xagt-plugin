# Architecture

```
OpenAPI JSON/YAML/URL
  -> importer (parse + validate + extract endpoints)
  -> analyzer (deterministic per-endpoint quality)
  -> tester (httpx, safe methods only, SSRF guard, timeout/retry)
  -> scoring (6 categories, 0-100, transparent)
  -> repair (declarative rules: rename/extract_number/map_enum/...)
  -> proxy (validate args -> upstream -> validate -> normalize -> stable JSON)
  -> tool_generator (agent-readable JSON per endpoint)
  -> retest (before/after comparison)
```

Storage: SQLite via SQLAlchemy (`backend/app/models/db.py`), one `projects` table with JSON columns.
No LLM required. Optional `LLM_*` env vars reserved for future description repair.
SSRF: blocks 0.0.0.0/metadata/private nets; `ALLOW_PRIVATE_NETWORK=true` only for local dev.
