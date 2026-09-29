"""Production composition root and startup gates for Hosted Facilitator."""

from __future__ import annotations

import argparse
from contextlib import asynccontextmanager
import os
from collections.abc import Mapping
import re
import sys
import time
from typing import Any, Callable

from config import HostedProductionConfig, HostedWatcherConfig


class ProductionStartupError(RuntimeError):
    """A required production dependency or chain invariant is unavailable."""


_SCHEMA_TABLES = frozenset(
    {
        "hosted_tenants",
        "hosted_enrollment_tokens",
        "hosted_node_registrations",
        "hosted_node_rotations",
        "hosted_retired_credentials",
        "hosted_dpop_replays",
        "hosted_preflight_records",
        "hosted_executions",
        "hosted_relayer_nonce_allocations",
        "hosted_execution_attempts",
        "hosted_execution_observations",
        "hosted_gate_controls",
        "hosted_gate_reservations",
        "hosted_gate_events",
    }
)
_SCHEMA_COLUMNS = {
    "hosted_preflight_records": {
        "request_id",
        "idempotency_key",
        "request_nonce",
        "capability_hash",
        "reservation_id",
        "request_hash",
        "signed_response_jws",
    },
    "hosted_enrollment_tokens": {
        "token_digest",
        "tenant_id",
        "expires_at",
        "consumed_at",
        "enrolled_node_id",
        "enrollment_binding_digest",
    },
    "hosted_node_registrations": {
        "tenant_id",
        "node_id",
        "wallet_binding_id",
        "device_public_jwk",
        "device_key_id",
        "access_token_digest",
        "credential_epoch",
        "status",
        "created_at",
        "updated_at",
        "revocation_id",
    },
    "hosted_node_rotations": {
        "rotation_id",
        "tenant_id",
        "node_id",
        "wallet_binding_id",
        "expected_epoch",
        "next_epoch",
        "pending_public_jwk",
        "pending_device_key_id",
        "pending_access_token_digest",
        "status",
        "prepared_at",
        "committed_at",
    },
    "hosted_executions": {
        "execution_id",
        "capability_id",
        "reservation_id",
        "idempotency_key",
        "chain",
        "amount_atomic",
        "owner_nonce",
        "relayer_address",
        "relayer_nonce",
        "signing_claim_generation",
        "signing_claim_expires_at",
        "status",
        "watcher_version",
        "watcher_attempted_at",
        "finality_boundary",
    },
    "hosted_relayer_nonce_allocations": {
        "chain",
        "relayer_address",
        "next_nonce",
        "updated_at",
    },
    "hosted_execution_attempts": {
        "attempt_id",
        "execution_id",
        "attempt_number",
        "raw_transaction_hash",
        "created_at",
    },
    "hosted_execution_observations": {
        "observation_id",
        "execution_id",
        "tx_hash",
        "block_number",
        "confirmations",
        "watcher_version",
        "canonical",
        "evidence",
        "observed_at",
    },
    "hosted_gate_controls": {
        "scope_type",
        "tenant_id",
        "node_id",
        "paused",
        "reason_code",
        "updated_at",
    },
    "hosted_gate_reservations": {
        "execution_id",
        "tenant_id",
        "node_id",
        "idempotency_key",
        "utc_day",
        "state",
        "gas_cost_usd_micros",
        "gas_utc_day",
        "created_at",
        "updated_at",
    },
    "hosted_gate_events": {
        "event_id",
        "execution_id",
        "tenant_id",
        "node_id",
        "idempotency_key",
        "event_type",
        "reason_code",
        "gas_cost_usd_micros",
        "created_at",
    },
}
_SCHEMA_UNIQUE_CONSTRAINTS = {
    "uq_hosted_enrollment_node_binding",
    "uq_hosted_node_access_digest",
    "uq_hosted_node_revocation_id",
    "uq_hosted_rotation_node_expected_epoch",
    "uq_hosted_rotation_pending_access_digest",
    "uq_hosted_dpop_scope_jti",
    "uq_hosted_preflight_request_id",
    "uq_hosted_preflight_idempotency",
    "uq_hosted_preflight_request_nonce",
    "uq_hosted_preflight_capability",
    "uq_hosted_preflight_reservation",
    "uq_hosted_execution_capability",
    "uq_hosted_execution_reservation",
    "uq_hosted_execution_purchase",
    "uq_hosted_execution_idempotency",
    "uq_hosted_execution_attempt_number",
    "uq_hosted_execution_observation_block",
}
_SCHEMA_INDEXES = {
    "uq_hosted_execution_active_chain_relayer_nonce",
    "ix_hosted_node_rotations_scope_status",
    "ix_hosted_gate_reservations_tenant_node_day_state",
    "ix_hosted_gate_reservations_platform_day_state",
    "ix_hosted_gate_events_execution_created",
    "ix_hosted_gate_events_tenant_node_created",
}
_SCHEMA_CHECK_CONSTRAINTS = {
    "ck_hosted_execution_supported_chain",
    "ck_hosted_execution_amount_present",
    "ck_hosted_execution_signer_epoch_positive",
    "ck_hosted_execution_owner_nonce_present",
    "ck_hosted_execution_relayer_nonce_nonnegative",
    "ck_hosted_execution_signing_claim_generation_nonnegative",
    "ck_hosted_execution_signing_claim_expiry",
    "ck_hosted_execution_status",
    "ck_hosted_execution_terminal_finality_evidence",
    "ck_hosted_enrollment_binding",
    "ck_hosted_rotation_expected_epoch_positive",
    "ck_hosted_rotation_epoch_step",
    "ck_hosted_rotation_status",
    "ck_hosted_rotation_commit_timestamp",
    "ck_hosted_gate_control_scope_type",
    "ck_hosted_gate_control_scope_shape",
    "ck_hosted_gate_reservation_state",
    "ck_hosted_gate_reservation_gas_nonnegative",
    "ck_hosted_gate_reservation_gas_day",
    "ck_hosted_gate_reservation_utc_day_nonnegative",
    "ck_hosted_gate_event_type",
    "ck_hosted_gate_event_gas_nonnegative",
}
_GETTER_SIGNATURES = {
    "chain_id": "EXECUTION_CHAIN_ID()",
    "asset_contract": "USDC()",
    "execution_signer": "executionSigner()",
    "signer_epoch": "signerEpoch()",
    "owner": "owner()",
    "pending_owner": "pendingOwner()",
    "paused": "paused()",
}


