# Application implementation

[ARCHITECTURE.md](../docs/ARCHITECTURE.md) describes modules, storage, and endpoints. [METHOD.md](../docs/METHOD.md) is the canonical financial method. `main.py` provides HTTP handling and experiment orchestration; `storage.py` defines storage exceptions and experiment-finalization rules; `workers_storage.py` implements session-scoped SQLite Durable Objects. `evidence.py` and `reproduce.py` export evidence and verify it offline. The domain layer depends on neither HTTP nor a database.
