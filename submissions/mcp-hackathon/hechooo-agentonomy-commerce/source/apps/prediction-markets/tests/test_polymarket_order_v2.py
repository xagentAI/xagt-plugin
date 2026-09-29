from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

import platforms.polymarket.order_v2 as order_v2_module

from platforms.polymarket.order_v2 import (
    NEG_RISK_EXCHANGE,
    ORDER_TYPE_STRING,
    ORDER_FIELDS,
    STANDARD_EXCHANGE,
    OrderProjectionError,
    build_order_projection,
    validate_signed_order,
)
from services.execution_service.repository import (
    OrderSigningSessionRepositoryError,
    SQLiteOrderSigningSessionRepository,
    build_order_signing_session_repository,
)
from services.execution_service.service import ExecutionService
from shared.config import AppConfig
from shared.schemas import (
    CompletePolymarketOrderSigningSessionRequest,
    CreatePolymarketOrderSigningSessionRequest,
    PolymarketOrderSigningSession,
    PredictionMarketOrderPreview,
    UnifiedMarket,
)


FIXTURE = Path(__file__).parent / "fixtures" / "polymarket_clob_v2_official_vectors.json"
REQUIREMENTS = Path(__file__).parents[1] / "requirements.txt"


def _repository_session(**updates) -> PolymarketOrderSigningSession:
    values = {
        "session_id": "pm_sign_sess_repo",
        "preview_id": "preview-1",
        "user_id": "user-1",
        "binding_id": "binding-1",
        "projection_hash": "ab" * 32,
        "status": "pending_browser_signature",
        "reason": None,
        "next_action": "open_polymarket_order_signing_url",
        "order_payload": {"projection_sha256": "ab" * 32},
        "created_at": "2026-08-20T00:00:00Z",
        "expires_at": "2026-08-20T00:10:00Z",
        "revision": 0,
        "metadata": {
            "polymarket_account_binding": {"binding_id": "binding-1"}
        },
    }
    values.update(updates)
    return PolymarketOrderSigningSession(**values)


def test_sqlite_order_signing_repository_creates_and_reads_authoritative_record(
    tmp_path: Path,
) -> None:
    repository = SQLiteOrderSigningSessionRepository(tmp_path / "sessions.sqlite3")
    created = repository.create(_repository_session())

    loaded = SQLiteOrderSigningSessionRepository(
        tmp_path / "sessions.sqlite3"
    ).get(created.session_id)

    assert loaded == created
    assert loaded is not None
    assert loaded.binding_id == "binding-1"
    assert loaded.projection_hash == "ab" * 32
    assert loaded.revision == 0


def test_sqlite_order_signing_repository_rejects_duplicate_session_id(
    tmp_path: Path,
) -> None:
    repository = SQLiteOrderSigningSessionRepository(tmp_path / "sessions.sqlite3")
    repository.create(_repository_session())

    with pytest.raises(
        OrderSigningSessionRepositoryError,
        match="order signing session already exists",
    ):
        repository.create(_repository_session(user_id="different-user"))


def test_order_signing_repository_claim_has_exactly_one_winner(tmp_path: Path) -> None:
    repository = SQLiteOrderSigningSessionRepository(tmp_path / "sessions.sqlite3")
    pending = repository.create(_repository_session())
    submitting = pending.model_copy(update={"status": "submitting"})

    winner = repository.claim_for_submission(
        session_id=pending.session_id,
        expected_revision=pending.revision,
        replacement=submitting,
    )
    loser = repository.claim_for_submission(
        session_id=pending.session_id,
        expected_revision=pending.revision,
        replacement=submitting,
    )

    assert winner is not None
    assert winner.status == "submitting"
    assert winner.revision == 1
    assert loser is None


def test_order_signing_repository_claim_never_accepts_non_pending_status(
    tmp_path: Path,
) -> None:
    repository = SQLiteOrderSigningSessionRepository(tmp_path / "sessions.sqlite3")
    blocked = repository.create(_repository_session(status="blocked"))

    assert repository.claim_for_submission(
        session_id=blocked.session_id,
        expected_revision=blocked.revision,
        replacement=blocked.model_copy(update={"status": "submitting"}),
    ) is None
    assert repository.get(blocked.session_id) == blocked


