from __future__ import annotations

import sqlite3
import os
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from io import BytesIO
from threading import Barrier, Lock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import CheckConstraint, UniqueConstraint, create_engine, inspect as sa_inspect, text
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.schema import CreateTable
from types import SimpleNamespace

from services.funding_adapter_service.repository import (
    BRIDGE_SCHEMA_VERSION,
    BridgeDepositClaimRow,
    BridgeDepositTargetRow,
    BridgeObservationRow,
    BridgeRepositoryError,
    PostgresBridgeRepository,
    SQLiteBridgeRepository,
)
from services.funding_adapter_service.schemas import (
    PolymarketBridgeDeposit,
    PolymarketBridgeStatus,
)
from shared.config import AppConfig
import services.funding_adapter_service.app as funding_app
import services.funding_adapter_service.repository as bridge_repository
import services.funding_adapter_service.service as funding_service


USER_ID = "telegram_user_1"
BINDING_ID = "pm_binding_1"
VENUE_WALLET = "0x1111111111111111111111111111111111111111"
BRIDGE_ADDRESS = "0x2222222222222222222222222222222222222222"
SOURCE_TOKEN = "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"
DESTINATION_TOKEN = "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb"
POLYGON_USDCE = "0x2791bca1f2de4661ed88a30c99a7a9449aa84174"
TX_HASH = "0x" + "a" * 64
NOW = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
NOT_BEFORE_TIME_MS = 1787121599000
UINT256_MAX_ATOMIC = str(2**256 - 1)


def _target(**updates: object) -> PolymarketBridgeDeposit:
    values: dict[str, object] = {
        "deposit_id": "pm_deposit_123",
        "user_id": USER_ID,
        "binding_id": BINDING_ID,
        "venue_wallet_address": VENUE_WALLET,
        "bridge_address": BRIDGE_ADDRESS,
        "source_network": "eip155:137",
        "source_token_address": SOURCE_TOKEN,
        "destination_network": "eip155:137",
        "destination_token_address": DESTINATION_TOKEN,
        "status": "ready",
        "created_at": NOW,
    }
    values.update(updates)
    return PolymarketBridgeDeposit.model_validate(values)


def _observation(**updates: object) -> PolymarketBridgeStatus:
    values: dict[str, object] = {
        "observation_id": "pm_bridge_observation_123",
        "user_id": USER_ID,
        "binding_id": BINDING_ID,
        "venue_wallet_address": VENUE_WALLET,
        "bridge_address": BRIDGE_ADDRESS,
        "source_network": "eip155:137",
        "source_token_address": SOURCE_TOKEN,
        "destination_network": "eip155:137",
        "destination_token_address": DESTINATION_TOKEN,
        "status": "COMPLETED",
        "tx_hash": TX_HASH,
        "amount_atomic": "1000000",
        "checked_at": NOW,
        "bridge_created_time_ms": 1787121600000,
    }
    values.update(updates)
    return PolymarketBridgeStatus.model_validate(values)


def test_profile_selection_is_strict_and_never_falls_back_between_backends(tmp_path) -> None:
    personal = AppConfig(
        profile="personal",
        polymarket_bridge_database_path=str(tmp_path / "bridge.sqlite3"),
    )
    assert personal.profile == "personal"
    assert not hasattr(personal, "polymarket_bridge_status_file")

    with pytest.raises(ValueError, match="prediction markets profile must be personal or server"):
        AppConfig(profile="development")
    with pytest.raises(ValueError, match="personal bridge database path is required"):
        AppConfig(profile="personal", polymarket_bridge_database_path="")
    with pytest.raises(ValueError, match="personal profile does not accept a server database URL"):
        AppConfig(
            profile="personal",
            polymarket_bridge_database_path=str(tmp_path / "bridge.sqlite3"),
            prediction_markets_database_url="postgresql+psycopg://clink:password@db/clink",
        )
    with pytest.raises(ValueError, match=r"server profile requires a postgresql\+psycopg database URL"):
        AppConfig(
            profile="server",
            prediction_markets_database_url=f"sqlite+pysqlite:///{tmp_path / 'wrong.sqlite3'}",
        )

    server = AppConfig(
        profile="server",
        prediction_markets_database_url="postgresql+psycopg://clink:db-password-marker@db/clink",
        prediction_markets_internal_api_token="internal-token-marker",
    )
    assert server.prediction_markets_database_url.startswith("postgresql+psycopg://")
    assert "db-password-marker" not in repr(server)
    assert "internal-token-marker" not in repr(server)


def test_sqlite_repository_is_idempotent_scoped_and_preserves_rows(tmp_path) -> None:
    database = tmp_path / "bridge.sqlite3"
    repository = SQLiteBridgeRepository(database)

    stored = repository.save_deposit_target(_target())
    replay = repository.save_deposit_target(_target())
    assert replay == stored
    assert repository.get_deposit_target(
        user_id=USER_ID,
        binding_id=BINDING_ID,
        venue_wallet_address=VENUE_WALLET,
        bridge_address=BRIDGE_ADDRESS,
    ) == stored
    assert repository.get_deposit_target(
        user_id="telegram_user_2",
        binding_id=BINDING_ID,
        venue_wallet_address=VENUE_WALLET,
        bridge_address=BRIDGE_ADDRESS,
    ) is None
    assert repository.get_deposit_target(
        user_id=USER_ID,
        binding_id="pm_binding_2",
        venue_wallet_address=VENUE_WALLET,
        bridge_address=BRIDGE_ADDRESS,
    ) is None

    observation = repository.save_bridge_observation(_observation())
    assert repository.get_bridge_observation(
        user_id=USER_ID,
        binding_id=BINDING_ID,
        venue_wallet_address=VENUE_WALLET,
        bridge_address=BRIDGE_ADDRESS,
        expected_tx_hash=TX_HASH,
    ) == observation
    assert repository.get_bridge_observation(
        user_id=USER_ID,
        binding_id=BINDING_ID,
        venue_wallet_address=VENUE_WALLET,
        bridge_address=BRIDGE_ADDRESS,
        expected_tx_hash="0x" + "b" * 64,
    ) is None

    reopened = SQLiteBridgeRepository(database)
    assert reopened.get_deposit_target(
        user_id=USER_ID,
        binding_id=BINDING_ID,
        venue_wallet_address=VENUE_WALLET,
        bridge_address=BRIDGE_ADDRESS,
    ) == stored


def test_uint256_atomic_amount_is_bounded_and_round_trips_exactly(tmp_path) -> None:
    database = tmp_path / "bridge.sqlite3"
    repository = SQLiteBridgeRepository(database)
    repository.save_deposit_target(_target())
    amount_atomic = UINT256_MAX_ATOMIC

    observation = _observation(amount_atomic=amount_atomic)
    assert observation.amount_usdc == (
        f"{UINT256_MAX_ATOMIC[:-6]}.{UINT256_MAX_ATOMIC[-6:]}"
    )
    with pytest.raises(ValueError, match="amount_atomic must be a uint256"):
        _observation(amount_atomic=str(2**256))
    repository.save_bridge_observation(observation)

    stored = repository.get_bridge_observation(
        user_id=USER_ID,
        binding_id=BINDING_ID,
        venue_wallet_address=VENUE_WALLET,
        bridge_address=BRIDGE_ADDRESS,
        expected_tx_hash=TX_HASH,
    )
    assert stored is not None
    assert stored.amount_atomic == amount_atomic