def _keccak(value: bytes | None = None, *, text: str | None = None) -> bytes:
    try:
        from eth_utils import keccak

        if text is not None:
            return keccak(text=text)
        return keccak(value or b"")
    except Exception:
        raise ProductionStartupError("Ethereum hashing dependency is unavailable") from None


def _getter_selector(field_name: str) -> str:
    signature = _GETTER_SIGNATURES.get(field_name)
    if signature is None:
        raise ProductionStartupError("startup contract getter is invalid")
    return "0x" + _keccak(text=signature)[:4].hex()


def _rpc_call(rpc: Any, method: str, params: list[Any]) -> Any:
    try:
        call = getattr(rpc, "call", None)
        if callable(call):
            return call(method, params)
        if callable(rpc):
            return rpc(method, params)
    except Exception:
        raise ProductionStartupError("startup RPC gate failed") from None
    raise ProductionStartupError("startup RPC client is invalid")


def _quantity(value: object, *, field_name: str) -> int:
    if not isinstance(value, str) or not value.startswith("0x") or not value[2:]:
        raise ProductionStartupError(f"startup {field_name} is invalid")
    try:
        return int(value, 16)
    except ValueError:
        raise ProductionStartupError(f"startup {field_name} is invalid") from None


def _word(value: object, *, field_name: str) -> bytes:
    if not isinstance(value, str) or not value.startswith("0x"):
        raise ProductionStartupError(f"startup {field_name} is invalid")
    try:
        raw = bytes.fromhex(value[2:])
    except ValueError:
        raise ProductionStartupError(f"startup {field_name} is invalid") from None
    if len(raw) != 32:
        raise ProductionStartupError(f"startup {field_name} is invalid")
    return raw


def _address_word(value: object, *, field_name: str) -> str:
    raw = _word(value, field_name=field_name)
    if raw[:12] != bytes(12):
        raise ProductionStartupError(f"startup {field_name} is invalid")
    return "0x" + raw[12:].hex()