def test_claimed_order_signing_session_stays_submitting_after_repository_restart(
    tmp_path: Path,
) -> None:
    path = tmp_path / "sessions.sqlite3"
    repository = SQLiteOrderSigningSessionRepository(path)
    pending = repository.create(_repository_session())
    claimed = repository.claim_for_submission(
        session_id=pending.session_id,
        expected_revision=pending.revision,
        replacement=pending.model_copy(update={"status": "submitting"}),
    )

    assert claimed is not None
    restarted = SQLiteOrderSigningSessionRepository(path)
    assert restarted.get(pending.session_id) == claimed
    assert restarted.claim_for_submission(
        session_id=pending.session_id,
        expected_revision=claimed.revision,
        replacement=claimed,
    ) is None


def test_order_signing_repository_rejects_future_schema_version_without_leaking_path(
    tmp_path: Path,
) -> None:
    path = tmp_path / "secret-marker.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE polymarket_order_signing_schema_version "
            "(singleton INTEGER PRIMARY KEY, version INTEGER NOT NULL)"
        )
        connection.execute(
            "INSERT INTO polymarket_order_signing_schema_version VALUES (1, 999)"
        )

    with pytest.raises(OrderSigningSessionRepositoryError) as caught:
        SQLiteOrderSigningSessionRepository(path)

    assert str(caught.value) == (
        "order signing session database schema is newer than this binary"
    )
    assert "secret-marker" not in str(caught.value)


def test_order_signing_repository_rejects_immutable_identity_drift_on_claim(
    tmp_path: Path,
) -> None:
    repository = SQLiteOrderSigningSessionRepository(tmp_path / "sessions.sqlite3")
    pending = repository.create(_repository_session())

    with pytest.raises(
        OrderSigningSessionRepositoryError,
        match="order signing session immutable fields changed",
    ):
        repository.claim_for_submission(
            session_id=pending.session_id,
            expected_revision=pending.revision,
            replacement=pending.model_copy(
                update={"status": "submitting", "binding_id": "binding-drift"}
            ),
        )


def test_concurrent_sqlite_claims_still_have_only_one_winner(tmp_path: Path) -> None:
    path = tmp_path / "sessions.sqlite3"
    repository = SQLiteOrderSigningSessionRepository(path)
    pending = repository.create(_repository_session())

    def claim_once(_index: int):
        contender = SQLiteOrderSigningSessionRepository(path)
        return contender.claim_for_submission(
            session_id=pending.session_id,
            expected_revision=pending.revision,
            replacement=pending.model_copy(update={"status": "submitting"}),
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(claim_once, range(8)))

    winners = [result for result in results if result is not None]
    assert len(winners) == 1
    assert repository.get(pending.session_id) == winners[0]


def test_terminal_compare_update_has_one_submitting_winner(tmp_path: Path) -> None:
    repository = SQLiteOrderSigningSessionRepository(tmp_path / "sessions.sqlite3")
    pending = repository.create(_repository_session())
    submitting = repository.claim_for_submission(
        session_id=pending.session_id,
        expected_revision=pending.revision,
        replacement=pending.model_copy(update={"status": "submitting"}),
    )
    assert submitting is not None
    submitted = submitting.model_copy(
        update={"status": "submitted", "execution_id": "execution-1"}
    )

    winner = repository.compare_and_set_terminal(
        session_id=submitting.session_id,
        expected_revision=submitting.revision,
        replacement=submitted,
    )
    loser = repository.compare_and_set_terminal(
        session_id=submitting.session_id,
        expected_revision=submitting.revision,
        replacement=submitted,
    )

    assert winner is not None
    assert winner.status == "submitted"
    assert winner.revision == 2
    assert loser is None


def test_terminal_compare_update_never_skips_submission_claim(tmp_path: Path) -> None:
    repository = SQLiteOrderSigningSessionRepository(tmp_path / "sessions.sqlite3")
    pending = repository.create(_repository_session())

    assert repository.compare_and_set_terminal(
        session_id=pending.session_id,
        expected_revision=pending.revision,
        replacement=pending.model_copy(update={"status": "submitted"}),
    ) is None
    assert repository.get(pending.session_id) == pending


def test_personal_repository_factory_derives_sqlite_from_legacy_filename(
    tmp_path: Path,
) -> None:
    legacy_path = tmp_path / "sessions.jsonl"
    legacy_path.write_text('{"must":"not be read"}\n', encoding="utf-8")
    repository = build_order_signing_session_repository(
        AppConfig(order_signing_session_file=str(legacy_path))
    )

    assert isinstance(repository, SQLiteOrderSigningSessionRepository)
    assert Path(repository.engine.url.database or "") == legacy_path.with_suffix(
        ".sqlite3"
    )
    assert repository.get("must-not-exist") is None