def test_sqlite_constraints_reject_context_drift_and_noncanonical_hashes(tmp_path) -> None:
    database = tmp_path / "bridge.sqlite3"
    repository = SQLiteBridgeRepository(database)
    repository.save_deposit_target(_target())

    with pytest.raises(BridgeRepositoryError, match="bridge target context conflict"):
        repository.save_deposit_target(
            _target(
                deposit_id="pm_deposit_456",
                bridge_address="0x3333333333333333333333333333333333333333",
            )
        )

    with sqlite3.connect(database) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO polymarket_bridge_observations (
                    observation_id, user_id, binding_id, venue_wallet_address,
                    bridge_address, source_network, source_token_address,
                    destination_network, destination_token_address, status,
                    tx_hash, amount_atomic, checked_at, bridge_created_time_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "pm_bridge_observation_bad",
                    USER_ID,
                    BINDING_ID,
                    VENUE_WALLET,
                    BRIDGE_ADDRESS,
                    "eip155:137",
                    SOURCE_TOKEN,
                    "eip155:137",
                    DESTINATION_TOKEN,
                    "COMPLETED",
                    "0x" + "A" * 64,
                    "1000000",
                    NOW.isoformat(),
                    1787121600000,
                ),
            )

    with sqlite3.connect(database) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO polymarket_bridge_observations (
                    observation_id, user_id, binding_id, venue_wallet_address,
                    bridge_address, source_network, source_token_address,
                    destination_network, destination_token_address, status,
                    tx_hash, amount_atomic, checked_at, bridge_created_time_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "pm_bridge_observation_uint256_overflow",
                    USER_ID,
                    BINDING_ID,
                    VENUE_WALLET,
                    BRIDGE_ADDRESS,
                    "eip155:137",
                    SOURCE_TOKEN,
                    "eip155:137",
                    DESTINATION_TOKEN,
                    "PROCESSING",
                    None,
                    str(2**256),
                    NOW.isoformat(),
                    1787121600000,
                ),
            )

    with sqlite3.connect(database) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO polymarket_bridge_deposit_targets (
                    deposit_id, user_id, binding_id, venue_wallet_address,
                    bridge_address, source_network, source_token_address,
                    destination_network, destination_token_address, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "pm_deposit_nonhex",
                    "telegram_user_nonhex",
                    "pm_binding_nonhex",
                    "0x" + "g" * 40,
                    BRIDGE_ADDRESS,
                    "eip155:137",
                    SOURCE_TOKEN,
                    "eip155:137",
                    DESTINATION_TOKEN,
                    "ready",
                    NOW.isoformat(),
                ),
            )

    with sqlite3.connect(database) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO polymarket_bridge_observations (
                    observation_id, user_id, binding_id, venue_wallet_address,
                    bridge_address, source_network, source_token_address,
                    destination_network, destination_token_address, status,
                    tx_hash, amount_atomic, checked_at, bridge_created_time_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "pm_bridge_observation_nonhex_hash",
                    USER_ID,
                    BINDING_ID,
                    VENUE_WALLET,
                    BRIDGE_ADDRESS,
                    "eip155:137",
                    SOURCE_TOKEN,
                    "eip155:137",
                    DESTINATION_TOKEN,
                    "COMPLETED",
                    "0x" + "g" * 64,
                    "1000000",
                    NOW.isoformat(),
                    1787121600000,
                ),
            )

    with sqlite3.connect(database) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO polymarket_bridge_observations (
                    observation_id, user_id, binding_id, venue_wallet_address,
                    bridge_address, source_network, source_token_address,
                    destination_network, destination_token_address, status,
                    tx_hash, amount_atomic, checked_at, bridge_created_time_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "pm_bridge_observation_bad_amount",
                    USER_ID,
                    BINDING_ID,
                    VENUE_WALLET,
                    BRIDGE_ADDRESS,
                    "eip155:137",
                    SOURCE_TOKEN,
                    "eip155:137",
                    DESTINATION_TOKEN,
                    "PROCESSING",
                    TX_HASH,
                    "1x",
                    NOW.isoformat(),
                    1787121600000,
                ),
            )


def test_sqlite_concurrent_replay_creates_one_target(tmp_path) -> None:
    database = tmp_path / "bridge.sqlite3"
    SQLiteBridgeRepository(database)

    def save() -> str:
        return SQLiteBridgeRepository(database).save_deposit_target(_target()).deposit_id

    with ThreadPoolExecutor(max_workers=6) as pool:
        assert set(pool.map(lambda _: save(), range(12))) == {"pm_deposit_123"}

    with sqlite3.connect(database) as connection:
        count = connection.execute(
            "SELECT count(*) FROM polymarket_bridge_deposit_targets"
        ).fetchone()[0]
    assert count == 1


def test_two_service_instances_create_one_bridge_address_with_one_post(tmp_path) -> None:
    database = tmp_path / "bridge.sqlite3"
    config = AppConfig(
        profile="personal",
        polymarket_bridge_database_path=str(database),
    )
    barrier = Barrier(2)

    class SlowBridgeClient(FakeBridgeClient):
        def __init__(self) -> None:
            super().__init__()
            self.lock = Lock()

        def post(self, path: str, payload: dict) -> dict:
            with self.lock:
                self.calls.append(("POST", path, payload))
            time.sleep(0.05)
            return self.deposit_response

    bridge_client = SlowBridgeClient()

    def create() -> PolymarketBridgeDeposit:
        repository = SQLiteBridgeRepository(database)
        service = funding_service.PolymarketFundingAdapterService(
            config=config,
            bridge_client=bridge_client,
            repository=repository,
            clock=lambda: NOW,
        )
        barrier.wait()
        return service.create_deposit_address(_request())

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: create(), range(2)))

    assert results[0] == results[1]
    assert [call for call in bridge_client.calls if call[0] == "POST"] == [
        ("POST", "/deposit", {"address": VENUE_WALLET})
    ]


def test_failed_bridge_creation_releases_claim_before_lease_expiry(
    tmp_path,
) -> None:
    class AmbiguousBridgeClient(FakeBridgeClient):
        def post(self, path: str, payload: dict) -> dict:
            self.calls.append(("POST", path, payload))
            raise funding_service.BridgeTransportError(
                "polymarket bridge request failed"
            )

    current_time = [NOW]
    first_client = AmbiguousBridgeClient()
    config = AppConfig(
        profile="personal",
        polymarket_bridge_database_path=str(tmp_path / "bridge.sqlite3"),
    )
    first_service = funding_service.PolymarketFundingAdapterService(
        config=config,
        bridge_client=first_client,
        clock=lambda: current_time[0],
    )

    with pytest.raises(
        funding_service.BridgeTransportError,
        match="polymarket bridge request failed",
    ):
        first_service.create_deposit_address(_request())
    assert len(first_client.calls) == 1

    current_time[0] += timedelta(minutes=5)
    second_client = FakeBridgeClient()
    second_service = funding_service.PolymarketFundingAdapterService(
        config=config,
        bridge_client=second_client,
        repository=SQLiteBridgeRepository(config.polymarket_bridge_database_path),
        clock=lambda: current_time[0],
    )
    deposit = second_service.create_deposit_address(_request())

    assert deposit.bridge_address == BRIDGE_ADDRESS
    assert second_client.calls == [("POST", "/deposit", {"address": VENUE_WALLET})]


