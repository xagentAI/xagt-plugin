from __future__ import annotations

import json
import hashlib
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from platforms.base import ExecutionAdapter, PlatformExecutionResult
from platforms.kalshi.executor import KalshiExecutor
from platforms.polymarket.executor import PolymarketExecutor
from platforms.polymarket.order_v2 import (
    OrderProjection,
    OrderProjectionError,
    build_order_projection,
    wrap_deposit_wallet_signature,
    validate_signed_order,
)
from services.execution_service.repository import (
    OrderSigningSessionRepositoryError,
    build_order_signing_session_repository,
)
from services.preview_service.service import CoreGateway, HttpCoreGateway, PreviewService
from shared.config import AppConfig
from shared.core_account_client import CoreAccountClient, CoreAccountClientError
from shared.core_http import core_request_headers
from shared.schemas import (
    CompletePolymarketOrderSigningSessionRequest,
    CreatePolymarketOrderSigningSessionRequest,
    ExecutePredictionMarketOrderRequest,
    ExecutionReadiness,
    PlatformExecutionReadiness,
    PolymarketOrderSigningSession,
    PredictionMarketExecution,
    PredictionMarketOrderPreview,
)
from storage.live_trading_repository import (
    LiveTradingRepositoryError,
    build_live_trading_repository,
)


_POLYMARKET_POLICY_NETWORK = "eip155:137"
_POLYMARKET_DIRECT_FUNDING_ACTION = (
    "fund_polymarket_from_spending_authorization"
)


class OrderSigningCapabilityError(ValueError):
    """A browser capability could not authorize an order-signing session."""


class OrderSigningPayloadError(ValueError):
    """A browser-supplied signature did not match the approved projection."""


class FundingGateway(Protocol):
    def get_funding_readiness(
        self,
        user_id: str,
        platform: str,
        amount_usd: str,
        *,
        funding_operation_id: str | None = None,
        binding_id: str | None = None,
        venue_wallet_address: str | None = None,
    ) -> dict[str, Any]:
        ...


class AccountBindingGateway(Protocol):
    def latest_polymarket_binding(self, user_id: str) -> dict[str, Any] | None:
        ...


class AccountIdentityGateway(Protocol):
    def active_wallet(self, user_id: str) -> str | None:
        ...


class HttpAccountIdentityGateway:
    def __init__(self, config: AppConfig) -> None:
        self.client = CoreAccountClient(
            config.clink_core_account_service_url,
            config.clink_core_internal_api_token,
        )

    def active_wallet(self, user_id: str) -> str | None:
        try:
            readiness = self.client.readiness(user_id)
        except CoreAccountClientError as exc:
            raise RuntimeError(str(exc)) from exc
        if not readiness.get("wallet_bound"):
            return None
        return str(readiness.get("wallet_address") or "").strip().lower() or None


class HttpAccountBindingGateway:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def latest_polymarket_binding(self, user_id: str) -> dict[str, Any] | None:
        request = urllib.request.Request(
            f"{self.config.account_binding_url}/internal/polymarket/bindings/latest/{user_id}",
            headers=core_request_headers(self.config),
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            detail = exc.read().decode("utf-8")
            raise RuntimeError(f"account binding service returned {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"account binding service unavailable: {exc}") from exc
        return payload if payload.get("status") == "active" else None


class HttpFundingGateway:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def get_funding_readiness(
        self,
        user_id: str,
        platform: str,
        amount_usd: str,
        *,
        funding_operation_id: str | None = None,
        binding_id: str | None = None,
        venue_wallet_address: str | None = None,
    ) -> dict[str, Any]:
        if platform != "polymarket":
            return {
                "ready": False,
                "status": "unsupported_platform",
                "reason": "funding adapter currently supports Polymarket only",
                "next_action": "choose_supported_funding_platform",
            }
        if not funding_operation_id:
            return {
                "ready": False,
                "status": "funding_operation_required",
                "reason": "an explicit Polymarket funding operation is required",
                "next_action": _POLYMARKET_DIRECT_FUNDING_ACTION,
            }
        if (
            not isinstance(binding_id, str)
            or not binding_id.strip()
            or not self._is_canonical_address(venue_wallet_address)
        ):
            return self._funding_not_ready(funding_operation_id)
        operation_path = urllib.parse.quote(str(funding_operation_id), safe="")
        query = urllib.parse.urlencode({"user_id": user_id})
        try:
            operation = self._request_json(
                f"{self.config.funding_adapter_url}/polymarket/funding-operations/"
                f"{operation_path}?{query}"
            )
        except Exception:
            return {
                "ready": False,
                "status": "funding_adapter_unavailable",
                "reason": "funding operation proof is unavailable",
                "next_action": "start_funding_adapter_service",
            }
        if not isinstance(operation, dict):
            return self._funding_not_ready(funding_operation_id)
        operation_status = operation.get("status")
        funded_amount = self._parse_optional_decimal(operation.get("amount_usdc"))
        amount_required = self._parse_optional_decimal(amount_usd)
        buying_power_after = self._parse_uint256(
            operation.get("venue_buying_power_after_atomic")
        )
        required_atomic: int | None = None
        if amount_required is not None and amount_required >= Decimal("0"):
            scaled_amount = amount_required * Decimal("1000000")
            if scaled_amount == scaled_amount.to_integral_value():
                required_atomic = int(scaled_amount)
        proof = {
            "operation_id": operation.get("operation_id"),
            "user_id": operation.get("user_id"),
            "binding_id": operation.get("binding_id"),
            "venue_wallet_address": operation.get("venue_wallet_address"),
            "bridge_address": operation.get("bridge_address"),
            "status": operation_status,
            "amount_usdc": operation.get("amount_usdc"),
            "resource": operation.get("resource"),
            "core_state": operation.get("core_state"),
            "bridge_status": operation.get("bridge_status"),
            "venue_buying_power_before_atomic": operation.get(
                "venue_buying_power_before_atomic"
            ),
            "venue_buying_power_after_atomic": operation.get(
                "venue_buying_power_after_atomic"
            ),
            "reservation_id": operation.get("reservation_id"),
            "audit_event_id": operation.get("audit_event_id"),
            "core_tx_hash": operation.get("core_tx_hash"),
        }
        proof_complete = bool(
            operation.get("operation_id") == funding_operation_id
            and operation.get("user_id") == user_id
            and operation.get("binding_id") == binding_id
            and operation.get("venue_wallet_address") == venue_wallet_address
            and self._is_canonical_address(operation.get("bridge_address"))
            and operation_status == "finalized"
            and operation.get("core_state") == "finalized"
            and operation.get("bridge_status") == "COMPLETED"
            and self._is_canonical_id(operation.get("reservation_id"))
            and self._is_canonical_id(operation.get("audit_event_id"))
            and self._is_canonical_hash(operation.get("core_tx_hash"))
            and self._is_canonical_uint256(
                operation.get("venue_buying_power_before_atomic")
            )
            and buying_power_after is not None
            and required_atomic is not None
            and buying_power_after >= required_atomic
            and isinstance(operation.get("resource"), str)
            and bool(operation.get("resource"))
        )
        ready = bool(
            proof_complete
            and funded_amount is not None
            and amount_required is not None
            and funded_amount >= amount_required
        )
        pending = operation_status not in {"finalized", "failed", "released"}
        return {
            "ready": ready,
            "status": "ready" if ready else ("pending" if pending else "funding_not_ready"),
            "funding_operation_id": funding_operation_id,
            "funding_proof": proof if ready else None,
            "operation_status": operation_status,
            "funded_amount_usdc": (
                str(funded_amount) if funded_amount is not None else None
            ),
            "amount_usd": amount_usd,
            "chain_status": operation.get("core_state"),
            "bridge_status": operation.get("bridge_status"),
            "buying_power_status": "verified" if proof_complete else "pending",
            "reservation_status": (
                "recorded" if operation.get("reservation_id") else "pending"
            ),
            "audit_status": (
                "recorded" if operation.get("audit_event_id") else "pending"
            ),
            "next_action": (
                "execute_prediction_market_order_preview"
                if ready
                else _POLYMARKET_DIRECT_FUNDING_ACTION
            ),
        }

    @staticmethod
    def _funding_not_ready(funding_operation_id: str) -> dict[str, Any]:
        return {
            "ready": False,
            "status": "funding_not_ready",
            "reason": "funding operation proof does not match account scope",
            "funding_operation_id": funding_operation_id,
            "next_action": _POLYMARKET_DIRECT_FUNDING_ACTION,
        }

    @staticmethod
    def _is_canonical_address(value: Any) -> bool:
        return bool(
            isinstance(value, str)
            and value != "0x" + "0" * 40
            and re.fullmatch(r"0x[0-9a-f]{40}", value)
        )

    @staticmethod
    def _is_canonical_hash(value: Any) -> bool:
        return bool(
            isinstance(value, str)
            and re.fullmatch(r"0x[0-9a-f]{64}", value)
        )

    @staticmethod
    def _is_canonical_id(value: Any) -> bool:
        return bool(
            isinstance(value, str)
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:@/-]{0,95}", value)
        )

    @staticmethod
    def _is_canonical_uint256(value: Any) -> bool:
        return bool(
            isinstance(value, str)
            and re.fullmatch(r"(?:0|[1-9][0-9]{0,77})", value)
            and int(value) < 2**256
        )

    @classmethod
    def _parse_uint256(cls, value: Any) -> int | None:
        return int(value) if cls._is_canonical_uint256(value) else None

    def _request_json(self, url: str) -> dict[str, Any]:
        token = self.config.prediction_markets_internal_api_token.strip()
        if not token:
            raise RuntimeError(
                "PREDICTION_MARKETS_INTERNAL_API_TOKEN is required for funding adapter requests"
            )
        request = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {token}"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(
                f"funding operation returned HTTP {exc.code}"
            ) from exc
        except (urllib.error.URLError, json.JSONDecodeError) as exc:
            raise RuntimeError("funding operation is unavailable") from exc

    @staticmethod
    def _parse_optional_decimal(value: Any) -> Decimal | None:
        if not isinstance(value, str):
            return None
        try:
            parsed = Decimal(value)
        except (InvalidOperation, ValueError):
            return None
        return parsed if parsed.is_finite() else None