def test_server_repository_factory_uses_only_postgres_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.execution_service.repository as repository_module

    observed: list[str] = []

    class FakePostgresRepository:
        def __init__(self, database_url: str) -> None:
            observed.append(database_url)

    monkeypatch.setattr(
        repository_module,
        "PostgresOrderSigningSessionRepository",
        FakePostgresRepository,
    )
    config = SimpleNamespace(
        profile="server",
        prediction_markets_database_url="postgresql+psycopg://db/order-signing",
        order_signing_session_file="must-not-be-used.jsonl",
    )

    repository = build_order_signing_session_repository(config)

    assert isinstance(repository, FakePostgresRepository)
    assert observed == ["postgresql+psycopg://db/order-signing"]


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["vector"]


def _inputs(**updates) -> dict:
    values = copy.deepcopy(_fixture()["inputs"])
    values.update(updates)
    return values


def test_official_deposit_wallet_vector_matches_exact_projection() -> None:
    vector = _fixture()
    projection = build_order_projection(**vector["inputs"])
    assert projection.payload == vector["expected_projection"]
    assert projection.projection_sha256 == vector["projection_sha256"]


def test_v2_order_fields_are_exact_and_ordered() -> None:
    assert ORDER_FIELDS == (
        ("salt", "uint256"),
        ("maker", "address"),
        ("signer", "address"),
        ("tokenId", "uint256"),
        ("makerAmount", "uint256"),
        ("takerAmount", "uint256"),
        ("side", "uint8"),
        ("signatureType", "uint8"),
        ("timestamp", "uint256"),
        ("metadata", "bytes32"),
        ("builder", "bytes32"),
    )


@pytest.mark.parametrize(
    ("mode", "maker", "core_signer", "order_signer", "signature_type"),
    [
        ("deposit_wallet", "0x" + "11" * 20, "0x" + "22" * 20, "0x" + "11" * 20, 3),
        ("proxy", "0x" + "22" * 20, "0x" + "33" * 20, "0x" + "33" * 20, 1),
        ("safe", "0x" + "44" * 20, "0x" + "55" * 20, "0x" + "55" * 20, 2),
        ("eoa", "0x" + "66" * 20, "0x" + "66" * 20, "0x" + "66" * 20, 0),
    ],
)
def test_wallet_mode_locks_maker_signer_and_signature_type(
    mode: str, maker: str, core_signer: str, order_signer: str, signature_type: int
) -> None:
    projection = build_order_projection(
        **_inputs(wallet_mode=mode, maker_wallet=maker, account_signer=core_signer)
    )
    order = projection.payload["order"]
    assert (order["maker"], order["signer"], order["signatureType"]) == (
        maker,
        order_signer,
        signature_type,
    )
    assert projection.payload["typed_data"]["primaryType"] == (
        "TypedDataSign" if mode == "deposit_wallet" else "Order"
    )


def test_neg_risk_selects_only_the_neg_risk_exchange() -> None:
    assert build_order_projection(**_inputs(neg_risk=False)).payload["exchange"] == STANDARD_EXCHANGE
    assert build_order_projection(**_inputs(neg_risk=True)).payload["exchange"] == NEG_RISK_EXCHANGE


@pytest.mark.parametrize(
    ("side", "maker", "taker"),
    [("BUY", "5200000", "10000000"), ("SELL", "10000000", "5200000")],
)
def test_amounts_use_exact_six_decimal_atomic_values(side: str, maker: str, taker: str) -> None:
    order = build_order_projection(**_inputs(side=side)).payload["order"]
    assert (order["makerAmount"], order["takerAmount"]) == (maker, taker)


@pytest.mark.parametrize("tick_size", ["0.1", "0.01", "0.005", "0.0025", "0.001", "0.0001"])
def test_all_official_tick_sizes_are_supported(tick_size: str) -> None:
    projection = build_order_projection(**_inputs(tick_size=tick_size, price=tick_size, size="5.019"))
    assert projection.payload["tickSize"] == tick_size
    assert int(projection.payload["order"]["makerAmount"]) > 0


@pytest.mark.parametrize(
    "updates",
    [
        {"price": "0.521", "tick_size": "0.01"},
        {"size": "4.99", "min_order_size": "5"},
        {"salt": "9007199254740992"},
        {"timestamp_ms": "0"},
        {"wallet_mode": "proxy", "maker_wallet": "0x" + "11" * 20, "account_signer": "0x" + "11" * 20},
    ],
)
def test_invalid_market_or_wallet_context_is_rejected(updates: dict) -> None:
    with pytest.raises(OrderProjectionError):
        build_order_projection(**_inputs(**updates))


