from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from platforms.base import PlatformExecutionResult
from platforms.polymarket.executor import PolymarketExecutor
from services.account_binding_service.schemas import (
    CompletePolymarketBindingSessionRequest,
    CreatePolymarketBindingSessionRequest,
)
from services.account_binding_service.service import (
    PolymarketAccountBindingService,
)
from services.execution_service.service import ExecutionService
from shared.config import AppConfig
from shared.schemas import (
    CompletePolymarketOrderSigningSessionRequest,
    CreatePolymarketOrderSigningSessionRequest,
    ExecutePredictionMarketOrderRequest,
    PredictionMarketOrderPreview,
    UnifiedMarket,
)


USER_ID = "telegram_investor_demo"
AGENT_ID = "agentonomy"
BINDING_ID = "pm_binding_policy_exact"
OWNER = "0x" + "22" * 20
DEPOSIT_WALLET = "0x" + "11" * 20
ATTACKER = "0x" + "99" * 20
POLYGON = "eip155:137"


class _PreviewStore:
    def __init__(self, preview: PredictionMarketOrderPreview) -> None:
        self.preview = preview

    def get_order_preview(
        self, preview_id: str
    ) -> PredictionMarketOrderPreview | None:
        return self.preview if preview_id == self.preview.preview_id else None


class _RecordingCoreGateway:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def create_action_intent(self, payload: dict) -> dict:
        observed = copy.deepcopy(payload)
        self.calls.append(("create_action", observed))
        return {"action_id": f"act_policy_{len(self.calls)}", **observed}

    def evaluate_policy(self, payload: dict) -> dict:
        observed = copy.deepcopy(payload)
        self.calls.append(("evaluate_policy", observed))
        return {
            "policy_decision_id": f"policy_policy_{len(self.calls)}",
            "approved": True,
            "decision": "approved",
            "reason_code": "APPROVED",
            "required_action": None,
            **observed,
        }

    def write_audit_event(self, payload: dict) -> dict:
        observed = copy.deepcopy(payload)
        self.calls.append(("write_audit", observed))
        return {"event_id": f"audit_policy_{len(self.calls)}", **observed}

    def payloads(self, kind: str) -> list[dict]:
        return [payload for call_kind, payload in self.calls if call_kind == kind]

    @property
    def policy_requests(self) -> list[dict]:
        return self.payloads("evaluate_policy")


class _BindingGateway:
    def __init__(self, binding: dict | None) -> None:
        self.binding = binding
        self.calls: list[str] = []

    def latest_polymarket_binding(self, user_id: str) -> dict | None:
        self.calls.append(user_id)
        return copy.deepcopy(self.binding)


class _IdentityGateway:
    def __init__(self, wallet: str | None = OWNER) -> None:
        self.wallet = wallet
        self.calls: list[str] = []

    def active_wallet(self, user_id: str) -> str | None:
        self.calls.append(user_id)
        return self.wallet


class _FundingGateway:
    def __init__(
        self,
        expected_amount_usd: str = "1.00",
        *,
        expected_binding_id: str = BINDING_ID,
        expected_venue_wallet: str = DEPOSIT_WALLET,
    ) -> None:
        self.expected_amount_usd = expected_amount_usd
        self.expected_binding_id = expected_binding_id
        self.expected_venue_wallet = expected_venue_wallet

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
        assert user_id == USER_ID
        assert platform == "polymarket"
        assert amount_usd == self.expected_amount_usd
        assert funding_operation_id == "funding-policy-exact"
        assert binding_id == self.expected_binding_id
        assert venue_wallet_address == self.expected_venue_wallet
        expected_amount = Decimal(self.expected_amount_usd)
        return {
            "ready": True,
            "status": "ready",
            "funding_operation_id": funding_operation_id,
            "funding_proof": {
                "operation_id": funding_operation_id,
                "user_id": user_id,
                "binding_id": binding_id,
                "venue_wallet_address": venue_wallet_address,
                "bridge_address": "0x" + "44" * 20,
                "status": "finalized",
                "amount_usdc": format(expected_amount, ".6f"),
                "resource": "polygon:usdc",
                "core_state": "finalized",
                "bridge_status": "COMPLETED",
                "venue_buying_power_before_atomic": "0",
                "venue_buying_power_after_atomic": str(
                    int(expected_amount * Decimal("1000000"))
                ),
                "reservation_id": "reservation-policy-exact",
                "audit_event_id": "audit-policy-exact",
                "core_tx_hash": "0x" + "44" * 32,
            },
        }


class _ReadyPolymarketExecutor(PolymarketExecutor):
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def readiness(self, user_id: str | None = None) -> PlatformExecutionResult:
        return PlatformExecutionResult(
            platform="polymarket", ready=True, status="ready"
        )


