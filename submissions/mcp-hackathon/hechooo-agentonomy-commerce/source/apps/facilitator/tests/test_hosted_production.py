from __future__ import annotations

from pathlib import Path

import pytest

from config import HostedProductionConfig, HostedWatcherConfig
from production import (
    ProductionStartupError,
    _SCHEMA_CHECK_CONSTRAINTS,
    _SCHEMA_COLUMNS,
    _SCHEMA_INDEXES,
    _SCHEMA_TABLES,
    _SCHEMA_UNIQUE_CONSTRAINTS,
    _migrate,
    _schema_gate,
    _contract_gate,
    build_production_app,
    build_production_reconciler,
    build_production_watcher,
    _getter_selector,
    main,
    startup_gate,
    watcher_startup_gate,
)
from watcher_worker import WatcherWorker


EXECUTOR = "0x" + "11" * 20
EXECUTION_SIGNER = "0x" + "22" * 20
RELAYER = "0x" + "33" * 20
EXECUTOR_ADMIN = "0x" + "44" * 20
CODE_HASH = "0x" + "44" * 32


def config_values(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "environment": "test",
        "public_origin": "http://127.0.0.1:8080",
        "postgres_url": "postgresql+psycopg://test:test@localhost/test",
        "redis_url": "redis://127.0.0.1:6379/0",
        "response_key_ref": "test://response",
        "core_authority_origin": "http://127.0.0.1:8090",
        "core_internal_token": "test-token",
        "chain_id": 8453,
        "asset_contract": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
        "submission_rpc_url": "http://127.0.0.1:8545",
        "watcher_rpc_url": "http://127.0.0.1:9545",
        "executor_address": EXECUTOR,
        "executor_admin_address": EXECUTOR_ADMIN,
        "executor_code_hash": CODE_HASH,
        "execution_kms_key_id": "kms://execution",
        "execution_signer_address": EXECUTION_SIGNER,
        "gas_kms_key_id": "kms://gas",
        "relayer_address": RELAYER,
        "response_kms_key_id": "test://response",
        "signer_epoch": 1,
        "max_gas_limit": 500_000,
        "max_fee_per_gas_wei": 100,
        "max_priority_fee_per_gas_wei": 10,
        "native_asset_usd_price_ceiling_micros": 4_000_000_000,
        "confirmation_depth": 2,
        "max_rpc_head_skew": 3,
        "bind_host": "127.0.0.1",
        "bind_port": 8081,
        "watch_batch_size": 10,
        "watch_poll_seconds": 1,
    }
    values.update(overrides)
    return values


def watcher_config_values(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "environment": "test",
        "postgres_url": "postgresql+psycopg://watcher:watcher@localhost/hosted",
        "chain_id": 8453,
        "asset_contract": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
        "watcher_rpc_url": "http://127.0.0.1:9545",
        "executor_address": EXECUTOR,
        "executor_admin_address": EXECUTOR_ADMIN,
        "executor_code_hash": CODE_HASH,
        "execution_signer_address": EXECUTION_SIGNER,
        "signer_epoch": 7,
        "native_asset_usd_price_ceiling_micros": 4_000_000_000,
        "max_in_flight_per_node": 10,
        "max_accepted_per_node_utc_day": 50,
        "max_accepted_per_node_lifetime": 250,
        "max_gas_usd_micros_per_node_utc_day": 1_000_000,
        "max_gas_usd_micros_platform_utc_day": 100_000_000,
        "confirmation_depth": 2,
        "rpc_timeout_seconds": 20,
        "watch_batch_size": 10,
        "watch_poll_seconds": 1,
    }
    values.update(overrides)
    return values


def test_hosted_production_config_is_coherent_and_hides_secret_refs() -> None:
    config = HostedProductionConfig(**config_values())

    assert config.chain_id == 8453
    assert config.asset_contract == "0x833589fcd6edb6e08f4c7c32d4f71b54bdA02913".lower()
    rendered = repr(config)
    assert "kms://execution" not in rendered
    assert "test-token" not in rendered
    assert "postgresql+psycopg://" not in rendered


