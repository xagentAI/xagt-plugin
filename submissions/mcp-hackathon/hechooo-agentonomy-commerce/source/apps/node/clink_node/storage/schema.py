from __future__ import annotations


SCHEMA_VERSION = 6
_FUTURE_SCHEMA_ERROR = "storage_schema_newer_than_binary"


def ensure_supported_schema_versions(*versions: object | None) -> None:
    normalized: list[int] = []
    try:
        for version in versions:
            if version is None or isinstance(version, bool):
                if version is None:
                    continue
                raise ValueError
            parsed = int(version)
            if parsed < 0:
                raise ValueError
            normalized.append(parsed)
    except (TypeError, ValueError):
        raise RuntimeError(_FUTURE_SCHEMA_ERROR) from None
    if normalized and max(normalized) > SCHEMA_VERSION:
        raise RuntimeError(_FUTURE_SCHEMA_ERROR)

SQLITE_MIGRATIONS: tuple[tuple[int, str], ...] = (
    (
        1,
        """
        CREATE TABLE IF NOT EXISTS node_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS module_state (
            name TEXT PRIMARY KEY,
            mode TEXT NOT NULL,
            status TEXT NOT NULL,
            pid INTEGER,
            endpoint TEXT,
            mcp_url TEXT,
            detail TEXT,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS interaction_session (
            session_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            user_id TEXT NOT NULL,
            token_hash TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            consumed_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_interaction_user
            ON interaction_session(user_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_interaction_expiry
            ON interaction_session(status, expires_at);

        CREATE TABLE IF NOT EXISTS event_outbox (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            aggregate_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            published_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_event_pending
            ON event_outbox(published_at, event_id);

        CREATE TABLE IF NOT EXISTS secret_reference (
            name TEXT PRIMARY KEY,
            backend TEXT NOT NULL,
            reference TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """,
    ),
    (
        2,
        """
        CREATE TABLE IF NOT EXISTS miniapp_browser_session (
            session_id TEXT PRIMARY KEY
                CHECK(length(session_id) BETWEEN 1 AND 256),
            telegram_user_id TEXT NOT NULL
                CHECK(length(telegram_user_id) BETWEEN 1 AND 256),
            subject_id TEXT NOT NULL
                CHECK(length(subject_id) BETWEEN 1 AND 256),
            exchange_hash TEXT NOT NULL UNIQUE
                CHECK(
                    length(exchange_hash) = 64
                    AND exchange_hash NOT GLOB '*[^0-9a-f]*'
                ),
            client_nonce_hash TEXT NOT NULL
                CHECK(
                    length(client_nonce_hash) = 64
                    AND client_nonce_hash NOT GLOB '*[^0-9a-f]*'
                ),
            session_token_hash TEXT NOT NULL UNIQUE
                CHECK(
                    length(session_token_hash) = 64
                    AND session_token_hash NOT GLOB '*[^0-9a-f]*'
                ),
            csrf_token_hash TEXT NOT NULL
                CHECK(
                    length(csrf_token_hash) = 64
                    AND csrf_token_hash NOT GLOB '*[^0-9a-f]*'
                ),
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            revoked_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_miniapp_browser_subject
            ON miniapp_browser_session(subject_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_miniapp_browser_active
            ON miniapp_browser_session(session_token_hash, expires_at)
            WHERE revoked_at IS NULL;

        CREATE TABLE IF NOT EXISTS miniapp_hermes_binding (
            subject_id TEXT PRIMARY KEY
                CHECK(length(subject_id) BETWEEN 1 AND 256),
            hermes_session_id TEXT NOT NULL UNIQUE
                CHECK(length(hermes_session_id) BETWEEN 1 AND 256),
            session_key_hash TEXT NOT NULL UNIQUE
                CHECK(
                    length(session_key_hash) = 64
                    AND session_key_hash NOT GLOB '*[^0-9a-f]*'
                ),
            created_at TEXT NOT NULL,
            revoked_at TEXT
        );

        CREATE TABLE IF NOT EXISTS miniapp_message_claim (
            subject_id TEXT NOT NULL
                CHECK(length(subject_id) BETWEEN 1 AND 256),
            client_message_id TEXT NOT NULL
                CHECK(length(client_message_id) BETWEEN 1 AND 256),
            payload_hash TEXT NOT NULL
                CHECK(
                    length(payload_hash) = 64
                    AND payload_hash NOT GLOB '*[^0-9a-f]*'
                ),
            status TEXT NOT NULL
                CHECK(status IN ('starting', 'accepted', 'unknown')),
            hermes_run_id TEXT
                CHECK(
                    hermes_run_id IS NULL
                    OR length(hermes_run_id) BETWEEN 1 AND 256
                ),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK(
                (
                    status IN ('starting', 'unknown')
                    AND hermes_run_id IS NULL
                ) OR (
                    status = 'accepted'
                    AND hermes_run_id IS NOT NULL
                    AND length(hermes_run_id) BETWEEN 1 AND 256
                )
            ),
            PRIMARY KEY(subject_id, client_message_id)
        );
        """,
    ),
    (
        3,
        """
        ALTER TABLE miniapp_message_claim
            RENAME TO miniapp_message_claim_v2;

        CREATE TABLE miniapp_message_claim (
            subject_id TEXT NOT NULL
                CHECK(length(subject_id) BETWEEN 1 AND 256),
            client_message_id TEXT NOT NULL
                CHECK(length(client_message_id) BETWEEN 1 AND 256),
            payload_hash TEXT NOT NULL
                CHECK(
                    length(payload_hash) = 64
                    AND payload_hash NOT GLOB '*[^0-9a-f]*'
                ),
            status TEXT NOT NULL
                CHECK(status IN ('starting', 'accepted', 'unknown')),
            hermes_run_id TEXT
                CHECK(
                    hermes_run_id IS NULL
                    OR length(hermes_run_id) BETWEEN 1 AND 256
                ),
            hermes_run_session_id TEXT
                CHECK(
                    hermes_run_session_id IS NULL
                    OR length(hermes_run_session_id) BETWEEN 1 AND 256
                ),
            legacy_unreconciled INTEGER NOT NULL DEFAULT 0
                CHECK(legacy_unreconciled IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK(
                (
                    legacy_unreconciled = 1
                    AND status = 'unknown'
                    AND hermes_run_id IS NULL
                    AND hermes_run_session_id IS NULL
                ) OR (
                    legacy_unreconciled = 0
                    AND hermes_run_session_id IS NOT NULL
                    AND length(hermes_run_session_id) BETWEEN 1 AND 256
                    AND (
                        (
                            status IN ('starting', 'unknown')
                            AND hermes_run_id IS NULL
                        ) OR (
                            status = 'accepted'
                            AND hermes_run_id IS NOT NULL
                            AND length(hermes_run_id) BETWEEN 1 AND 256
                        )
                    )
                )
            ),
            PRIMARY KEY(subject_id, client_message_id)
        );

        INSERT INTO miniapp_message_claim(
            subject_id, client_message_id, payload_hash,
            status, hermes_run_id, hermes_run_session_id,
            legacy_unreconciled, created_at, updated_at
        )
        SELECT
            subject_id, client_message_id, payload_hash,
            'unknown', NULL, NULL,
            1, created_at, updated_at
        FROM miniapp_message_claim_v2;

        DROP TABLE miniapp_message_claim_v2;
        """,
    ),
    (
        4,
        """
        CREATE TABLE miniapp_active_run_lease (
            subject_id TEXT PRIMARY KEY
                CHECK(length(subject_id) BETWEEN 1 AND 256),
            client_message_id TEXT NOT NULL
                CHECK(length(client_message_id) BETWEEN 1 AND 256),
            acquired_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(subject_id, client_message_id)
                REFERENCES miniapp_message_claim(
                    subject_id, client_message_id
                )
                ON DELETE RESTRICT
        );

        INSERT INTO miniapp_active_run_lease(
            subject_id, client_message_id, acquired_at, updated_at
        )
        SELECT
            claim.subject_id,
            claim.client_message_id,
            claim.created_at,
            claim.updated_at
        FROM miniapp_message_claim AS claim
        WHERE claim.legacy_unreconciled = 0
          AND NOT EXISTS (
              SELECT 1
              FROM miniapp_message_claim AS newer
              WHERE newer.subject_id = claim.subject_id
                AND newer.legacy_unreconciled = 0
                AND (
                    newer.created_at > claim.created_at
                    OR (
                        newer.created_at = claim.created_at
                        AND newer.client_message_id
                            > claim.client_message_id
                    )
                )
          );
        """,
    ),
    (
        5,
        """
        CREATE TABLE agent_binding (
            agent_id TEXT PRIMARY KEY
                CHECK(length(agent_id) BETWEEN 1 AND 256),
            user_id TEXT NOT NULL UNIQUE
                CHECK(length(user_id) BETWEEN 1 AND 96),
            issuer TEXT NOT NULL
                CHECK(length(issuer) BETWEEN 1 AND 256),
            subject_id TEXT NOT NULL
                CHECK(length(subject_id) BETWEEN 1 AND 256),
            external_agent_id TEXT NOT NULL
                CHECK(length(external_agent_id) BETWEEN 1 AND 256),
            current_credential_id TEXT
                CHECK(
                    current_credential_id IS NULL
                    OR length(current_credential_id) BETWEEN 1 AND 256
                ),
            created_at TEXT NOT NULL,
            UNIQUE(issuer, subject_id),
            UNIQUE(issuer, external_agent_id)
        );
        CREATE INDEX idx_agent_binding_issuer_subject
            ON agent_binding(issuer, subject_id);
        CREATE INDEX idx_agent_binding_issuer_external_agent
            ON agent_binding(issuer, external_agent_id);

        CREATE TABLE agent_runtime_credential (
            credential_id TEXT PRIMARY KEY
                CHECK(length(credential_id) BETWEEN 1 AND 256),
            agent_id TEXT NOT NULL
                CHECK(length(agent_id) BETWEEN 1 AND 256),
            runtime_id TEXT NOT NULL
                CHECK(length(runtime_id) BETWEEN 1 AND 256),
            request_id TEXT NOT NULL
                CHECK(length(request_id) BETWEEN 1 AND 256),
            scope TEXT NOT NULL
                CHECK(scope IN ('read', 'payments')),
            request_fingerprint TEXT NOT NULL
                CHECK(
                    length(request_fingerprint) = 64
                    AND request_fingerprint NOT GLOB '*[^0-9a-f]*'
                ),
            secret_digest TEXT NOT NULL UNIQUE
                CHECK(
                    length(secret_digest) = 64
                    AND secret_digest NOT GLOB '*[^0-9a-f]*'
                ),
            issued_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            revoked_at TEXT,
            replaced_credential_id TEXT
                CHECK(
                    replaced_credential_id IS NULL
                    OR length(replaced_credential_id) BETWEEN 1 AND 256
                ),
            FOREIGN KEY(agent_id)
                REFERENCES agent_binding(agent_id)
                ON DELETE RESTRICT,
            UNIQUE(agent_id, request_id)
        );
        CREATE INDEX idx_agent_runtime_credential_digest
            ON agent_runtime_credential(secret_digest);
        CREATE INDEX idx_agent_runtime_credential_agent
            ON agent_runtime_credential(agent_id, credential_id);
        CREATE INDEX idx_agent_runtime_credential_expiry
            ON agent_runtime_credential(expires_at, revoked_at);
        """,
    ),
    (
        6,
        """
        CREATE TABLE agent_runtime_revocation (
            agent_id TEXT NOT NULL
                CHECK(length(agent_id) BETWEEN 1 AND 256),
            runtime_id TEXT NOT NULL
                CHECK(length(runtime_id) BETWEEN 1 AND 256),
            revoked_at TEXT NOT NULL,
            FOREIGN KEY(agent_id)
                REFERENCES agent_binding(agent_id)
                ON DELETE RESTRICT,
            PRIMARY KEY(agent_id, runtime_id)
        );
        CREATE INDEX idx_agent_runtime_revocation_runtime
            ON agent_runtime_revocation(runtime_id);

        INSERT INTO agent_runtime_revocation(
            agent_id, runtime_id, revoked_at
        )
        SELECT
            binding.agent_id,
            credential.runtime_id,
            credential.revoked_at
        FROM agent_binding AS binding
        JOIN agent_runtime_credential AS credential
          ON credential.agent_id = binding.agent_id
         AND credential.credential_id = binding.current_credential_id
        WHERE credential.revoked_at IS NOT NULL;
        """,
    ),
)
