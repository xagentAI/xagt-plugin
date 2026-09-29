from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from platforms.base import PlatformExecutionResult
from platforms.polymarket.executor import PolymarketExecutor
from platforms.polymarket.order_v2 import wrap_deposit_wallet_signature
from services.account_binding_service.credential_store import (
    CredentialStore,
    PolymarketApiCredentials,
)
from services.execution_service.service import ExecutionService, HttpFundingGateway
from shared.config import AppConfig
from shared.schemas import (
    CompletePolymarketOrderSigningSessionRequest,
    CreatePolymarketOrderSigningSessionRequest,
    PredictionMarketOrderPreview,
    UnifiedMarket,
)


USER_ID = "user-live-1"
BINDING_ID = "binding-live-1"
WALLET = "0x1111111111111111111111111111111111111111"
OWNER_WALLET = "0x2222222222222222222222222222222222222222"
CLIENT_ORDER_ID = "0xb768847313ab5dbef850b8254824ce43a114a83c7a2d2cdf5574a2224bca8dfd"
FIXTURE = Path(__file__).parent / "fixtures" / "polymarket_clob_v2_official_vectors.json"


def _official_projection() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["vector"][
        "expected_projection"
    ]


def _active_binding(*, binding_id: str = BINDING_ID, wallet: str = WALLET) -> dict:
    return {
        "binding_id": binding_id,
        "user_id": USER_ID,
        "status": "active",
        "wallet_address": "0x2222222222222222222222222222222222222222",
        "funder_address": wallet,
        "polymarket_deposit_wallet": wallet,
    }


def _create_submitted_record(repository, *, session_id: str):
    intent = repository.create_submission_intent(
        signing_session_id=session_id,
        user_id=USER_ID,
        binding_id=BINDING_ID,
        wallet_address=WALLET,
        client_order_id=CLIENT_ORDER_ID,
        projection_hash="12" * 32,
        funding_operation_id="funding-live-1",
    )
    claimed = repository.claim_submission(
        signing_session_id=intent.signing_session_id,
        expected_revision=intent.revision,
    )
    assert claimed is not None
    submitted = repository.record_submission_result(
        signing_session_id=claimed.signing_session_id,
        expected_revision=claimed.revision,
        submission_status="submitted",
        order_id=CLIENT_ORDER_ID,
    )
    assert submitted is not None
    return submitted


class RecordingCredentialStore:
    def __init__(self) -> None:
        self.lookups: list[str] = []

    def get_polymarket_credentials(self, user_id: str):
        self.lookups.append(user_id)
        if user_id != USER_ID:
            return None
        return PolymarketApiCredentials(
            api_key="l2-key-secret",
            api_secret="l2-api-secret",
            api_passphrase="l2-passphrase-secret",
            signature_type="3",
            funder_address=WALLET,
            wallet_address=OWNER_WALLET,
        )


def _transport_credentials() -> SimpleNamespace:
    return SimpleNamespace(
        api_key="l2-key-secret",
        api_secret="c2VjcmV0LXRlc3Q=",
        api_passphrase="l2-passphrase-secret",
        signature_type="3",
        wallet_address=OWNER_WALLET,
        funder_address=WALLET,
    )


def _browser_signed_order() -> dict:
    order = copy.deepcopy(_official_projection()["order"])
    order["signature"] = "0x" + "11" * 65
    return order


def test_credential_store_returns_encrypted_record_owner_wallet(
    tmp_path: Path,
) -> None:
    from cryptography.fernet import Fernet

    store = CredentialStore(
        AppConfig(
            credential_store_file=str(tmp_path / "credentials.jsonl"),
            credential_encryption_key=Fernet.generate_key().decode("ascii"),
        )
    )
    store.save_polymarket_credentials(
        user_id=USER_ID,
        wallet_address=OWNER_WALLET,
        credentials=PolymarketApiCredentials(
            api_key="l2-key-secret",
            api_secret="l2-api-secret",
            api_passphrase="l2-passphrase-secret",
            signature_type="3",
            funder_address=WALLET,
        ),
    )

    loaded = store.get_polymarket_credentials(USER_ID)

    assert loaded is not None
    assert loaded.wallet_address == OWNER_WALLET
    persisted = store.storage_file.read_text(encoding="utf-8")
    assert "l2-api-secret" not in persisted
    assert "l2-passphrase-secret" not in persisted


