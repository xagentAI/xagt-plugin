from __future__ import annotations

import os
from pathlib import Path
import sys

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

from shared.config import AppConfig


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_TABLES = {
    "account_wallet_bootstrap_states",
    "account_sessions",
    "action_approvals",
    "action_intents",
    "allowance_recovery_attempts",
    "audit_events",
    "asset_allowances",
    "funding_ledger_records",
    "funding_payment_capabilities",
    "funding_locks",
    "funding_relayer_nonces",
    "funding_transaction_bindings",
    "opc_access_credentials",
    "opc_installations",
    "opc_pairings",
    "public_account_sessions",
    "policy_decisions",
    "spending_grant_daily_usage",
    "spending_grant_rolling_usage",
    "spending_grants",
    "wallet_identities",
}
REQUIRED_COLUMNS = {
    "account_wallet_bootstrap_states": {
        "binding_state",
        "binding_generation",
        "unbound_at",
    },
    "account_sessions": {"created_by_public_account_session_id"},
    "action_intents": {
        "action_id",
        "user_id",
        "agent_id",
        "action_type",
        "state",
        "policy_decision_id",
        "payload",
        "version",
        "created_at",
        "updated_at",
    },
    "allowance_recovery_attempts": {
        "attempt_id",
        "user_id",
        "wallet_identity_id",
        "network",
        "token_address",
        "spender_address",
        "amount_atomic",
        "allowance_tx_hash",
        "status",
        "reason_code",
        "created_at",
        "updated_at",
        "next_check_at",
        "request_key_digest",
        "check_count",
        "actual_approved_amount_atomic",
        "observed_allowance_atomic",
        "confirmed_block",
        "confirmed_block_hash",
        "verified_at",
    },
    "action_approvals": {
        "approval_id",
        "action_id",
        "user_id",
        "agent_id",
        "state",
        "proof_hash",
        "payload",
        "version",
        "created_at",
        "updated_at",
    },
    "policy_decisions": {
        "policy_decision_id",
        "action_id",
        "user_id",
        "agent_id",
        "action_type",
        "decision",
        "target_address",
        "chain",
        "payload",
        "evaluated_at",
    },
    "spending_grants": {
        "hourly_limit_usdc",
        "merchant_trust_scopes",
        "notification_mode",
    },
    "funding_payment_capabilities": {
        "capability_id",
        "capability_version",
        "capability_hash",
        "reservation_id",
        "idempotency_key",
        "tenant_id",
        "node_id",
        "wallet_binding_id",
        "wallet_identity_id",
        "canonical_payload",
        "issued_at",
        "expires_at",
        "created_at",
    },
    "opc_installations": {
        "installation_id",
        "public_jwk",
        "public_jwk_thumbprint",
        "status",
        "scope",
        "user_id",
        "wallet_identity_id",
        "spending_grant_id",
        "consent_expires_at",
        "consent_hash",
        "approved_at",
        "revoked_at",
        "created_at",
        "updated_at",
    },
    "opc_pairings": {
        "pairing_id",
        "installation_id",
        "request_id",
        "request_fingerprint",
        "public_account_session_id",
        "target_user_id",
        "status",
        "expires_at",
        "linked_at",
    },
    "opc_access_credentials": {
        "credential_id",
        "installation_id",
        "request_id",
        "request_fingerprint",
        "token_digest",
        "status",
        "issued_at",
        "expires_at",
        "revoked_at",
    },
}
REQUIRED_CHECK_CONSTRAINTS = {
    "account_wallet_bootstrap_states": {
        "ck_account_wallet_bootstrap_binding_state",
        "ck_account_wallet_bootstrap_unbound_at",
    },
    "account_sessions": {"ck_wallet_challenge_creating_public_session"},
    "action_intents": {
        "ck_action_intent_id_nonempty",
        "ck_action_intent_state_nonempty",
    },
    "allowance_recovery_attempts": {
        "ck_allowance_recovery_status",
        "ck_allowance_recovery_network",
        "ck_allowance_recovery_token_address",
        "ck_allowance_recovery_spender_address",
        "ck_allowance_recovery_amount_atomic_positive",
        "ck_allowance_recovery_tx_hash",
        "ck_allowance_recovery_request_key_digest",
        "ck_allowance_recovery_reason_code",
        "ck_allowance_recovery_check_count_nonnegative",
        "ck_allowance_recovery_actual_amount_positive",
        "ck_allowance_recovery_confirmed_block_nonnegative",
        "ck_allowance_recovery_confirmed_block_hash",
        "ck_allowance_recovery_mismatch_evidence_complete",
    },
    "action_approvals": {
        "ck_action_approval_proof_hash_canonical",
        "ck_action_approval_state_nonempty",
    },
    "policy_decisions": {
        "ck_policy_decision_target_canonical",
        "ck_policy_decision_chain_canonical",
    },
    "funding_payment_capabilities": {
        "ck_payment_capability_version",
        "ck_payment_capability_hash_canonical",
        "ck_payment_capability_lifetime",
    },
    "opc_installations": {
        "ck_opc_installation_status",
        "ck_opc_installation_scope",
    },
    "opc_pairings": {"ck_opc_pairing_status"},
    "opc_access_credentials": {"ck_opc_credential_status"},
}
REQUIRED_PRIMARY_KEYS = {
    "allowance_recovery_attempts": {"attempt_id"},
    "funding_payment_capabilities": {"capability_id"},
    "opc_installations": {"installation_id"},
    "opc_pairings": {"pairing_id"},
    "opc_access_credentials": {"credential_id"},
}
REQUIRED_UNIQUE_CONSTRAINTS = {
    "funding_payment_capabilities": {
        "uq_payment_capability_hash",
        "uq_payment_capability_reservation",
        "uq_payment_capability_idempotency",
    },
    "opc_installations": {"uq_opc_installation_thumbprint"},
    "opc_pairings": {"uq_opc_pairing_installation_request"},
    "opc_access_credentials": {
        "uq_opc_credential_token_digest",
        "uq_opc_credential_installation_request",
    },
}
REQUIRED_INDEXES = {
    "allowance_recovery_attempts": {
        "uq_allowance_recovery_open_scope",
        "uq_allowance_recovery_wallet_network_hash",
        "uq_allowance_recovery_request_key_digest",
        "ix_allowance_recovery_wallet_created",
        "ix_allowance_recovery_due",
        "ix_allowance_recovery_attempts_user_id",
        "ix_allowance_recovery_attempts_wallet_identity_id",
        "ix_allowance_recovery_attempts_status",
        "ix_allowance_recovery_attempts_created_at",
        "ix_allowance_recovery_attempts_updated_at",
        "ix_allowance_recovery_attempts_next_check_at",
    },
    "wallet_identities": {
        "uq_wallet_identity_open_scope",
        "uq_wallet_identity_open_user",
    },
    "action_intents": {"ix_action_intents_user_agent_created"},
    "action_approvals": {"ix_action_approvals_action_created"},
    "policy_decisions": {"ix_policy_decisions_action_evaluated"},
    "spending_grant_rolling_usage": {
        "ix_spending_grant_rolling_usage_spending_grant_id",
        "ix_spending_grant_rolling_usage_state",
        "ix_spending_grant_rolling_usage_occurred_at",
        "ix_grant_rolling_usage_window",
    },
    "opc_installations": {
        "ix_opc_installations_status",
        "ix_opc_installations_user_id",
        "ix_opc_installations_wallet_identity_id",
        "ix_opc_installations_spending_grant_id",
        "ix_opc_installations_consent_expires_at",
    },
    "opc_pairings": {
        "ix_opc_pairings_status",
        "ix_opc_pairings_installation_id",
        "ix_opc_pairings_public_account_session_id",
        "ix_opc_pairings_target_user_id",
        "ix_opc_pairings_expires_at",
    },
    "opc_access_credentials": {
        "ix_opc_access_credentials_installation_id",
        "ix_opc_access_credentials_status",
        "ix_opc_access_credentials_expires_at",
    },
}
REQUIRED_FOREIGN_KEYS = {
    "allowance_recovery_attempts": {
        ("wallet_identity_id", "wallet_identities"),
    },
    "action_approvals": {("action_id", "action_intents")},
    "spending_grant_rolling_usage": {
        ("spending_grant_id", "spending_grants")
    },
    "opc_installations": {
        ("wallet_identity_id", "wallet_identities"),
        ("spending_grant_id", "spending_grants"),
    },
    "opc_pairings": {
        ("installation_id", "opc_installations"),
        ("public_account_session_id", "public_account_sessions"),
    },
    "opc_access_credentials": {
        ("installation_id", "opc_installations"),
    },
}