def test_hosted_production_total_fee_limit_is_optional_and_positive() -> None:
    assert HostedProductionConfig(**config_values()).max_total_fee_wei is None
    assert (
        HostedProductionConfig(
            **config_values(max_total_fee_wei=100_000_000_000_000)
        ).max_total_fee_wei
        == 100_000_000_000_000
    )
    with pytest.raises((ValueError, TypeError), match="total fee"):
        HostedProductionConfig(**config_values(max_total_fee_wei=0))


def test_watcher_composition_uses_only_the_narrow_config() -> None:
    config = HostedWatcherConfig(**watcher_config_values())

    worker = build_production_watcher(config, run_startup_gate=False)
    try:
        assert worker.chain == config.chain
        assert worker._repository.pilot_policy == config.pilot_gate_policy
    finally:
        worker.close()


def test_watcher_startup_gate_accepts_narrow_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import production as production_module

    config = HostedWatcherConfig(**watcher_config_values())
    monkeypatch.setattr(production_module, "_schema_gate", lambda _engine: None)
    monkeypatch.setattr(production_module, "_code_hash", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(production_module, "_contract_gate", lambda *_args, **_kwargs: None)

    watcher_startup_gate(
        config,
        repository_engine=object(),
        watcher_rpc=FakeRpc(),
    )


def test_watcher_startup_gate_verifies_public_signer_and_epoch_from_rpc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import production as production_module

    config = HostedWatcherConfig(**watcher_config_values())
    seen_getters: list[str] = []

    def address_word(value: str) -> str:
        return "0x" + "00" * 12 + value[2:]

    getter_values = {
        _getter_selector("chain_id"): f"0x{config.chain_id:064x}",
        _getter_selector("asset_contract"): address_word(config.asset_contract),
        _getter_selector("execution_signer"): address_word(config.execution_signer_address),
        _getter_selector("signer_epoch"): f"0x{config.signer_epoch:064x}",
        _getter_selector("paused"): "0x" + "00" * 32,
        _getter_selector("owner"): address_word(config.executor_admin_address),
        _getter_selector("pending_owner"): "0x" + "00" * 32,
    }

    class WatcherContractRpc:
        def call(self, method: str, params: list[object]) -> object:
            if method == "eth_chainId":
                return hex(config.chain_id)
            if method == "eth_getBlockByNumber":
                return {"number": "0x64", "hash": "0x" + "55" * 32}
            if method == "eth_call":
                data = params[0]["data"]  # type: ignore[index]
                seen_getters.append(data)
                return getter_values[data]
            raise AssertionError(method)

    monkeypatch.setattr(production_module, "_schema_gate", lambda _engine: None)
    monkeypatch.setattr(production_module, "_code_hash", lambda *_args, **_kwargs: None)

    watcher_startup_gate(
        config,
        repository_engine=object(),
        watcher_rpc=WatcherContractRpc(),
    )

    assert _getter_selector("execution_signer") in seen_getters
    assert _getter_selector("signer_epoch") in seen_getters
    assert _getter_selector("owner") in seen_getters
    assert _getter_selector("pending_owner") in seen_getters


def test_watcher_command_does_not_load_production_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import production as production_module

    config = HostedWatcherConfig(**watcher_config_values())

    def fail_if_loaded(cls):
        del cls
        raise AssertionError("API production config must not be loaded by watcher")

    class FakeWorker:
        def run_forever(self) -> None:
            return None

        def close(self) -> None:
            return None

    monkeypatch.setattr(HostedProductionConfig, "from_env", classmethod(fail_if_loaded))
    monkeypatch.setattr(HostedWatcherConfig, "from_env", classmethod(lambda cls: config))
    monkeypatch.setattr(production_module, "build_production_watcher", lambda value: FakeWorker())

    assert main(["watcher"]) == 0


def test_startup_gate_probes_agentonomy_executor_immutable_getters() -> None:
    from eth_utils import keccak

    assert _getter_selector("chain_id") == "0x" + keccak(text="EXECUTION_CHAIN_ID()")[:4].hex()
    assert _getter_selector("asset_contract") == "0x" + keccak(text="USDC()")[:4].hex()
    assert _getter_selector("owner") == "0x" + keccak(text="owner()")[:4].hex()
    assert _getter_selector("pending_owner") == "0x" + keccak(text="pendingOwner()")[:4].hex()


def test_contract_gate_accepts_immutable_getter_values_with_address_words() -> None:
    config = HostedProductionConfig(**config_values())

    def address_word(value: str) -> str:
        return "0x" + "00" * 12 + value[2:]

    getter_values = {
        _getter_selector("chain_id"): f"0x{config.chain_id:064x}",
        _getter_selector("asset_contract"): address_word(config.asset_contract),
        _getter_selector("execution_signer"): address_word(config.execution_signer_address),
        _getter_selector("signer_epoch"): f"0x{config.signer_epoch:064x}",
        _getter_selector("paused"): "0x" + "00" * 32,
        _getter_selector("owner"): address_word(config.executor_admin_address),
        _getter_selector("pending_owner"): "0x" + "00" * 32,
    }

    class ImmutableGetterRpc:
        def call(self, method: str, params: list[object]) -> object:
            assert method == "eth_call"
            data = params[0]["data"]  # type: ignore[index]
            return getter_values[data]

    _contract_gate(ImmutableGetterRpc(), config, label="test")


@pytest.mark.parametrize("field", ["owner", "pending_owner"])
def test_contract_gate_rejects_executor_admin_or_pending_owner_drift(field: str) -> None:
    config = HostedProductionConfig(**config_values())

    def address_word(value: str) -> str:
        return "0x" + "00" * 12 + value[2:]

    getter_values = {
        _getter_selector("chain_id"): f"0x{config.chain_id:064x}",
        _getter_selector("asset_contract"): address_word(config.asset_contract),
        _getter_selector("execution_signer"): address_word(config.execution_signer_address),
        _getter_selector("signer_epoch"): f"0x{config.signer_epoch:064x}",
        _getter_selector("paused"): "0x" + "00" * 32,
        _getter_selector("owner"): address_word(config.executor_admin_address),
        _getter_selector("pending_owner"): "0x" + "00" * 32,
    }
    getter_values[_getter_selector(field)] = address_word("0x" + "55" * 20)

    class DriftedRpc:
        def call(self, method: str, params: list[object]) -> object:
            assert method == "eth_call"
            return getter_values[params[0]["data"]]  # type: ignore[index]

    with pytest.raises(ProductionStartupError, match="contract state"):
        _contract_gate(DriftedRpc(), config, label="test")


def test_public_production_bind_requires_declared_trusted_tls_terminator() -> None:
    with pytest.raises(ValueError, match="TLS terminator"):
        HostedProductionConfig(
            **config_values(
            environment="production",
            public_origin="https://hosted.example.com",
            bind_host="0.0.0.0",
            response_key_ref="alias/hosted-response",
            response_kms_key_id="alias/hosted-response",
            core_authority_origin="https://core.example.com",
        )
        )

    config = HostedProductionConfig(
        **config_values(
            environment="production",
            public_origin="https://hosted.example.com",
            bind_host="0.0.0.0",
            trusted_tls_terminator=True,
            response_key_ref="alias/hosted-response",
            response_kms_key_id="alias/hosted-response",
            core_authority_origin="https://core.example.com",
        )
    )
    assert config.trusted_tls_terminator is True


def test_response_key_reference_is_the_only_runtime_key_truth() -> None:
    with pytest.raises(ValueError, match="response key"):
        HostedProductionConfig(
            **config_values(
                response_key_ref="vault://response-a",
                response_kms_key_id="alias/response-b",
            )
        )


@pytest.mark.parametrize(
    "field",
    [
        "submission_rpc_url",
        "watcher_rpc_url",
        "executor_code_hash",
        "executor_admin_address",
        "execution_kms_key_id",
        "execution_signer_address",
        "gas_kms_key_id",
        "relayer_address",
        "response_kms_key_id",
    ],
)
def test_hosted_production_config_rejects_partial_runtime(field: str) -> None:
    with pytest.raises(ValueError):
        HostedProductionConfig(**config_values(**{field: ""}))


def test_hosted_production_config_from_env_does_not_use_float_or_defaults_for_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = config_values(
        chain_id=137,
        asset_contract="0x3c499c542cef5e3811e1192ce70d8cc03d5c3359",
    )
    env = {
        "CLINK_FACILITATOR_ENV": "test",
        "CLINK_HOSTED_PUBLIC_ORIGIN": values["public_origin"],
        "CLINK_HOSTED_POSTGRES_URL": values["postgres_url"],
        "CLINK_HOSTED_REDIS_URL": values["redis_url"],
        "CLINK_HOSTED_RESPONSE_KEY_REF": values["response_key_ref"],
        "CLINK_CORE_AUTHORITY_ORIGIN": values["core_authority_origin"],
        "CLINK_CORE_INTERNAL_API_TOKEN": values["core_internal_token"],
        "CLINK_HOSTED_CHAIN_ID": values["chain_id"],
        "CLINK_HOSTED_SUBMISSION_RPC_URL": values["submission_rpc_url"],
        "CLINK_HOSTED_WATCHER_RPC_URL": values["watcher_rpc_url"],
        "CLINK_HOSTED_EXECUTOR_ADDRESS": values["executor_address"],
        "CLINK_HOSTED_EXECUTOR_ADMIN_ADDRESS": values["executor_admin_address"],
        "CLINK_HOSTED_EXECUTOR_CODE_HASH": values["executor_code_hash"],
        "CLINK_HOSTED_EXECUTION_KMS_KEY_ID": values["execution_kms_key_id"],
        "CLINK_HOSTED_EXECUTION_SIGNER_ADDRESS": values["execution_signer_address"],
        "CLINK_HOSTED_GAS_KMS_KEY_ID": values["gas_kms_key_id"],
        "CLINK_HOSTED_RELAYER_ADDRESS": values["relayer_address"],
        "CLINK_HOSTED_RESPONSE_KMS_KEY_ID": values["response_kms_key_id"],
        "CLINK_HOSTED_MAX_GAS_LIMIT": values["max_gas_limit"],
        "CLINK_HOSTED_MAX_FEE_PER_GAS_WEI": values["max_fee_per_gas_wei"],
        "CLINK_HOSTED_MAX_PRIORITY_FEE_PER_GAS_WEI": values[
            "max_priority_fee_per_gas_wei"
        ],
        "CLINK_HOSTED_MAX_TOTAL_FEE_WEI": 100_000_000_000_000,
        "CLINK_HOSTED_NATIVE_ASSET_USD_PRICE_CEILING_MICROS": values[
            "native_asset_usd_price_ceiling_micros"
        ],
    }
    for key, value in env.items():
        monkeypatch.setenv(key, str(value))

    config = HostedProductionConfig.from_env()
    assert config.chain_id == 137
    assert config.asset_contract == values["asset_contract"]
    assert type(config.confirmation_depth) is int
    assert type(config.watch_poll_seconds) is int
    assert config.max_total_fee_wei == 100_000_000_000_000


def test_migrate_requires_explicit_postgresql_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALEMBIC_DATABASE_URL", raising=False)
    monkeypatch.delenv("CLINK_HOSTED_POSTGRES_URL", raising=False)

    with pytest.raises(ProductionStartupError, match="PostgreSQL URL is required"):
        _migrate()


def test_production_runtime_declares_uvicorn_dependency() -> None:
    requirements = Path(__file__).parents[1] / "requirements.txt"
    assert any(
        line.strip().startswith("uvicorn")
        for line in requirements.read_text(encoding="utf-8").splitlines()
    )


def test_production_composition_cannot_disable_startup_gates_or_inject_fakes() -> None:
    config = HostedProductionConfig(
        **config_values(
            environment="production",
            public_origin="https://hosted.example.com",
            trusted_tls_terminator=True,
            response_key_ref="alias/hosted-response",
            response_kms_key_id="alias/hosted-response",
            core_authority_origin="https://core.example.com",
        )
    )

    with pytest.raises(ProductionStartupError, match="startup gate"):
        build_production_app(config, run_startup_gate=False)
    with pytest.raises(ProductionStartupError, match="dependency injection"):
        build_production_app(config, kms_client=object())
    watcher_config = HostedWatcherConfig(
        **watcher_config_values(
            environment="production",
            watcher_rpc_url="https://watcher.example.com",
        )
    )
    with pytest.raises(ProductionStartupError, match="startup gate"):
        build_production_watcher(watcher_config, run_startup_gate=False)
    with pytest.raises(ProductionStartupError, match="startup gate"):
        build_production_reconciler(config, run_startup_gate=False)
    with pytest.raises(ProductionStartupError, match="dependency injection"):
        build_production_reconciler(config, submission_client=object())


def test_reconciler_composition_keeps_inspection_and_submission_rpc_distinct() -> None:
    config = HostedProductionConfig(**config_values())

    class HttpClient:
        def post(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("startup gate is disabled in this composition test")

    reconciler, resources = build_production_reconciler(
        config,
        submission_client=HttpClient(),
        watcher_client=HttpClient(),
        run_startup_gate=False,
    )
    try:
        assert reconciler._rpc is resources[1]
        assert reconciler._inspection_rpc is resources[2]
        assert reconciler._rpc is not reconciler._inspection_rpc
    finally:
        production_resources = list(resources)
        for resource in reversed(production_resources):
            close = getattr(resource, "close", None)
            if callable(close):
                close()


class MissingSchemaRevision:
    def has_table(self, _name: str) -> bool:
        return True

    current_heads = set()


class MissingSchemaColumn(MissingSchemaRevision):
    current_heads = {"20260901_0008"}

    def get_table_names(self) -> list[str]:
        return [
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
        ]

    def get_columns(self, _name: str) -> list[dict[str, str]]:
        return []


def test_schema_gate_requires_migration_head_and_structural_contract() -> None:
    assert "ck_hosted_gate_reservation_gas_day" in _SCHEMA_CHECK_CONSTRAINTS
    with pytest.raises(ProductionStartupError, match="revision"):
        _schema_gate(MissingSchemaRevision())
    with pytest.raises(ProductionStartupError, match="column"):
        _schema_gate(MissingSchemaColumn())


class FakeWorkerRepository:
    def __init__(self) -> None:
        self.page_count = 0
        self.pages = {
            (None, 2): ["exec_1", "exec_2"],
            ("exec_2", 2): [],
        }
        self.calls: list[tuple[str | None, int]] = []

    def list_watchable_ids(self, *, chain: str, after_execution_id: str | None, limit: int) -> list[str]:
        assert chain == "eip155:8453"
        self.calls.append((after_execution_id, limit))
        self.page_count += 1
        if self.page_count > 1:
            return []
        return list(self.pages.get((after_execution_id, limit), []))

    def record_watcher_attempt(self, execution_id: str) -> None:
        return None


class FakeWatcher:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.chain = "eip155:8453"

    def watch(self, execution_id: str) -> str:
        self.calls.append(execution_id)
        if execution_id == "exec_1":
            raise RuntimeError("provider payload must not escape")
        return execution_id + ":ok"


class FakeLogger:
    def __init__(self) -> None:
        self.records: list[tuple[str, dict[str, object]]] = []

    def warning(self, message: str, *, extra: dict[str, object]) -> None:
        self.records.append((message, extra))


def test_watcher_worker_isolates_single_item_errors_and_resets_cursor() -> None:
    repository = FakeWorkerRepository()
    watcher = FakeWatcher()
    logger = FakeLogger()
    worker = WatcherWorker(repository, watcher, batch_size=2, poll_seconds=1, logger=logger)

    results = worker.run_once()
    assert results == ["exec_2:ok"]
    assert worker.cursor == "exec_2"
    assert worker.run_once() == []
    assert worker.cursor is None
    assert watcher.calls == ["exec_1", "exec_2"]
    assert logger.records == [
        (
            "watcher_item_failed",
            {"execution_id": "exec_1", "error_code": "watch_failed"},
        )
    ]


class FairWorkerRepository:
    def __init__(self) -> None:
        self.execution_ids = ["exec_a", "exec_m", "exec_z"]
        self.attempts: dict[str, int] = {}

    def list_watchable_ids(self, *, chain: str, after_execution_id: str | None, limit: int) -> list[str]:
        assert chain == "eip155:8453"
        del after_execution_id
        return sorted(
            self.execution_ids,
            key=lambda execution_id: (self.attempts.get(execution_id, 0), execution_id),
        )[:limit]

    def record_watcher_attempt(self, execution_id: str) -> None:
        self.attempts[execution_id] = self.attempts.get(execution_id, 0) + 1


class FairWatcher:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.chain = "eip155:8453"

    def watch(self, execution_id: str) -> str:
        self.calls.append(execution_id)
        if execution_id == "exec_a":
            raise RuntimeError("transient watcher failure")
        return execution_id


def test_watcher_worker_durably_round_robins_failed_ids() -> None:
    repository = FairWorkerRepository()
    watcher = FairWatcher()
    worker = WatcherWorker(repository, watcher, batch_size=2, poll_seconds=1)

    worker.run_once()
    repository.execution_ids.append("exec_zz")
    worker.run_once()
    worker.run_once()

    assert "exec_z" in watcher.calls
    assert "exec_zz" in watcher.calls
    assert repository.attempts["exec_a"] == 2


def test_watcher_worker_can_stop_async_loop_without_chain_side_effects() -> None:
    repository = FakeWorkerRepository()
    watcher = FakeWatcher()
    worker = WatcherWorker(repository, watcher, batch_size=2, poll_seconds=0)
    worker.stop()
    worker.run_forever()
    assert watcher.calls == []


def test_watcher_worker_waits_after_a_nonempty_watch_round() -> None:
    class PersistentRepository:
        def list_watchable_ids(
            self,
            *,
            chain: str,
            after_execution_id: str | None,
            limit: int,
        ) -> list[str]:
            assert chain == "eip155:8453"
            del after_execution_id, limit
            return ["exec_pending"]

        def record_watcher_attempt(self, execution_id: str) -> None:
            assert execution_id == "exec_pending"

    class PersistentWatcher:
        chain = "eip155:8453"

        def __init__(self) -> None:
            self.calls = 0
            self.worker: WatcherWorker | None = None

        def watch(self, execution_id: str) -> str:
            assert execution_id == "exec_pending"
            self.calls += 1
            if self.calls == 2:
                assert self.worker is not None
                self.worker.stop()
            return "pending"

    sleeps: list[float] = []
    watcher = PersistentWatcher()
    worker: WatcherWorker

    def stop_after_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        worker.stop()

    worker = WatcherWorker(
        PersistentRepository(),
        watcher,
        batch_size=1,
        poll_seconds=3,
        sleep=stop_after_sleep,
    )
    watcher.worker = worker

    worker.run_forever()

    assert watcher.calls == 1
    assert sleeps == [3]


def test_watcher_worker_rejects_chain_different_from_watcher_instance() -> None:
    with pytest.raises(ValueError, match="does not match"):
        WatcherWorker(
            FakeWorkerRepository(),
            FakeWatcher(),
            chain="eip155:137",
        )


class FakeRpc:
    def __init__(self, *, head: int = 100, chain_id: int = 8453, code_hash: str = CODE_HASH) -> None:
        self.head = head
        self.chain_id = chain_id
        self.code_hash = code_hash

    def call(self, method: str, params: list[object]) -> object:
        if method == "eth_chainId":
            return hex(self.chain_id)
        if method == "eth_getBlockByNumber":
            return {"number": hex(self.head), "hash": "0x" + "55" * 32}
        if method == "eth_getCode":
            return "0x6001"
        if method == "eth_call":
            return "0x" + "00" * 32
        raise AssertionError(method)


class FakeInspector:
    def has_table(self, name: str) -> bool:
        return name in {
            "hosted_tenants",
            "hosted_node_registrations",
            "hosted_dpop_replays",
            "hosted_preflight_records",
            "hosted_executions",
        }


class CompleteInspector:
    current_heads = {"20260901_0008"}

    def has_table(self, _name: str) -> bool:
        return True

    def get_table_names(self) -> list[str]:
        return sorted(_SCHEMA_TABLES)

    def get_columns(self, name: str) -> list[dict[str, str]]:
        return [{"name": column} for column in _SCHEMA_COLUMNS[name]]

    def get_unique_constraints(self, _name: str) -> list[dict[str, str]]:
        return [{"name": name} for name in _SCHEMA_UNIQUE_CONSTRAINTS]

    def get_check_constraints(self, _name: str) -> list[dict[str, str]]:
        return [{"name": name} for name in _SCHEMA_CHECK_CONSTRAINTS]

    def get_indexes(self, _name: str) -> list[dict[str, str]]:
        indexes = [
            {"name": name}
            for name in _SCHEMA_INDEXES
            if name != "uq_hosted_execution_active_chain_relayer_nonce"
        ]
        if _name == "hosted_executions":
            indexes.append(
                {
                    "name": "uq_hosted_execution_active_chain_relayer_nonce",
                    "column_names": ["chain", "relayer_address", "relayer_nonce"],
                    "unique": True,
                    "dialect_options": {
                        "postgresql_where": "status NOT IN ('expired', 'released')",
                    },
                }
            )
        return indexes


class CompleteRpc:
    def __init__(self, head: int) -> None:
        self.head = head

    def call(self, method: str, params: list[object]) -> object:
        if method == "eth_chainId":
            return "0x2105"
        if method == "eth_getBlockByNumber":
            return {"number": hex(self.head), "hash": "0x" + "55" * 32}
        if method == "eth_getCode":
            return "0x6001"
        if method == "eth_call":
            data = params[0]["data"]  # type: ignore[index]
            if data.endswith("()"):
                raise AssertionError("selector expected")
            # The startup gate only needs ABI words; the selector is checked
            # by the production code and this fake intentionally ignores it.
            return "0x" + "00" * 31 + "01"
        raise AssertionError(method)


def test_chain_gate_samples_rpc_heads_without_static_checks_between_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import production as production_module

    config = HostedProductionConfig(**config_values(max_rpc_head_skew=0))
    events: list[str] = []

    class OrderedRpc:
        def __init__(self, label: str) -> None:
            self.label = label

        def call(self, method: str, _params: list[object]) -> object:
            if method == "eth_chainId":
                events.append(f"{self.label}:chain")
                return hex(config.chain_id)
            if method == "eth_getBlockByNumber":
                events.append(f"{self.label}:head")
                return {"number": "0x64", "hash": "0x" + "55" * 32}
            raise AssertionError(method)

    monkeypatch.setattr(production_module, "_schema_gate", lambda _engine: None)
    monkeypatch.setattr(
        production_module,
        "_code_hash",
        lambda _rpc, _config, *, label: events.append(f"{label}:code"),
    )
    monkeypatch.setattr(
        production_module,
        "_contract_gate",
        lambda _rpc, _config, *, label: events.append(f"{label}:contract"),
    )

    startup_gate(
        config,
        repository_engine=object(),
        submission_rpc=OrderedRpc("submission"),
        watcher_rpc=OrderedRpc("watcher"),
    )

    submission_head = events.index("submission:head")
    assert events[submission_head : submission_head + 2] == [
        "submission:head",
        "watcher:head",
    ]


def test_startup_gate_fails_closed_on_chain_id_and_head_skew() -> None:
    config = HostedProductionConfig(**config_values(max_rpc_head_skew=1))
    with pytest.raises(ProductionStartupError):
        startup_gate(
            config,
            repository_engine=FakeInspector(),
            submission_rpc=FakeRpc(head=100),
            watcher_rpc=FakeRpc(head=102),
        )
    with pytest.raises(ProductionStartupError):
        startup_gate(
            config,
            repository_engine=FakeInspector(),
            submission_rpc=FakeRpc(chain_id=1),
            watcher_rpc=FakeRpc(),
        )


def test_startup_gate_checks_complete_schema_and_both_rpc_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = HostedProductionConfig(**config_values(max_rpc_head_skew=1))
    monkeypatch.setattr(
        "production._keccak",
        lambda value=None, *, text=None: bytes.fromhex(CODE_HASH[2:]),
    )

    with pytest.raises(ProductionStartupError, match="contract state"):
        startup_gate(
            config,
            repository_engine=CompleteInspector(),
            submission_rpc=CompleteRpc(100),
            watcher_rpc=CompleteRpc(100),
        )


def test_schema_gate_requires_rotation_scope_index() -> None:
    class MissingRotationScopeIndex(CompleteInspector):
        def get_indexes(self, _name: str) -> list[dict[str, str]]:
            return []

    with pytest.raises(ProductionStartupError, match="index"):
        _schema_gate(MissingRotationScopeIndex())


def test_schema_gate_requires_pilot_gate_indexes() -> None:
    class MissingPilotGateIndexes(CompleteInspector):
        def get_indexes(self, _name: str) -> list[dict[str, str]]:
            return [
                {"name": "ix_hosted_node_rotations_scope_status"},
            ]

    with pytest.raises(ProductionStartupError, match="index"):
        _schema_gate(MissingPilotGateIndexes())


_ACTIVE_RELAYER_NONCE_INDEX = "uq_hosted_execution_active_chain_relayer_nonce"
_VALID_ACTIVE_RELAYER_NONCE_INDEX = {
    "name": _ACTIVE_RELAYER_NONCE_INDEX,
    "column_names": ["chain", "relayer_address", "relayer_nonce"],
    "unique": True,
    "dialect_options": {
        "postgresql_where": "status NOT IN ('expired', 'released')",
    },
}


class ActiveRelayerNonceIndexVariant(CompleteInspector):
    def __init__(self, *, table_name: str, index: dict[str, object]) -> None:
        self.table_name = table_name
        self.index = index

    def get_indexes(self, name: str) -> list[dict[str, object]]:
        indexes = [
            item
            for item in super().get_indexes(name)
            if item.get("name") != _ACTIVE_RELAYER_NONCE_INDEX
        ]
        if name == self.table_name:
            indexes.append(dict(self.index))
        return indexes


def test_schema_gate_accepts_structurally_valid_active_relayer_nonce_index() -> None:
    _schema_gate(CompleteInspector())


def test_schema_gate_accepts_sqlalchemy_predicate_expression() -> None:
    from sqlalchemy import text

    index = {
        **_VALID_ACTIVE_RELAYER_NONCE_INDEX,
        "dialect_options": {
            "postgresql_where": text("status NOT IN ('expired', 'released')"),
        },
    }
    _schema_gate(ActiveRelayerNonceIndexVariant(table_name="hosted_executions", index=index))


def test_schema_gate_accepts_postgresql_deparsed_not_in_predicate() -> None:
    index = {
        **_VALID_ACTIVE_RELAYER_NONCE_INDEX,
        "dialect_options": {
            "postgresql_where": (
                "((status)::text <> ALL ((ARRAY["
                "'expired'::character varying, "
                "'released'::character varying"
                "])::text[]))"
            ),
        },
    }
    _schema_gate(ActiveRelayerNonceIndexVariant(table_name="hosted_executions", index=index))


@pytest.mark.parametrize(
    "predicate",
    [
        (
            "((status)::text <> ALL ((ARRAY["
            "'expired'::character varying, 'pending'::character varying"
            "])::text[]))"
        ),
        "status <> ALL (ARRAY['expired'::character varying])",
    ],
    ids=["wrong-array", "missing-status-value"],
)
def test_schema_gate_rejects_malformed_postgresql_deparsed_predicate(
    predicate: str,
) -> None:
    index = {
        **_VALID_ACTIVE_RELAYER_NONCE_INDEX,
        "dialect_options": {"postgresql_where": predicate},
    }
    with pytest.raises(ProductionStartupError, match="index"):
        _schema_gate(ActiveRelayerNonceIndexVariant(table_name="hosted_executions", index=index))


@pytest.mark.parametrize(
    "table_name,index",
    [
        (
            "hosted_tenants",
            _VALID_ACTIVE_RELAYER_NONCE_INDEX,
        ),
        (
            "hosted_executions",
            {
                **_VALID_ACTIVE_RELAYER_NONCE_INDEX,
                "column_names": ["relayer_address", "chain", "relayer_nonce"],
            },
        ),
        (
            "hosted_executions",
            {**_VALID_ACTIVE_RELAYER_NONCE_INDEX, "unique": False},
        ),
        (
            "hosted_executions",
            {
                **_VALID_ACTIVE_RELAYER_NONCE_INDEX,
                "dialect_options": {
                    "postgresql_where": "status <> 'expired'",
                },
            },
        ),
    ],
    ids=["wrong-table", "wrong-column-order", "not-unique", "wrong-predicate"],
)
def test_schema_gate_rejects_malformed_active_relayer_nonce_index(
    table_name: str,
    index: dict[str, object],
) -> None:
    with pytest.raises(ProductionStartupError, match="index"):
        _schema_gate(ActiveRelayerNonceIndexVariant(table_name=table_name, index=index))