def test_production_post_uses_address_only_l2_and_exact_v2_wire_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from py_clob_client_v2.client import ClobClient
    from py_clob_client_v2.signing.hmac import build_hmac_signature

    calls: list[dict] = []

    def capture_post(self, endpoint, headers=None, data=None, params=None):
        calls.append(
            {
                "client": self,
                "endpoint": endpoint,
                "headers": dict(headers or {}),
                "data": data,
                "params": params,
            }
        )
        return {"orderID": CLIENT_ORDER_ID, "status": "live"}

    monkeypatch.setattr(ClobClient, "_post", capture_post)
    executor = PolymarketExecutor(
        config=SimpleNamespace(
            polymarket_clob_host="https://clob.invalid",
            polymarket_chain_id=137,
        ),
        credential_store=SimpleNamespace(),
    )
    signed_order = _browser_signed_order()

    result = executor._post_signed_order_with_credentials(
        signed_order,
        "GTC",
        _transport_credentials(),
    )

    assert result["order_id"] == CLIENT_ORDER_ID
    assert len(calls) == 1
    call = calls[0]
    expected_body = {
        "order": {
            "salt": int(signed_order["salt"]),
            "maker": signed_order["maker"],
            "signer": signed_order["signer"],
            "tokenId": signed_order["tokenId"],
            "makerAmount": signed_order["makerAmount"],
            "takerAmount": signed_order["takerAmount"],
            "side": "BUY",
            "expiration": signed_order["expiration"],
            "signatureType": signed_order["signatureType"],
            "timestamp": signed_order["timestamp"],
            "metadata": signed_order["metadata"],
            "builder": signed_order["builder"],
            "signature": signed_order["signature"],
        },
        "owner": "l2-key-secret",
        "orderType": "GTC",
        "deferExec": False,
        "postOnly": False,
    }
    expected_serialized = json.dumps(
        expected_body, separators=(",", ":"), ensure_ascii=False
    )
    assert call["endpoint"] == "https://clob.invalid/order"
    assert call["data"] == expected_serialized
    assert call["headers"]["POLY_ADDRESS"] == OWNER_WALLET
    assert call["headers"]["POLY_SIGNATURE"] == build_hmac_signature(
        "c2VjcmV0LXRlc3Q=",
        int(call["headers"]["POLY_TIMESTAMP"]),
        "POST",
        "/order",
        expected_serialized,
    )
    assert call["client"].retry_on_error is False
    assert int(call["client"].builder.signature_type) == 3
    assert call["client"].builder.funder == WALLET
    assert call["client"].signer.address() == OWNER_WALLET
    assert not hasattr(call["client"].signer, "private_key")


def test_production_get_uses_exact_order_hash_and_address_only_l2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from py_clob_client_v2.client import ClobClient
    from py_clob_client_v2.signing.hmac import build_hmac_signature

    calls: list[dict] = []

    def capture_get(self, endpoint, headers=None, params=None):
        calls.append(
            {
                "client": self,
                "endpoint": endpoint,
                "headers": dict(headers or {}),
                "params": params,
            }
        )
        return {"id": CLIENT_ORDER_ID, "status": "LIVE"}

    monkeypatch.setattr(ClobClient, "_get", capture_get)
    executor = PolymarketExecutor(
        config=SimpleNamespace(
            polymarket_clob_host="https://clob.invalid",
            polymarket_chain_id=137,
        ),
        credential_store=SimpleNamespace(),
    )

    result = executor._get_order_with_credentials(
        CLIENT_ORDER_ID,
        _transport_credentials(),
    )

    assert result == {"id": CLIENT_ORDER_ID, "status": "LIVE"}
    assert len(calls) == 1
    request_path = f"/data/order/{CLIENT_ORDER_ID}"
    assert calls[0]["endpoint"] == f"https://clob.invalid{request_path}"
    assert calls[0]["headers"]["POLY_ADDRESS"] == OWNER_WALLET
    assert calls[0]["headers"]["POLY_SIGNATURE"] == build_hmac_signature(
        "c2VjcmV0LXRlc3Q=",
        int(calls[0]["headers"]["POLY_TIMESTAMP"]),
        "GET",
        request_path,
        None,
    )
    assert calls[0]["client"].retry_on_error is False
    assert int(calls[0]["client"].builder.signature_type) == 3
    assert calls[0]["client"].builder.funder == WALLET
    assert not hasattr(calls[0]["client"].signer, "private_key")


