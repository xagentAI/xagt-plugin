from __future__ import annotations

import asyncio
import copy
import json
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from apps.node.clink_node.adapters.http import DownstreamError
from apps.node.clink_node.agent_access_views import owned_account
from apps.node.clink_node.api import NodeApiContext, create_app
from apps.node.clink_node.config import AgentAccessSettings, NodeSettings, Profile
from apps.node.clink_node.paths import NodePaths
from apps.node.clink_node.projections import build_balance_summary
from apps.node.tests.test_mcp_gateway import NativeBusiness, NativePrediction, NativeRepository
from services.account_service.schemas import SpendingGrant


ROOT = Path(__file__).parents[3]
SAMPLES = ROOT / "docs/development/c-account-state-samples.json"
CONTROL = "synthetic-c-account-control-token"
AGENT_ID = "agent_c_contract_demo"
USER_ID = "agent:v1:c_account_demo"
WALLET_ADDRESS = "0x1111111111111111111111111111111111111111"
WALLET_IDENTITY_ID = "wallet_c_contract_demo"
TOKEN_ADDRESS = "0x41e94eb019c0762f9bfcf9fb1e58725bfb0e7582"
NETWORK = "eip155:80002"
LIMITS = {
    "per_transaction": "1",
    "rolling_hour": "2",
    "daily": "3",
    "total": "5",
}
REMAINING = {"rolling_hour": "1.5", "daily": "2.5", "total": "4.5"}
SUCCESS_CASES = {
    "wallet_unbound",
    "wallet_bound_no_mandate",
    "wallet_mandate_allowance_hosted_ready",
    "wallet_mandate_hosted_enrollment_required",
}


def _samples() -> dict[str, dict[str, Any]]:
    payload = json.loads(SAMPLES.read_text())
    return {sample["case"]: sample for sample in payload["samples"]}


class FixtureCore:
    def __init__(self, case: str) -> None:
        self.case = case

    def account_readiness(self, user_id: str) -> dict[str, Any]:
        bound = self.case != "wallet_unbound"
        active = bound and self.case not in {"wallet_bound_no_mandate"}
        mandate = None
        if active:
            mandate = {
                "spending_grant_id": "grant_c_contract_demo",
                "agent_id": "hermes",
                "limits_usdc": copy.deepcopy(LIMITS),
                "remaining_usdc": copy.deepcopy(REMAINING),
                "product_scopes": ["marketplace", "prediction_markets"],
                "venue_scopes": [],
                "merchant_scopes": [],
                "merchant_trust_scopes": ["clink_verified"],
                "network_scopes": [NETWORK],
                "asset_scopes": [TOKEN_ADDRESS],
                "notification_mode": "notify_all",
                "expires_at": "2026-10-01T00:00:00Z",
            }
        return {
            "user_id": user_id,
            "wallet_bound": bound,
            "wallet_address": WALLET_ADDRESS if bound else None,
            "wallet_identity_id": WALLET_IDENTITY_ID if bound else None,
            "spending_grant_active": active,
            "active_spending_mandate": mandate,
            "chain_allowances": {NETWORK: active},
            "ready": active,
        }

    def wallet_balances(self, user_id: str) -> dict[str, Any]:
        if self.case == "wallet_unbound":
            return {
                "user_id": user_id,
                "status": "not_bound",
                "wallet_bound": False,
                "wallet_address": None,
                "balances": {},
            }
        return {
            "user_id": user_id,
            "status": "ready",
            "wallet_bound": True,
            "wallet_address": WALLET_ADDRESS,
            "balances": {
                NETWORK: {
                    "status": "ready",
                    "network": NETWORK,
                    "asset": "USDC",
                    "token_address": TOKEN_ADDRESS,
                    "amount_atomic": "12500000",
                    "amount_usdc": "12.500000",
                }
            },
        }

    def hosted_wallet_readiness(self, user_id: str) -> dict[str, Any]:
        reason = (
            "WALLET_NOT_READY"
            if self.case == "wallet_unbound"
            else "HOSTED_ENROLLMENT_REQUIRED"
            if self.case == "wallet_mandate_hosted_enrollment_required"
            else None
        )
        return {
            "user_id": user_id,
            "ready": reason is None,
            "credential_routing": "per_wallet",
            "reason_code": reason,
        }