def _schema_gate(repository_engine: Any) -> None:
    engine = getattr(repository_engine, "engine", repository_engine)
    try:
        if callable(getattr(engine, "has_table", None)):
            inspector = engine
        else:
            from sqlalchemy import inspect

            inspector = inspect(engine)
        missing = [name for name in sorted(_SCHEMA_TABLES) if not inspector.has_table(name)]
    except Exception:
        raise ProductionStartupError("PostgreSQL schema gate failed") from None
    if missing:
        raise ProductionStartupError("PostgreSQL schema table is incomplete")

    current_heads = getattr(inspector, "current_heads", None)
    if current_heads is None:
        try:
            from alembic.config import Config
            from alembic.migration import MigrationContext
            from alembic.script import ScriptDirectory

            config = Config(os.path.join(os.path.dirname(__file__), "alembic.ini"))
            expected_heads = set(ScriptDirectory.from_config(config).get_heads())
            connect = getattr(engine, "connect", None)
            if not callable(connect):
                raise RuntimeError("schema connection is unavailable")
            with connect() as connection:
                current_heads = set(
                    MigrationContext.configure(connection).get_current_heads()
                )
        except Exception:
            raise ProductionStartupError("PostgreSQL schema revision is unavailable") from None
    else:
        try:
            from alembic.config import Config
            from alembic.script import ScriptDirectory

            config = Config(os.path.join(os.path.dirname(__file__), "alembic.ini"))
            expected_heads = set(ScriptDirectory.from_config(config).get_heads())
        except Exception:
            raise ProductionStartupError("PostgreSQL schema revision is unavailable") from None
    if set(current_heads) != expected_heads:
        raise ProductionStartupError("PostgreSQL schema revision is not current")

    try:
        table_names = set(inspector.get_table_names())
        for table_name, required_columns in _SCHEMA_COLUMNS.items():
            if table_name not in table_names:
                raise ProductionStartupError("PostgreSQL schema table is incomplete")
            columns = {column.get("name") for column in inspector.get_columns(table_name)}
            if not required_columns.issubset(columns):
                raise ProductionStartupError("PostgreSQL schema column contract is incomplete")
        unique_names = {
            item.get("name") for table_name in table_names for item in inspector.get_unique_constraints(table_name)
        }
        if not _SCHEMA_UNIQUE_CONSTRAINTS.issubset(unique_names):
            raise ProductionStartupError("PostgreSQL schema uniqueness contract is incomplete")
        active_relayer_nonce_indexes: list[tuple[str, Mapping[str, object]]] = []
        index_names: set[object] = set()
        for table_name in table_names:
            for item in inspector.get_indexes(table_name):
                if not isinstance(item, Mapping):
                    raise ProductionStartupError("PostgreSQL schema index contract is incomplete")
                name = item.get("name")
                index_names.add(name)
                if name == "uq_hosted_execution_active_chain_relayer_nonce":
                    active_relayer_nonce_indexes.append((table_name, item))
        if not _SCHEMA_INDEXES.issubset(index_names):
            raise ProductionStartupError("PostgreSQL schema index contract is incomplete")
        if len(active_relayer_nonce_indexes) != 1:
            raise ProductionStartupError("PostgreSQL schema index contract is incomplete")
        table_name, active_relayer_nonce_index = active_relayer_nonce_indexes[0]
        if table_name != "hosted_executions":
            raise ProductionStartupError("PostgreSQL schema index contract is incomplete")
        if active_relayer_nonce_index.get("column_names") != [
            "chain",
            "relayer_address",
            "relayer_nonce",
        ] or active_relayer_nonce_index.get("unique") is not True:
            raise ProductionStartupError("PostgreSQL schema index contract is incomplete")
        dialect_options = active_relayer_nonce_index.get("dialect_options")
        predicate = active_relayer_nonce_index.get("postgresql_where")
        if predicate is None and isinstance(dialect_options, Mapping):
            predicate = dialect_options.get("postgresql_where")
        if predicate is None:
            predicate = active_relayer_nonce_index.get("filter_definition")
        predicate_text = re.sub(
            r"\s+",
            " ",
            str(predicate if predicate is not None else "").strip().lower(),
        )
        predicate_text = re.sub(
            r"::(?:text|varchar|character varying)(?:\[\])?",
            "",
            predicate_text,
        )
        while predicate_text.startswith("(") and predicate_text.endswith(")"):
            predicate_text = predicate_text[1:-1].strip()
        predicate_match = re.fullmatch(
            r"status\s+not\s+in\s*\(\s*'([^']+)'\s*,\s*'([^']+)'\s*\)",
            predicate_text,
        )
        if predicate_match is None:
            predicate_match = re.fullmatch(
                r"\(*\s*\(*status\)*\s*<>\s*all\s*\(\s*\(*array\s*\[\s*'([^']+)'\s*,\s*'([^']+)'\s*\]\s*\)*\s*\)*\)*",
                predicate_text,
            )
        if predicate_match is None or {
            predicate_match.group(1),
            predicate_match.group(2),
        } != {"expired", "released"}:
            raise ProductionStartupError("PostgreSQL schema index contract is incomplete")
        check_names = {
            item.get("name") for table_name in table_names for item in inspector.get_check_constraints(table_name)
        }
        if not _SCHEMA_CHECK_CONSTRAINTS.issubset(check_names):
            raise ProductionStartupError("PostgreSQL schema check contract is incomplete")
    except ProductionStartupError:
        raise
    except Exception:
        raise ProductionStartupError("PostgreSQL schema structural contract is unavailable") from None