def test_executor_requires_exact_owner_and_funder_scope_before_post() -> None:
    credentials = _transport_credentials()
    posts: list[dict] = []
    executor = PolymarketExecutor(
        config=SimpleNamespace(),
        credential_store=SimpleNamespace(
            get_polymarket_credentials=lambda _user_id: credentials
        ),
    )
    executor.readiness = lambda user_id=None: PlatformExecutionResult(
        platform="polymarket", ready=True, status="ready"
    )
    executor._post_signed_order_with_credentials = (
        lambda *_args: posts.append({}) or {"order_id": CLIENT_ORDER_ID}
    )

    missing_owner = executor.submit_signed_order(
        _browser_signed_order(),
        "GTC",
        user_id=USER_ID,
        binding_id=BINDING_ID,
        wallet_address=WALLET,
        client_order_id=CLIENT_ORDER_ID,
        order_projection=_official_projection(),
    )
    assert missing_owner.status == "blocked"

    valid = executor.submit_signed_order(
        _browser_signed_order(),
        "GTC",
        user_id=USER_ID,
        binding_id=BINDING_ID,
        owner_address=OWNER_WALLET,
        wallet_address=WALLET,
        client_order_id=CLIENT_ORDER_ID,
        order_projection=_official_projection(),
    )
    assert valid.submitted is True

    for owner_address, funder_address in (
        ("0x3333333333333333333333333333333333333333", WALLET),
        (OWNER_WALLET, "0x3333333333333333333333333333333333333333"),
    ):
        result = executor.submit_signed_order(
            _browser_signed_order(),
            "GTC",
            user_id=USER_ID,
            binding_id=BINDING_ID,
            owner_address=owner_address,
            wallet_address=funder_address,
            client_order_id=CLIENT_ORDER_ID,
            order_projection=_official_projection(),
        )
        assert result.status == "blocked"

    assert posts == [{}]


def test_http_funding_gateway_requires_exact_scoped_finalization_proof() -> None:
    exact = {
        "operation_id": "funding-live-1",
        "user_id": USER_ID,
        "binding_id": BINDING_ID,
        "venue_wallet_address": WALLET,
        "bridge_address": "0x4444444444444444444444444444444444444444",
        "status": "finalized",
        "amount_usdc": "2.000000",
        "resource": "polygon:usdc",
        "core_state": "finalized",
        "bridge_status": "COMPLETED",
        "venue_buying_power_before_atomic": "0",
        "venue_buying_power_after_atomic": "1000000",
        "reservation_id": "reservation-live-1",
        "audit_event_id": "audit-live-1",
        "core_tx_hash": "0x" + "44" * 32,
    }
    response = copy.deepcopy(exact)
    gateway = HttpFundingGateway(
        SimpleNamespace(funding_adapter_url="http://funding.invalid")
    )
    gateway._request_json = lambda _url: copy.deepcopy(response)

    ready = gateway.get_funding_readiness(
        user_id=USER_ID,
        platform="polymarket",
        amount_usd="1.00",
        funding_operation_id="funding-live-1",
        binding_id=BINDING_ID,
        venue_wallet_address=WALLET,
    )

    assert ready["ready"] is True
    assert ready["funding_proof"] == exact

    for field, drift in (
        ("operation_id", "funding-live-other"),
        ("user_id", "user-live-other"),
        ("binding_id", "binding-live-other"),
        ("venue_wallet_address", OWNER_WALLET),
        ("bridge_address", "not-an-address"),
        ("status", "venue_credited"),
        ("core_state", "settled"),
        ("bridge_status", "PENDING"),
        ("reservation_id", None),
        ("audit_event_id", None),
        ("core_tx_hash", None),
        ("amount_usdc", "0.500000"),
        ("venue_buying_power_after_atomic", "999999"),
    ):
        response.clear()
        response.update(exact)
        response[field] = drift
        assert gateway.get_funding_readiness(
            user_id=USER_ID,
            platform="polymarket",
            amount_usd="1.00",
            funding_operation_id="funding-live-1",
            binding_id=BINDING_ID,
            venue_wallet_address=WALLET,
        )["ready"] is False


