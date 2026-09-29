from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from shared.config import AppConfig
from shared.core_http import core_request_headers
from shared.schemas import (
    CreateOrderPreviewRequest,
    PredictionMarketOrderPreview,
)


class CoreGateway(Protocol):
    def create_action_intent(self, payload: dict[str, Any]) -> dict[str, Any]: ...
    def evaluate_policy(self, payload: dict[str, Any]) -> dict[str, Any]: ...
    def write_audit_event(self, payload: dict[str, Any]) -> dict[str, Any]: ...


class HttpCoreGateway:
    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or AppConfig.from_env()

    def create_action_intent(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post_json(f"{self.config.clink_core_action_service_url.rstrip('/')}/actions", payload)

    def evaluate_policy(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post_json(f"{self.config.clink_core_policy_service_url.rstrip('/')}/policies/evaluate", payload)

    def write_audit_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post_json(f"{self.config.clink_core_audit_service_url.rstrip('/')}/audit/events", payload)

    def _post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers=core_request_headers(self.config, json_content=True),
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8")
            raise RuntimeError(f"clink-core request failed: {exc.code} {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"clink-core request failed: {exc}") from exc


class PreviewService:
    def __init__(
        self,
        storage_file: Path | str | None = None,
        core_gateway: CoreGateway | None = None,
        config: AppConfig | None = None,
    ) -> None:
        self.config = config or AppConfig.from_env()
        self.storage_file = Path(storage_file or self.config.preview_file)
        self.core_gateway = core_gateway or HttpCoreGateway(self.config)

    def create_order_preview(self, request: CreateOrderPreviewRequest) -> PredictionMarketOrderPreview:
        amount = self._parse_decimal(request.amount_usd, "amount_usd")
        price = self._select_order_price(request)
        self._validate_slippage(request.max_slippage_bps)
        if not request.market.tradable:
            raise ValueError("market must be tradable before creating an order preview")

        core_action = self._create_core_action(request)
        action_id = str(core_action.get("action_id"))
        policy = self._evaluate_core_policy(request, action_id)
        audit_events = [
            self._write_audit(
                "prediction_market_preview_requested",
                request,
                action_id,
                None,
                {"market": request.market.model_dump()},
            ),
            self._write_audit(
                "prediction_market_policy_evaluated",
                request,
                action_id,
                policy.get("policy_decision_id"),
                {"policy": policy},
            ),
        ]
        audit_event_ids = [str(event.get("event_id")) for event in audit_events if event.get("event_id")]

        state, next_action = self._derive_state(policy)
        now = self._utc_now()
        expires_at = now + timedelta(minutes=10)
        estimated_contracts = amount / price
        slippage_usd = self._slippage_usd(amount, request.max_slippage_bps)
        worst_case_price = self._worst_case_price(price, request.max_slippage_bps)
        venue_metadata = self._venue_order_metadata(request, amount)

        preview = PredictionMarketOrderPreview(
            preview_id=f"pm_preview_{uuid4().hex[:12]}",
            user_id=request.user_id,
            agent_id=request.agent_id,
            platform=request.market.platform,
            market_id=request.market.market_id,
            title=request.market.title,
            outcome=request.outcome,
            side=request.side,
            amount_usd=self._format_decimal(amount),
            limit_price=float(price),
            estimated_contracts=float(estimated_contracts),
            max_slippage_bps=request.max_slippage_bps,
            max_slippage_usd=self._format_decimal(slippage_usd),
            worst_case_price=float(worst_case_price),
            state=state,
            next_action=next_action,
            requires_user_confirmation=request.requires_user_confirmation,
            live_mode=request.live_mode,
            core_action_id=action_id,
            core_policy_decision_id=policy.get("policy_decision_id"),
            core_audit_event_ids=audit_event_ids,
            core_policy_decision=policy,
            market=request.market,
            metadata={**request.metadata, **venue_metadata},
            created_at=self._format_time(now),
            expires_at=self._format_time(expires_at),
            event_log=[
                {"event": "preview_created", "state": state, "created_at": self._format_time(now)},
                {"event": "core_action_created", "action_id": action_id, "created_at": self._format_time(now)},
                {"event": "core_policy_evaluated", "policy_decision_id": policy.get("policy_decision_id"), "created_at": self._format_time(now)},
            ],
        )
        self._save(preview)
        return preview

    def get_order_preview(self, preview_id: str) -> PredictionMarketOrderPreview | None:
        if not self.storage_file.exists():
            return None
        latest = None
        with self.storage_file.open() as handle:
            for line in handle:
                if not line.strip():
                    continue
                preview = PredictionMarketOrderPreview(**json.loads(line))
                if preview.preview_id == preview_id:
                    latest = preview
        return latest

    def _create_core_action(self, request: CreateOrderPreviewRequest) -> dict[str, Any]:
        return self.core_gateway.create_action_intent({
            "user_id": request.user_id,
            "agent_id": request.agent_id,
            "action_type": "prediction_market_order_preview",
            "amount_usdc": request.amount_usd,
            "target": request.market.market_id,
            "merchant_id": request.market.platform,
            "description": request.market.title,
            "metadata": {
                "platform": request.market.platform,
                "market_id": request.market.market_id,
                "outcome": request.outcome,
                "side": request.side,
                **request.metadata,
            },
        })

    def _evaluate_core_policy(self, request: CreateOrderPreviewRequest, action_id: str) -> dict[str, Any]:
        return self.core_gateway.evaluate_policy({
            "action_id": action_id,
            "user_id": request.user_id,
            "agent_id": request.agent_id,
            "action_type": "prediction_market_order_preview",
            "amount_usdc": request.amount_usd,
            "merchant_id": request.market.platform,
            "risk_level": "medium" if request.live_mode else "low",
            "risk_score": 45 if request.live_mode else 20,
            "risk_action": "manual_review" if request.live_mode else "approve",
            "user_confirmed": False,
            "requires_confirmation": request.requires_user_confirmation,
            "live_mode": request.live_mode,
            "metadata": {"platform": request.market.platform, "market_id": request.market.market_id},
        })

    def _write_audit(
        self,
        event_type: str,
        request: CreateOrderPreviewRequest,
        action_id: str,
        policy_decision_id: str | None,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self._write_audit_event(event_type, request.user_id, request.agent_id, action_id, policy_decision_id, payload)

    def _write_audit_event(
        self,
        event_type: str,
        user_id: str,
        agent_id: str,
        action_id: str,
        policy_decision_id: str | None,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self.core_gateway.write_audit_event({
            "event_type": event_type,
            "source_service": "clink-prediction-markets",
            "action_id": action_id,
            "user_id": user_id,
            "agent_id": agent_id,
            "policy_decision_id": policy_decision_id,
            "payload": payload,
        })

    @staticmethod
    def _derive_state(policy: dict[str, Any]) -> tuple[str, str]:
        decision = str(policy.get("decision") or "").lower()
        if decision == "blocked" or policy.get("approved") is False and policy.get("required_action") == "resolve_policy_block":
            return "blocked", str(policy.get("required_action") or "resolve_policy_block")
        if decision in {"needs_confirmation", "review", "manual_review"} or policy.get("required_action"):
            return "confirmation_required", str(policy.get("required_action") or "request_user_confirmation")
        if policy.get("approved") and policy.get("required_action") is None:
            return "confirmation_required", "request_user_confirmation"
        return "confirmation_required", "request_user_confirmation"

    @staticmethod
    def _select_order_price(request: CreateOrderPreviewRequest) -> Decimal:
        explicit = request.limit_price
        if explicit is not None:
            return PreviewService._parse_price(explicit, "limit_price")
        outcome = request.outcome.lower()
        price = request.market.no_price if outcome == "no" else request.market.yes_price
        return PreviewService._parse_price(price, "market price")

    @staticmethod
    def _parse_decimal(value: str, field_name: str) -> Decimal:
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"{field_name} must be a valid decimal") from exc
        if amount <= Decimal("0"):
            raise ValueError(f"{field_name} must be greater than zero")
        return amount

    @staticmethod
    def _parse_price(value: float | str | None, field_name: str) -> Decimal:
        try:
            price = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"{field_name} must be a valid number") from exc
        if price <= Decimal("0") or price >= Decimal("1"):
            raise ValueError(f"{field_name} must be between 0 and 1")
        return price

    @staticmethod
    def _validate_slippage(max_slippage_bps: int) -> None:
        if max_slippage_bps < 0 or max_slippage_bps > 10000:
            raise ValueError("max_slippage_bps must be between 0 and 10000")

    @staticmethod
    def _slippage_usd(amount: Decimal, max_slippage_bps: int) -> Decimal:
        return amount * Decimal(max_slippage_bps) / Decimal("10000")

    @staticmethod
    def _worst_case_price(price: Decimal, max_slippage_bps: int) -> Decimal:
        worst_case_price = price * (Decimal("1") + Decimal(max_slippage_bps) / Decimal("10000"))
        if worst_case_price >= Decimal("1"):
            return Decimal("0.999999")
        return worst_case_price

    @staticmethod
    def _venue_order_metadata(request: CreateOrderPreviewRequest, amount: Decimal) -> dict[str, Any]:
        if request.market.platform != "polymarket":
            return {}
        minimum = PreviewService._polymarket_minimum_order_amount(request.market.raw)
        if minimum is None:
            return {}
        metadata = {"venue_minimum_order_usd": PreviewService._format_decimal(minimum)}
        if amount < minimum:
            metadata.update(
                {
                    "venue_minimum_order_warning": True,
                    "venue_block_reason": f"Polymarket limit orders report a {PreviewService._format_decimal(minimum)} minimum; buy executions use dollar-amount market orders",
                }
            )
        return metadata

    @staticmethod
    def _polymarket_minimum_order_amount(raw: dict[str, Any]) -> Decimal | None:
        for key in ("orderMinSize", "order_min_size", "minOrderSize", "minimum_order_size"):
            value = raw.get(key)
            if value in (None, ""):
                continue
            try:
                minimum = Decimal(str(value))
            except (InvalidOperation, ValueError):
                continue
            return minimum if minimum > 0 else None
        return None

    @staticmethod
    def _format_decimal(value: Decimal) -> str:
        rendered = format(value.quantize(Decimal("0.000001")), "f")
        return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered

    def _save(self, preview: PredictionMarketOrderPreview) -> None:
        self.storage_file.parent.mkdir(parents=True, exist_ok=True)
        with self.storage_file.open("a") as handle:
            handle.write(json.dumps(preview.model_dump(), ensure_ascii=False) + "\n")

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.utcnow()

    @staticmethod
    def _format_time(value: datetime) -> str:
        return value.isoformat() + "Z"