class ExecutionService:
    def __init__(
        self,
        config: AppConfig | None = None,
        preview_store: Any | None = None,
        executors: dict[str, ExecutionAdapter] | None = None,
        core_gateway: CoreGateway | None = None,
        funding_gateway: FundingGateway | None = None,
        account_binding_gateway: AccountBindingGateway | None = None,
        account_identity_gateway: AccountIdentityGateway | None = None,
        storage_file: Path | str | None = None,
        order_signing_session_repository: Any | None = None,
        live_trading_repository: Any | None = None,
    ) -> None:
        self.config = config or AppConfig.from_env()
        self.preview_store = preview_store or PreviewService(config=self.config)
        self.core_gateway = core_gateway or HttpCoreGateway(self.config)
        self.funding_gateway = funding_gateway or HttpFundingGateway(self.config)
        self.account_binding_gateway = account_binding_gateway or HttpAccountBindingGateway(self.config)
        self.account_identity_gateway = account_identity_gateway or HttpAccountIdentityGateway(self.config)
        self.executors = executors or {
            "polymarket": PolymarketExecutor(self.config),
            "kalshi": KalshiExecutor(self.config),
        }
        self.storage_file = Path(storage_file or self.config.execution_file)
        self.order_signing_session_file = Path(self.config.order_signing_session_file)
        self.order_signing_session_repository = (
            order_signing_session_repository
            or build_order_signing_session_repository(self.config)
        )
        self.live_trading_repository = live_trading_repository

    def check_readiness(self) -> ExecutionReadiness:
        missing: list[str] = []
        warnings: list[str] = []
        platforms: dict[str, PlatformExecutionReadiness] = {}
        if not self.config.live_mode:
            missing.append("PREDICTION_MARKETS_LIVE_MODE=true")
        if self.config.require_user_confirmation is not True:
            missing.append("PREDICTION_MARKETS_REQUIRE_USER_CONFIRMATION=true")
        for platform, executor in self.executors.items():
            result = executor.readiness()
            platforms[platform] = PlatformExecutionReadiness(
                platform=platform,
                ready=result.ready,
                missing=result.missing,
                warnings=result.warnings,
                status=result.status,
                metadata=result.metadata,
            )
        live_capable_platform_ready = any(platform.ready for platform in platforms.values())
        if not live_capable_platform_ready:
            missing.append("at least one live platform executor must be ready")
        return ExecutionReadiness(
            live_ready=not missing,
            live_mode_enabled=self.config.live_mode,
            missing=missing,
            warnings=warnings,
            platforms=platforms,
            next_action="execute_prediction_market_order_preview" if not missing else "configure_live_execution",
            configured={
                "PREDICTION_MARKETS_LIVE_MODE": self.config.live_mode,
                "PREDICTION_MARKETS_REQUIRE_USER_CONFIRMATION": self.config.require_user_confirmation,
            },
        )

    def execute_order_preview(self, request: ExecutePredictionMarketOrderRequest) -> PredictionMarketExecution:
        now = self._utc_now()
        preview = self.preview_store.get_order_preview(request.preview_id)
        if preview is None:
            execution = self._build_execution(request, None, now, "blocked", "blocked", False, "order preview not found", "create_order_preview")
            self._save(execution)
            return execution

        blocked_reason, next_action = self._blocking_reason(preview, request, now)
        if blocked_reason:
            execution = self._build_execution(request, preview, now, "blocked", "blocked", False, blocked_reason, next_action)
            self._save(execution)
            return execution

        executor = self.executors.get(preview.platform)
        if executor is None:
            execution = self._build_execution(request, preview, now, "blocked", "not_supported", False, f"platform {preview.platform} is not supported", "choose_supported_platform")
            self._save(execution)
            return execution

        binding = None
        binding_metadata = None
        if preview.platform == "polymarket":
            (
                binding,
                binding_metadata,
                binding_reason,
                binding_next_action,
            ) = self._polymarket_execution_binding(str(preview.user_id or ""))
            if binding_reason:
                execution = self._build_execution(
                    request,
                    preview,
                    now,
                    "blocked",
                    "blocked",
                    False,
                    binding_reason,
                    binding_next_action,
                )
                self._save(execution)
                return execution

        core_context = self._evaluate_core_execution_policy(
            preview,
            request,
            binding=binding,
        )
        policy = core_context["policy"]
        if not policy.get("approved"):
            reason_code = policy.get("reason_code", "POLICY_BLOCKED")
            reason = f"execution blocked by Clink Core policy: {reason_code}"
            next_action = policy.get("required_action") or "resolve_policy_block"
            execution = self._build_execution(
                request,
                preview,
                now,
                "blocked",
                "blocked",
                False,
                reason,
                next_action,
                core_context=core_context,
            )
            self._save(execution)
            return execution

        if not self.config.live_mode:
            execution = self._build_execution(
                request,
                preview,
                now,
                "simulated_live_execution",
                "dry_run",
                False,
                "PREDICTION_MARKETS_LIVE_MODE is false; no live order was submitted",
                "enable_live_mode_for_real_execution",
                core_context=core_context,
            )
            self._save(execution)
            return execution

        funding_context = self._funding_execution_gate(
            preview,
            binding=binding_metadata,
        )
        if funding_context and not funding_context.get("ready"):
            execution = self._build_execution(
                request,
                preview,
                now,
                "blocked",
                "blocked",
                False,
                funding_context.get("reason") or f"funding is {funding_context.get('status', 'not ready')}",
                funding_context.get("next_action") or "complete_funding_before_execution",
                core_context=core_context,
                funding_context=funding_context,
            )
            self._save(execution)
            return execution

        result = executor.submit_order(preview)
        if result.status == "not_supported":
            execution = self._build_execution(request, preview, now, "blocked", "not_supported", False, result.reason, "choose_supported_platform", platform_result=result, core_context=core_context)
            self._save(execution)
            return execution
        if not result.submitted:
            execution = self._build_execution(request, preview, now, "failed" if result.ready else "blocked", "live", False, result.reason or "platform execution failed", "inspect_execution_error", platform_result=result, core_context=core_context)
            self._save(execution)
            return execution
        execution = self._build_execution(
            request,
            preview,
            now,
            "submitted",
            "live",
            True,
            f"{preview.platform} order submitted with status {result.status or 'submitted'}",
            "monitor_order_status",
            order_id=result.order_id,
            tx_hash=result.tx_hash,
            platform_result=result,
            core_context=core_context,
        )
        self._save(execution)
        return execution

    def create_polymarket_order_signing_session(
        self,
        request: CreatePolymarketOrderSigningSessionRequest,
    ) -> PolymarketOrderSigningSession:
        now = self._utc_now()
        preview = self.preview_store.get_order_preview(request.preview_id)
        if preview is None:
            session = self._build_signing_session(request, None, now, "blocked", "order preview not found", "create_prediction_market_order_preview")
            self._save_order_signing_session(session)
            return session
        if preview.platform != "polymarket":
            session = self._build_signing_session(request, preview, now, "blocked", "browser signing is currently supported for Polymarket only", "choose_polymarket_preview")
            self._save_order_signing_session(session)
            return session

        execute_request = ExecutePredictionMarketOrderRequest(
            preview_id=request.preview_id,
            user_confirmed=request.user_confirmed,
            live_submission_confirmed=request.live_submission_confirmed,
            confirmation_message=request.confirmation_message,
            metadata=request.metadata,
        )
        blocked_reason, next_action = self._blocking_reason(preview, execute_request, now)
        if blocked_reason:
            session = self._build_signing_session(request, preview, now, "blocked", blocked_reason, next_action)
            self._save_order_signing_session(session)
            return session

        token_id = PolymarketExecutor._resolve_token_id(preview)
        if not token_id:
            session = self._build_signing_session(request, preview, now, "blocked", "Polymarket CLOB token_id is missing from order preview", "refresh_market_context")
            self._save_order_signing_session(session)
            return session

        (
            binding,
            binding_metadata,
            binding_reason,
            binding_next_action,
        ) = self._polymarket_execution_binding(str(preview.user_id or ""))
        if binding_reason:
            session = self._build_signing_session(
                request,
                preview,
                now,
                "blocked",
                binding_reason,
                binding_next_action,
                metadata=(
                    {"polymarket_account_binding": binding_metadata}
                    if binding_metadata
                    else None
                ),
            )
            self._save_order_signing_session(session)
            return session

        core_context = self._evaluate_core_execution_policy(
            preview,
            execute_request,
            binding=binding,
        )
        policy = core_context["policy"]
        if not policy.get("approved"):
            reason_code = policy.get("reason_code", "POLICY_BLOCKED")
            session = self._build_signing_session(
                request,
                preview,
                now,
                "blocked",
                f"execution blocked by Clink Core policy: {reason_code}",
                policy.get("required_action") or "resolve_policy_block",
                core_context=core_context,
                metadata={"polymarket_account_binding": binding_metadata},
            )
            self._save_order_signing_session(session)
            return session

        funding_context = self._funding_execution_gate(
            preview,
            binding=binding_metadata,
        )
        if (
            not funding_context
            or not funding_context.get("ready")
            or not isinstance(funding_context.get("funding_proof"), dict)
        ):
            session = self._build_signing_session(
                request,
                preview,
                now,
                "blocked",
                (funding_context or {}).get("reason")
                or "an explicit finalized funding operation is required",
                (funding_context or {}).get("next_action")
                or "complete_funding_before_execution",
                core_context=core_context,
                metadata={
                    "polymarket_account_binding": binding_metadata,
                    "funding_readiness": funding_context,
                },
            )
            self._save_order_signing_session(session)
            return session

        try:
            session = self._build_signing_session(
                request,
                preview,
                now,
                "pending_browser_signature",
                None,
                "open_polymarket_order_signing_url",
                core_context=core_context,
                token_id=token_id,
                metadata={
                    "polymarket_account_binding": binding_metadata,
                    "funding_proof": funding_context["funding_proof"],
                },
            )
        except OrderProjectionError:
            session = self._build_signing_session(
                request,
                preview,
                now,
                "blocked",
                "current Polymarket order constraints are unavailable",
                "refresh_market_context",
                core_context=core_context,
                metadata={"polymarket_account_binding": binding_metadata},
            )
        self._save_order_signing_session(session)
        return session

    def complete_polymarket_order_signing_session(
        self,
        session_id: str,
        request: CompletePolymarketOrderSigningSessionRequest,
    ) -> PolymarketOrderSigningSession:
        session = self.get_polymarket_order_signing_session(session_id)
        now = self._utc_now()
        if session is None:
            raise ValueError(f"order signing session not found: {session_id}")
        if session.status in {"submitting", "unknown"}:
            return self._reconcile_order_signing_session(session, now)
        if session.status != "pending_browser_signature":
            return session
        if session.expires_at and self._parse_time(session.expires_at) <= now:
            updated = session.model_copy(update={"status": "expired", "reason": "order signing session expired", "next_action": "create_polymarket_order_signing_session", "completed_at": self._format_time(now)})
            return self._persist_order_signing_terminal(session, updated)

        executor = self.executors.get("polymarket")
        if not isinstance(executor, PolymarketExecutor):
            updated = session.model_copy(update={"status": "failed", "reason": "Polymarket executor is unavailable", "next_action": "inspect_execution_service", "completed_at": self._format_time(now)})
            return self._persist_order_signing_terminal(session, updated)

        binding_metadata = session.metadata.get("polymarket_account_binding") or {}
        (
            active_binding,
            active_binding_metadata,
            binding_reason,
            binding_next_action,
        ) = self._polymarket_execution_binding(str(session.user_id or ""))
        if binding_reason:
            return self._block_order_signing_session(
                session,
                now,
                binding_reason,
                binding_next_action,
            )
        if not self._polymarket_binding_scopes_match(
            binding_id=str(session.binding_id or ""),
            stored_binding=binding_metadata,
            active_binding=active_binding_metadata or {},
        ):
            return self._block_order_signing_session(
                session,
                now,
                "Polymarket account binding is no longer active for this order",
                "complete_polymarket_account_binding",
            )

        preview = self.preview_store.get_order_preview(session.preview_id)
        if preview is None:
            return self._block_order_signing_session(
                session, now, "order preview is no longer available", "create_prediction_market_order_preview"
            )
        execute_request = ExecutePredictionMarketOrderRequest(
            preview_id=preview.preview_id,
            user_confirmed=True,
            live_submission_confirmed=True,
            confirmation_message="browser wallet signed the approved Polymarket order",
            metadata={
                **request.metadata,
                **session.metadata,
                "order_signing_session_id": session.session_id,
            },
        )
        core_context = self._evaluate_core_execution_policy(
            preview,
            execute_request,
            binding=active_binding,
        )
        policy = core_context["policy"]
        if not policy.get("approved"):
            reason_code = policy.get("reason_code", "POLICY_BLOCKED")
            return self._block_order_signing_session(
                session,
                now,
                f"execution blocked by Clink Core policy: {reason_code}",
                policy.get("required_action") or "resolve_policy_block",
                core_context=core_context,
            )
        funding_context = self._funding_execution_gate(
            preview,
            binding=binding_metadata,
        )
        if (
            not funding_context
            or not funding_context.get("ready")
            or not isinstance(session.metadata.get("funding_proof"), dict)
            or funding_context.get("funding_proof")
            != session.metadata.get("funding_proof")
        ):
            return self._block_order_signing_session(
                session,
                now,
                (funding_context or {}).get("reason")
                or "funding authorization is no longer ready",
                (funding_context or {}).get("next_action")
                or "restore_funding_authorization",
                core_context=core_context,
            )
        signed_order_reason = self._signed_order_mismatch_reason(session, request)
        if signed_order_reason:
            return self._block_order_signing_session(
                session,
                now,
                signed_order_reason,
                "sign_exact_approved_order",
                core_context=core_context,
            )

        submitting = session.model_copy(
            update={
                "status": "submitting",
                "reason": "order submission outcome is pending",
                "next_action": "check_polymarket_order_signing_session",
                "signed_order": request.signed_order,
                "core_action_id": core_context["action_id"],
                "core_policy_decision_id": policy.get("policy_decision_id"),
                "core_audit_event_ids": [
                    *session.core_audit_event_ids,
                    *core_context.get("audit_event_ids", []),
                ],
                "metadata": {**request.metadata, **session.metadata},
                "event_log": [
                    *session.event_log,
                    {
                        "event": "polymarket_order_signing_session_submission_claimed",
                        "status": "submitting",
                        "created_at": self._format_time(now),
                    },
                ],
            }
        )
        claimed = self.order_signing_session_repository.claim_for_submission(
            session_id=session.session_id,
            expected_revision=session.revision,
            replacement=submitting,
        )
        if claimed is None:
            current = self.get_polymarket_order_signing_session(session.session_id)
            if current is None:
                raise OrderSigningSessionRepositoryError(
                    "order signing session record is unavailable"
                )
            return current

        binding_scope = claimed.metadata.get("polymarket_account_binding") or {}
        venue_wallet = str(
            binding_scope.get("funder_address")
            or binding_scope.get("polymarket_deposit_wallet")
            or ""
        ).lower()
        owner_wallet = str(binding_scope.get("wallet_address") or "").lower()
        submission = executor.submit_signed_order
        funding_operation_id = str(
            claimed.order_payload.get("provenance", {}).get(
                "funding_operation_id"
            )
            or ""
        ).strip()
        if not funding_operation_id or funding_operation_id == "unassigned":
            updated = claimed.model_copy(
                update={
                    "status": "failed",
                    "reason": "live trading funding provenance is unavailable",
                    "next_action": "restore_funding_authorization",
                    "completed_at": self._format_time(now),
                }
            )
            return self._persist_order_signing_terminal(claimed, updated)
        try:
            client_order_id = executor.official_order_id(claimed.order_payload)
            live_repository = self._live_trading_repository()
            live_intent = live_repository.create_submission_intent(
                signing_session_id=claimed.session_id,
                user_id=str(claimed.user_id or ""),
                binding_id=str(claimed.binding_id or ""),
                wallet_address=venue_wallet,
                client_order_id=client_order_id,
                projection_hash=str(claimed.projection_hash or ""),
                funding_operation_id=funding_operation_id,
            )
            live_claim = live_repository.claim_submission(
                signing_session_id=claimed.session_id,
                expected_revision=live_intent.revision,
            )
        except (LiveTradingRepositoryError, ValueError):
            updated = claimed.model_copy(
                update={
                    "status": "failed",
                    "reason": "live trading submission could not be persisted",
                    "next_action": "inspect_execution_service",
                    "completed_at": self._format_time(now),
                }
            )
            return self._persist_order_signing_terminal(claimed, updated)
        if live_claim is None:
            updated = claimed.model_copy(
                update={
                    "status": "unknown",
                    "reason": "order submission outcome is pending reconciliation",
                    "next_action": "check_polymarket_order_signing_session",
                    "completed_at": self._format_time(now),
                }
            )
            return self._persist_order_signing_terminal(claimed, updated)
        result = submission(
            request.signed_order.get("order") or request.signed_order,
            request.order_type or claimed.order_type or "FAK",
            user_id=claimed.user_id,
            binding_id=claimed.binding_id,
            owner_address=owner_wallet,
            wallet_address=venue_wallet,
            client_order_id=client_order_id,
            order_projection=claimed.order_payload,
        )
        live_status = (
            "submitted"
            if result.submitted
            else "unknown"
            if result.status == "unknown"
            else "rejected"
            if result.status == "rejected"
            else "unknown"
        )
        try:
            persisted_live = live_repository.record_submission_result(
                signing_session_id=claimed.session_id,
                expected_revision=live_claim.revision,
                submission_status=live_status,
                order_id=client_order_id if result.submitted else None,
            )
        except LiveTradingRepositoryError:
            unknown = claimed.model_copy(
                update={
                    "status": "unknown",
                    "reason": "order submission outcome is pending reconciliation",
                    "next_action": "check_polymarket_order_signing_session",
                    "completed_at": self._format_time(now),
                }
            )
            return self._persist_order_signing_terminal(claimed, unknown)
        if persisted_live is None:
            persisted_live = live_repository.get_submission(
                signing_session_id=claimed.session_id,
                user_id=str(claimed.user_id or ""),
                binding_id=str(claimed.binding_id or ""),
                wallet_address=venue_wallet,
            )
        if (
            persisted_live is None
            or persisted_live.submission_status != live_status
            or (
                live_status == "submitted"
                and persisted_live.order_id != client_order_id
            )
        ):
            unknown = claimed.model_copy(
                update={
                    "status": "unknown",
                    "reason": "order submission outcome is pending reconciliation",
                    "next_action": "check_polymarket_order_signing_session",
                    "completed_at": self._format_time(now),
                }
            )
            return self._persist_order_signing_terminal(claimed, unknown)
        execution = self._execution_from_signed_order_session(
            claimed,
            request,
            result,
            now,
            live_record=persisted_live,
        )
        self._save(execution)
        status = (
            "submitted"
            if result.submitted
            else "unknown"
            if result.status == "unknown"
            else "failed"
        )
        updated = claimed.model_copy(
            update={
                "status": status,
                "reason": execution.reason,
                "next_action": execution.next_action,
                "signed_order": request.signed_order,
                "execution_id": execution.execution_id,
                "completed_at": self._format_time(now),
                "metadata": {**claimed.metadata, **request.metadata, "platform_result": result.model_dump()},
                "event_log": [
                    *claimed.event_log,
                    {
                        "event": "polymarket_order_signing_session_completed",
                        "status": status,
                        "execution_id": execution.execution_id,
                        "created_at": self._format_time(now),
                    },
                ],
            }
        )
        return self._persist_order_signing_terminal(claimed, updated)

    def _block_order_signing_session(
        self,
        session: PolymarketOrderSigningSession,
        now: datetime,
        reason: str,
        next_action: str,
        *,
        core_context: dict[str, Any] | None = None,
    ) -> PolymarketOrderSigningSession:
        updated = session.model_copy(
            update={
                "status": "blocked",
                "reason": reason,
                "next_action": next_action,
                "core_action_id": core_context["action_id"] if core_context else session.core_action_id,
                "core_policy_decision_id": (
                    core_context["policy"].get("policy_decision_id")
                    if core_context
                    else session.core_policy_decision_id
                ),
                "core_audit_event_ids": [
                    *session.core_audit_event_ids,
                    *(core_context.get("audit_event_ids", []) if core_context else []),
                ],
                "completed_at": self._format_time(now),
                "event_log": [
                    *session.event_log,
                    {
                        "event": "polymarket_order_signing_session_blocked",
                        "reason": reason,
                        "created_at": self._format_time(now),
                    },
                ],
            }
        )
        return self._persist_order_signing_terminal(session, updated)

    def _persist_order_signing_terminal(
        self,
        current: PolymarketOrderSigningSession,
        replacement: PolymarketOrderSigningSession,
    ) -> PolymarketOrderSigningSession:
        persisted = self.order_signing_session_repository.compare_and_set_terminal(
            session_id=current.session_id,
            expected_revision=current.revision,
            replacement=replacement,
        )
        if persisted is not None:
            return persisted
        latest = self.get_polymarket_order_signing_session(current.session_id)
        if latest is None:
            raise OrderSigningSessionRepositoryError(
                "order signing session record is unavailable"
            )
        return latest

    def _signed_order_mismatch_reason(
        self,
        session: PolymarketOrderSigningSession,
        request: CompletePolymarketOrderSigningSessionRequest,
    ) -> str | None:
        if session.order_payload.get("projection_sha256"):
            stored = dict(session.order_payload)
            stored_hash = stored.pop("projection_sha256", None)
            canonical = json.dumps(
                stored, sort_keys=True, separators=(",", ":"), ensure_ascii=True
            )
            if hashlib.sha256(canonical.encode("utf-8")).hexdigest() != stored_hash:
                return "stored V2 order projection is invalid"
            projection = OrderProjection(
                canonical_json=canonical,
                projection_sha256=str(stored_hash),
            )
            try:
                validate_signed_order(projection, request.signed_order)
            except OrderProjectionError:
                return "signed order does not match the immutable V2 projection"
            if request.order_type and request.order_type != stored.get("orderType"):
                return "signed order type does not match the approved session"
            return None
        order = request.signed_order.get("order") or request.signed_order

        def value(*names: str) -> Any:
            for name in names:
                if name in order:
                    return order[name]
            return None

        if request.order_type and request.order_type != session.order_type:
            return "signed order type does not match the approved session"
        if str(value("tokenId", "tokenID", "asset_id") or "") != str(session.token_id or ""):
            return "signed order token does not match the approved session"
        expected_side = 0 if (session.side or "buy").lower() == "buy" else 1
        submitted_side = value("side")
        normalized_side = {"BUY": 0, "SELL": 1, "buy": 0, "sell": 1}.get(
            submitted_side, submitted_side
        )
        try:
            if int(normalized_side) != expected_side:
                return "signed order side does not match the approved session"
        except (TypeError, ValueError):
            return "signed order side is missing or invalid"
        binding = session.metadata.get("polymarket_account_binding") or {}
        expected_maker = str(binding.get("funder_address") or "").lower()
        expected_signer = str(binding.get("wallet_address") or "").lower()
        if str(value("maker") or "").lower() != expected_maker:
            return "signed order maker does not match the approved Polymarket account"
        if str(value("signer") or "").lower() != expected_signer:
            return "signed order signer does not match the active Core wallet"
        try:
            expected_signature_type = int(binding.get("polymarket_signature_type") or 0)
            if int(value("signatureType", "signature_type")) != expected_signature_type:
                return "signed order signature type does not match the approved account"
            maker_amount = Decimal(str(value("makerAmount", "maker_amount"))) / Decimal(1_000_000)
            taker_amount = Decimal(str(value("takerAmount", "taker_amount"))) / Decimal(1_000_000)
            approved_price = Decimal(str(session.order_payload.get("price")))
            approved_quantity = (
                Decimal(str(session.order_payload.get("amount")))
                if expected_side == 0
                else Decimal(str(session.order_payload.get("size")))
            )
        except (InvalidOperation, TypeError, ValueError):
            return "signed order economic fields are missing or invalid"
        if maker_amount <= 0 or taker_amount <= 0:
            return "signed order amounts must be positive"
        submitted_price = maker_amount / taker_amount if expected_side == 0 else taker_amount / maker_amount
        submitted_quantity = maker_amount if expected_side == 0 else maker_amount
        if abs(submitted_quantity - approved_quantity) > Decimal("0.01"):
            return "signed order quantity exceeds the approved session"
        if abs(submitted_price - approved_price) > Decimal("0.001"):
            return "signed order price does not match the approved session"
        if not value("signature"):
            return "signed order signature is missing"
        return None

    def get_polymarket_order_signing_session(self, session_id: str) -> PolymarketOrderSigningSession | None:
        return self.order_signing_session_repository.get(session_id)

    def get_polymarket_order_signing_session_by_capability(
        self,
        *,
        access_token: str,
        origin: str,
        status_only: bool = False,
    ) -> dict[str, Any]:
        session = self._authorized_order_signing_session(
            access_token=access_token,
            origin=origin,
        )
        if status_only and session.status in {"submitting", "unknown"}:
            session = self._reconcile_order_signing_session(
                session,
                self._utc_now(),
            )
        if status_only:
            return {
                "session_id": session.session_id,
                "status": session.status,
                "reason": session.reason,
                "next_action": session.next_action,
                "execution_id": session.execution_id,
            }
        binding = session.metadata.get("polymarket_account_binding") or {}
        display = session.metadata.get("browser_order_display") or {}
        return {
            "session_id": session.session_id,
            "status": session.status,
            "reason": session.reason,
            "next_action": session.next_action,
            "title": session.title,
            "outcome": session.outcome,
            "side": session.side,
            "amount_usd": session.amount_usd,
            "limit_price": session.limit_price,
            "worst_case_price": display.get("worst_case_price")
            or session.limit_price,
            "max_slippage_bps": display.get("max_slippage_bps", 0),
            "wallet_address": binding.get("wallet_address"),
            "exchange": session.order_payload.get("exchange"),
            "wallet_mode": binding.get("account_mode"),
            "order_payload": session.order_payload,
            "expires_at": session.expires_at,
            "return_url": self._execution_console_origin() + "/",
        }

    def complete_polymarket_order_signing_session_by_capability(
        self,
        *,
        access_token: str,
        origin: str,
        request: CompletePolymarketOrderSigningSessionRequest,
    ) -> dict[str, Any]:
        session = self._authorized_order_signing_session(
            access_token=access_token,
            origin=origin,
        )
        signed_order = json.loads(json.dumps(request.signed_order))
        order = signed_order.get("order") if isinstance(signed_order, dict) else None
        try:
            if (
                isinstance(order, dict)
                and session.order_payload.get("order", {}).get("signatureType") == 3
                and isinstance(order.get("signature"), str)
                and len(order["signature"]) == 132
            ):
                order["signature"] = wrap_deposit_wallet_signature(
                    raw_signature=order["signature"],
                    typed_data=session.order_payload.get("typed_data") or {},
                )
        except OrderProjectionError:
            raise OrderSigningPayloadError("signed order payload is invalid") from None
        authorized_request = request.model_copy(update={"signed_order": signed_order})
        if self._signed_order_mismatch_reason(session, authorized_request):
            raise OrderSigningPayloadError("signed order payload is invalid")
        completed = self.complete_polymarket_order_signing_session(
            session.session_id,
            authorized_request,
        )
        return self._order_signing_status_projection(completed)

    @staticmethod
    def _order_signing_status_projection(
        session: PolymarketOrderSigningSession,
    ) -> dict[str, Any]:
        return {
            "session_id": session.session_id,
            "status": session.status,
            "reason": session.reason,
            "next_action": session.next_action,
            "execution_id": session.execution_id,
        }

    def _authorized_order_signing_session(
        self,
        *,
        access_token: str,
        origin: str,
    ) -> PolymarketOrderSigningSession:
        if (
            not isinstance(access_token, str)
            or len(access_token) < 32
            or len(access_token) > 256
            or origin != self._execution_console_origin()
        ):
            raise OrderSigningCapabilityError("order signing capability is invalid")
        capability_hash = hashlib.sha256(access_token.encode("utf-8")).hexdigest()
        session = self.order_signing_session_repository.get_by_capability(
            capability_hash=capability_hash,
            origin=origin,
        )
        if session is None:
            raise OrderSigningCapabilityError("order signing capability is invalid")
        expires_at = self._parse_time(session.expires_at)
        if expires_at is None or self._utc_now() >= expires_at:
            raise OrderSigningCapabilityError("order signing capability is invalid")
        return session

    def _reconcile_order_signing_session(
        self,
        session: PolymarketOrderSigningSession,
        now: datetime,
    ) -> PolymarketOrderSigningSession:
        executor = self.executors.get("polymarket")
        binding = session.metadata.get("polymarket_account_binding") or {}
        venue_wallet = str(
            binding.get("funder_address")
            or binding.get("polymarket_deposit_wallet")
            or ""
        ).lower()
        owner_wallet = str(binding.get("wallet_address") or "").lower()
        if (
            not isinstance(executor, PolymarketExecutor)
            or not venue_wallet
            or not owner_wallet
            or not self._active_polymarket_binding_matches(
                user_id=str(session.user_id or ""),
                binding_id=str(session.binding_id or ""),
                stored_binding=binding,
            )
        ):
            return session
        try:
            repository = self._live_trading_repository()
            live = repository.get_submission(
                signing_session_id=session.session_id,
                user_id=str(session.user_id or ""),
                binding_id=str(session.binding_id or ""),
                wallet_address=venue_wallet,
            )
        except LiveTradingRepositoryError:
            return session
        if live is None:
            return session
        try:
            result = executor.reconcile_signed_order(
                user_id=str(session.user_id or ""),
                binding_id=str(session.binding_id or ""),
                owner_address=owner_wallet,
                wallet_address=venue_wallet,
                client_order_id=live.client_order_id,
            )
        except Exception:
            return session
        target_status = (
            "submitted"
            if result.submitted
            else "unknown"
            if result.status == "unknown"
            else "rejected"
        )
        if target_status != live.submission_status:
            try:
                reconciled = repository.record_submission_result(
                    signing_session_id=session.session_id,
                    expected_revision=live.revision,
                    submission_status=target_status,
                    order_id=live.client_order_id if result.submitted else None,
                )
                if reconciled is not None:
                    live = reconciled
            except LiveTradingRepositoryError:
                return session
        if not result.submitted:
            return session
        existing_execution = (
            self.get_execution(session.execution_id)
            if session.execution_id
            else None
        )
        recovery_reason = (
            "Polymarket order submission was independently verified"
        )
        if existing_execution is None:
            recovery_request = CompletePolymarketOrderSigningSessionRequest(
                signed_order=session.signed_order or {},
                order_type=session.order_type,
            )
            execution = self._execution_from_signed_order_session(
                session,
                recovery_request,
                result.model_copy(
                    update={
                        "submitted": True,
                        "status": "submitted",
                        "order_id": live.client_order_id,
                        "reason": recovery_reason,
                    }
                ),
                now,
                live_record=live,
            ).model_copy(
                update={
                    "execution_id": (
                        "pm_exec_recovery_"
                        + hashlib.sha256(
                            session.session_id.encode("utf-8")
                        ).hexdigest()[:12]
                    )
                }
            )
        else:
            execution = existing_execution.model_copy(
                update={
                    "state": "submitted",
                    "submitted": True,
                    "order_id": live.client_order_id,
                    "reason": recovery_reason,
                    "next_action": "monitor_order_status",
                    "event_log": [
                        *existing_execution.event_log,
                        {
                            "event": (
                                "prediction_market_browser_signed_execution_reconciled"
                            ),
                            "state": "submitted",
                            "submitted": True,
                            "order_id": live.client_order_id,
                            "created_at": self._format_time(now),
                        },
                    ],
                    "metadata": {
                        **existing_execution.metadata,
                        "platform_result": result.model_dump(),
                        "submission_status": live.submission_status,
                    },
                }
            )
        self._save(execution)
        recovered = session.model_copy(
            update={
                "status": "submitted",
                "reason": recovery_reason,
                "next_action": "monitor_order_status",
                "execution_id": execution.execution_id,
                "completed_at": session.completed_at or self._format_time(now),
                "metadata": {
                    **session.metadata,
                    "submission_status": live.submission_status,
                },
            }
        )
        if session.status in {"submitting", "unknown"}:
            return self._persist_order_signing_terminal(session, recovered)
        return recovered

    def get_execution(self, execution_id: str) -> PredictionMarketExecution | None:
        if not self.storage_file.exists():
            return None
        latest = None
        with self.storage_file.open() as handle:
            for line in handle:
                if not line.strip():
                    continue
                execution = PredictionMarketExecution(**json.loads(line))
                if execution.execution_id == execution_id:
                    latest = execution
        return latest

    def _blocking_reason(
        self,
        preview: PredictionMarketOrderPreview,
        request: ExecutePredictionMarketOrderRequest,
        now: datetime,
    ) -> tuple[str | None, str | None]:
        if self.config.require_user_confirmation and not request.user_confirmed:
            return "user confirmation is required before execution", "request_user_confirmation"
        if self.config.live_mode and not request.live_submission_confirmed:
            return "live submission requires explicit live_submission_confirmed=true", "confirm_live_submission_intent"
        if preview.state == "blocked":
            return "order preview is blocked by policy", "resolve_policy_block"
        if preview.expires_at and self._parse_time(preview.expires_at) <= now:
            return "order preview is expired", "create_order_preview"
        try:
            amount = self._parse_decimal(preview.amount_usd or "0", "amount_usd")
        except ValueError as exc:
            return str(exc), "create_order_preview"
        if amount <= Decimal("0"):
            return "order amount must be greater than 0", "create_order_preview"
        return None, None

    def _build_execution(
        self,
        request: ExecutePredictionMarketOrderRequest,
        preview: PredictionMarketOrderPreview | None,
        now: datetime,
        state: str,
        execution_mode: str,
        submitted: bool,
        reason: str | None,
        next_action: str | None,
        order_id: str | None = None,
        tx_hash: str | None = None,
        platform_result: PlatformExecutionResult | None = None,
        core_context: dict[str, Any] | None = None,
        funding_context: dict[str, Any] | None = None,
    ) -> PredictionMarketExecution:
        metadata = dict(request.metadata or {})
        if platform_result is not None:
            metadata["platform_result"] = platform_result.model_dump()
        if core_context is not None:
            metadata["core_execution_policy"] = core_context["policy"]
        if funding_context is not None:
            metadata["funding_readiness"] = funding_context
        core_action_id = core_context["action_id"] if core_context else preview.core_action_id if preview else None
        core_policy_decision_id = core_context["policy"].get("policy_decision_id") if core_context else preview.core_policy_decision_id if preview else None
        core_audit_event_ids = [
            *(preview.core_audit_event_ids if preview else []),
            *(core_context.get("audit_event_ids", []) if core_context else []),
        ]
        execution = PredictionMarketExecution(
            execution_id=f"pm_exec_{uuid4().hex[:12]}",
            preview_id=request.preview_id,
            user_id=preview.user_id if preview else None,
            agent_id=preview.agent_id if preview else None,
            platform=preview.platform if preview else None,
            market_id=preview.market_id if preview else None,
            title=preview.title if preview else None,
            outcome=preview.outcome if preview else None,
            side=preview.side if preview else None,
            amount_usd=preview.amount_usd if preview else None,
            limit_price=preview.limit_price if preview else None,
            estimated_contracts=preview.estimated_contracts if preview else None,
            state=state,
            execution_mode=execution_mode,
            submitted=submitted,
            live_mode_enabled=self.config.live_mode,
            order_id=order_id,
            tx_hash=tx_hash,
            reason=reason,
            next_action=next_action,
            core_action_id=core_action_id,
            core_policy_decision_id=core_policy_decision_id,
            core_audit_event_ids=core_audit_event_ids,
            created_at=self._format_time(now),
            event_log=[
                {
                    "event": "prediction_market_execution_evaluated",
                    "state": state,
                    "execution_mode": execution_mode,
                    "submitted": submitted,
                    "reason": reason,
                    "order_id": order_id,
                    "tx_hash": tx_hash,
                    "created_at": self._format_time(now),
                }
            ],
            metadata=metadata,
        )
        return execution

    def _build_signing_session(
        self,
        request: CreatePolymarketOrderSigningSessionRequest,
        preview: PredictionMarketOrderPreview | None,
        now: datetime,
        status: str,
        reason: str | None,
        next_action: str | None,
        core_context: dict[str, Any] | None = None,
        token_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PolymarketOrderSigningSession:
        expires_at = now + timedelta(minutes=max(1, request.expires_in_minutes))
        side = preview.side if preview else None
        order_type = "GTC"
        session_id = f"pm_sign_sess_{uuid4().hex[:12]}"
        merged_metadata = {**(request.metadata or {}), **(metadata or {})}
        if preview is not None:
            merged_metadata["browser_order_display"] = {
                "worst_case_price": str(preview.worst_case_price),
                "max_slippage_bps": preview.max_slippage_bps,
            }
            merged_metadata["order_projection_provenance"] = {
                "core_action_id": str(
                    (core_context or {}).get("action_id")
                    or preview.core_action_id
                    or "unassigned"
                ),
                "core_policy_decision_id": str(
                    ((core_context or {}).get("policy") or {}).get(
                        "policy_decision_id"
                    )
                    or preview.core_policy_decision_id
                    or "unassigned"
                ),
                "funding_operation_id": str(
                    preview.metadata.get("funding_operation_id") or "unassigned"
                ),
            }
        order_payload = (
            self._polymarket_order_payload(
                preview,
                token_id,
                order_type,
                merged_metadata,
                session_id=session_id,
                now=now,
            )
            if preview and token_id
            else {}
        )
        event = {
            "event": "polymarket_order_signing_session_created",
            "status": status,
            "reason": reason,
            "created_at": self._format_time(now),
        }
        return PolymarketOrderSigningSession(
            session_id=session_id,
            preview_id=request.preview_id,
            user_id=preview.user_id if preview else None,
            binding_id=(
                ((merged_metadata.get("polymarket_account_binding") or {}).get(
                    "binding_id"
                ))
                if preview
                else None
            ),
            projection_hash=(
                str(order_payload.get("projection_sha256"))
                if order_payload.get("projection_sha256")
                else None
            ),
            agent_id=preview.agent_id if preview else None,
            market_id=preview.market_id if preview else None,
            title=preview.title if preview else None,
            outcome=preview.outcome if preview else None,
            side=preview.side if preview else None,
            amount_usd=preview.amount_usd if preview else None,
            limit_price=preview.limit_price if preview else None,
            order_type=order_type,
            token_id=token_id,
            order_payload=order_payload,
            signing_url=self._polymarket_order_signing_url(session_id) if status == "pending_browser_signature" else None,
            status=status,
            reason=reason,
            next_action=next_action,
            core_action_id=core_context["action_id"] if core_context else preview.core_action_id if preview else None,
            core_policy_decision_id=core_context["policy"].get("policy_decision_id") if core_context else preview.core_policy_decision_id if preview else None,
            core_audit_event_ids=[
                *(preview.core_audit_event_ids if preview else []),
                *(core_context.get("audit_event_ids", []) if core_context else []),
            ],
            created_at=self._format_time(now),
            expires_at=self._format_time(expires_at),
            metadata=merged_metadata,
            event_log=[event],
        )

    def _polymarket_order_payload(
        self,
        preview: PredictionMarketOrderPreview,
        token_id: str,
        order_type: str,
        metadata: dict[str, Any] | None = None,
        *,
        session_id: str,
        now: datetime,
    ) -> dict[str, Any]:
        side = "BUY" if (preview.side or "buy").lower() == "buy" else "SELL"
        binding = (metadata or {}).get("polymarket_account_binding") or {}
        wallet_mode = str(binding.get("account_mode") or "").lower()
        maker = str(
            binding.get("funder_address")
            or binding.get("polymarket_deposit_wallet")
            or ""
        )
        signer = str(binding.get("wallet_address") or "")
        raw = preview.market.raw or {}
        provenance = (metadata or {}).get("order_projection_provenance") or {}
        tick_size = str(raw.get("tickSize") or raw.get("tick_size") or "")
        min_order_size = str(
            raw.get("minOrderSize") or raw.get("min_order_size") or ""
        )
        neg_risk_value = (
            raw.get("negRisk")
            if raw.get("negRisk") is not None
            else raw.get("neg_risk")
        )
        price = Decimal(
            str(
                (preview.worst_case_price or preview.limit_price)
                if side == "BUY"
                else preview.limit_price
            )
        )
        size = (
            Decimal(preview.amount_usd) / price
            if side == "BUY"
            else Decimal(str(preview.estimated_contracts))
        )
        salt = str(int.from_bytes(hashlib.sha256(session_id.encode("utf-8")).digest()[:6]))
        projection = build_order_projection(
            wallet_mode=wallet_mode,
            maker_wallet=maker,
            account_signer=signer,
            token_id=str(token_id),
            side=side,
            price=format(price, "f"),
            size=format(size, "f"),
            tick_size=tick_size,
            min_order_size=min_order_size,
            neg_risk=neg_risk_value,
            salt=salt,
            timestamp_ms=str(int(now.timestamp() * 1000)),
            order_type=order_type,
            expiration="0",
            provenance={
                "preview_id": preview.preview_id,
                "market_id": preview.market_id,
                "core_action_id": str(
                    provenance.get("core_action_id")
                    or preview.core_action_id
                    or "unassigned"
                ),
                "core_policy_decision_id": str(
                    provenance.get("core_policy_decision_id")
                    or preview.core_policy_decision_id
                    or "unassigned"
                ),
                "funding_operation_id": str(
                    provenance.get("funding_operation_id")
                    or preview.metadata.get("funding_operation_id")
                    or "unassigned"
                ),
            },
        )
        return {
            **projection.payload,
            "projection_sha256": projection.projection_sha256,
        }

    def _latest_polymarket_binding(self, user_id: str) -> dict[str, Any] | None:
        if not user_id:
            return None
        try:
            return self.account_binding_gateway.latest_polymarket_binding(user_id)
        except RuntimeError:
            return None

    def _polymarket_execution_binding(
        self,
        user_id: str,
    ) -> tuple[
        dict[str, Any] | None,
        dict[str, Any] | None,
        str | None,
        str,
    ]:
        binding = self._latest_polymarket_binding(user_id)
        if binding is None:
            return (
                None,
                None,
                "Polymarket account binding is missing for this user",
                "create_polymarket_account_binding",
            )
        if self._active_deposit_wallet_binding_reason(user_id, binding):
            return (
                None,
                None,
                "Polymarket account binding is not an active Deposit Wallet binding for this user",
                "complete_polymarket_account_binding",
            )
        binding_metadata = self._public_binding_metadata(binding)
        identity_reason = self._core_wallet_binding_reason(
            user_id,
            binding_metadata or {},
        )
        if identity_reason:
            return (
                None,
                binding_metadata,
                identity_reason,
                "restore_core_wallet_identity",
            )
        return binding, binding_metadata, None, "execute_prediction_market_order_preview"

    @classmethod
    def _active_deposit_wallet_binding_reason(
        cls,
        user_id: str,
        binding: dict[str, Any] | None,
    ) -> str | None:
        if not isinstance(binding, dict):
            return "binding is unavailable"
        if binding.get("status") != "active":
            return "binding is not active"
        if not user_id or binding.get("user_id") != user_id:
            return "binding user does not match"
        binding_id = binding.get("binding_id")
        if not (
            isinstance(binding_id, str)
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:@/-]{0,95}", binding_id)
        ):
            return "binding id is invalid"
        owner = cls._canonical_binding_address(binding.get("wallet_address"))
        deposit_wallet = cls._canonical_binding_address(
            binding.get("polymarket_deposit_wallet")
        )
        funder = cls._canonical_binding_address(binding.get("funder_address"))
        if owner is None:
            return "binding owner wallet is invalid"
        if deposit_wallet is None or funder is None or funder != deposit_wallet:
            return "binding Deposit Wallet is invalid"
        if binding.get("account_mode") != "deposit_wallet":
            return "binding account mode is not Deposit Wallet"
        if str(binding.get("polymarket_signature_type")) != "3":
            return "binding signature type is not POLY_1271"
        return None

    @staticmethod
    def _canonical_binding_address(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip().lower()
        if (
            value != normalized
            or normalized == "0x" + "0" * 40
            or not re.fullmatch(r"0x[0-9a-f]{40}", normalized)
        ):
            return None
        return normalized

    def _core_wallet_binding_reason(self, user_id: str, binding: dict[str, Any]) -> str | None:
        try:
            active_wallet = self.account_identity_gateway.active_wallet(user_id)
        except RuntimeError:
            return "Core Account wallet identity could not be verified"
        binding_wallet = str(binding.get("wallet_address") or "").strip().lower()
        if not active_wallet:
            return "Core Account wallet identity is no longer active"
        if not binding_wallet or binding_wallet != active_wallet.lower():
            return "Polymarket binding wallet does not match the active Core wallet"
        return None

    def _active_polymarket_binding_matches(
        self,
        *,
        user_id: str,
        binding_id: str,
        stored_binding: dict[str, Any],
    ) -> bool:
        _active, active_metadata, reason, _next_action = (
            self._polymarket_execution_binding(user_id)
        )
        if reason or active_metadata is None:
            return False
        return self._polymarket_binding_scopes_match(
            binding_id=binding_id,
            stored_binding=stored_binding,
            active_binding=active_metadata,
        )

    @classmethod
    def _polymarket_binding_scopes_match(
        cls,
        *,
        binding_id: str,
        stored_binding: dict[str, Any],
        active_binding: dict[str, Any],
    ) -> bool:
        stored_wallet = cls._canonical_binding_address(
            stored_binding.get("wallet_address")
        )
        active_wallet = cls._canonical_binding_address(
            active_binding.get("wallet_address")
        )
        stored_deposit = cls._canonical_binding_address(
            stored_binding.get("polymarket_deposit_wallet")
        )
        active_deposit = cls._canonical_binding_address(
            active_binding.get("polymarket_deposit_wallet")
        )
        stored_funder = cls._canonical_binding_address(
            stored_binding.get("funder_address")
        )
        active_funder = cls._canonical_binding_address(
            active_binding.get("funder_address")
        )
        return bool(
            binding_id
            and stored_binding.get("binding_id") == binding_id
            and active_binding.get("binding_id") == binding_id
            and stored_wallet
            and active_wallet == stored_wallet
            and stored_deposit
            and active_deposit == stored_deposit
            and stored_funder
            and active_funder == stored_funder
            and stored_funder == stored_deposit
            and active_funder == active_deposit
            and stored_binding.get("account_mode") == "deposit_wallet"
            and active_binding.get("account_mode") == "deposit_wallet"
            and str(stored_binding.get("polymarket_signature_type")) == "3"
            and str(active_binding.get("polymarket_signature_type")) == "3"
        )

    @staticmethod
    def _public_binding_metadata(binding: dict[str, Any] | None) -> dict[str, Any] | None:
        if not binding:
            return None
        return {
            "binding_id": binding.get("binding_id"),
            "wallet_address": binding.get("wallet_address"),
            "polymarket_deposit_wallet": binding.get("polymarket_deposit_wallet"),
            "funder_address": binding.get("funder_address"),
            "account_mode": binding.get("account_mode") or binding.get("metadata", {}).get("account_mode"),
            "polymarket_signature_type": binding.get("polymarket_signature_type") or binding.get("metadata", {}).get("resolved_signature_type"),
            "api_key_fingerprint": binding.get("api_key_fingerprint"),
        }

    def _execution_from_signed_order_session(
        self,
        session: PolymarketOrderSigningSession,
        request: CompletePolymarketOrderSigningSessionRequest,
        result: PlatformExecutionResult,
        now: datetime,
        *,
        live_record: Any | None = None,
    ) -> PredictionMarketExecution:
        state = (
            "submitted"
            if result.submitted
            else "unknown"
            if result.status == "unknown"
            else "failed"
        )
        reason = (
            f"polymarket browser-signed order submitted with status {result.status or 'submitted'}"
            if result.submitted
            else result.reason or "Polymarket signed order submission failed"
        )
        next_action = (
            "monitor_order_status"
            if result.submitted
            else "check_polymarket_order_signing_session"
            if result.status == "unknown"
            else "inspect_execution_error"
        )
        return PredictionMarketExecution(
            execution_id=f"pm_exec_{uuid4().hex[:12]}",
            preview_id=session.preview_id,
            user_id=session.user_id,
            agent_id=session.agent_id,
            platform="polymarket",
            market_id=session.market_id,
            title=session.title,
            outcome=session.outcome,
            side=session.side,
            amount_usd=session.amount_usd,
            limit_price=session.limit_price,
            state=state,
            execution_mode="browser_signed_live",
            submitted=result.submitted,
            live_mode_enabled=self.config.live_mode,
            order_id=result.order_id,
            tx_hash=result.tx_hash,
            reason=reason,
            next_action=next_action,
            core_action_id=session.core_action_id,
            core_policy_decision_id=session.core_policy_decision_id,
            core_audit_event_ids=session.core_audit_event_ids,
            created_at=self._format_time(now),
            event_log=[
                {
                    "event": "prediction_market_browser_signed_execution_evaluated",
                    "state": state,
                    "execution_mode": "browser_signed_live",
                    "submitted": result.submitted,
                    "reason": reason,
                    "order_id": result.order_id,
                    "tx_hash": result.tx_hash,
                    "created_at": self._format_time(now),
                }
            ],
            metadata={
                **session.metadata,
                **request.metadata,
                "order_signing_session_id": session.session_id,
                "platform_result": result.model_dump(),
                "submission_status": (
                    live_record.submission_status if live_record else state
                ),
            },
        )

    def _live_trading_repository(self):
        if self.live_trading_repository is None:
            self.live_trading_repository = build_live_trading_repository(self.config)
        return self.live_trading_repository

    def _save_order_signing_session(
        self, session: PolymarketOrderSigningSession
    ) -> PolymarketOrderSigningSession:
        if session.status != "pending_browser_signature":
            self.order_signing_session_repository.create(session)
            return session
        access_token = secrets.token_urlsafe(32)
        capability_hash = hashlib.sha256(access_token.encode("utf-8")).hexdigest()
        persisted = session.model_copy(update={"signing_url": None})
        self.order_signing_session_repository.create(
            persisted,
            capability_hash=capability_hash,
            capability_origin=self._execution_console_origin(),
        )
        session.signing_url = (
            f"{self._polymarket_order_signing_url(session.session_id)}"
            f"#access_token={access_token}"
        )
        return session

    def _polymarket_order_signing_url(self, session_id: str) -> str:
        del session_id
        parsed = urllib.parse.urlsplit(
            str(self.config.execution_console_base_url).rstrip("/")
        )
        prefix = parsed.path.rstrip("/")
        if prefix.endswith("/execution"):
            path = f"{prefix}/polymarket/order-signing-console/"
        else:
            path = f"{prefix}/execution/polymarket/order-signing-console/"
        return urllib.parse.urlunsplit(
            (parsed.scheme, parsed.netloc, path, "", "")
        )

    def _execution_console_origin(self) -> str:
        parsed = urllib.parse.urlsplit(str(self.config.execution_console_base_url))
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username
            or parsed.password
        ):
            raise ValueError("execution console public origin is invalid")
        return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"

    def _funding_execution_gate(
        self,
        preview: PredictionMarketOrderPreview,
        *,
        binding: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if (
            preview.platform != "polymarket"
            and not self.config.require_funding_before_execution
        ):
            return None
        if preview.platform == "polymarket":
            binding_scope = binding or self._public_binding_metadata(
                self._latest_polymarket_binding(str(preview.user_id or ""))
            )
            binding_id = str((binding_scope or {}).get("binding_id") or "").strip()
            owner_address = str(
                (binding_scope or {}).get("wallet_address") or ""
            ).strip().lower()
            venue_wallet_address = str(
                (binding_scope or {}).get("funder_address")
                or (binding_scope or {}).get("polymarket_deposit_wallet")
                or ""
            ).strip().lower()
            if not binding_id or not owner_address or not venue_wallet_address:
                return {
                    "ready": False,
                    "status": "funding_not_ready",
                    "reason": "Polymarket funding account scope is unavailable",
                    "next_action": "complete_polymarket_account_binding",
                }
        else:
            binding_id = None
            venue_wallet_address = None
        operation_id = preview.metadata.get("funding_operation_id")
        if preview.platform != "polymarket":
            return self.funding_gateway.get_funding_readiness(
                user_id=preview.user_id,
                platform=preview.platform,
                amount_usd=preview.amount_usd,
                funding_operation_id=(
                    str(operation_id) if operation_id is not None else None
                ),
            )
        return self.funding_gateway.get_funding_readiness(
            user_id=preview.user_id,
            platform=preview.platform,
            amount_usd=preview.amount_usd,
            funding_operation_id=(
                str(operation_id) if operation_id is not None else None
            ),
            binding_id=binding_id,
            venue_wallet_address=venue_wallet_address,
        )

    def _evaluate_core_execution_policy(
        self,
        preview: PredictionMarketOrderPreview,
        request: ExecutePredictionMarketOrderRequest,
        *,
        binding: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        readiness = self.check_readiness()
        platform_readiness = readiness.platforms.get(preview.platform)
        execution_ready = bool(
            platform_readiness and platform_readiness.ready
        ) if self.config.live_mode else True
        action_metadata = {
            "preview_id": preview.preview_id,
            "preview_core_action_id": preview.core_action_id,
            "platform": preview.platform,
            "market_id": preview.market_id,
            "outcome": preview.outcome,
            "side": preview.side,
            "limit_price": preview.limit_price,
            **request.metadata,
        }
        policy_metadata = {
            "preview_id": preview.preview_id,
            "platform": preview.platform,
            "market_id": preview.market_id,
            "execution_ready": execution_ready,
            "platform_readiness": (
                platform_readiness.model_dump() if platform_readiness else None
            ),
            "readiness": readiness.model_dump(),
        }
        target_address = None
        chain = None
        if preview.platform == "polymarket":
            binding_reason = self._active_deposit_wallet_binding_reason(
                str(preview.user_id or ""),
                binding,
            )
            if binding_reason:
                raise ValueError(
                    "an exact active Polymarket Deposit Wallet binding is required"
                )
            target_address = self._canonical_binding_address(
                (binding or {}).get("funder_address")
            )
            if target_address is None:
                raise ValueError(
                    "an exact active Polymarket Deposit Wallet binding is required"
                )
            chain = _POLYMARKET_POLICY_NETWORK
            action_metadata = {
                **action_metadata,
                "execution_ready": execution_ready,
                "platform_readiness": (
                    platform_readiness.model_dump() if platform_readiness else None
                ),
                "readiness": readiness.model_dump(),
                "destination": target_address,
                "network": chain,
            }
            policy_metadata = dict(action_metadata)

        action = self.core_gateway.create_action_intent(
            {
                "user_id": preview.user_id,
                "agent_id": preview.agent_id,
                "action_type": "prediction_market_order_execute",
                "amount_usdc": preview.amount_usd,
                "target": f"{preview.platform}:{preview.market_id}",
                "merchant_id": preview.platform,
                "description": f"Execute prediction market order: {preview.title}",
                "metadata": dict(action_metadata),
            }
        )
        action_id = str(action.get("action_id"))
        audit_requested = self.core_gateway.write_audit_event(
            {
                "event_type": "prediction_market_execution_requested",
                "source_service": "clink-prediction-markets",
                "action_id": action_id,
                "user_id": preview.user_id,
                "agent_id": preview.agent_id,
                "payload": {
                    "preview_id": preview.preview_id,
                    "preview_core_action_id": preview.core_action_id,
                    "platform": preview.platform,
                    "market_id": preview.market_id,
                    "amount_usd": preview.amount_usd,
                    "live_mode": self.config.live_mode,
                    "execution_ready": execution_ready,
                    "platform_readiness": platform_readiness.model_dump() if platform_readiness else None,
                },
            }
        )
        policy = self.core_gateway.evaluate_policy(
            {
                "action_id": action_id,
                "user_id": preview.user_id,
                "agent_id": preview.agent_id,
                "action_type": "prediction_market_order_execute",
                "amount_usdc": preview.amount_usd,
                "merchant_id": preview.platform,
                "target_address": target_address,
                "chain": chain,
                "risk_level": "medium" if self.config.live_mode else "low",
                "risk_score": 60 if self.config.live_mode else 25,
                "risk_action": "approve",
                "user_confirmed": request.user_confirmed,
                "requires_confirmation": self.config.require_user_confirmation,
                "live_mode": self.config.live_mode,
                "metadata": dict(policy_metadata),
            }
        )
        audit_policy = self.core_gateway.write_audit_event(
            {
                "event_type": "prediction_market_execution_policy_evaluated",
                "source_service": "clink-prediction-markets",
                "action_id": action_id,
                "user_id": preview.user_id,
                "agent_id": preview.agent_id,
                "policy_decision_id": policy.get("policy_decision_id"),
                "payload": {"policy": policy},
            }
        )
        return {
            "action_id": action_id,
            "policy": policy,
            "audit_event_ids": [
                str(event.get("event_id"))
                for event in (audit_requested, audit_policy)
                if event.get("event_id")
            ],
        }

    def _save(self, execution: PredictionMarketExecution) -> None:
        self.storage_file.parent.mkdir(parents=True, exist_ok=True)
        with self.storage_file.open("a") as handle:
            handle.write(json.dumps(execution.model_dump(), ensure_ascii=False) + "\n")

    @staticmethod
    def _parse_decimal(value: str, field_name: str) -> Decimal:
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"{field_name} must be a valid decimal string") from exc
        if amount <= Decimal("0"):
            raise ValueError(f"{field_name} must be greater than zero")
        return amount

    @staticmethod
    def _parse_time(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", ""))

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)

    @staticmethod
    def _format_time(value: datetime) -> str:
        return value.isoformat() + "Z"