def test_live_polymarket_funding_gate_ignores_legacy_optional_flag() -> None:
    class RecordingFundingGateway:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def get_funding_readiness(self, **kwargs):
            self.calls.append(kwargs)
            return {"ready": True, "status": "ready"}

    funding = RecordingFundingGateway()
    service = object.__new__(ExecutionService)
    service.config = SimpleNamespace(require_funding_before_execution=False)
    service.funding_gateway = funding
    preview = SimpleNamespace(
        user_id=USER_ID,
        platform="polymarket",
        amount_usd="1.00",
        metadata={"funding_operation_id": "funding-live-1"},
    )

    result = service._funding_execution_gate(
        preview,
        binding=_active_binding(),
    )

    assert result == {"ready": True, "status": "ready"}
    assert funding.calls == [
        {
            "user_id": USER_ID,
            "platform": "polymarket",
            "amount_usd": "1.00",
            "funding_operation_id": "funding-live-1",
            "binding_id": BINDING_ID,
            "venue_wallet_address": WALLET,
        }
    ]


def test_same_signing_session_claim_allows_exactly_one_clob_post(
    tmp_path: Path,
) -> None:
    from storage.live_trading_repository import SQLiteLiveTradingRepository

    repository = SQLiteLiveTradingRepository(tmp_path / "live.sqlite3")
    intent = repository.create_submission_intent(
        signing_session_id="session-live-1",
        user_id=USER_ID,
        binding_id=BINDING_ID,
        wallet_address=WALLET,
        client_order_id=CLIENT_ORDER_ID,
        projection_hash="cd" * 32,
        funding_operation_id="funding-live-1",
    )

    winners = [
        repository.claim_submission(
            signing_session_id=intent.signing_session_id,
            expected_revision=intent.revision,
        )
        for _ in range(2)
    ]
    clob_posts = [winner for winner in winners if winner is not None]

    assert len(clob_posts) == 1
    assert clob_posts[0].submission_status == "submitting"