class _BindingClobAuthClient:
    def get_server_time(self) -> str:
        return "1780000000"

    def derive_api_credentials(
        self,
        *,
        wallet_address: str,
        signature: str,
        timestamp: str,
        nonce: int,
    ) -> dict[str, str]:
        del wallet_address, timestamp, nonce
        assert signature == "0xclobauth"
        return {
            "apiKey": "pm-contract-key",
            "secret": "pm-contract-secret",
            "passphrase": "pm-contract-passphrase",
        }


def _binding() -> dict:
    return {
        "binding_id": BINDING_ID,
        "user_id": USER_ID,
        "status": "active",
        "wallet_address": OWNER,
        "polymarket_deposit_wallet": DEPOSIT_WALLET,
        "funder_address": DEPOSIT_WALLET,
        "account_mode": "deposit_wallet",
        "polymarket_signature_type": "3",
        "api_key_fingerprint": "sha256:test-only",
    }


def _preview(amount_usd: str = "1.00") -> PredictionMarketOrderPreview:
    market = UnifiedMarket(
        platform="polymarket",
        market_id="market-policy-exact",
        title="Will the policy binding contract pass?",
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
    return PredictionMarketOrderPreview(
        preview_id="preview-policy-exact",
        user_id=USER_ID,
        agent_id=AGENT_ID,
        platform="polymarket",
        market_id=market.market_id,
        title=market.title,
        outcome="Yes",
        side="buy",
        amount_usd=amount_usd,
        limit_price=0.2,
        estimated_contracts=5,
        max_slippage_bps=0,
        max_slippage_usd="0.00",
        worst_case_price=0.2,
        state="confirmation_required",
        next_action="request_user_confirmation",
        live_mode=True,
        core_action_id="preview-action",
        core_policy_decision_id="preview-policy",
        market=market,
        metadata={"funding_operation_id": "funding-policy-exact"},
        created_at="2026-08-20T00:00:00Z",
        expires_at="2099-01-01T00:00:00Z",
    )


def _service(
    tmp_path: Path,
    *,
    binding: dict | None,
    amount_usd: str = "1.00",
    identity_wallet: str = OWNER,
) -> tuple[ExecutionService, _RecordingCoreGateway, _BindingGateway]:
    config = AppConfig(
        live_mode=True,
        polymarket_execution_mode="browser_signed",
        order_signing_session_file=str(tmp_path / "signing.jsonl"),
        execution_file=str(tmp_path / "executions.jsonl"),
        ledger_db_file=str(tmp_path / "ledger.sqlite3"),
    )
    core = _RecordingCoreGateway()
    bindings = _BindingGateway(binding)
    service = ExecutionService(
        config=config,
        preview_store=_PreviewStore(_preview(amount_usd)),
        executors={"polymarket": _ReadyPolymarketExecutor(config)},
        core_gateway=core,
        funding_gateway=_FundingGateway(
            amount_usd,
            expected_binding_id=str(
                (binding or {}).get("binding_id") or BINDING_ID
            ),
            expected_venue_wallet=str(
                (binding or {}).get("polymarket_deposit_wallet")
                or DEPOSIT_WALLET
            ),
        ),
        account_binding_gateway=bindings,
        account_identity_gateway=_IdentityGateway(identity_wallet),
    )
    return service, core, bindings


def _create_request(**metadata: str) -> CreatePolymarketOrderSigningSessionRequest:
    return CreatePolymarketOrderSigningSessionRequest(
        preview_id="preview-policy-exact",
        user_confirmed=True,
        live_submission_confirmed=True,
        metadata=metadata,
    )


def test_execution_readiness_has_no_static_order_cap(tmp_path: Path) -> None:
    service, _core, _bindings = _service(tmp_path, binding=_binding())

    readiness = service.check_readiness()

    assert "PREDICTION_MARKETS_MAX_ORDER_USD" not in readiness.configured
    assert not hasattr(readiness, "max_order_usd")


def test_exact_amount_reaches_core_without_static_order_cap(tmp_path: Path) -> None:
    service, core, _bindings = _service(
        tmp_path,
        binding=_binding(),
        amount_usd="25",
    )

    session = service.create_polymarket_order_signing_session(_create_request())

    assert session.status == "pending_browser_signature"
    assert core.policy_requests[-1]["amount_usdc"] == "25"
    assert "exceeds max order" not in str(session.reason or "")


def test_account_binding_checksum_output_satisfies_execution_binding_contract(
    tmp_path: Path,
) -> None:
    owner = Account.from_key("0x" + "11" * 32)
    checksum_deposit_wallet = "0x52908400098527886E0F7030069857D2E4169EE7"
    binding_service = PolymarketAccountBindingService(
        config=AppConfig(
            account_binding_file=str(tmp_path / "bindings.jsonl"),
            credential_store_file=str(tmp_path / "credentials.jsonl"),
            account_binding_console_base_url="http://127.0.0.1:8047",
        ),
        clob_auth_client=_BindingClobAuthClient(),
    )
    binding_session = binding_service.create_binding_session(
        CreatePolymarketBindingSessionRequest(
            user_id=USER_ID,
            wallet_address=owner.address,
            polymarket_deposit_wallet=checksum_deposit_wallet,
        )
    )
    owner_signature = Account.sign_message(
        encode_defunct(text=binding_session.message_to_sign),
        owner.key,
    ).signature.hex()
    completed = binding_service.complete_binding_session(
        binding_session.session_id,
        CompletePolymarketBindingSessionRequest(
            wallet_address=owner.address,
            signature=owner_signature,
            signed_message=binding_session.message_to_sign,
            clob_auth_signature="0xclobauth",
            clob_auth_timestamp="1780000000",
        ),
    )
    binding = binding_service.get_binding(str(completed.binding_id))

    assert owner.address != owner.address.lower()
    assert binding is not None
    assert binding.wallet_address == owner.address.lower()
    assert binding.polymarket_deposit_wallet == checksum_deposit_wallet.lower()
    assert binding.funder_address == checksum_deposit_wallet.lower()

    execution_service, core, _bindings = _service(
        tmp_path / "execution",
        binding=binding.model_dump(),
        identity_wallet=owner.address.lower(),
    )
    order_session = execution_service.create_polymarket_order_signing_session(
        _create_request()
    )

    assert order_session.status == "pending_browser_signature"
    assert core.policy_requests[-1]["target_address"] == (
        checksum_deposit_wallet.lower()
    )


@pytest.mark.parametrize("amount_usd", ["0", "not-a-decimal"])
def test_invalid_order_amount_is_rejected_before_external_execution(
    tmp_path: Path,
    amount_usd: str,
) -> None:
    service, core, bindings = _service(
        tmp_path,
        binding=_binding(),
        amount_usd=amount_usd,
    )

    session = service.create_polymarket_order_signing_session(_create_request())

    assert session.status == "blocked"
    assert session.next_action == "create_order_preview"
    assert core.calls == []
    assert bindings.calls == []


def _assert_real_core_accepts_contract(
    tmp_path: Path, *, action_payload: dict, policy_payload: dict
) -> None:
    core_root = Path(__file__).resolve().parents[2] / "core"
    script = """
import json
import sys
from datetime import UTC, datetime, timedelta
from services.action_service.schemas import CreateActionIntentRequest
from services.action_service.service import ActionService
from services.policy_service.risk_provider import RiskProviderResult
from services.policy_service.schemas import EvaluateActionPolicyRequest
from services.policy_service.service import PolicyService
from shared.config import AppConfig

class AllowRiskProvider:
    def assess(self, *, subject, network, asset="USDC"):
        assessed_at = datetime.now(UTC)
        return RiskProviderResult(
            provider="misttrack",
            endpoint="v2/risk_score",
            subject=subject,
            network=network,
            asset=asset,
            coin="USDC-Polygon" if network == "eip155:137" else "USDC-Base",
            score=10,
            risk_level="low",
            indicators=(),
            risk_details=(),
            hacking_event=None,
            assessed_at=assessed_at,
            expires_at=assessed_at + timedelta(minutes=5),
            response_sha256="a" * 64,
        )

payload = json.load(sys.stdin)
config = AppConfig(
    funding_database_url=payload["database_url"],
    risk_provider="misttrack",
    risk_mode="enforce",
    misttrack_api_key="test-only-key",
)
action = ActionService(config=config).create_intent(
    CreateActionIntentRequest(**payload["action"])
)
policy_request = dict(payload["policy"])
policy_request["action_id"] = action.action_id
decision = PolicyService(
    config=config,
    risk_provider=AllowRiskProvider(),
).evaluate(EvaluateActionPolicyRequest(**policy_request))
print(json.dumps({
    "approved": decision.approved,
    "decision": decision.decision,
    "reason_code": decision.reason_code,
    "target_address": decision.target_address,
    "chain": decision.chain,
    "metadata": decision.metadata,
}))
"""
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(core_root),
    }
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=core_root,
        env=env,
        input=json.dumps(
            {
                "database_url": (
                    f"sqlite+pysqlite:///{tmp_path / 'real-core.sqlite3'}"
                ),
                "action": action_payload,
                "policy": policy_payload,
            }
        ),
        text=True,
        capture_output=True,
        check=True,
    )
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result == {
        "approved": True,
        "decision": "approved",
        "reason_code": "APPROVED",
        "target_address": DEPOSIT_WALLET,
        "chain": POLYGON,
        "metadata": action_payload["metadata"],
    }