def test_failed_bridge_creation_releases_claim_for_retry(tmp_path) -> None:
    class FailingOnceBridgeClient(FakeBridgeClient):
        def __init__(self) -> None:
            super().__init__()
            self.fail = True

        def post(self, path: str, payload: dict) -> dict:
            self.calls.append(("POST", path, payload))
            if self.fail:
                self.fail = False
                raise funding_service.BridgeTransportError(
                    "polymarket bridge request failed"
                )
            return self.deposit_response

    client = FailingOnceBridgeClient()
    service, _, _ = _service(tmp_path, client)

    with pytest.raises(funding_service.BridgeTransportError):
        service.create_deposit_address(_request())

    deposit = service.create_deposit_address(_request())

    assert deposit.bridge_address == BRIDGE_ADDRESS
    assert len(client.calls) == 2


def test_expired_deposit_creation_claim_is_still_busy(tmp_path) -> None:
    database = tmp_path / "bridge.sqlite3"
    first_repository = SQLiteBridgeRepository(database)
    second_repository = SQLiteBridgeRepository(database)

    assert first_repository.try_claim_deposit_creation(
        user_id=USER_ID,
        binding_id=BINDING_ID,
        venue_wallet_address=VENUE_WALLET,
        claim_token="pm_claim_first",
        claimed_at=NOW,
        lease_expires_at=NOW + timedelta(seconds=30),
    ) == "acquired"
    assert second_repository.try_claim_deposit_creation(
        user_id=USER_ID,
        binding_id=BINDING_ID,
        venue_wallet_address=VENUE_WALLET,
        claim_token="pm_claim_second",
        claimed_at=NOW + timedelta(minutes=5),
        lease_expires_at=NOW + timedelta(minutes=6),
    ) == "busy"


def test_sqlite_concurrent_observation_replay_is_idempotent(tmp_path) -> None:
    database = tmp_path / "bridge.sqlite3"
    repository = SQLiteBridgeRepository(database)
    repository.save_deposit_target(_target())

    def save() -> str:
        return (
            SQLiteBridgeRepository(database)
            .save_bridge_observation(_observation())
            .observation_id
        )

    with ThreadPoolExecutor(max_workers=6) as pool:
        assert set(pool.map(lambda _: save(), range(12))) == {
            "pm_bridge_observation_123"
        }

    with sqlite3.connect(database) as connection:
        count = connection.execute(
            "SELECT count(*) FROM polymarket_bridge_observations"
        ).fetchone()[0]
    assert count == 1


def test_repository_schema_uses_shared_database_constraints_for_both_dialects() -> None:
    for table in (
        BridgeDepositClaimRow.__table__,
        BridgeDepositTargetRow.__table__,
        BridgeObservationRow.__table__,
    ):
        constraints = table.constraints
        assert any(isinstance(item, CheckConstraint) for item in constraints)
        assert any(isinstance(item, UniqueConstraint) for item in constraints)
        sqlite_ddl = str(CreateTable(table).compile(dialect=sqlite.dialect())).lower()
        postgres_ddl = str(CreateTable(table).compile(dialect=postgresql.dialect())).lower()
        for fragment in ("check", "unique", "lower", "length"):
            assert fragment in sqlite_ddl
            assert fragment in postgres_ddl
        assert "replace(" in sqlite_ddl
        assert "replace(" in postgres_ddl
    observation_sqlite = str(
        CreateTable(BridgeObservationRow.__table__).compile(dialect=sqlite.dialect())
    )
    observation_postgres = str(
        CreateTable(BridgeObservationRow.__table__).compile(
            dialect=postgresql.dialect()
        )
    )
    assert UINT256_MAX_ATOMIC in observation_sqlite
    assert UINT256_MAX_ATOMIC in observation_postgres


def test_future_schema_fails_closed_before_creating_or_changing_tables(tmp_path) -> None:
    database = tmp_path / "future.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE polymarket_bridge_schema_version (singleton INTEGER PRIMARY KEY, version INTEGER NOT NULL)"
        )
        connection.execute(
            "INSERT INTO polymarket_bridge_schema_version (singleton, version) VALUES (1, ?)",
            (BRIDGE_SCHEMA_VERSION + 1,),
        )

    with pytest.raises(BridgeRepositoryError, match="bridge database schema is newer than this binary"):
        SQLiteBridgeRepository(database)

    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        version = connection.execute(
            "SELECT version FROM polymarket_bridge_schema_version WHERE singleton = 1"
        ).fetchone()[0]
    assert tables == {"polymarket_bridge_schema_version"}
    assert version == BRIDGE_SCHEMA_VERSION + 1


def test_partial_unversioned_schema_fails_closed_without_metadata_write(tmp_path) -> None:
    database = tmp_path / "partial.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE polymarket_bridge_deposit_targets (deposit_id TEXT PRIMARY KEY)")

    with pytest.raises(BridgeRepositoryError, match="bridge database schema metadata is missing"):
        SQLiteBridgeRepository(database)

    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert tables == {"polymarket_bridge_deposit_targets"}


def test_current_schema_version_with_missing_tables_fails_closed_without_ddl(tmp_path) -> None:
    database = tmp_path / "incomplete.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE polymarket_bridge_schema_version (singleton INTEGER PRIMARY KEY, version INTEGER NOT NULL)"
        )
        connection.execute(
            "INSERT INTO polymarket_bridge_schema_version (singleton, version) VALUES (1, ?)",
            (BRIDGE_SCHEMA_VERSION,),
        )

    with pytest.raises(
        BridgeRepositoryError, match="bridge database schema is incomplete"
    ):
        SQLiteBridgeRepository(database)

    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert tables == {"polymarket_bridge_schema_version"}


class FakeBridgeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict | None]] = []
        self.deposit_response: dict = {
            "address": {
                "evm": BRIDGE_ADDRESS,
                "svm": "6vMbiwQjZ6hYwX8b3PjrNBMzCLcXRrsVo8bVn6m5R7qi",
                "btc": "bc1qexample",
                "tron": "TExample",
            },
            "note": "Send only supported assets.",
        }
        self.status_response: dict = {
            "transactions": [
                {
                    "fromChainId": "137",
                    "fromTokenAddress": SOURCE_TOKEN,
                    "fromAmountBaseUnit": "1000000",
                    "toChainId": "137",
                    "toTokenAddress": DESTINATION_TOKEN,
                    "status": "COMPLETED",
                    "txHash": TX_HASH,
                    "createdTimeMs": 1787121600000,
                }
            ],
            "nextCursor": None,
        }

    def post(self, path: str, payload: dict) -> dict:
        self.calls.append(("POST", path, payload))
        return self.deposit_response

    def get(self, path: str) -> dict:
        self.calls.append(("GET", path, None))
        return self.status_response


def _service(tmp_path, client: FakeBridgeClient | None = None):
    config = AppConfig(
        profile="personal",
        polymarket_bridge_database_path=str(tmp_path / "bridge.sqlite3"),
        prediction_markets_internal_api_token="i" * 32,
    )
    repository = SQLiteBridgeRepository(config.polymarket_bridge_database_path)
    return (
        funding_service.PolymarketFundingAdapterService(
            config=config,
            bridge_client=client or FakeBridgeClient(),
            repository=repository,
        ),
        config,
        repository,
    )