def test_gtc_and_gtd_expiration_are_envelope_only() -> None:
    gtc = build_order_projection(**_inputs())
    gtd = build_order_projection(**_inputs(order_type="GTD", expiration="1787187600"))
    assert gtc.payload["order"]["expiration"] == "0"
    assert gtd.payload["order"]["expiration"] == "1787187600"
    assert "expiration" not in gtd.payload["typed_data"]["message"]["contents"]


@pytest.mark.parametrize("removed", ["taker", "nonce", "feeRateBps"])
def test_removed_v1_fields_are_rejected_on_completion(removed: str) -> None:
    projection = build_order_projection(**_inputs(wallet_mode="eoa"))
    submitted = copy.deepcopy(projection.payload["order"])
    submitted["signature"] = "0x" + "ab" * 65
    submitted[removed] = "0"
    with pytest.raises(OrderProjectionError):
        validate_signed_order(projection, {"order": submitted, "orderType": "GTC"})


def test_full_field_drift_is_rejected() -> None:
    projection = build_order_projection(**_inputs(wallet_mode="eoa"))
    submitted = copy.deepcopy(projection.payload["order"])
    submitted["signature"] = "0x" + "ab" * 65
    submitted["makerAmount"] = "5200001"
    with pytest.raises(OrderProjectionError, match="signed order does not match projection"):
        validate_signed_order(projection, {"order": submitted, "orderType": "GTC"})


def test_exact_signed_order_is_accepted_without_storing_signature_in_projection() -> None:
    projection = build_order_projection(**_inputs(wallet_mode="eoa"))
    submitted = copy.deepcopy(projection.payload["order"])
    submitted["signature"] = "0x" + "ab" * 65
    validated = validate_signed_order(projection, {"order": submitted, "orderType": "GTC"})
    assert validated["order"]["signature"] == submitted["signature"]
    assert "signature" not in projection.payload["order"]


def test_python_clob_v2_wire_contract_is_exactly_pinned() -> None:
    lines = REQUIREMENTS.read_text(encoding="utf-8").splitlines()
    assert "py-clob-client-v2==1.1.0" in lines
    assert not any(line.startswith("py-clob-client-v2>=") for line in lines)


def test_deposit_wallet_accepts_only_the_erc7739_wrapped_signature_shape() -> None:
    projection = build_order_projection(**_inputs())
    submitted = copy.deepcopy(projection.payload["order"])
    wrapped_bytes = 65 + 32 + 32 + len(ORDER_TYPE_STRING.encode("utf-8")) + 2
    submitted["signature"] = "0x" + "ab" * wrapped_bytes
    assert validate_signed_order(
        projection, {"order": submitted, "orderType": "GTC"}
    )["order"]["signature"] == submitted["signature"]

    submitted["signature"] = "0x" + "ab" * 65
    with pytest.raises(OrderProjectionError, match="signature is invalid"):
        validate_signed_order(projection, {"order": submitted, "orderType": "GTC"})


def _preview() -> PredictionMarketOrderPreview:
    market = UnifiedMarket(
        platform="polymarket",
        market_id="market-1",
        title="Will the test pass?",
        yes_price=0.52,
        no_price=0.48,
        tradable=True,
        execution_ready=True,
        raw={
            "clobTokenIds": '["102936", "102937"]',
            "outcomes": '["Yes", "No"]',
            "tick_size": "0.01",
            "min_order_size": "5",
            "neg_risk": False,
        },
    )
    return PredictionMarketOrderPreview(
        preview_id="preview-1",
        user_id="user-1",
        agent_id="agentonomy",
        platform="polymarket",
        market_id="market-1",
        title=market.title,
        outcome="Yes",
        side="buy",
        amount_usd="5.20",
        limit_price=0.52,
        estimated_contracts=10,
        max_slippage_bps=0,
        max_slippage_usd="0",
        worst_case_price=0.52,
        state="confirmation_required",
        next_action="request_user_confirmation",
        live_mode=True,
        core_action_id="action-1",
        core_policy_decision_id="policy-1",
        market=market,
        metadata={"funding_operation_id": "funding-1"},
        created_at="2026-08-20T00:00:00Z",
        expires_at="2026-08-21T00:00:00Z",
    )