def test_browser_session_binds_exact_server_destination_to_real_core_policy(
    tmp_path: Path,
) -> None:
    service, core, _bindings = _service(tmp_path, binding=_binding())

    session = service.create_polymarket_order_signing_session(
        _create_request(
            destination=ATTACKER,
            network="eip155:8453",
            browser_note="investor demo",
        )
    )

    assert session.status == "pending_browser_signature"
    action = core.payloads("create_action")[0]
    policy = core.payloads("evaluate_policy")[0]
    assert action["metadata"]["destination"] == DEPOSIT_WALLET
    assert action["metadata"]["network"] == POLYGON
    assert action["metadata"]["browser_note"] == "investor demo"
    assert policy["target_address"] == DEPOSIT_WALLET
    assert policy["chain"] == POLYGON
    assert policy["metadata"] == action["metadata"]
    _assert_real_core_accepts_contract(
        tmp_path,
        action_payload=action,
        policy_payload=policy,
    )


@pytest.mark.parametrize(
    ("case", "binding", "expected_next_action"),
    [
        ("missing", None, "create_polymarket_account_binding"),
        (
            "stale",
            {**_binding(), "status": "revoked"},
            "complete_polymarket_account_binding",
        ),
        (
            "wrong_user",
            {**_binding(), "user_id": "telegram_other"},
            "complete_polymarket_account_binding",
        ),
        (
            "missing_user",
            {key: value for key, value in _binding().items() if key != "user_id"},
            "complete_polymarket_account_binding",
        ),
        (
            "wrong_type3",
            {**_binding(), "polymarket_signature_type": "1"},
            "complete_polymarket_account_binding",
        ),
        (
            "wrong_mode",
            {**_binding(), "account_mode": "proxy"},
            "complete_polymarket_account_binding",
        ),
        (
            "funder_deposit_drift",
            {**_binding(), "funder_address": "0x" + "33" * 20},
            "complete_polymarket_account_binding",
        ),
    ],
)
def test_invalid_polymarket_binding_blocks_before_any_core_mutation(
    tmp_path: Path,
    case: str,
    binding: dict | None,
    expected_next_action: str,
) -> None:
    del case
    service, core, _bindings = _service(tmp_path, binding=binding)

    session = service.create_polymarket_order_signing_session(_create_request())

    assert session.status == "blocked"
    assert session.next_action == expected_next_action
    assert core.calls == []