def _request(**updates: object):
    values: dict[str, object] = {
        "user_id": USER_ID,
        "binding_id": BINDING_ID,
        "venue_wallet_address": VENUE_WALLET,
    }
    values.update(updates)
    return funding_service.CreatePolymarketBridgeDepositRequest.model_validate(values)


def test_bridge_v2_deposit_uses_exact_body_and_persists_allowlisted_scope(tmp_path) -> None:
    client = FakeBridgeClient()
    service, _, repository = _service(tmp_path, client)

    deposit = service.create_deposit_address(_request())

    assert client.calls == [("POST", "/deposit", {"address": VENUE_WALLET})]
    assert deposit.user_id == USER_ID
    assert deposit.binding_id == BINDING_ID
    assert deposit.venue_wallet_address == VENUE_WALLET
    assert deposit.bridge_address == BRIDGE_ADDRESS
    assert deposit.source_network == "eip155:137"
    assert deposit.source_token_address == SOURCE_TOKEN
    assert deposit.destination_token_address == DESTINATION_TOKEN
    assert "raw_response" not in deposit.model_dump()
    assert "note" not in deposit.model_dump()
    assert repository.get_deposit_target(
        user_id=USER_ID,
        binding_id=BINDING_ID,
        venue_wallet_address=VENUE_WALLET,
        bridge_address=BRIDGE_ADDRESS,
    ) == deposit

    assert service.create_deposit_address(_request()) == deposit
    assert len(client.calls) == 1


def test_deposit_response_accepts_documented_missing_builder_code_warning(
    tmp_path,
) -> None:
    client = FakeBridgeClient()
    client.deposit_response["warnings"] = [
        {
            "code": "missing_builder_code",
            "message": "The optional builder code was not provided.",
        }
    ]
    service, _, _ = _service(tmp_path, client)

    deposit = service.create_deposit_address(_request())

    assert deposit.status == "ready"
    assert "warnings" not in deposit.model_dump()


@pytest.mark.parametrize(
    "response",
    [
        {"depositAddress": BRIDGE_ADDRESS},
        {"address": BRIDGE_ADDRESS},
        {"address": {}},
        {"address": {"evm": "0x" + "0" * 40}},
        {"address": {"evm": BRIDGE_ADDRESS}, "unexpected": True},
        {"address": {"evm": BRIDGE_ADDRESS, "privateKey": "do-not-return"}},
        {"address": {"evm": BRIDGE_ADDRESS}, "note": "x" * 1025},
        {"address": {"evm": BRIDGE_ADDRESS}, "warnings": None},
        {"address": {"evm": BRIDGE_ADDRESS}, "warnings": []},
        {
            "address": {"evm": BRIDGE_ADDRESS},
            "warnings": [{"code": "unknown_warning", "message": "unknown"}],
        },
        {
            "address": {"evm": BRIDGE_ADDRESS},
            "warnings": [
                {
                    "code": "missing_builder_code",
                    "message": "documented warning",
                    "unexpected": True,
                }
            ],
        },
        {
            "address": {"evm": BRIDGE_ADDRESS},
            "warnings": [
                {
                    "code": "missing_builder_code",
                    "message": "x" * 1025,
                }
            ],
        },
    ],
)
def test_deposit_response_rejects_legacy_malformed_zero_unknown_and_sensitive_shapes(
    tmp_path, response
) -> None:
    client = FakeBridgeClient()
    client.deposit_response = response
    service, _, repository = _service(tmp_path, client)

    with pytest.raises(
        funding_service.BridgeAdapterError,
        match="polymarket bridge response is invalid",
    ):
        service.create_deposit_address(_request())
    assert repository.find_deposit_target(
        user_id=USER_ID,
        binding_id=BINDING_ID,
        venue_wallet_address=VENUE_WALLET,
    ) is None


def test_zero_venue_wallet_is_rejected_before_bridge_io() -> None:
    with pytest.raises(ValueError, match="venue_wallet_address must not be the zero address"):
        _request(venue_wallet_address="0x" + "0" * 40)


def test_binding_or_wallet_drift_fails_without_a_second_bridge_request(tmp_path) -> None:
    client = FakeBridgeClient()
    service, _, _ = _service(tmp_path, client)
    service.create_deposit_address(_request())

    with pytest.raises(
        funding_service.BridgeAdapterError, match="bridge binding context conflict"
    ):
        service.create_deposit_address(
            _request(venue_wallet_address="0x3333333333333333333333333333333333333333")
        )
    assert len(client.calls) == 1


def test_status_is_full_scope_expected_transaction_and_newest_first(tmp_path) -> None:
    client = FakeBridgeClient()
    service, _, repository = _service(tmp_path, client)
    service.create_deposit_address(_request())
    client.status_response["transactions"].insert(
        0,
        {
            "fromChainId": "137",
            "fromTokenAddress": SOURCE_TOKEN,
            "fromAmountBaseUnit": "2000000",
            "toChainId": "137",
            "toTokenAddress": DESTINATION_TOKEN,
            "status": "PROCESSING",
            "createdTimeMs": 1787121600100,
        },
    )

    status = service.get_bridge_status(
        user_id=USER_ID,
        binding_id=BINDING_ID,
        venue_wallet_address=VENUE_WALLET,
        bridge_address=BRIDGE_ADDRESS,
        expected_amount_atomic="1000000",
        not_before_time_ms=NOT_BEFORE_TIME_MS,
        expected_bridge_tx_hash=TX_HASH,
    )

    assert client.calls[-1] == (
        "GET",
        f"/status/{BRIDGE_ADDRESS}?limit=50",
        None,
    )
    assert status.tx_hash == TX_HASH
    assert status.status == "COMPLETED"
    assert status.amount_atomic == "1000000"
    assert repository.get_bridge_observation(
        user_id=USER_ID,
        binding_id=BINDING_ID,
        venue_wallet_address=VENUE_WALLET,
        bridge_address=BRIDGE_ADDRESS,
        expected_tx_hash=TX_HASH,
    ) == status


def test_status_accepts_unique_scoped_match_when_origin_and_bridge_hashes_differ(
    tmp_path,
) -> None:
    client = FakeBridgeClient()
    bridge_tx_hash = "0x" + "b" * 64
    client.status_response["transactions"][0]["txHash"] = bridge_tx_hash
    service, _, repository = _service(tmp_path, client)
    service.create_deposit_address(_request())

    status = service.get_bridge_status(
        user_id=USER_ID,
        binding_id=BINDING_ID,
        venue_wallet_address=VENUE_WALLET,
        bridge_address=BRIDGE_ADDRESS,
        expected_amount_atomic="1000000",
        not_before_time_ms=NOT_BEFORE_TIME_MS,
        expected_bridge_tx_hash=TX_HASH,
    )

    assert status.status == "COMPLETED"
    assert status.tx_hash == bridge_tx_hash
    assert repository.get_bridge_observation(
        user_id=USER_ID,
        binding_id=BINDING_ID,
        venue_wallet_address=VENUE_WALLET,
        bridge_address=BRIDGE_ADDRESS,
        expected_tx_hash=bridge_tx_hash,
    ) == status