def test_execution_service_builds_only_the_canonical_v2_projection() -> None:
    service = object.__new__(ExecutionService)
    payload = service._polymarket_order_payload(
        _preview(),
        "102936",
        "GTC",
        {
            "polymarket_account_binding": {
                "account_mode": "eoa",
                "funder_address": "0x" + "22" * 20,
                "wallet_address": "0x" + "22" * 20,
                "polymarket_signature_type": "0",
            },
            "order_projection_provenance": {
                "core_action_id": "action-new",
                "core_policy_decision_id": "policy-new",
                "funding_operation_id": "funding-1",
            },
        },
        session_id="pm_sign_sess_test",
        now=datetime(2026, 8, 20, tzinfo=UTC),
    )

    assert payload["typed_data"]["primaryType"] == "Order"
    assert payload["order"]["makerAmount"] == "5200000"
    assert payload["order"]["takerAmount"] == "10000000"
    assert payload["orderType"] == "GTC"
    assert payload["provenance"] == {
        "preview_id": "preview-1",
        "market_id": "market-1",
        "core_action_id": "action-new",
        "core_policy_decision_id": "policy-new",
        "funding_operation_id": "funding-1",
    }
    assert "projection_sha256" in payload
    encoded = json.dumps(payload)
    assert all(removed not in encoded for removed in ('"taker"', '"nonce"', '"feeRateBps"'))
    assert not any(isinstance(value, float) for value in payload["order"].values())


def test_browser_signing_session_uses_supported_gtc_envelope() -> None:
    service = object.__new__(ExecutionService)
    observed: list[str] = []

    def build_payload(_preview, _token, order_type, _metadata, **_kwargs):
        observed.append(order_type)
        return {"orderType": order_type}

    service._polymarket_order_payload = build_payload
    service._polymarket_order_signing_url = lambda _session_id: "/order-signing/"
    session = service._build_signing_session(
        CreatePolymarketOrderSigningSessionRequest(
            preview_id="preview-1",
            user_confirmed=True,
            live_submission_confirmed=True,
        ),
        _preview(),
        datetime(2026, 8, 20, tzinfo=UTC),
        "pending_browser_signature",
        None,
        "open_polymarket_order_signing_url",
        token_id="102936",
    )
    assert observed == ["GTC"]
    assert session.order_type == "GTC"


def test_execution_completion_rejects_any_v2_projection_field_drift() -> None:
    service = object.__new__(ExecutionService)
    payload = service._polymarket_order_payload(
        _preview(),
        "102936",
        "GTC",
        {
            "polymarket_account_binding": {
                "account_mode": "eoa",
                "funder_address": "0x" + "22" * 20,
                "wallet_address": "0x" + "22" * 20,
                "polymarket_signature_type": "0",
            }
        },
        session_id="pm_sign_sess_test",
        now=datetime(2026, 8, 20, tzinfo=UTC),
    )
    signed_order = copy.deepcopy(payload["order"])
    signed_order["signature"] = "0x" + "ab" * 65
    signed_order["timestamp"] = str(int(signed_order["timestamp"]) + 1)
    session = SimpleNamespace(
        order_type="GTC",
        token_id="102936",
        side="buy",
        metadata={
            "polymarket_account_binding": {
                "funder_address": "0x" + "22" * 20,
                "wallet_address": "0x" + "22" * 20,
                "polymarket_signature_type": "0",
            }
        },
        order_payload=payload,
    )
    request = CompletePolymarketOrderSigningSessionRequest(
        signed_order={"order": signed_order, "orderType": "GTC"},
        order_type="GTC",
    )
    assert service._signed_order_mismatch_reason(session, request) == (
        "signed order does not match the immutable V2 projection"
    )


def test_browser_capability_is_stored_only_as_sha256_and_resolves_by_exact_origin(
    tmp_path: Path,
) -> None:
    path = tmp_path / "sessions.sqlite3"
    repository = SQLiteOrderSigningSessionRepository(path)
    raw_token = "browser-capability-token-with-256-bits-of-entropy"
    capability_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    session = _repository_session()

    repository.create(
        session,
        capability_hash=capability_hash,
        capability_origin="https://clink.example",
    )

    authorized = repository.get_by_capability(
        capability_hash=capability_hash,
        origin="https://clink.example",
    )
    assert authorized == session
    assert repository.get_by_capability(
        capability_hash=capability_hash,
        origin="https://evil.example",
    ) is None
    with sqlite3.connect(path) as connection:
        row = connection.execute(
            "SELECT capability_hash, capability_origin, record_json "
            "FROM polymarket_order_signing_sessions WHERE session_id = ?",
            (session.session_id,),
        ).fetchone()
    assert row is not None
    assert row[0] == capability_hash
    assert row[1] == "https://clink.example"
    assert raw_token not in "".join(str(value) for value in row)