def _head(rpc: Any, *, label: str) -> int:
    block = _rpc_call(rpc, "eth_getBlockByNumber", ["latest", False])
    if not isinstance(block, Mapping):
        raise ProductionStartupError(f"startup {label} head is unavailable")
    return _quantity(block.get("number"), field_name=f"{label}_head")


def _code_hash(rpc: Any, config: Any, *, label: str) -> None:
    code = _rpc_call(rpc, "eth_getCode", [config.executor_address, config.finality_boundary])
    if not isinstance(code, str) or not code.startswith("0x") or not code[2:]:
        raise ProductionStartupError(f"startup {label} executor code is missing")
    try:
        raw = bytes.fromhex(code[2:])
    except ValueError:
        raise ProductionStartupError(f"startup {label} executor code is invalid") from None
    if not raw or "0x" + _keccak(raw).hex() != config.executor_code_hash:
        raise ProductionStartupError(f"startup {label} executor code does not match")


def _contract_gate(rpc: Any, config: Any, *, label: str) -> None:
    checks = {
        "chain_id": config.chain_id,
        "asset_contract": config.asset_contract,
        "execution_signer": config.execution_signer_address,
        "signer_epoch": config.signer_epoch,
        "owner": config.executor_admin_address,
        "pending_owner": "0x" + "00" * 20,
        "paused": 0,
    }
    for field_name, expected in checks.items():
        result = _rpc_call(
            rpc,
            "eth_call",
            [
                {"to": config.executor_address, "data": _getter_selector(field_name)},
                config.finality_boundary,
            ],
        )
        if field_name in {
            "asset_contract",
            "execution_signer",
            "owner",
            "pending_owner",
        }:
            actual: object = _address_word(result, field_name=f"{label}_{field_name}")
            if actual != expected:
                raise ProductionStartupError(f"startup {label} contract state does not match")
        else:
            actual = int.from_bytes(_word(result, field_name=f"{label}_{field_name}"), "big")
            if actual != expected:
                raise ProductionStartupError(f"startup {label} contract state does not match")


def _chain_gate(
    config: HostedProductionConfig,
    *,
    submission_rpc: Any,
    watcher_rpc: Any,
    require_distinct: bool = True,
) -> None:
    if require_distinct and submission_rpc is watcher_rpc:
        raise ProductionStartupError("submission and watcher RPC clients must be distinct")
    for label, rpc in (("submission", submission_rpc), ("watcher", watcher_rpc)):
        chain_id = _quantity(_rpc_call(rpc, "eth_chainId", []), field_name=f"{label}_chain_id")
        if chain_id != config.chain_id:
            raise ProductionStartupError(f"startup {label} chain is not configured")
        _code_hash(rpc, config, label=label)
        _contract_gate(rpc, config, label=label)
    heads = [
        _head(submission_rpc, label="submission"),
        _head(watcher_rpc, label="watcher"),
    ]
    if abs(heads[0] - heads[1]) > config.max_rpc_head_skew:
        raise ProductionStartupError("submission and watcher RPC heads are too far apart")


def startup_gate(
    config: HostedProductionConfig,
    *,
    repository_engine: Any,
    submission_rpc: Any,
    watcher_rpc: Any,
) -> None:
    """Verify schema, independent RPCs, code identity and Executor state."""

    if not isinstance(config, HostedProductionConfig):
        raise ProductionStartupError("Hosted production config is required")
    _schema_gate(repository_engine)
    _chain_gate(
        config,
        submission_rpc=submission_rpc,
        watcher_rpc=watcher_rpc,
        require_distinct=True,
    )


def watcher_startup_gate(
    config: HostedWatcherConfig,
    *,
    repository_engine: Any,
    watcher_rpc: Any,
) -> None:
    """Run only the gates needed by the watcher process."""

    if not isinstance(config, HostedWatcherConfig):
        raise ProductionStartupError("Hosted watcher config is required")
    _schema_gate(repository_engine)
    chain_id = _quantity(_rpc_call(watcher_rpc, "eth_chainId", []), field_name="watcher_chain_id")
    if chain_id != config.chain_id:
        raise ProductionStartupError("startup watcher chain is not configured")
    _head(watcher_rpc, label="watcher")
    _code_hash(watcher_rpc, config, label="watcher")
    _contract_gate(watcher_rpc, config, label="watcher")