def test_status_accepts_documented_usdce_onramp_precursor_and_records_reported_token(
    tmp_path,
) -> None:
    client = FakeBridgeClient()
    client.status_response["transactions"][0]["toTokenAddress"] = POLYGON_USDCE
    service, _, repository = _service(tmp_path, client)
    service.create_deposit_address(_request())

    status = service.get_bridge_status(
        user_id=USER_ID,
        binding_id=BINDING_ID,
        venue_wallet_address=VENUE_WALLET,
        bridge_address=BRIDGE_ADDRESS,
        expected_amount_atomic="1000000",
        not_before_time_ms=NOT_BEFORE_TIME_MS,
        expected_bridge_tx_hash=TX_HASH,
    )

    assert status.status == "COMPLETED"
    assert status.destination_token_address == POLYGON_USDCE
    assert repository.get_bridge_observation(
        user_id=USER_ID,
        binding_id=BINDING_ID,
        venue_wallet_address=VENUE_WALLET,
        bridge_address=BRIDGE_ADDRESS,
        expected_tx_hash=TX_HASH,
    ) == status


def test_processing_and_failed_statuses_do_not_require_a_bridge_tx_hash(tmp_path) -> None:
    for bridge_status in ("PROCESSING", "FAILED"):
        client = FakeBridgeClient()
        transaction = client.status_response["transactions"][0]
        transaction["status"] = bridge_status
        transaction.pop("txHash")
        service, _, _ = _service(tmp_path / bridge_status.lower(), client)
        service.create_deposit_address(_request())

        status = service.get_bridge_status(
            user_id=USER_ID,
            binding_id=BINDING_ID,
            venue_wallet_address=VENUE_WALLET,
            bridge_address=BRIDGE_ADDRESS,
            expected_amount_atomic="1000000",
            not_before_time_ms=NOT_BEFORE_TIME_MS,
        )

        assert status.status == bridge_status
        assert status.tx_hash is None


def test_status_ignores_valid_unrelated_multichain_history(tmp_path) -> None:
    client = FakeBridgeClient()
    client.status_response["transactions"].insert(
        0,
        {
            "fromChainId": "1151111081099710",
            "fromTokenAddress": "11111111111111111111111111111111",
            "fromAmountBaseUnit": "13500152",
            "toChainId": "137",
            "toTokenAddress": DESTINATION_TOKEN,
            "status": "COMPLETED",
            "txHash": (
                "3atr19NAiNCYt24RHM1WnzZp47RXskpTDzspJoCBBaMFwUB8fk37hFkxz35P5UEnnmWz21rb2t5wJ8pq3EE2XnxU"
            ),
            "createdTimeMs": 1787121600200,
        },
    )
    service, _, _ = _service(tmp_path, client)
    service.create_deposit_address(_request())

    status = service.get_bridge_status(
        user_id=USER_ID,
        binding_id=BINDING_ID,
        venue_wallet_address=VENUE_WALLET,
        bridge_address=BRIDGE_ADDRESS,
        expected_amount_atomic="1000000",
        not_before_time_ms=NOT_BEFORE_TIME_MS,
        expected_bridge_tx_hash=TX_HASH,
    )

    assert status.status == "COMPLETED"
    assert status.tx_hash == TX_HASH


def test_status_rejects_numeric_amount_instead_of_official_decimal_string(tmp_path) -> None:
    client = FakeBridgeClient()
    client.status_response["transactions"][0]["fromAmountBaseUnit"] = 1_000_000
    service, _, _ = _service(tmp_path, client)
    service.create_deposit_address(_request())

    with pytest.raises(
        funding_service.BridgeAdapterError,
        match="polymarket bridge response is invalid",
    ):
        service.get_bridge_status(
            user_id=USER_ID,
            binding_id=BINDING_ID,
            venue_wallet_address=VENUE_WALLET,
            bridge_address=BRIDGE_ADDRESS,
            expected_amount_atomic="1000000",
            not_before_time_ms=NOT_BEFORE_TIME_MS,
        )


@pytest.mark.parametrize("case", ["old_same_amount", "multiple_matches", "missing_time"])
def test_status_without_bridge_hash_rejects_stale_ambiguous_or_undated_matches(
    tmp_path, case
) -> None:
    client = FakeBridgeClient()
    base = {
        "fromChainId": "137",
        "fromTokenAddress": SOURCE_TOKEN,
        "fromAmountBaseUnit": "1000000",
        "toChainId": "137",
        "toTokenAddress": DESTINATION_TOKEN,
        "status": "PROCESSING",
    }
    if case == "old_same_amount":
        client.status_response["transactions"] = [
            {**base, "fromAmountBaseUnit": "2000000", "createdTimeMs": 1787121600100},
            {**base, "createdTimeMs": NOT_BEFORE_TIME_MS - 1},
        ]
    elif case == "multiple_matches":
        client.status_response["transactions"] = [
            {**base, "createdTimeMs": 1787121600100},
            {**base, "createdTimeMs": 1787121600000},
        ]
    else:
        client.status_response["transactions"] = [base]
    service, _, _ = _service(tmp_path, client)
    service.create_deposit_address(_request())

    with pytest.raises(
        funding_service.BridgeAdapterError,
        match="expected bridge transaction is unavailable",
    ):
        service.get_bridge_status(
            user_id=USER_ID,
            binding_id=BINDING_ID,
            venue_wallet_address=VENUE_WALLET,
            bridge_address=BRIDGE_ADDRESS,
            expected_amount_atomic="1000000",
            not_before_time_ms=NOT_BEFORE_TIME_MS,
        )


def test_status_rejects_wrong_owner_before_bridge_io(tmp_path) -> None:
    client = FakeBridgeClient()
    service, _, _ = _service(tmp_path, client)
    service.create_deposit_address(_request())

    with pytest.raises(funding_service.BridgeAdapterError, match="bridge target is unavailable"):
        service.get_bridge_status(
            user_id="telegram_user_2",
            binding_id=BINDING_ID,
            venue_wallet_address=VENUE_WALLET,
            bridge_address=BRIDGE_ADDRESS,
            expected_amount_atomic="1000000",
            not_before_time_ms=NOT_BEFORE_TIME_MS,
            expected_bridge_tx_hash=TX_HASH,
        )
    assert len(client.calls) == 1


def test_status_rejects_ambiguous_transactions_when_bridge_hash_differs(tmp_path) -> None:
    client = FakeBridgeClient()
    client.status_response["transactions"].append(
        {
            **client.status_response["transactions"][0],
            "txHash": "0x" + "b" * 64,
            "createdTimeMs": 1787121600101,
        }
    )
    service, _, _ = _service(tmp_path, client)
    service.create_deposit_address(_request())

    with pytest.raises(
        funding_service.BridgeAdapterError,
        match="expected bridge transaction is unavailable",
    ):
        service.get_bridge_status(
            user_id=USER_ID,
            binding_id=BINDING_ID,
            venue_wallet_address=VENUE_WALLET,
            bridge_address=BRIDGE_ADDRESS,
            expected_amount_atomic="1000000",
            not_before_time_ms=NOT_BEFORE_TIME_MS,
            expected_bridge_tx_hash="0x" + "c" * 64,
        )
    assert len(client.calls) == 2