def test_browser_capability_survives_submission_claim_without_raw_token(
    tmp_path: Path,
) -> None:
    repository = SQLiteOrderSigningSessionRepository(tmp_path / "sessions.sqlite3")
    token_hash = hashlib.sha256(b"one-time-token").hexdigest()
    pending = repository.create(
        _repository_session(),
        capability_hash=token_hash,
        capability_origin="https://clink.example",
    )
    claimed = repository.claim_for_submission(
        session_id=pending.session_id,
        expected_revision=0,
        replacement=pending.model_copy(update={"status": "submitting"}),
    )

    assert claimed is not None
    assert repository.get_by_capability(
        capability_hash=token_hash,
        origin="https://clink.example",
    ) == claimed


def test_service_returns_browser_capability_once_in_fragment_and_never_persists_it() -> None:
    captured: dict = {}

    class CapturingRepository:
        def create(self, session, **capability):
            captured["session"] = session
            captured.update(capability)
            return session

    service = object.__new__(ExecutionService)
    service.config = SimpleNamespace(
        execution_console_base_url="https://clink.example/execution"
    )
    service.order_signing_session_repository = CapturingRepository()
    pending = _repository_session(signing_url=None)

    response = service._save_order_signing_session(pending)

    parsed = urlsplit(response.signing_url)
    assert parsed.scheme == "https"
    assert parsed.netloc == "clink.example"
    assert parsed.path.endswith("/execution/polymarket/order-signing-console/")
    assert parsed.query == ""
    assert parsed.fragment.startswith("access_token=")
    raw_token = parsed.fragment.removeprefix("access_token=")
    assert len(raw_token) >= 43
    assert captured["capability_hash"] == hashlib.sha256(
        raw_token.encode("utf-8")
    ).hexdigest()
    assert captured["capability_origin"] == "https://clink.example"
    assert captured["session"].signing_url is None
    assert raw_token not in captured["session"].model_dump_json()


def test_deposit_wallet_raw_signature_wraps_to_official_erc7739_shape() -> None:
    projection = build_order_projection(**_inputs())
    raw_signature = "0x" + "ab" * 65

    wrapped = order_v2_module.wrap_deposit_wallet_signature(
        raw_signature=raw_signature,
        typed_data=projection.payload["typed_data"],
    )

    assert wrapped == (
        "0x" + "ab" * 65
        + "3264e159346253e26a64e00b69032db0e7d32f94628de3e6eecb50304d7af3d2"
        + "a93eff65aa806653f335e1a463afcc9b1633b2a409a61459e02cb19908d9fcf7"
        + ORDER_TYPE_STRING.encode("utf-8").hex()
        + len(ORDER_TYPE_STRING.encode("utf-8")).to_bytes(2, "big").hex()
    )
    submitted = copy.deepcopy(projection.payload["order"])
    submitted["signature"] = wrapped
    assert validate_signed_order(
        projection, {"order": submitted, "orderType": "GTC"}
    )["order"]["signature"] == wrapped


def test_deposit_wallet_order_signer_is_funder_not_bound_eoa() -> None:
    maker = "0x" + "11" * 20
    signer = "0x" + "22" * 20
    projection = build_order_projection(
        **_inputs(
            wallet_mode="deposit_wallet",
            maker_wallet=maker,
            account_signer=signer,
        )
    )

    assert projection.payload["order"]["maker"] == maker
    assert projection.payload["order"]["signer"] == maker
    assert projection.payload["order"]["signatureType"] == 3
    assert projection.payload["typed_data"]["message"]["contents"]["signer"] == maker
    assert projection.payload["typed_data"]["message"]["verifyingContract"] == maker