def test_completion_reuses_locked_active_binding_for_second_policy_evaluation(
    tmp_path: Path,
) -> None:
    service, core, bindings = _service(tmp_path, binding=_binding())
    session = service.create_polymarket_order_signing_session(
        _create_request(destination=ATTACKER, network="eip155:8453")
    )
    initial_call_count = len(core.calls)

    completed = service.complete_polymarket_order_signing_session(
        session.session_id,
        CompletePolymarketOrderSigningSessionRequest(
            signed_order={"order": {}, "orderType": "GTC"},
            metadata={"destination": ATTACKER, "network": "eip155:8453"},
        ),
    )

    assert completed.status == "blocked"
    assert len(bindings.calls) >= 2
    assert len(core.calls) > initial_call_count
    actions = core.payloads("create_action")
    policies = core.payloads("evaluate_policy")
    assert len(actions) == len(policies) == 2
    assert policies[1]["target_address"] == DEPOSIT_WALLET
    assert policies[1]["chain"] == POLYGON
    assert policies[1]["metadata"] == actions[1]["metadata"]

    second_service, second_core, second_bindings = _service(
        tmp_path / "stale", binding=_binding()
    )
    stale_session = second_service.create_polymarket_order_signing_session(
        _create_request()
    )
    calls_before_stale_completion = len(second_core.calls)
    second_bindings.binding = {
        **_binding(),
        "binding_id": "pm_binding_replaced",
    }

    stale = second_service.complete_polymarket_order_signing_session(
        stale_session.session_id,
        CompletePolymarketOrderSigningSessionRequest(
            signed_order={"order": {}, "orderType": "GTC"}
        ),
    )

    assert stale.status == "blocked"
    assert len(second_core.calls) == calls_before_stale_completion


def test_direct_polymarket_execution_without_exact_binding_has_zero_core_mutation(
    tmp_path: Path,
) -> None:
    service, core, _bindings = _service(tmp_path, binding=None)

    result = service.execute_order_preview(
        ExecutePredictionMarketOrderRequest(
            preview_id="preview-policy-exact",
            user_confirmed=True,
            live_submission_confirmed=True,
        )
    )

    assert result.state == "blocked"
    assert result.next_action == "create_polymarket_account_binding"
    assert core.calls == []