class FixturePrediction(NativePrediction):
    def __init__(self, case: str) -> None:
        super().__init__("prediction-markets")
        self.case = case

    def account_status(self, user_id: str) -> dict[str, Any]:
        if self.case in {
            "wallet_unbound",
            "wallet_bound_no_mandate",
            "wallet_mandate_allowance_hosted_ready",
        }:
            return {
                "user_id": user_id,
                "status": "not_configured",
                "next_action": "create_polymarket_account_binding",
            }
        return {
            "user_id": user_id,
            "binding_id": "binding_c_contract_demo",
            "status": "active",
            "wallet_address": WALLET_ADDRESS,
            "has_api_credentials": True,
        }

    def account_balance(self, user_id: str) -> dict[str, Any]:
        if self.case != "wallet_mandate_hosted_enrollment_required":
            raise DownstreamError("prediction", 503, "synthetic venue outage")
        return {
            "status": "ready",
            "user_id": user_id,
            "venue": "polymarket",
            "venue_wallet_address": "0x2222222222222222222222222222222222222222",
            "asset": "USDC",
            "available_amount_atomic": "2000000",
            "available_amount_usdc": "2.000000",
        }


def _projected_body(sample: dict[str, Any]) -> dict[str, Any]:
    body = sample["body"]
    user_id = USER_ID
    context = SimpleNamespace(
        core=FixtureCore(sample["case"]),
        prediction_markets=FixturePrediction(sample["case"]),
    )
    return {
        "agent_id": AGENT_ID,
        "account": owned_account(context, user_id),
        "balances": build_balance_summary(
            context.core,
            context.prediction_markets,
            user_id,
            strict_owner=True,
        ),
        "permissions_editable_by_agent": False,
    }


@pytest.mark.parametrize("case", sorted(SUCCESS_CASES))
def test_success_samples_equal_current_node_projections(case: str) -> None:
    sample = _samples()[case]
    assert sample["http_status"] == 200
    assert _projected_body(sample) == sample["body"]


def test_ready_sample_mandate_uses_core_canonical_scope_types() -> None:
    samples = _samples()
    mandate = samples["wallet_mandate_allowance_hosted_ready"]["body"]["account"]["core"][
        "active_spending_mandate"
    ]
    grant = SpendingGrant(
        spending_grant_id=mandate["spending_grant_id"],
        wallet_identity_id=WALLET_IDENTITY_ID,
        user_id=USER_ID,
        agent_id=mandate["agent_id"],
        status="active",
        max_amount_usdc=Decimal(mandate["limits_usdc"]["total"]),
        per_transaction_limit_usdc=Decimal(mandate["limits_usdc"]["per_transaction"]),
        hourly_limit_usdc=Decimal(mandate["limits_usdc"]["rolling_hour"]),
        daily_limit_usdc=Decimal(mandate["limits_usdc"]["daily"]),
        product_scopes=mandate["product_scopes"],
        venue_scopes=mandate["venue_scopes"],
        merchant_scopes=mandate["merchant_scopes"],
        merchant_trust_scopes=mandate["merchant_trust_scopes"],
        network_scopes=mandate["network_scopes"],
        asset_scopes=mandate["asset_scopes"],
        starts_at=datetime(2026, 9, 1, tzinfo=UTC),
        expires_at=datetime.fromisoformat(mandate["expires_at"].replace("Z", "+00:00")),
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
        updated_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    assert grant.asset_scopes == [TOKEN_ADDRESS]
    assert grant.merchant_trust_scopes == ["clink_verified"]


class UnavailableCore(FixtureCore):
    def account_readiness(self, user_id: str) -> dict[str, Any]:
        raise DownstreamError("core", 503, "synthetic Core outage")


class FixtureAccessService:
    def __init__(self, user_id: str) -> None:
        self.user_id = user_id

    def get_agent(self, agent_id: str) -> SimpleNamespace:
        return SimpleNamespace(agent_id=agent_id, user_id=self.user_id)


def test_core_unavailable_sample_is_the_actual_c_account_http_error() -> None:
    sample = _samples()["core_unavailable"]
    expected = sample["body"]

    async def scenario() -> None:
        user_id = USER_ID
        settings = replace(
            NodeSettings.defaults(
                Profile.SERVER,
                paths=NodePaths.from_home(Path("/tmp/c-account-sample-test")),
            ),
            agent_access=AgentAccessSettings(
                True,
                "synthetic-c-account-issuer",
                "https://agents.example/mcp",
            ),
        )
        context = NodeApiContext(
            settings=settings,
            repository=NativeRepository(),
            interaction_service=None,
            session_token="synthetic-session",
            core=UnavailableCore("core_unavailable"),
            marketplace=NativeBusiness("marketplace"),
            prediction_markets=FixturePrediction("core_unavailable"),
            agent_access_service=FixtureAccessService(user_id),
            agent_control_token=CONTROL,
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(context)),
            base_url="http://127.0.0.1",
        ) as client:
            response = await client.get(
                "/v1/c/agents/agent_c_contract_demo/account",
                headers={"Authorization": "Bearer " + CONTROL},
            )
        assert response.status_code == sample["http_status"]
        assert response.json() == expected

    asyncio.run(scenario())