def test_status_rejects_bridge_hash_fallback_before_pagination_is_exhausted(
    tmp_path,
) -> None:
    client = FakeBridgeClient()
    client.status_response["transactions"][0]["txHash"] = "0x" + "b" * 64
    client.status_response["nextCursor"] = "next-page"
    service, _, _ = _service(tmp_path, client)
    service.create_deposit_address(_request())

    with pytest.raises(
        funding_service.BridgeAdapterError,
        match="expected bridge transaction is unavailable",
    ):
        service.get_bridge_status(
            user_id=USER_ID,
            binding_id=BINDING_ID,
            venue_wallet_address=VENUE_WALLET,
            bridge_address=BRIDGE_ADDRESS,
            expected_amount_atomic="1000000",
            not_before_time_ms=NOT_BEFORE_TIME_MS,
            expected_bridge_tx_hash=TX_HASH,
        )


@pytest.mark.parametrize(
    ("transaction_patch", "expected_error"),
    [
        ({"fromChainId": "1"}, "expected bridge transaction is unavailable"),
        ({"fromChainId": 137}, "polymarket bridge response is invalid"),
        ({"fromChainId": "0137"}, "polymarket bridge response is invalid"),
        (
            {"fromTokenAddress": "0x4444444444444444444444444444444444444444"},
            "expected bridge transaction is unavailable",
        ),
        ({"toChainId": "1"}, "expected bridge transaction is unavailable"),
        (
            {"toTokenAddress": "0x5555555555555555555555555555555555555555"},
            "expected bridge transaction is unavailable",
        ),
        ({"status": "UNKNOWN"}, "polymarket bridge response is invalid"),
        ({"fromAmountBaseUnit": "0"}, "polymarket bridge response is invalid"),
        ({"txHash": "0xshort"}, "polymarket bridge response is invalid"),
        ({"privateKey": "must-not-be-accepted"}, "polymarket bridge response is invalid"),
    ],
)
def test_status_rejects_unknown_chain_token_status_amount_hash_and_sensitive_fields(
    tmp_path, transaction_patch, expected_error
) -> None:
    client = FakeBridgeClient()
    client.status_response["transactions"][0].update(transaction_patch)
    service, _, repository = _service(tmp_path, client)
    service.create_deposit_address(_request())

    with pytest.raises(
        funding_service.BridgeAdapterError,
        match=expected_error,
    ):
        service.get_bridge_status(
            user_id=USER_ID,
            binding_id=BINDING_ID,
            venue_wallet_address=VENUE_WALLET,
            bridge_address=BRIDGE_ADDRESS,
            expected_amount_atomic="1000000",
            not_before_time_ms=NOT_BEFORE_TIME_MS,
        )
    assert repository.get_bridge_observation(
        user_id=USER_ID,
        binding_id=BINDING_ID,
        venue_wallet_address=VENUE_WALLET,
        bridge_address=BRIDGE_ADDRESS,
    ) is None


def test_status_accepts_the_official_bounded_page_of_fifty_transactions(tmp_path) -> None:
    client = FakeBridgeClient()
    client.status_response["transactions"] = [
        {
            "fromChainId": "137",
            "fromTokenAddress": SOURCE_TOKEN,
            "fromAmountBaseUnit": str(1_000_000 + index),
            "toChainId": "137",
            "toTokenAddress": DESTINATION_TOKEN,
            "status": "PROCESSING",
            "createdTimeMs": 1787121600000 - index,
        }
        for index in range(50)
    ]
    service, _, _ = _service(tmp_path, client)
    service.create_deposit_address(_request())

    status = service.get_bridge_status(
        user_id=USER_ID,
        binding_id=BINDING_ID,
        venue_wallet_address=VENUE_WALLET,
        bridge_address=BRIDGE_ADDRESS,
        expected_amount_atomic="1000000",
        not_before_time_ms=NOT_BEFORE_TIME_MS,
    )

    assert status.tx_hash is None
    assert status.amount_atomic == "1000000"


def test_postgres_connection_failure_is_fixed_and_redacted(monkeypatch) -> None:
    class FailedEngine:
        dialect = SimpleNamespace(name="postgresql")

        def connect(self):
            raise SQLAlchemyError("password=must-not-leak host=secret.example")

    monkeypatch.setattr(
        bridge_repository,
        "create_engine",
        lambda *_args, **_kwargs: FailedEngine(),
    )
    with pytest.raises(BridgeRepositoryError) as captured:
        bridge_repository.PostgresBridgeRepository(
            "postgresql+psycopg://clink:must-not-leak@secret.example/clink"
        )
    assert str(captured.value) == "bridge database migration failed"
    assert captured.value.__cause__ is None


