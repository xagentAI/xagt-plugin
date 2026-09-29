# Current-source privacy and integrity checks

Review commit: `029cd0ba9aff3c25fffa33ae27f94615c1eebe2b`.

All 738 exported source files were checked against the exact committed snapshot by SHA-256, byte size and complete path set. The outer manifest is authoritative. The official baseline secret scanner and export preflight reported no secret findings. A targeted scan of the whole current submission found no occurrences of the former personal sample identifier; generic `telegram_demo_user` fixtures remain.

New public-demo credentials are generated at runtime, stored only as hashes in the session ledger, and delivered through HttpOnly cookies. The browser stores only noncredential session/order identifiers. Runtime databases, cookie jars, verifier private state files, deployment environment files, private API tokens, and company deployment settings are excluded. Checked deployment evidence is projected to source version, boolean results, simulated budget/counters and public status.

A focused code review covered authentication separation, CSRF, visitor isolation, worker lifecycle, and verifier recovery. Two recovery issues were fixed and rechecked. This is a targeted snapshot review, not a history rewrite or comprehensive security certification. Public contact information was supplied by the owner.