def test_response_loss_is_unknown_and_recovery_only_gets_original_order_id() -> None:
    credentials = RecordingCredentialStore()
    executor = PolymarketExecutor(
        config=SimpleNamespace(),
        credential_store=credentials,
    )
    executor.readiness = lambda user_id=None: PlatformExecutionResult(
        platform="polymarket", ready=True, status="ready"
    )
    calls: list[tuple[str, str | None]] = []

    def lose_response(_order, _order_type, _credentials):
        calls.append(("POST", None))
        raise TimeoutError("must-not-leak-l2-api-secret")

    def read_original(order_id, _credentials):
        calls.append(("GET", order_id))
        return {"id": order_id, "status": "LIVE", "size_matched": "0"}

    executor._post_signed_order_with_credentials = lose_response
    executor._get_order_with_credentials = read_original

    projection = _official_projection()
    signed_order = copy.deepcopy(projection["order"])
    signed_order["signature"] = "0x" + "11" * 65
    submitted = executor.submit_signed_order(
        signed_order,
        "GTC",
        user_id=USER_ID,
        binding_id=BINDING_ID,
        owner_address=OWNER_WALLET,
        wallet_address=WALLET,
        client_order_id=CLIENT_ORDER_ID,
        order_projection=projection,
    )
    recovered = executor.reconcile_signed_order(
        user_id=USER_ID,
        binding_id=BINDING_ID,
        owner_address=OWNER_WALLET,
        wallet_address=WALLET,
        client_order_id=CLIENT_ORDER_ID,
    )

    assert submitted.status == "unknown"
    assert submitted.submitted is False
    assert submitted.reason == "Polymarket order submission outcome is unknown"
    assert "secret" not in submitted.model_dump_json()
    assert recovered.status == "submitted"
    assert calls == [("POST", None), ("GET", CLIENT_ORDER_ID)]
    assert PolymarketExecutor.official_order_id(projection) == CLIENT_ORDER_ID
    assert CLIENT_ORDER_ID != "0x" + hashlib.sha256(
        json.dumps(
            signed_order,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


def test_protocol_or_sdk_exception_after_post_is_unknown_not_rejected() -> None:
    credentials = RecordingCredentialStore()
    executor = PolymarketExecutor(
        config=SimpleNamespace(),
        credential_store=credentials,
    )
    executor.readiness = lambda user_id=None: PlatformExecutionResult(
        platform="polymarket", ready=True, status="ready"
    )
    executor._post_signed_order_with_credentials = (
        lambda *_args: (_ for _ in ()).throw(
            ValueError("must-not-leak-response-parser-detail")
        )
    )
    projection = _official_projection()
    signed_order = copy.deepcopy(projection["order"])
    signed_order["signature"] = "0x" + "11" * 65

    result = executor.submit_signed_order(
        signed_order,
        "GTC",
        user_id=USER_ID,
        binding_id=BINDING_ID,
        owner_address=OWNER_WALLET,
        wallet_address=WALLET,
        client_order_id=CLIENT_ORDER_ID,
        order_projection=projection,
    )

    assert result.status == "unknown"
    assert result.submitted is False
    assert result.reason == "Polymarket order submission outcome is unknown"
    assert "parser" not in result.model_dump_json()


def test_ambiguous_four_xx_is_unknown_then_status_only_by_official_hash() -> None:
    class VenueError(Exception):
        def __init__(self, status_code: int, error_msg) -> None:
            self.status_code = status_code
            self.error_msg = error_msg

    projection = _official_projection()
    for error in (
        VenueError(408, {"error_code": "INVALID_ORDER"}),
        VenueError(409, {"error_code": "INVALID_ORDER"}),
        VenueError(429, {"error_code": "INVALID_ORDER"}),
        VenueError(400, "plain unstructured response"),
        VenueError(418, {"error_code": "UNRECOGNIZED"}),
    ):
        calls: list[tuple[str, str | None]] = []
        executor = PolymarketExecutor(
            config=SimpleNamespace(),
            credential_store=RecordingCredentialStore(),
        )
        executor.readiness = lambda user_id=None: PlatformExecutionResult(
            platform="polymarket", ready=True, status="ready"
        )

        def reject(_order, _order_type, _credentials):
            calls.append(("POST", None))
            raise error

        def status_only(order_id, _credentials):
            calls.append(("GET", order_id))
            return {"id": order_id, "status": "unknown"}

        executor._post_signed_order_with_credentials = reject
        executor._get_order_with_credentials = status_only
        submitted = executor.submit_signed_order(
            _browser_signed_order(),
            "GTC",
            user_id=USER_ID,
            binding_id=BINDING_ID,
            owner_address=OWNER_WALLET,
            wallet_address=WALLET,
            client_order_id=CLIENT_ORDER_ID,
            order_projection=projection,
        )
        recovered = executor.reconcile_signed_order(
            user_id=USER_ID,
            binding_id=BINDING_ID,
            owner_address=OWNER_WALLET,
            wallet_address=WALLET,
            client_order_id=CLIENT_ORDER_ID,
        )

        assert submitted.status == "unknown"
        assert recovered.status == "unknown"
        assert calls == [("POST", None), ("GET", CLIENT_ORDER_ID)]

    executor = PolymarketExecutor(
        config=SimpleNamespace(),
        credential_store=RecordingCredentialStore(),
    )
    executor.readiness = lambda user_id=None: PlatformExecutionResult(
        platform="polymarket", ready=True, status="ready"
    )
    executor._post_signed_order_with_credentials = (
        lambda *_args: (_ for _ in ()).throw(
            VenueError(400, {"error_code": "INVALID_ORDER"})
        )
    )
    definite = executor.submit_signed_order(
        _browser_signed_order(),
        "GTC",
        user_id=USER_ID,
        binding_id=BINDING_ID,
        owner_address=OWNER_WALLET,
        wallet_address=WALLET,
        client_order_id=CLIENT_ORDER_ID,
        order_projection=projection,
    )
    assert definite.status == "rejected"


def test_success_response_order_id_must_match_precomputed_official_hash() -> None:
    credentials = RecordingCredentialStore()
    executor = PolymarketExecutor(
        config=SimpleNamespace(),
        credential_store=credentials,
    )
    executor.readiness = lambda user_id=None: PlatformExecutionResult(
        platform="polymarket", ready=True, status="ready"
    )
    executor._post_signed_order_with_credentials = lambda *_args: {
        "order_id": "0x" + "ff" * 32,
        "tx_hash": None,
        "status": "submitted",
        "raw_response": {"orderID": "0x" + "ff" * 32},
    }
    projection = _official_projection()
    signed_order = copy.deepcopy(projection["order"])
    signed_order["signature"] = "0x" + "11" * 65

    result = executor.submit_signed_order(
        signed_order,
        "GTC",
        user_id=USER_ID,
        binding_id=BINDING_ID,
        owner_address=OWNER_WALLET,
        wallet_address=WALLET,
        client_order_id=CLIENT_ORDER_ID,
        order_projection=projection,
    )

    assert result.status == "unknown"
    assert result.submitted is False
    assert result.order_id is None
    assert result.metadata["client_order_id"] == CLIENT_ORDER_ID


def test_minimal_live_repository_is_sqlite_only_and_exactly_scoped(
    tmp_path: Path,
) -> None:
    import storage.live_trading_repository as repository_module
    from storage.live_trading_repository import SQLiteLiveTradingRepository

    repository = SQLiteLiveTradingRepository(tmp_path / "minimal-live.sqlite3")
    intent = repository.create_submission_intent(
        signing_session_id="session-minimal-live-1",
        user_id=USER_ID,
        binding_id=BINDING_ID,
        wallet_address=WALLET,
        client_order_id=CLIENT_ORDER_ID,
        projection_hash="12" * 32,
        funding_operation_id="funding-live-1",
    )
    claimed = repository.claim_submission(
        signing_session_id=intent.signing_session_id,
        expected_revision=intent.revision,
    )
    assert claimed is not None
    unknown = repository.record_submission_result(
        signing_session_id=claimed.signing_session_id,
        expected_revision=claimed.revision,
        submission_status="unknown",
        order_id=None,
    )
    assert unknown is not None

    assert repository.get_submission(
        signing_session_id=unknown.signing_session_id,
        user_id=USER_ID,
        binding_id=BINDING_ID,
        wallet_address=WALLET,
    ) == unknown
    for user_id, binding_id, wallet_address in (
        ("user-live-other", BINDING_ID, WALLET),
        (USER_ID, "binding-live-other", WALLET),
        (USER_ID, BINDING_ID, OWNER_WALLET),
    ):
        assert repository.get_submission(
            signing_session_id=unknown.signing_session_id,
            user_id=user_id,
            binding_id=binding_id,
            wallet_address=wallet_address,
        ) is None

    assert not hasattr(repository_module, "PostgresLiveTradingRepository")
    assert not hasattr(repository, "record_reconciliation")
    assert not hasattr(repository, "list_history")

@pytest.mark.parametrize(
    "scenario",
    ["transport_unknown", "post_persist_failure", "missing_funding"],
)
def test_execution_service_persists_unknown_before_status_only_recovery(
    tmp_path: Path,
    scenario: str,
) -> None:
    from storage.live_trading_repository import (
        LiveTradingRepositoryError,
        SQLiteLiveTradingRepository,
    )

    class FakePreviewStore:
        def __init__(self, preview) -> None:
            self.preview = preview

        def get_order_preview(self, preview_id):
            return self.preview if preview_id == self.preview.preview_id else None

    class FakeCoreGateway:
        def create_action_intent(self, payload):
            return {"action_id": "action-live", **payload}

        def evaluate_policy(self, payload):
            return {
                "policy_decision_id": "policy-live",
                "approved": True,
                "decision": "approved",
                "reason_code": "APPROVED",
                "required_action": None,
                **payload,
            }

        def write_audit_event(self, payload):
            return {"event_id": f"audit-{payload['event_type']}", **payload}

    class FakeAccountBindingGateway:
        def latest_polymarket_binding(self, user_id):
            assert user_id == USER_ID
            return {
                "binding_id": BINDING_ID,
                "user_id": USER_ID,
                "status": "active",
                "wallet_address": "0x2222222222222222222222222222222222222222",
                "funder_address": WALLET,
                "polymarket_deposit_wallet": WALLET,
                "account_mode": "deposit_wallet",
                "polymarket_signature_type": "3",
            }

    class FakeAccountIdentityGateway:
        def active_wallet(self, user_id):
            assert user_id == USER_ID
            return "0x2222222222222222222222222222222222222222"

    class FakeFundingGateway:
        def get_funding_readiness(
            self,
            *,
            user_id,
            platform,
            amount_usd,
            funding_operation_id=None,
            binding_id,
            venue_wallet_address,
        ):
            assert user_id == USER_ID
            assert platform == "polymarket"
            assert amount_usd == "1.00"
            assert binding_id == BINDING_ID
            assert venue_wallet_address == WALLET
            if not funding_operation_id:
                return {
                    "ready": False,
                    "status": "funding_operation_required",
                    "reason": "an explicit Polymarket funding operation is required",
                    "next_action": "open_polymarket_funding_operation",
                }
            return {
                "ready": True,
                "status": "ready",
                "funding_operation_id": funding_operation_id,
                "funding_proof": {
                    "operation_id": funding_operation_id,
                    "user_id": USER_ID,
                    "binding_id": BINDING_ID,
                    "venue_wallet_address": WALLET,
                    "bridge_address": "0x4444444444444444444444444444444444444444",
                    "status": "finalized",
                    "amount_usdc": "1.000000",
                    "resource": "polygon:usdc",
                    "core_state": "finalized",
                    "bridge_status": "COMPLETED",
                    "venue_buying_power_before_atomic": "0",
                    "venue_buying_power_after_atomic": "1000000",
                    "reservation_id": "reservation-live-1",
                    "audit_event_id": "audit-live-1",
                    "core_tx_hash": "0x" + "44" * 32,
                },
            }

    class OutcomeExecutor(PolymarketExecutor):
        def __init__(self, config) -> None:
            self.config = config
            self.submit_calls = 0
            self.reconcile_calls = 0
            self.observed: dict = {}

        def readiness(self, user_id=None) -> PlatformExecutionResult:
            return PlatformExecutionResult(
                platform="polymarket", ready=True, status="ready"
            )

        def submit_signed_order(self, signed_order, order_type="FAK", user_id=None, **scope):
            self.submit_calls += 1
            self.observed = {"user_id": user_id, **scope}
            if scenario == "post_persist_failure":
                return PlatformExecutionResult(
                    platform="polymarket",
                    ready=True,
                    submitted=True,
                    status="submitted",
                    order_id=scope["client_order_id"],
                    metadata={"client_order_id": scope["client_order_id"]},
                )
            return PlatformExecutionResult(
                platform="polymarket",
                ready=True,
                submitted=False,
                status="unknown",
                reason="Polymarket order submission outcome is unknown",
                metadata={"client_order_id": scope["client_order_id"]},
            )

        def reconcile_signed_order(self, **scope):
            self.reconcile_calls += 1
            self.observed["recovery"] = scope
            if scenario == "post_persist_failure":
                return PlatformExecutionResult(
                    platform="polymarket",
                    ready=True,
                    submitted=True,
                    status="submitted",
                    order_id=scope["client_order_id"],
                    metadata={"client_order_id": scope["client_order_id"]},
                )
            return PlatformExecutionResult(
                platform="polymarket",
                ready=True,
                submitted=False,
                status="unknown",
                reason="Polymarket order status is unavailable",
                metadata={"client_order_id": scope["client_order_id"]},
            )

    market = UnifiedMarket(
        platform="polymarket",
        market_id="market-live-1",
        title="Will the live reconciliation test pass?",
        yes_price=0.2,
        no_price=0.8,
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
    preview = PredictionMarketOrderPreview(
        preview_id="preview-live-1",
        user_id=USER_ID,
        agent_id="agent-live-1",
        platform="polymarket",
        market_id=market.market_id,
        title=market.title,
        outcome="Yes",
        side="buy",
        amount_usd="1.00",
        limit_price=0.2,
        estimated_contracts=5,
        max_slippage_bps=0,
        max_slippage_usd="0.00",
        worst_case_price=0.2,
        state="confirmation_required",
        next_action="request_user_confirmation",
        live_mode=True,
        market=market,
        metadata=(
            {}
            if scenario == "missing_funding"
            else {"funding_operation_id": "funding-live-1"}
        ),
        created_at="2026-08-20T00:00:00Z",
        expires_at="2099-01-01T00:00:00Z",
    )
    config = AppConfig(
        live_mode=True,
        polymarket_execution_mode="browser_signed",
        order_signing_session_file=str(tmp_path / "signing.jsonl"),
        execution_file=str(tmp_path / "executions.jsonl"),
        ledger_db_file=str(tmp_path / "ledger.sqlite3"),
    )
    class InjectedRepository(SQLiteLiveTradingRepository):
        def __init__(self, database_path) -> None:
            super().__init__(database_path)
            self.fail_next_result_write = scenario == "post_persist_failure"

        def record_submission_result(self, **kwargs):
            if self.fail_next_result_write:
                self.fail_next_result_write = False
                raise LiveTradingRepositoryError(
                    "live trading database operation failed"
                )
            return super().record_submission_result(**kwargs)

    live_repository = InjectedRepository(tmp_path / "live.sqlite3")
    executor = OutcomeExecutor(config)
    service = ExecutionService(
        config=config,
        preview_store=FakePreviewStore(preview),
        executors={"polymarket": executor},
        core_gateway=FakeCoreGateway(),
        funding_gateway=FakeFundingGateway(),
        account_binding_gateway=FakeAccountBindingGateway(),
        account_identity_gateway=FakeAccountIdentityGateway(),
        live_trading_repository=live_repository,
    )
    session = service.create_polymarket_order_signing_session(
        CreatePolymarketOrderSigningSessionRequest(
            preview_id=preview.preview_id,
            user_confirmed=True,
            live_submission_confirmed=True,
        )
    )
    if scenario == "missing_funding":
        assert session.status == "blocked"
        assert "funding operation" in (session.reason or "")
        assert executor.submit_calls == 0
        assert executor.reconcile_calls == 0
        return
    signed_order = copy.deepcopy(session.order_payload["order"])
    signed_order["signature"] = wrap_deposit_wallet_signature(
        raw_signature="0x" + "ab" * 65,
        typed_data=session.order_payload["typed_data"],
    )
    completion = CompletePolymarketOrderSigningSessionRequest(
        signed_order={"order": signed_order, "orderType": "GTC"}
    )

    completed = service.complete_polymarket_order_signing_session(
        session.session_id,
        completion,
    )
    if scenario == "post_persist_failure":
        unknown = service.get_polymarket_order_signing_session(session.session_id)
        assert unknown is not None
        assert unknown.status == "unknown"
        for forbidden_status in ("failed", "blocked"):
            assert service.order_signing_session_repository.compare_and_set_terminal(
                session_id=unknown.session_id,
                expected_revision=unknown.revision,
                replacement=unknown.model_copy(
                    update={"status": forbidden_status}
                ),
            ) is None
    replayed = service.complete_polymarket_order_signing_session(
        session.session_id,
        completion,
    )

    expected_status = {
        "transport_unknown": "unknown",
        "post_persist_failure": "submitted",
    }[scenario]
    assert completed.status == (
        "unknown" if scenario == "post_persist_failure" else expected_status
    )
    assert replayed.status == expected_status
    assert executor.submit_calls == 1
    assert executor.reconcile_calls == 1
    official_id = PolymarketExecutor.official_order_id(session.order_payload)
    assert executor.observed["client_order_id"] == official_id
    assert executor.observed["order_projection"] == session.order_payload
    if scenario == "transport_unknown":
        assert executor.observed["owner_address"] == OWNER_WALLET
    live = live_repository.get_submission(
        signing_session_id=session.session_id,
        user_id=preview.user_id,
        binding_id=session.binding_id,
        wallet_address="0x1111111111111111111111111111111111111111",
    )
    assert live is not None
    assert live.submission_status == (
        "submitted" if scenario == "post_persist_failure" else "unknown"
    )
    assert live.client_order_id == official_id
    assert executor.observed["recovery"]["client_order_id"] == official_id
    assert executor.observed["recovery"]["owner_address"] == OWNER_WALLET
    if scenario == "post_persist_failure":
        fresh = service.get_polymarket_order_signing_session(session.session_id)
        assert fresh is not None
        assert fresh.status == "submitted"
        assert fresh.execution_id
        execution = service.get_execution(fresh.execution_id)
        assert execution is not None
        assert execution.state == "submitted"
        assert execution.order_id == official_id
        third = service.complete_polymarket_order_signing_session(
            session.session_id,
            completion,
        )
        assert third.status == "submitted"
        assert executor.submit_calls == 1
        assert executor.reconcile_calls == 1