def test_postgres_repository_live_contract_when_configured() -> None:
    postgres_url = os.getenv("TEST_PREDICTION_MARKETS_POSTGRES_URL")
    if not postgres_url:
        pytest.skip("TEST_PREDICTION_MARKETS_POSTGRES_URL is not configured")

    schema = f"clink_bridge_{uuid4().hex}"
    future_schema = f"clink_bridge_future_{uuid4().hex}"

    def scoped_url(name: str) -> str:
        return (
            make_url(postgres_url)
            .update_query_dict({"options": f"-csearch_path={name}"})
            .render_as_string(hide_password=False)
        )

    admin_engine = create_engine(postgres_url)
    repositories = []
    future_engine = None
    try:
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'CREATE SCHEMA "{future_schema}"'))

        repositories = [
            PostgresBridgeRepository(scoped_url(schema)),
            PostgresBridgeRepository(scoped_url(schema)),
        ]
        with repositories[0].engine.connect() as connection:
            assert {
                "polymarket_bridge_schema_version",
                "polymarket_bridge_deposit_claims",
                "polymarket_bridge_deposit_targets",
                "polymarket_bridge_observations",
            }.issubset(set(sa_inspect(connection).get_table_names()))

        with ThreadPoolExecutor(max_workers=2) as pool:
            targets = list(
                pool.map(
                    lambda repository: repository.save_deposit_target(_target()),
                    repositories,
                )
            )
        assert targets[0] == targets[1]

        with ThreadPoolExecutor(max_workers=2) as pool:
            observations = list(
                pool.map(
                    lambda repository: repository.save_bridge_observation(
                        _observation()
                    ),
                    repositories,
                )
            )
        assert observations[0] == observations[1]

        with ThreadPoolExecutor(max_workers=2) as pool:
            claims = list(
                pool.map(
                    lambda item: item[0].try_claim_deposit_creation(
                        user_id="telegram_claim_user",
                        binding_id="pm_claim_binding",
                        venue_wallet_address=VENUE_WALLET,
                        claim_token=f"pm_claim_{item[1]}",
                        claimed_at=NOW,
                        lease_expires_at=NOW + timedelta(seconds=30),
                    ),
                    zip(repositories, ("one", "two"), strict=True),
                )
            )
        assert sorted(claims) == ["acquired", "busy"]

        invalid_statements = [
            (
                """
                INSERT INTO polymarket_bridge_deposit_targets (
                    deposit_id, user_id, binding_id, venue_wallet_address,
                    bridge_address, source_network, source_token_address,
                    destination_network, destination_token_address, status, created_at
                ) VALUES (:deposit_id, :user_id, :binding_id, :wallet, :bridge,
                    'eip155:137', :source_token, 'eip155:137', :destination_token,
                    'ready', :created_at)
                """,
                {
                    "deposit_id": "pm_deposit_pg_nonhex",
                    "user_id": "telegram_pg_nonhex",
                    "binding_id": "pm_binding_pg_nonhex",
                    "wallet": "0x" + "g" * 40,
                    "bridge": BRIDGE_ADDRESS,
                    "source_token": SOURCE_TOKEN,
                    "destination_token": DESTINATION_TOKEN,
                    "created_at": NOW,
                },
            ),
            (
                """
                INSERT INTO polymarket_bridge_observations (
                    observation_id, user_id, binding_id, venue_wallet_address,
                    bridge_address, source_network, source_token_address,
                    destination_network, destination_token_address, status,
                    tx_hash, amount_atomic, checked_at, bridge_created_time_ms
                ) VALUES (:observation_id, :user_id, :binding_id, :wallet, :bridge,
                    'eip155:137', :source_token, 'eip155:137', :destination_token,
                    :status, :tx_hash, :amount, :checked_at, :created_time)
                """,
                {
                    "observation_id": "pm_observation_pg_nonhex",
                    "user_id": USER_ID,
                    "binding_id": BINDING_ID,
                    "wallet": VENUE_WALLET,
                    "bridge": BRIDGE_ADDRESS,
                    "source_token": SOURCE_TOKEN,
                    "destination_token": DESTINATION_TOKEN,
                    "status": "COMPLETED",
                    "tx_hash": "0x" + "g" * 64,
                    "amount": "1000000",
                    "checked_at": NOW,
                    "created_time": 1787121600000,
                },
            ),
            (
                """
                INSERT INTO polymarket_bridge_observations (
                    observation_id, user_id, binding_id, venue_wallet_address,
                    bridge_address, source_network, source_token_address,
                    destination_network, destination_token_address, status,
                    tx_hash, amount_atomic, checked_at, bridge_created_time_ms
                ) VALUES (:observation_id, :user_id, :binding_id, :wallet, :bridge,
                    'eip155:137', :source_token, 'eip155:137', :destination_token,
                    :status, NULL, :amount, :checked_at, :created_time)
                """,
                {
                    "observation_id": "pm_observation_pg_overflow",
                    "user_id": USER_ID,
                    "binding_id": BINDING_ID,
                    "wallet": VENUE_WALLET,
                    "bridge": BRIDGE_ADDRESS,
                    "source_token": SOURCE_TOKEN,
                    "destination_token": DESTINATION_TOKEN,
                    "status": "PROCESSING",
                    "amount": str(2**256),
                    "checked_at": NOW,
                    "created_time": 1787121600000,
                },
            ),
            (
                """
                INSERT INTO polymarket_bridge_observations (
                    observation_id, user_id, binding_id, venue_wallet_address,
                    bridge_address, source_network, source_token_address,
                    destination_network, destination_token_address, status,
                    tx_hash, amount_atomic, checked_at, bridge_created_time_ms
                ) VALUES (:observation_id, :user_id, :binding_id, :wallet, :bridge,
                    'eip155:137', :source_token, 'eip155:137', :destination_token,
                    :status, NULL, :amount, :checked_at, :created_time)
                """,
                {
                    "observation_id": "pm_observation_pg_wrong_scope",
                    "user_id": "telegram_wrong_scope",
                    "binding_id": BINDING_ID,
                    "wallet": VENUE_WALLET,
                    "bridge": BRIDGE_ADDRESS,
                    "source_token": SOURCE_TOKEN,
                    "destination_token": DESTINATION_TOKEN,
                    "status": "PROCESSING",
                    "amount": "1000000",
                    "checked_at": NOW,
                    "created_time": 1787121600000,
                },
            ),
        ]
        for statement, parameters in invalid_statements:
            with pytest.raises(SQLAlchemyError):
                with repositories[0].engine.begin() as connection:
                    connection.execute(text(statement), parameters)

        future_engine = create_engine(scoped_url(future_schema))
        with future_engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE polymarket_bridge_schema_version "
                    "(singleton INTEGER PRIMARY KEY, version INTEGER NOT NULL)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO polymarket_bridge_schema_version "
                    "(singleton, version) VALUES (1, :version)"
                ),
                {"version": BRIDGE_SCHEMA_VERSION + 1},
            )
        with pytest.raises(
            BridgeRepositoryError,
            match="bridge database schema is newer than this binary",
        ):
            PostgresBridgeRepository(scoped_url(future_schema))
        with future_engine.connect() as connection:
            assert set(sa_inspect(connection).get_table_names()) == {
                "polymarket_bridge_schema_version"
            }
            assert connection.scalar(
                text(
                    "SELECT version FROM polymarket_bridge_schema_version "
                    "WHERE singleton = 1"
                )
            ) == BRIDGE_SCHEMA_VERSION + 1
    finally:
        for repository in repositories:
            repository.engine.dispose()
        if future_engine is not None:
            future_engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            connection.execute(
                text(f'DROP SCHEMA IF EXISTS "{future_schema}" CASCADE')
            )
        admin_engine.dispose()


def test_repository_read_validation_failure_is_fixed_without_exception_chain(
    tmp_path, monkeypatch
) -> None:
    marker = "must-not-leak-poisoned-row"
    repository = SQLiteBridgeRepository(tmp_path / "bridge.sqlite3")
    repository.save_deposit_target(_target())

    def poisoned_target(_row):
        return PolymarketBridgeDeposit.model_validate(
            {**_target().model_dump(), "bridge_address": marker}
        )

    monkeypatch.setattr(repository, "_target_from_row", poisoned_target)
    with pytest.raises(BridgeRepositoryError) as captured:
        repository.get_deposit_target(
            user_id=USER_ID,
            binding_id=BINDING_ID,
            venue_wallet_address=VENUE_WALLET,
            bridge_address=BRIDGE_ADDRESS,
        )
    assert str(captured.value) == "bridge database read failed"
    assert marker not in repr(captured.value)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


@pytest.mark.parametrize(
    ("operation", "expected_message"),
    [
        ("create", "bridge target lookup failed"),
        ("status", "bridge target lookup failed"),
        ("target", "bridge target lookup failed"),
        ("observation", "bridge observation lookup failed"),
    ],
)
def test_service_repository_read_failures_are_fixed_and_redacted(
    tmp_path, operation, expected_message
) -> None:
    marker = "must-not-leak-repository-marker"

    class FailingRepository:
        def __getattribute__(self, name):
            if name.startswith("find_") or name.startswith("get_"):
                raise BridgeRepositoryError(marker)
            return object.__getattribute__(self, name)

    config = AppConfig(
        profile="personal",
        polymarket_bridge_database_path=str(tmp_path / "bridge.sqlite3"),
    )
    service = funding_service.PolymarketFundingAdapterService(
        config=config,
        bridge_client=FakeBridgeClient(),
        repository=FailingRepository(),
    )
    calls = {
        "create": lambda: service.create_deposit_address(_request()),
        "status": lambda: service.get_bridge_status(
            user_id=USER_ID,
            binding_id=BINDING_ID,
            venue_wallet_address=VENUE_WALLET,
            bridge_address=BRIDGE_ADDRESS,
            expected_amount_atomic="1000000",
            not_before_time_ms=NOT_BEFORE_TIME_MS,
        ),
        "target": lambda: service.get_deposit_target(
            user_id=USER_ID,
            binding_id=BINDING_ID,
            venue_wallet_address=VENUE_WALLET,
            bridge_address=BRIDGE_ADDRESS,
        ),
        "observation": lambda: service.get_bridge_observation(
            user_id=USER_ID,
            binding_id=BINDING_ID,
            venue_wallet_address=VENUE_WALLET,
            bridge_address=BRIDGE_ADDRESS,
        ),
    }

    with pytest.raises(funding_service.BridgeAdapterError) as captured:
        calls[operation]()
    assert str(captured.value) == expected_message
    assert marker not in repr(captured.value)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