def test_deposit_wallet_bound_eoa_erc7739_golden_vector(monkeypatch) -> None:
    import py_clob_client_v2.order_utils.exchange_order_builder_v2 as sdk_module
    from py_clob_client_v2.order_builder.builder import OrderBuilder as SdkOrderBuilder
    from py_clob_client_v2.order_utils import (
        ExchangeOrderBuilderV2,
        OrderDataV2,
        Side,
        SignatureTypeV2,
    )

    maker = "0x" + "11" * 20
    core_eoa = "0x" + "22" * 20
    projection = build_order_projection(
        **_inputs(
            wallet_mode="deposit_wallet",
            maker_wallet=maker,
            account_signer=core_eoa,
        )
    )
    raw_signature = "0x" + "ab" * 65
    wrapped = order_v2_module.wrap_deposit_wallet_signature(
        raw_signature=raw_signature,
        typed_data=projection.payload["typed_data"],
    )

    class FixtureSigner:
        private_key = object()

        def address(self) -> str:
            return core_eoa

    resolver = SdkOrderBuilder(
        FixtureSigner(), SignatureTypeV2.POLY_1271, funder=maker
    )
    assert resolver._v2_order_signer() == maker
    expected = projection.payload["order"]
    sdk_builder = ExchangeOrderBuilderV2(
        projection.payload["exchange"],
        137,
        FixtureSigner(),
        generate_salt=lambda: int(expected["salt"]),
    )
    sdk_order = sdk_builder.build_order(
        OrderDataV2(
            maker=maker,
            signer=resolver._v2_order_signer(),
            tokenId=expected["tokenId"],
            makerAmount=expected["makerAmount"],
            takerAmount=expected["takerAmount"],
            side=Side.BUY,
            signatureType=SignatureTypeV2.POLY_1271,
            timestamp=expected["timestamp"],
            metadata=expected["metadata"],
            builder=expected["builder"],
            expiration=expected["expiration"],
        )
    )
    sdk_typed_data = sdk_builder.build_order_typed_data(sdk_order)
    contents = projection.payload["typed_data"]["message"]["contents"]
    assert sdk_order.maker == sdk_order.signer == contents["maker"] == contents["signer"]
    assert sdk_typed_data["types"]["Order"] == projection.payload["typed_data"]["types"]["Order"]
    for field, _field_type in ORDER_FIELDS:
        sdk_value = sdk_typed_data["message"][field]
        if isinstance(sdk_value, bytes):
            sdk_value = "0x" + sdk_value.hex()
        assert str(sdk_value) == str(contents[field])
    monkeypatch.setattr(
        sdk_module.Account,
        "_sign_hash",
        lambda _digest, private_key: SimpleNamespace(signature=bytes.fromhex("ab" * 65)),
    )
    assert sdk_builder.build_order_signature(sdk_typed_data) == wrapped

    assert wrapped == (
        raw_signature
        + "3264e159346253e26a64e00b69032db0e7d32f94628de3e6eecb50304d7af3d2"
        + "a93eff65aa806653f335e1a463afcc9b1633b2a409a61459e02cb19908d9fcf7"
        + ORDER_TYPE_STRING.encode("utf-8").hex()
        + "00ba"
    )


def test_non_deposit_wallet_signatures_are_never_wrapped() -> None:
    raw_signature = "0x" + "ab" * 65
    for mode in ("eoa", "proxy", "safe"):
        projection = build_order_projection(
            **_inputs(
                wallet_mode=mode,
                maker_wallet="0x" + "22" * 20,
                account_signer=(
                    "0x" + "22" * 20 if mode == "eoa" else "0x" + "33" * 20
                ),
            )
        )
        assert order_v2_module.wrap_deposit_wallet_signature(
            raw_signature=raw_signature,
            typed_data=projection.payload["typed_data"],
            signature_type=projection.payload["order"]["signatureType"],
        ) == raw_signature


