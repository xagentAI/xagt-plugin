import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from platforms.base import PlatformExecutionResult  # noqa: E402
from platforms.polymarket.executor import PolymarketExecutor  # noqa: E402
from platforms.polymarket.order_v2 import wrap_deposit_wallet_signature  # noqa: E402
from services.execution_service.service import ExecutionService  # noqa: E402
from shared.config import AppConfig  # noqa: E402
from shared.schemas import (  # noqa: E402
    CompletePolymarketOrderSigningSessionRequest,
    CreatePolymarketOrderSigningSessionRequest,
    PredictionMarketOrderPreview,
    UnifiedMarket,
)


class FakePreviewStore:
    def __init__(self, preview: PredictionMarketOrderPreview) -> None:
        self.preview = preview

    def get_order_preview(self, preview_id: str) -> PredictionMarketOrderPreview | None:
        return self.preview if preview_id == self.preview.preview_id else None


class FakeCoreGateway:
    def __init__(self) -> None:
        self.approved = True
        self.policy_calls = 0

    def create_action_intent(self, payload: dict) -> dict:
        return {"action_id": "act_browser_signed", **payload}

    def evaluate_policy(self, payload: dict) -> dict:
        self.policy_calls += 1
        return {
            "policy_decision_id": "policy_browser_signed",
            "approved": self.approved,
            "decision": "approved" if self.approved else "blocked",
            "reason_code": "APPROVED" if self.approved else "SPENDING_AUTHORIZATION_REVOKED",
            "required_action": None if self.approved else "restore_spending_authorization",
            **payload,
        }

    def write_audit_event(self, payload: dict) -> dict:
        return {"event_id": f"audit_{payload['event_type']}", **payload}


class FakeAccountBindingGateway:
    def latest_polymarket_binding(self, user_id: str) -> dict:
        assert user_id == "telegram_demo_user"
        return {
            "binding_id": "pm_binding_browser_signed",
            "user_id": user_id,
            "wallet_address": "0x2222222222222222222222222222222222222222",
            "polymarket_deposit_wallet": "0x1111111111111111111111111111111111111111",
            "funder_address": "0x1111111111111111111111111111111111111111",
            "account_mode": "deposit_wallet",
            "polymarket_signature_type": "3",
            "api_key_fingerprint": "sha256:test",
            "status": "active",
        }


class FakeAccountIdentityGateway:
    def __init__(self) -> None:
        self.wallet_address = "0x2222222222222222222222222222222222222222"

    def active_wallet(self, user_id: str) -> str | None:
        assert user_id == "telegram_demo_user"
        return self.wallet_address


class FakeFundingGateway:
    def get_funding_readiness(
        self,
        *,
        user_id: str,
        platform: str,
        amount_usd: str,
        funding_operation_id: str | None,
        binding_id: str,
        venue_wallet_address: str,
    ) -> dict:
        assert user_id == "telegram_demo_user"
        assert platform == "polymarket"
        assert amount_usd == "1"
        assert funding_operation_id == "funding_browser_signed"
        assert binding_id == "pm_binding_browser_signed"
        assert venue_wallet_address == (
            "0x1111111111111111111111111111111111111111"
        )
        return {
            "ready": True,
            "status": "ready",
            "funding_operation_id": funding_operation_id,
            "funding_proof": {
                "operation_id": funding_operation_id,
                "user_id": user_id,
                "binding_id": binding_id,
                "venue_wallet_address": venue_wallet_address,
                "bridge_address": "0x4444444444444444444444444444444444444444",
                "status": "finalized",
                "amount_usdc": "1.000000",
                "resource": "polygon:usdc",
                "core_state": "finalized",
                "bridge_status": "COMPLETED",
                "venue_buying_power_before_atomic": "0",
                "venue_buying_power_after_atomic": "1000000",
                "reservation_id": "reservation-browser-signed",
                "audit_event_id": "audit-browser-signed",
                "core_tx_hash": "0x" + "44" * 32,
            },
        }


class FakePolymarketExecutor(PolymarketExecutor):
    def readiness(self) -> PlatformExecutionResult:
        return PlatformExecutionResult(platform="polymarket", ready=True, status="ready", metadata={"fake": True})

    def submit_signed_order(
        self,
        signed_order: dict,
        order_type: str = "FAK",
        user_id: str | None = None,
        *,
        binding_id: str,
        owner_address: str,
        wallet_address: str,
        client_order_id: str,
        order_projection: dict,
    ) -> PlatformExecutionResult:
        self.submit_calls = getattr(self, "submit_calls", 0) + 1
        if getattr(self, "raise_on_submit", False):
            raise RuntimeError("simulated process interruption after claim")
        assert signed_order["signature"].startswith("0x" + "ab" * 65)
        assert len(signed_order["signature"]) > 132
        assert signed_order["maker"] == "0x1111111111111111111111111111111111111111"
        assert signed_order["signer"] == "0x1111111111111111111111111111111111111111"
        assert order_type == "GTC"
        assert user_id == "telegram_demo_user"
        assert binding_id == "pm_binding_browser_signed"
        assert owner_address == "0x2222222222222222222222222222222222222222"
        assert wallet_address == "0x1111111111111111111111111111111111111111"
        assert client_order_id == self.official_order_id(order_projection)
        assert order_projection["provenance"]["funding_operation_id"] == (
            "funding_browser_signed"
        )
        return PlatformExecutionResult(
            platform="polymarket",
            ready=True,
            submitted=True,
            status="matched",
            order_id=client_order_id,
            tx_hash="0xsigned_tx",
            raw_response={"status": "matched", "orderID": client_order_id},
        )