class FakeHttpResponse:
    def __init__(self, *, status: int, body: bytes, content_type: str = "application/json") -> None:
        self.status = status
        self.body = BytesIO(body)
        self.headers = {
            "Content-Type": content_type,
            "Content-Length": str(len(body)),
        }

    def read(self, size: int = -1) -> bytes:
        return self.body.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None


class FakeOpener:
    def __init__(self, response=None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.requests = []

    def open(self, request, timeout: float):
        self.requests.append((request, timeout))
        if self.error is not None:
            raise self.error
        return self.response


@pytest.mark.parametrize(
    "base_url",
    [
        "http://bridge.example.invalid",
        "https://user@bridge.example.invalid",
        "https://bridge.example.invalid/api",
        "https://bridge.example.invalid?token=value",
        "https://bridge.example.invalid#fragment",
    ],
)
def test_http_transport_requires_a_clean_https_origin(base_url) -> None:
    with pytest.raises(
        ValueError, match="polymarket bridge base URL must be a clean HTTPS origin"
    ):
        funding_service.HttpBridgeClient(base_url)


@pytest.mark.parametrize(
    "response",
    [
        FakeHttpResponse(status=200, body=b"not-json", content_type="text/plain"),
        FakeHttpResponse(status=200, body=b'{"address":1,"address":2}'),
        FakeHttpResponse(status=200, body=b"{" + b"x" * 65537),
        FakeHttpResponse(status=202, body=b"{}"),
    ],
)
def test_http_transport_rejects_non_json_duplicate_oversized_and_unexpected_status(response) -> None:
    opener = FakeOpener(response=response)
    client = funding_service.HttpBridgeClient(
        "https://bridge.example.invalid", opener=opener
    )

    with pytest.raises(
        funding_service.BridgeTransportError,
        match="^polymarket bridge request failed$",
    ):
        client.get(f"/status/{BRIDGE_ADDRESS}?limit=50")


def test_http_transport_rejects_redirect_without_leaking_url_or_body() -> None:
    error = urllib.error.HTTPError(
        "https://bridge.example.invalid/secret?token=value",
        302,
        "redirect",
        {},
        BytesIO(b'{"secret":"do-not-leak"}'),
    )
    client = funding_service.HttpBridgeClient(
        "https://bridge.example.invalid", opener=FakeOpener(error=error)
    )

    with pytest.raises(funding_service.BridgeTransportError) as captured:
        client.get(f"/status/{BRIDGE_ADDRESS}?limit=50")
    rendered = str(captured.value)
    assert rendered == "polymarket bridge request failed"
    assert "secret" not in rendered
    assert "token" not in rendered
    assert "bridge.example" not in rendered
    assert captured.value.__cause__ is None


def test_http_transport_rejects_sensitive_fields_before_service_parsing() -> None:
    response = FakeHttpResponse(
        status=200,
        body=b'{"address":{"evm":"0x2222222222222222222222222222222222222222"},"secret":"do-not-store"}',
    )
    client = funding_service.HttpBridgeClient(
        "https://bridge.example.invalid", opener=FakeOpener(response=response)
    )

    with pytest.raises(
        funding_service.BridgeTransportError,
        match="^polymarket bridge request failed$",
    ):
        client.get(f"/status/{BRIDGE_ADDRESS}?limit=50")


def test_http_transport_sends_a_stable_clink_user_agent_for_get_and_post() -> None:
    response = FakeHttpResponse(status=200, body=b"{}")
    opener = FakeOpener(response=response)
    client = funding_service.HttpBridgeClient(
        "https://bridge.example.invalid", opener=opener
    )

    client.get(f"/status/{BRIDGE_ADDRESS}?limit=50")
    response.body = BytesIO(b"{}")
    response.status = 201
    client.post("/deposit", {"address": VENUE_WALLET})

    assert [request.get_header("User-agent") for request, _ in opener.requests] == [
        "ClinkPredictionMarkets/1.0",
        "ClinkPredictionMarkets/1.0",
    ]


def test_internal_bearer_runs_before_body_parsing_and_global_latest_is_absent(tmp_path) -> None:
    service, config, _ = _service(tmp_path)
    app = funding_app.create_app(config=config, service=service)
    client = TestClient(app)

    assert client.get("/healthz").status_code == 200
    unauthenticated = client.post(
        "/polymarket/deposit-address",
        content=b"{not-json",
        headers={"Content-Type": "application/json"},
    )
    assert unauthenticated.status_code == 401
    assert unauthenticated.json() == {"detail": "invalid internal bearer token"}

    duplicate = client.post(
        "/polymarket/deposit-address",
        content=b"{not-json",
        headers=[
            ("Content-Type", "application/json"),
            ("Authorization", f"Bearer {config.prediction_markets_internal_api_token}"),
            ("Authorization", f"Bearer {config.prediction_markets_internal_api_token}"),
        ],
    )
    assert duplicate.status_code == 401

    malformed = client.post(
        "/polymarket/deposit-address",
        content=b"{not-json",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer  {config.prediction_markets_internal_api_token}",
        },
    )
    assert malformed.status_code == 401

    authorized = client.post(
        "/polymarket/deposit-address",
        json={
            "user_id": USER_ID,
            "binding_id": BINDING_ID,
            "venue_wallet_address": VENUE_WALLET,
        },
        headers={
            "Authorization": f"Bearer {config.prediction_markets_internal_api_token}"
        },
    )
    assert authorized.status_code == 201
    payload = authorized.json()
    assert payload["user_id"] == USER_ID
    assert "raw_response" not in payload

    assert (
        client.get(
            "/polymarket/latest-bridge-status",
            headers={
                "Authorization": f"Bearer {config.prediction_markets_internal_api_token}"
            },
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/polymarket/bridge-quote",
            json={},
            headers={
                "Authorization": f"Bearer {config.prediction_markets_internal_api_token}"
            },
        ).status_code
        == 404
    )


def test_scoped_status_route_requires_all_context_and_expected_hash(tmp_path) -> None:
    service, config, _ = _service(tmp_path)
    app = funding_app.create_app(config=config, service=service)
    client = TestClient(app)
    headers = {
        "Authorization": f"Bearer {config.prediction_markets_internal_api_token}"
    }
    created = client.post(
        "/polymarket/deposit-address",
        json={
            "user_id": USER_ID,
            "binding_id": BINDING_ID,
            "venue_wallet_address": VENUE_WALLET,
        },
        headers=headers,
    )
    assert created.status_code == 201

    missing_scope = client.get(
        f"/polymarket/bridge-status/{BRIDGE_ADDRESS}", headers=headers
    )
    assert missing_scope.status_code == 422
    observed = client.get(
        f"/polymarket/bridge-status/{BRIDGE_ADDRESS}",
        params={
            "user_id": USER_ID,
            "binding_id": BINDING_ID,
            "venue_wallet_address": VENUE_WALLET,
            "expected_amount_atomic": "1000000",
            "not_before_time_ms": NOT_BEFORE_TIME_MS,
            "expected_bridge_tx_hash": TX_HASH,
        },
        headers=headers,
    )
    assert observed.status_code == 200
    assert observed.json()["tx_hash"] == TX_HASH