def test_order_signing_http_shell_and_capability_contract(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient
    from services.execution_service.app import create_app

    token = "browser-capability"
    origin = "https://clink.example"

    class FakeService:
        def create_polymarket_order_signing_session(self, _request):
            return _repository_session(
                signing_url=f"{origin}/execution/polymarket/order-signing-console/#access_token={token}"
            )

        def get_polymarket_order_signing_session_by_capability(
            self, *, access_token: str, origin: str, status_only: bool = False
        ):
            assert access_token == token
            assert origin == "https://clink.example"
            session = _repository_session(signing_url=None)
            return (
                {"session_id": session.session_id, "status": session.status}
                if status_only
                else session.model_dump()
            )

        def complete_polymarket_order_signing_session_by_capability(
            self, *, access_token: str, origin: str, request
        ):
            if access_token != token:
                import services.execution_service.service as service_module

                error_type = getattr(
                    service_module,
                    "OrderSigningCapabilityError",
                    RuntimeError,
                )
                raise error_type("raw capability details must not escape")
            assert origin == "https://clink.example"
            if (request.signed_order.get("order") or {}).get("reject"):
                import services.execution_service.service as service_module

                error_type = getattr(
                    service_module,
                    "OrderSigningPayloadError",
                    RuntimeError,
                )
                raise error_type("upstream payload details must not escape")
            return _repository_session(
                signing_url=None,
                status="submitted",
                revision=2,
                signed_order={"signature": "must-not-leak"},
                metadata={"platform_result": {"secret": "must-not-leak"}},
            )

    config = SimpleNamespace(
        prediction_markets_internal_api_token="internal-token",
        execution_console_base_url=origin,
    )
    client = TestClient(create_app(service=FakeService(), config=config))

    shell = client.get("/execution/polymarket/order-signing-console/")
    assert shell.status_code == 200
    assert token not in shell.text
    assert "pm_sign_sess_repo" not in shell.text
    assert shell.headers["cache-control"] == "no-store"
    assert shell.headers["referrer-policy"] == "no-referrer"
    assert shell.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'none'" in shell.headers["content-security-policy"]

    unauthorized = client.post(
        "/execution/polymarket/order-signing-sessions",
        json={"preview_id": "preview-1"},
    )
    assert unauthorized.status_code == 401
    assert unauthorized.json() == {"detail": "internal authorization is required"}

    created = client.post(
        "/execution/polymarket/order-signing-sessions",
        headers={"Authorization": "Bearer internal-token"},
        json={"preview_id": "preview-1"},
    )
    assert created.status_code == 200
    assert created.json()["signing_url"].endswith(f"#access_token={token}")
    assert token not in created.request.url.path
    assert token not in str(created.request.url.query)

    capability_headers = {
        "Authorization": f"Bearer {token}",
        "Origin": origin,
    }
    loaded = client.get(
        "/execution/polymarket/browser-order-signing-session",
        headers=capability_headers,
    )
    assert loaded.status_code == 200
    assert loaded.json()["session_id"] == "pm_sign_sess_repo"
    assert loaded.json().get("signing_url") is None
    assert token not in loaded.text
    assert loaded.headers["cache-control"] == "no-store"
    assert loaded.headers["referrer-policy"] == "no-referrer"
    assert loaded.headers["x-content-type-options"] == "nosniff"

    status = client.get(
        "/execution/polymarket/browser-order-signing-session/status",
        headers=capability_headers,
    )
    assert status.json() == {
        "session_id": "pm_sign_sess_repo",
        "status": "pending_browser_signature",
    }
    assert status.headers["cache-control"] == "no-store"
    completed = client.post(
        "/execution/polymarket/browser-order-signing-session/complete",
        headers=capability_headers,
        json={"signed_order": {"order": {}, "orderType": "GTC"}},
    )
    assert completed.status_code == 200
    assert completed.json() == {
        "session_id": "pm_sign_sess_repo",
        "status": "submitted",
        "reason": None,
        "next_action": "open_polymarket_order_signing_url",
        "execution_id": None,
    }
    assert "must-not-leak" not in completed.text
    assert completed.headers["cache-control"] == "no-store"

    invalid_capability = client.post(
        "/execution/polymarket/browser-order-signing-session/complete",
        headers={"Authorization": "Bearer wrong-token", "Origin": origin},
        json={"signed_order": {"order": {}, "orderType": "GTC"}},
    )
    assert invalid_capability.status_code == 401
    assert invalid_capability.json() == {
        "detail": "order signing capability is invalid"
    }

    invalid_payload = client.post(
        "/execution/polymarket/browser-order-signing-session/complete",
        headers=capability_headers,
        json={
            "signed_order": {
                "order": {"reject": True},
                "orderType": "GTC",
            }
        },
    )
    assert invalid_payload.status_code == 400
    assert invalid_payload.json() == {
        "detail": "signed order payload is invalid"
    }
    assert "upstream" not in invalid_payload.text


def test_order_signing_http_rejects_wrong_origin_without_wildcard_cors() -> None:
    from fastapi.testclient import TestClient
    from services.execution_service.app import create_app

    config = SimpleNamespace(
        prediction_markets_internal_api_token="internal-token",
        execution_console_base_url="https://clink.example",
    )
    client = TestClient(create_app(service=SimpleNamespace(), config=config))

    wrong = client.get(
        "/execution/polymarket/browser-order-signing-session",
        headers={
            "Authorization": "Bearer token",
            "Origin": "https://evil.example",
        },
    )
    assert wrong.status_code == 403
    assert wrong.json() == {"detail": "request origin is not allowed"}

    preflight = client.options(
        "/execution/polymarket/browser-order-signing-session",
        headers={
            "Origin": "https://clink.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert preflight.headers.get("access-control-allow-origin") == "https://clink.example"
    assert preflight.headers.get("access-control-allow-origin") != "*"