def _preview() -> PredictionMarketOrderPreview:
    market = UnifiedMarket(
        platform="polymarket",
        market_id="558934",
        title="Will Spain win the 2026 FIFA World Cup?",
        yes_price=0.123,
        no_price=0.877,
        tradable=True,
        execution_ready=True,
        raw={
            "clobTokenIds": '["123456789", "987654321"]',
            "outcomes": '["Yes", "No"]',
            "tick_size": "0.001",
            "min_order_size": "5",
            "neg_risk": False,
        },
    )

    return PredictionMarketOrderPreview(
        preview_id="pm_preview_browser_signed",
        user_id="telegram_demo_user",
        agent_id="hermes_agent",
        platform="polymarket",
        market_id=market.market_id,
        title=market.title,
        outcome="Yes",
        side="buy",
        amount_usd="1",
        limit_price=0.123,
        estimated_contracts=8.13,
        max_slippage_bps=100,
        max_slippage_usd="0.01",
        worst_case_price=0.124,
        state="confirmation_required",
        next_action="request_user_confirmation",
        live_mode=True,
        market=market,
        metadata={"funding_operation_id": "funding_browser_signed"},
        created_at="2026-07-05T00:00:00Z",
        expires_at="2099-01-01T00:00:00Z",
    )


def _signed_order(
    session, *, token_id: str = "123456789", raw_deposit_signature: bool = False
) -> dict:
    order = dict(session.order_payload["order"])
    order["tokenId"] = token_id
    raw_signature = "0x" + "ab" * 65
    order["signature"] = (
        raw_signature
        if raw_deposit_signature or order["signatureType"] != 3
        else wrap_deposit_wallet_signature(
            raw_signature=raw_signature,
            typed_data=session.order_payload["typed_data"],
        )
    )
    return {"order": order, "orderType": session.order_type}