def check_runtime_schema(database_url: str) -> list[str]:
    config = Config(str(ROOT / "alembic.ini"))
    expected_heads = set(ScriptDirectory.from_config(config).get_heads())
    version_table = (
        "alembic_version_core"
        if os.getenv("CLINK_NODE_MANAGED") == "1"
        else "alembic_version"
    )
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            current_heads = set(
                MigrationContext.configure(
                    connection,
                    opts={"version_table": version_table},
                ).get_current_heads()
            )
            schema = inspect(connection)
            tables = set(schema.get_table_names())
            columns_by_table = {
                table: {
                    column["name"] for column in schema.get_columns(table)
                }
                for table in REQUIRED_COLUMNS.keys() & tables
            }
            constraints_by_table = {
                table: {
                    constraint["name"]
                    for constraint in schema.get_check_constraints(table)
                    if constraint.get("name")
                }
                for table in REQUIRED_CHECK_CONSTRAINTS.keys() & tables
            }
            primary_keys_by_table = {
                table: set(
                    schema.get_pk_constraint(table).get("constrained_columns", [])
                )
                for table in REQUIRED_PRIMARY_KEYS.keys() & tables
            }
            unique_constraints_by_table = {
                table: {
                    constraint["name"]
                    for constraint in schema.get_unique_constraints(table)
                    if constraint.get("name")
                }
                for table in REQUIRED_UNIQUE_CONSTRAINTS.keys() & tables
            }
            indexes_by_table = {
                table: {index["name"] for index in schema.get_indexes(table)}
                for table in REQUIRED_INDEXES.keys() & tables
            }
            foreign_keys_by_table = {
                table: {
                    (column, foreign_key["referred_table"])
                    for foreign_key in schema.get_foreign_keys(table)
                    for column in foreign_key["constrained_columns"]
                }
                for table in REQUIRED_FOREIGN_KEYS.keys() & tables
            }
    finally:
        engine.dispose()

    problems = []
    if current_heads != expected_heads:
        problems.append(
            "migration revision is not at head "
            f"(current={sorted(current_heads)}, expected={sorted(expected_heads)})"
        )
    problems.extend(
        f"missing required table: {table}"
        for table in sorted(REQUIRED_TABLES - tables)
    )
    problems.extend(
        f"missing required column: {table}.{column}"
        for table, required_columns in sorted(REQUIRED_COLUMNS.items())
        for column in sorted(required_columns - columns_by_table.get(table, set()))
    )
    problems.extend(
        f"missing required check constraint: {table}.{constraint}"
        for table, required_constraints in sorted(REQUIRED_CHECK_CONSTRAINTS.items())
        for constraint in sorted(
            required_constraints - constraints_by_table.get(table, set())
        )
    )
    problems.extend(
        f"missing required primary key: {table}.{column}"
        for table, required_columns in sorted(REQUIRED_PRIMARY_KEYS.items())
        for column in sorted(
            required_columns - primary_keys_by_table.get(table, set())
        )
    )
    problems.extend(
        f"missing required unique constraint: {table}.{constraint}"
        for table, required_constraints in sorted(REQUIRED_UNIQUE_CONSTRAINTS.items())
        for constraint in sorted(
            required_constraints - unique_constraints_by_table.get(table, set())
        )
    )
    problems.extend(
        f"missing required index: {table}.{index}"
        for table, required_indexes in sorted(REQUIRED_INDEXES.items())
        for index in sorted(required_indexes - indexes_by_table.get(table, set()))
    )
    problems.extend(
        f"missing required foreign key: {table}.{column}->{target}"
        for table, required_foreign_keys in sorted(REQUIRED_FOREIGN_KEYS.items())
        for column, target in sorted(
            required_foreign_keys - foreign_keys_by_table.get(table, set())
        )
    )
    return problems


def main() -> int:
    try:
        problems = check_runtime_schema(AppConfig.from_env().funding_database_url)
    except Exception as exc:
        print(f"Core schema check failed: {exc}", file=sys.stderr)
        return 1
    if problems:
        for problem in problems:
            print(f"Core schema is not ready: {problem}", file=sys.stderr)
        return 1
    print("Core schema is at the required migration revision.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