def _kms_client(client: Any | None) -> Any:
    if client is not None:
        return client
    try:
        import boto3

        return boto3.client("kms")
    except Exception:
        raise ProductionStartupError("KMS client is unavailable") from None


def _clock() -> int:
    return int(time.time())


def _close_resources(resources: list[Any]) -> None:
    for resource in reversed(resources):
        close = getattr(resource, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass
            continue
        engine = getattr(resource, "engine", None)
        dispose = getattr(engine, "dispose", None)
        if callable(dispose):
            try:
                dispose()
            except Exception:
                pass


def _attach_lifespan(app: Any, resources: list[Any]) -> Any:
    @asynccontextmanager
    async def lifespan(_app: Any):
        try:
            yield
        finally:
            _close_resources(resources)

    app.router.lifespan_context = lifespan
    app.state.production_resources = tuple(resources)
    return app


def build_production_app(
    config: HostedProductionConfig | None = None,
    *,
    clock: Callable[[], int] = _clock,
    kms_client: Any | None = None,
    core_client: Any | None = None,
    submission_client: Any | None = None,
    watcher_client: Any | None = None,
    redis_client: Any | None = None,
    run_startup_gate: bool = True,
) -> Any:
    """Construct the API only after all production gates pass."""

    config = config or HostedProductionConfig.from_env()
    if not isinstance(config, HostedProductionConfig):
        raise ProductionStartupError("Hosted production config is required")
    if config.environment == "production":
        if run_startup_gate is not True:
            raise ProductionStartupError("production startup gate cannot be disabled")
        if any(
            client is not None
            for client in (kms_client, core_client, submission_client, watcher_client, redis_client)
        ):
            raise ProductionStartupError("production dependency injection is not allowed")
    resources: list[Any] = []
    try:
        from app import create_app
        from authority import CoreAuthorityResolver
        from execution_repository import ExecutionRepository
        from kms_response_signer import KMSResponseSigner
        from relayer import HostedRelayer
        from replay import RedisReplayCoordinator
        from repository import PostgresRepository
        from rpc import JsonRpcTransport, require_distinct_rpc_origins

        control_repository = PostgresRepository(config.postgres_url)
        resources.append(control_repository)
        execution_repository = ExecutionRepository(
            config.postgres_url,
            create_schema=False,
            pilot_policy=config.pilot_gate_policy,
        )
        resources.append(execution_repository)
        replay = RedisReplayCoordinator(config.redis_url, client=redis_client)
        resources.append(replay)
        submission_rpc = JsonRpcTransport(
            config.submission_rpc_url,
            environment=config.environment,
            client=submission_client,
            timeout_seconds=config.rpc_timeout_seconds,
        )
        watcher_rpc = JsonRpcTransport(
            config.watcher_rpc_url,
            environment=config.environment,
            client=watcher_client,
            timeout_seconds=config.rpc_timeout_seconds,
        )
        require_distinct_rpc_origins(
            config.submission_rpc_url,
            config.watcher_rpc_url,
            environment=config.environment,
        )
        resources.extend((submission_rpc, watcher_rpc))
        kms = _kms_client(kms_client)
        from kms_signer import KMSExecutionSigner

        execution_signer = KMSExecutionSigner(
            kms,
            key_id=config.execution_kms_key_id,
            expected_signer_address=config.execution_signer_address,
            gas_relayer_key_id=config.gas_kms_key_id,
            gas_relayer_address=config.relayer_address,
        )
        gas_signer = KMSExecutionSigner(
            kms,
            key_id=config.gas_kms_key_id,
            expected_signer_address=config.relayer_address,
        )
        execution_signer.validate()
        gas_signer.validate()
        response_signer = KMSResponseSigner(kms, key_id=config.response_key_ref)
        core_authority = CoreAuthorityResolver(
            origin=config.core_authority_origin,
            internal_token=config.core_internal_token,
            relayer_address=config.relayer_address,
            signer_epoch=config.signer_epoch,
            environment=config.environment,
            client=core_client,
            chain=config.chain,
            token=config.asset_contract,
            chain_id=config.chain_id,
        )
        resources.extend((core_authority, response_signer))
        relayer = HostedRelayer(
            repository=execution_repository,
            rpc=submission_rpc,
            inspection_rpc=watcher_rpc,
            execution_signer=execution_signer,
            gas_signer=gas_signer,
            approval_verifier=core_authority,
            executor_address=config.executor_address,
            relayer_address=config.relayer_address,
            max_gas_limit=config.max_gas_limit,
            max_fee_per_gas_wei=config.max_fee_per_gas_wei,
            max_priority_fee_per_gas_wei=config.max_priority_fee_per_gas_wei,
            max_total_fee_wei=config.max_total_fee_wei,
            clock=clock,
            chain=config.chain,
            token=config.asset_contract,
            chain_id=config.chain_id,
        )
        if run_startup_gate:
            startup_gate(
                config,
                repository_engine=control_repository.engine,
                submission_rpc=submission_rpc,
                watcher_rpc=watcher_rpc,
            )
        app = create_app(
            config,
            repository=control_repository,
            replay=replay,
            response_signer=response_signer,
            clock=clock,
            execution_repository=execution_repository,
            execution_service=relayer,
            intent_resolver=core_authority,
        )
        return _attach_lifespan(app, resources)
    except Exception:
        _close_resources(resources)
        raise


def build_production_watcher(
    config: HostedWatcherConfig | None = None,
    *,
    watcher_client: Any | None = None,
    run_startup_gate: bool = True,
) -> WatcherWorker:
    """Construct only the durable execution repository and watcher path."""

    config = config or HostedWatcherConfig.from_env()
    if not isinstance(config, HostedWatcherConfig):
        raise ProductionStartupError("Hosted watcher config is required")
    if config.environment == "production":
        if run_startup_gate is not True:
            raise ProductionStartupError("production startup gate cannot be disabled")
        if watcher_client is not None:
            raise ProductionStartupError("production dependency injection is not allowed")
    from execution_repository import ExecutionRepository
    from rpc import JsonRpcTransport, PacedRpcTransport
    from watcher import HostedChainWatcher
    from watcher_worker import WatcherWorker

    execution_repository = ExecutionRepository(
        config.postgres_url,
        create_schema=False,
        pilot_policy=config.pilot_gate_policy,
    )
    watcher_rpc_base = JsonRpcTransport(
        config.watcher_rpc_url,
        environment=config.environment,
        client=watcher_client,
        timeout_seconds=config.rpc_timeout_seconds,
    )
    watcher_rpc = PacedRpcTransport(
        watcher_rpc_base,
        min_interval_seconds=config.watcher_rpc_min_interval_ms / 1000,
    )
    try:
        if run_startup_gate:
            watcher_startup_gate(
                config,
                repository_engine=execution_repository.engine,
                watcher_rpc=watcher_rpc,
            )
        chain_watcher = HostedChainWatcher(
            execution_repository,
            watcher_rpc,
            executor_address=config.executor_address,
            executor_code_hash=config.executor_code_hash,
            confirmation_depth=config.confirmation_depth,
            chain=config.chain,
            token=config.asset_contract,
            finality_boundary=config.finality_boundary,
            chain_id=config.chain_id,
        )
        worker = WatcherWorker(
            execution_repository,
            chain_watcher,
            batch_size=config.watch_batch_size,
            poll_seconds=config.watch_poll_seconds,
            chain=config.chain,
            resources=(execution_repository, watcher_rpc),
        )
        return worker
    except Exception:
        watcher_rpc.close()
        execution_repository.engine.dispose()
        raise


def build_production_reconciler(
    config: HostedProductionConfig | None = None,
    *,
    submission_client: Any | None = None,
    watcher_client: Any | None = None,
    run_startup_gate: bool = True,
) -> tuple[Any, list[Any]]:
    """Construct the narrow operator-only persisted transaction recovery path."""

    config = config or HostedProductionConfig.from_env()
    if not isinstance(config, HostedProductionConfig):
        raise ProductionStartupError("Hosted production config is required")
    if config.environment == "production":
        if run_startup_gate is not True:
            raise ProductionStartupError("production startup gate cannot be disabled")
        if submission_client is not None or watcher_client is not None:
            raise ProductionStartupError("production dependency injection is not allowed")
    resources: list[Any] = []
    try:
        from execution_repository import ExecutionRepository
        from relayer import HostedSubmissionReconciler
        from rpc import JsonRpcTransport, require_distinct_rpc_origins

        execution_repository = ExecutionRepository(
            config.postgres_url,
            create_schema=False,
            pilot_policy=config.pilot_gate_policy,
        )
        resources.append(execution_repository)
        submission_rpc = JsonRpcTransport(
            config.submission_rpc_url,
            environment=config.environment,
            client=submission_client,
            timeout_seconds=config.rpc_timeout_seconds,
        )
        watcher_rpc = JsonRpcTransport(
            config.watcher_rpc_url,
            environment=config.environment,
            client=watcher_client,
            timeout_seconds=config.rpc_timeout_seconds,
        )
        require_distinct_rpc_origins(
            config.submission_rpc_url,
            config.watcher_rpc_url,
            environment=config.environment,
        )
        resources.extend((submission_rpc, watcher_rpc))
        reconciler = HostedSubmissionReconciler(
            repository=execution_repository,
            rpc=submission_rpc,
            inspection_rpc=watcher_rpc,
            executor_address=config.executor_address,
            relayer_address=config.relayer_address,
            clock=_clock,
            chain=config.chain,
            token=config.asset_contract,
            chain_id=config.chain_id,
        )
        if run_startup_gate:
            startup_gate(
                config,
                repository_engine=execution_repository.engine,
                submission_rpc=submission_rpc,
                watcher_rpc=watcher_rpc,
            )
        return reconciler, resources
    except Exception:
        _close_resources(resources)
        raise


def _migrate() -> None:
    database_url = os.environ.get("ALEMBIC_DATABASE_URL") or os.environ.get(
        "CLINK_HOSTED_POSTGRES_URL", ""
    )
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://", "postgresql+psycopg2://")):
        raise ProductionStartupError("Alembic PostgreSQL URL is required")
    try:
        from alembic import command
        from alembic.config import Config

        alembic_config = Config(os.path.join(os.path.dirname(__file__), "alembic.ini"))
        alembic_config.set_main_option("sqlalchemy.url", database_url)
        command.upgrade(alembic_config, "head")
    except ProductionStartupError:
        raise
    except Exception:
        raise ProductionStartupError("Alembic migration failed") from None


def _issue_invite(*, tenant_id: str, ttl_seconds: int) -> int:
    """Issue one enrollment invite through the durable PostgreSQL repository."""

    from enrollment import EnrollmentService
    from models import validate_identifier
    from repository import PostgresRepository

    try:
        validate_identifier(tenant_id, field_name="tenant_id")
    except (TypeError, ValueError):
        print("tenant-id is invalid", file=sys.stderr)
        return 2
    if type(ttl_seconds) is not int or not 30 <= ttl_seconds <= 900:
        print("ttl-seconds must be between 30 and 900", file=sys.stderr)
        return 2

    database_url = os.environ.get("CLINK_HOSTED_POSTGRES_URL") or os.environ.get(
        "ALEMBIC_DATABASE_URL", ""
    )
    if not database_url.startswith(
        ("postgresql://", "postgresql+psycopg://", "postgresql+psycopg2://")
    ):
        print("PostgreSQL URL is required", file=sys.stderr)
        return 2

    resources: list[Any] = []
    try:
        repository = PostgresRepository(database_url)
        resources.append(repository)
        service = EnrollmentService(
            repository=repository,
            enrollment_ttl_seconds=ttl_seconds,
            clock=_clock,
        )
        token = service.issue_enrollment_token(tenant_id)
        print(token)
        return 0
    except Exception:
        # Do not expose database URLs, driver details, or the generated token.
        print("invite could not be issued", file=sys.stderr)
        return 1
    finally:
        _close_resources(resources)


def _set_pilot_pause(
    *,
    scope_type: str,
    paused: bool,
    reason_code: str,
    tenant_id: str,
    node_id: str,
) -> int:
    """Persist one operator pause/resume decision without exposing secrets."""

    from execution_repository import ExecutionRepository
    from models import validate_identifier

    if scope_type == "platform":
        if tenant_id or node_id:
            print("tenant-id and node-id are not allowed for platform scope", file=sys.stderr)
            return 2
    elif scope_type == "tenant":
        if not tenant_id:
            print("tenant-id is required for tenant scope", file=sys.stderr)
            return 2
        if node_id:
            print("node-id is not allowed for tenant scope", file=sys.stderr)
            return 2
    elif scope_type == "node":
        if not tenant_id or not node_id:
            print("tenant-id and node-id are required for node scope", file=sys.stderr)
            return 2
    else:  # pragma: no cover - argparse limits this value
        print("scope is invalid", file=sys.stderr)
        return 2

    for value, field_name in ((tenant_id, "tenant-id"), (node_id, "node-id")):
        if value:
            try:
                validate_identifier(value, field_name=field_name)
            except (TypeError, ValueError):
                print(f"{field_name} is invalid", file=sys.stderr)
                return 2
    if (
        not isinstance(reason_code, str)
        or re.fullmatch(r"[a-z][a-z0-9_]{0,127}", reason_code) is None
    ):
        print("reason-code is invalid", file=sys.stderr)
        return 2

    database_url = os.environ.get("CLINK_HOSTED_POSTGRES_URL") or os.environ.get(
        "ALEMBIC_DATABASE_URL", ""
    )
    if not database_url.startswith(
        ("postgresql://", "postgresql+psycopg://", "postgresql+psycopg2://")
    ):
        print("PostgreSQL URL is required", file=sys.stderr)
        return 2

    resources: list[Any] = []
    try:
        repository = ExecutionRepository(database_url, create_schema=False)
        resources.append(repository)
        repository.set_pilot_pause(
            scope_type=scope_type,
            paused=paused,
            reason_code=reason_code,
            tenant_id=tenant_id,
            node_id=node_id,
        )
        print("pilot gate paused" if paused else "pilot gate resumed")
        return 0
    except Exception:
        print("pilot gate update failed", file=sys.stderr)
        return 1
    finally:
        _close_resources(resources)


def _reconcile_execution(*, execution_id: str, rebroadcast: bool) -> int:
    """Inspect or explicitly rebroadcast one immutable persisted transaction."""

    from execution_models import ExecutionState
    from models import validate_identifier

    try:
        validate_identifier(execution_id, field_name="execution_id")
    except (TypeError, ValueError):
        print("execution-id is invalid", file=sys.stderr)
        return 2

    resources: list[Any] = []
    try:
        reconciler, resources = build_production_reconciler()
        if rebroadcast:
            execution = reconciler.rebroadcast_identical(execution_id)
            output = f"execution reconciliation status: {ExecutionState(execution.status).value}"
        else:
            execution, exact_transaction_found = (
                reconciler.inspect_submission_with_evidence(execution_id)
            )
            output = (
                "execution reconciliation status: "
                f"{ExecutionState(execution.status).value}; "
                "exact_transaction_found="
                f"{'true' if exact_transaction_found else 'false'}"
            )
        print(output)
        return 0
    except Exception:
        print("execution reconciliation failed", file=sys.stderr)
        return 1
    finally:
        _close_resources(resources)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m production")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("api")
    subparsers.add_parser("watcher")
    subparsers.add_parser("migrate")
    issue_invite_parser = subparsers.add_parser("issue-invite")
    issue_invite_parser.add_argument("--tenant-id", required=True)
    issue_invite_parser.add_argument("--ttl-seconds", required=True, type=int)
    pilot_gate_parser = subparsers.add_parser("pilot-gate")
    pilot_gate_parser.add_argument(
        "--scope", required=True, choices=("platform", "tenant", "node")
    )
    pilot_gate_parser.add_argument("--tenant-id", default="")
    pilot_gate_parser.add_argument("--node-id", default="")
    pilot_gate_parser.add_argument("--reason-code", required=True)
    pilot_gate_action = pilot_gate_parser.add_mutually_exclusive_group(required=True)
    pilot_gate_action.add_argument("--pause", action="store_true")
    pilot_gate_action.add_argument("--resume", action="store_true")
    reconcile_parser = subparsers.add_parser("reconcile-execution")
    reconcile_parser.add_argument("--execution-id", required=True)
    reconcile_action = reconcile_parser.add_mutually_exclusive_group(required=True)
    reconcile_action.add_argument("--inspect", action="store_true")
    reconcile_action.add_argument("--rebroadcast", action="store_true")
    args, extra_args = parser.parse_known_args(argv)
    if extra_args:
        parser.error("unrecognized arguments")
    if args.command == "migrate":
        _migrate()
        return 0
    if args.command == "issue-invite":
        return _issue_invite(
            tenant_id=args.tenant_id,
            ttl_seconds=args.ttl_seconds,
        )
    if args.command == "pilot-gate":
        return _set_pilot_pause(
            scope_type=args.scope,
            paused=args.pause,
            reason_code=args.reason_code,
            tenant_id=args.tenant_id,
            node_id=args.node_id,
        )
    if args.command == "reconcile-execution":
        return _reconcile_execution(
            execution_id=args.execution_id,
            rebroadcast=args.rebroadcast,
        )
    if args.command == "api":
        config = HostedProductionConfig.from_env()
        try:
            import uvicorn

            app = build_production_app(config)
            uvicorn.run(app, host=config.bind_host, port=config.bind_port)
        except ProductionStartupError:
            raise
        return 0
    config = HostedWatcherConfig.from_env()
    worker = build_production_watcher(config)
    try:
        worker.run_forever()
    finally:
        worker.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