def main() -> None:
    preview = _preview()
    config = AppConfig(
        live_mode=True,
        polymarket_execution_mode="browser_signed",
        order_signing_session_file="/tmp/clink_pm_order_signing_sessions.jsonl",
        execution_file="/tmp/clink_pm_browser_signed_executions.jsonl",
        ledger_db_file="/tmp/clink_pm_browser_signed_live.sqlite3",
    )
    Path(config.order_signing_session_file).unlink(missing_ok=True)
    signing_database = Path(config.order_signing_session_file).with_suffix(".sqlite3")
    signing_database.unlink(missing_ok=True)
    Path(config.execution_file).unlink(missing_ok=True)
    Path(config.ledger_db_file).unlink(missing_ok=True)
    identity_gateway = FakeAccountIdentityGateway()
    core_gateway = FakeCoreGateway()
    executor = FakePolymarketExecutor(config)
    service = ExecutionService(
        config=config,
        preview_store=FakePreviewStore(preview),
        executors={"polymarket": executor},
        core_gateway=core_gateway,
        funding_gateway=FakeFundingGateway(),
        account_binding_gateway=FakeAccountBindingGateway(),
        account_identity_gateway=identity_gateway,
    )
    session = service.create_polymarket_order_signing_session(
        CreatePolymarketOrderSigningSessionRequest(
            preview_id=preview.preview_id,
            user_confirmed=True,
            live_submission_confirmed=True,
        )
    )
    assert session.status == "pending_browser_signature"
    assert session.signing_url
    assert session.order_payload["order"]["tokenId"] == "123456789"
    assert session.order_payload["order"]["signatureType"] == 3
    assert session.order_payload["order"]["maker"] == "0x1111111111111111111111111111111111111111"
    assert session.order_payload["order"]["signer"] == "0x1111111111111111111111111111111111111111"
    assert session.order_payload["typed_data"]["primaryType"] == "TypedDataSign"
    assert session.order_payload["typed_data"]["message"]["verifyingContract"] == (
        "0x1111111111111111111111111111111111111111"
    )
    assert session.order_payload["orderType"] == "GTC"
    assert "projection_sha256" in session.order_payload
    assert session.next_action == "open_polymarket_order_signing_url"
    assert signing_database.exists()
    assert not Path(config.order_signing_session_file).exists()

    identity_gateway.wallet_address = None
    revoked = service.complete_polymarket_order_signing_session(
        session.session_id,
        CompletePolymarketOrderSigningSessionRequest(signed_order=_signed_order(session)),
    )
    assert revoked.status == "blocked"
    assert revoked.next_action == "restore_core_wallet_identity"

    identity_gateway.wallet_address = "0x2222222222222222222222222222222222222222"
    service.order_signing_session_file.unlink(missing_ok=True)
    session = service.create_polymarket_order_signing_session(
        CreatePolymarketOrderSigningSessionRequest(
            preview_id=preview.preview_id,
            user_confirmed=True,
            live_submission_confirmed=True,
        )
    )

    mismatched = service.complete_polymarket_order_signing_session(
        session.session_id,
        CompletePolymarketOrderSigningSessionRequest(
            signed_order=_signed_order(session, token_id="987654321")
        ),
    )
    assert mismatched.status == "blocked"
    assert mismatched.next_action == "sign_exact_approved_order"

    service.order_signing_session_file.unlink(missing_ok=True)
    session = service.create_polymarket_order_signing_session(
        CreatePolymarketOrderSigningSessionRequest(
            preview_id=preview.preview_id,
            user_confirmed=True,
            live_submission_confirmed=True,
        )
    )
    core_gateway.approved = False
    policy_blocked = service.complete_polymarket_order_signing_session(
        session.session_id,
        CompletePolymarketOrderSigningSessionRequest(signed_order=_signed_order(session)),
    )
    assert policy_blocked.status == "blocked"
    assert policy_blocked.next_action == "restore_spending_authorization"

    core_gateway.approved = True
    service.order_signing_session_file.unlink(missing_ok=True)
    session = service.create_polymarket_order_signing_session(
        CreatePolymarketOrderSigningSessionRequest(
            preview_id=preview.preview_id,
            user_confirmed=True,
            live_submission_confirmed=True,
        )
    )

    signing_url = urlsplit(session.signing_url or "")
    browser_token = parse_qs(signing_url.fragment).get("access_token", [None])[0]
    assert browser_token
    assert not signing_url.query
    persisted = service.get_polymarket_order_signing_session(session.session_id)
    assert persisted is not None
    assert persisted.signing_url is None
    assert browser_token.encode("utf-8") not in signing_database.read_bytes()
    browser_session = service.get_polymarket_order_signing_session_by_capability(
        access_token=browser_token,
        origin="http://127.0.0.1:8042",
    )
    assert browser_session["session_id"] == session.session_id
    assert browser_session["wallet_address"] == (
        "0x2222222222222222222222222222222222222222"
    )

    completed = service.complete_polymarket_order_signing_session_by_capability(
        access_token=browser_token,
        origin="http://127.0.0.1:8042",
        request=CompletePolymarketOrderSigningSessionRequest(
            signed_order=_signed_order(session, raw_deposit_signature=True)
        ),
    )
    assert completed["status"] == "submitted"
    assert completed["execution_id"]
    assert set(completed) == {
        "session_id", "status", "reason", "next_action", "execution_id"
    }
    execution = service.get_execution(completed["execution_id"])
    assert execution is not None
    assert execution.execution_mode == "browser_signed_live"
    assert execution.submitted is True
    assert execution.order_id == PolymarketExecutor.official_order_id(
        session.order_payload
    )
    assert execution.tx_hash == "0xsigned_tx"
    assert core_gateway.policy_calls >= 6

    interrupted = service.create_polymarket_order_signing_session(
        CreatePolymarketOrderSigningSessionRequest(
            preview_id=preview.preview_id,
            user_confirmed=True,
            live_submission_confirmed=True,
        )
    )
    executor.raise_on_submit = True
    try:
        service.complete_polymarket_order_signing_session(
            interrupted.session_id,
            CompletePolymarketOrderSigningSessionRequest(
                signed_order=_signed_order(interrupted)
            ),
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError("simulated submit interruption must propagate")
    claimed = service.get_polymarket_order_signing_session(interrupted.session_id)
    assert claimed is not None
    assert claimed.status == "submitting"
    submit_calls_after_interruption = executor.submit_calls

    executor.raise_on_submit = False
    replayed = service.complete_polymarket_order_signing_session(
        interrupted.session_id,
        CompletePolymarketOrderSigningSessionRequest(
            signed_order=_signed_order(interrupted)
        ),
    )
    assert replayed.status == "submitting"
    assert executor.submit_calls == submit_calls_after_interruption

    print(json.dumps({"status": "ok", "session_id": session.session_id, "execution_id": execution.execution_id}, indent=2))


if __name__ == "__main__":
    main()
