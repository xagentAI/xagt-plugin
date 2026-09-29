import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4

import redis

from services.policy_service.schemas import EvaluateActionPolicyRequest, PolicyDecision
from services.policy_service.misttrack import (
    MistTrackProvider,
    _read_response_chunk,
    _set_response_read_timeout,
)
from services.policy_service.risk_cache import (
    InMemoryRiskCache,
    RedisRiskCache,
    RiskCache,
)
from services.policy_service.risk_rate_limiter import (
    RedisRiskRateLimiter,
    RiskRateLimiter,
)
from services.policy_service.risk_policy import map_risk_result
from services.policy_service.risk_provider import RiskProvider, RiskProviderError
from services.action_policy_repository import ActionPolicyRepository
from services.action_service.service import ActionService
from services.account_service.schemas import canonicalize_evm_address
from shared.canonical_assets import AMOY_NETWORK, POLYGON_NETWORK
from shared.config import AppConfig


class PolicyService:
    """Evaluates whether an agent action can proceed under Clink Core policy."""

    SAFE_RISK_PROVIDER_ERROR_CATEGORIES = frozenset(
        {
            "configuration",
            "invalid_address",
            "invalid_key",
            "invalid_response",
            "not_configured",
            "payment_required",
            "plan_expired",
            "provider_error",
            "rate_limited",
            "unavailable",
            "unsupported_asset",
            "unsupported_network",
        }
    )
    BLOCKING_RISK_ACTIONS = {"reject", "block", "blocked", "deny"}
    REVIEW_RISK_ACTIONS = {"manual_review", "review"}
    BLOCKING_RISK_LEVELS = {"high", "critical"}
    PREDICTION_MARKET_PREVIEW_ACTION_TYPES = {
        "prediction_market_order_preview",
    }
    PREDICTION_MARKET_EXECUTE_ACTION_TYPES = {
        "prediction_market_order_execute",
    }
    RISK_PROVIDER_ACTION_TYPES = {
        "service_purchase",
        "market_trade",
        "data_purchase",
        "subscription",
        "refund",
        "funding_transfer",
        "marketplace_purchase",
        *PREDICTION_MARKET_EXECUTE_ACTION_TYPES,
    }
    FUNDABLE_ACTION_TYPES = {
        "funding_transfer",
        "marketplace_purchase",
        *PREDICTION_MARKET_EXECUTE_ACTION_TYPES,
    }
    SUPPORTED_ACTION_TYPES = {
        "service_purchase",
        "market_trade",
        "data_purchase",
        "subscription",
        "refund",
        "dispute",
        "funding_transfer",
        "marketplace_purchase",
        *PREDICTION_MARKET_PREVIEW_ACTION_TYPES,
        *PREDICTION_MARKET_EXECUTE_ACTION_TYPES,
    }
    REDIS_RISK_CACHE_KEY_PREFIX = "clink:core:risk:misttrack:v1"
    RISK_READINESS_RESPONSE_LIMIT_BYTES = 4096

    def __init__(
        self,
        config: AppConfig | None = None,
        storage_file: Path | str | None = None,
        risk_provider: RiskProvider | None = None,
        risk_rate_limiter: RiskRateLimiter | None = None,
    ) -> None:
        self.config = config or AppConfig.from_env()
        self.legacy_storage_file = Path(storage_file) if storage_file is not None else None
        self.repository = ActionPolicyRepository(self.config.funding_database_url)
        self.risk_rate_limiter = risk_rate_limiter
        self.risk_provider = (
            risk_provider
            if risk_provider is not None
            else self._build_risk_provider()
        )

    def evaluate(self, request: EvaluateActionPolicyRequest) -> PolicyDecision:
        now = self._utc_now()
        reasons: list[str] = []
        events: list[dict] = [
            {
                "event": "policy_evaluation_started",
                "created_at": self._format_time(now),
                "action_type": request.action_type,
            }
        ]
        decision = "approved"
        reason_code = "APPROVED"
        required_action: str | None = None
        authorization_approved: bool | None = None
        remaining_amount_usdc: str | None = None
        risk_assessment: dict | None = None

        bound_request, binding_error = self._bind_fundable_payment_request(request)
        if binding_error is not None:
            return self._finalize_decision(
                request=request.model_copy(
                    update={"target_address": None, "chain": None}
                ),
                now=now,
                approved=False,
                decision="blocked",
                reason_code="PAYMENT_TARGET_BINDING_REQUIRED",
                reasons=[binding_error],
                required_action="provide_exact_payment_target_and_network",
                authorization_approved=None,
                remaining_amount_usdc=None,
                events=events,
                risk_assessment=None,
            )
        request = bound_request

        try:
            amount = self._parse_amount(request.amount_usdc)
        except ValueError as exc:
            return self._finalize_decision(
                request=request,
                now=now,
                approved=False,
                decision="blocked",
                reason_code="INVALID_AMOUNT",
                reasons=[str(exc)],
                required_action="provide_valid_amount",
                authorization_approved=None,
                remaining_amount_usdc=None,
                events=events,
                risk_assessment=None,
            )

        if amount <= Decimal("0"):
            reasons.append("amount_usdc must be greater than zero")
            decision = "blocked"
            reason_code = "INVALID_AMOUNT"
            required_action = "provide_positive_amount"

        if request.action_type not in self.SUPPORTED_ACTION_TYPES:
            reasons.append(f"unsupported action_type: {request.action_type}")
            decision = "blocked"
            reason_code = "UNSUPPORTED_ACTION_TYPE"
            required_action = "use_supported_action_type"

        if decision != "blocked" and request.action_type in self.FUNDABLE_ACTION_TYPES:
            assert request.target_address is not None
            if request.target_address in self.config.funding_destination_denylist:
                reasons.append("destination is denied by funding policy")
                decision = "blocked"
                reason_code = "DESTINATION_DENYLISTED"
                required_action = "choose_an_allowed_destination"
            elif (
                self.config.funding_destination_allowlist
                and request.target_address
                not in self.config.funding_destination_allowlist
            ):
                reasons.append("destination is not in the funding allowlist")
                decision = "blocked"
                reason_code = "DESTINATION_NOT_ALLOWLISTED"
                required_action = "choose_an_allowed_destination"

        if (
            decision != "blocked"
            and request.action_type in self.PREDICTION_MARKET_EXECUTE_ACTION_TYPES
            and request.metadata.get("execution_ready") is not True
        ):
            reasons.append("prediction market execution readiness must be true before execution")
            decision = "blocked"
            reason_code = "EXECUTION_NOT_READY"
            required_action = "check_execution_readiness"

        if decision != "blocked" and request.action_type in self.RISK_PROVIDER_ACTION_TYPES:
            risk_assessment = self._assess_risk_provider(request, events)
            risk_decision = risk_assessment["decision"]
            if self.config.risk_mode == "enforce":
                if risk_decision == "deny":
                    reasons.append("risk provider denied the transaction target")
                    decision = "blocked"
                    reason_code = "RISK_PROVIDER_DENIED"
                    required_action = "choose_lower_risk_target"
                elif risk_decision == "hold":
                    if request.user_confirmed:
                        reasons.append("risk hold accepted by explicit user confirmation")
                        events.append(
                            {
                                "event": "risk_hold_confirmed",
                                "created_at": self._format_time(self._utc_now()),
                            }
                        )
                    else:
                        reasons.append("risk provider placed the transaction target on hold")
                        decision = "needs_confirmation"
                        reason_code = "RISK_PROVIDER_HOLD"
                        required_action = "request_user_confirmation"
                elif risk_decision == "unavailable":
                    reasons.append("risk provider assessment could not be completed")
                    decision = "needs_confirmation"
                    reason_code = "RISK_PROVIDER_UNAVAILABLE"
                    required_action = "resolve_risk_assessment"

        normalized_risk_action = (request.risk_action or "").strip().lower()
        normalized_risk_level = (request.risk_level or "").strip().lower()
        if normalized_risk_action in self.BLOCKING_RISK_ACTIONS or normalized_risk_level in self.BLOCKING_RISK_LEVELS:
            reasons.append("risk policy blocked this action")
            decision = "blocked"
            reason_code = "RISK_BLOCKED"
            required_action = "choose_lower_risk_target"
        elif decision == "approved" and normalized_risk_action in self.REVIEW_RISK_ACTIONS:
            reasons.append("risk policy requires manual review")
            decision = "needs_confirmation"
            reason_code = "RISK_REVIEW_REQUIRED"
            required_action = "request_user_confirmation"

        if request.authorization_id:
            auth_check = self._check_authorization(request.authorization_id, self._format_amount(amount))
            authorization_approved = bool(auth_check.get("approved"))
            remaining_amount_usdc = auth_check.get("remaining_amount_usdc")
            events.append(
                {
                    "event": "authorization_checked",
                    "authorization_id": request.authorization_id,
                    "approved": authorization_approved,
                    "reason": auth_check.get("reason"),
                    "created_at": self._format_time(self._utc_now()),
                }
            )
            if not authorization_approved:
                reasons.append(f"authorization check failed: {auth_check.get('reason', 'unknown')}")
                decision = "blocked"
                reason_code = "BUDGET_AUTHORIZATION_BLOCKED"
                required_action = "increase_budget_or_reduce_amount"
        elif (
            request.requires_confirmation
            and not request.user_confirmed
            and decision == "approved"
        ):
            reasons.append("user confirmation or active authorization is required")
            decision = "needs_confirmation"
            reason_code = "USER_CONFIRMATION_REQUIRED"
            required_action = "request_user_confirmation"

        if (
            request.live_mode
            and request.action_type == "market_trade"
            and not request.user_confirmed
            and decision == "approved"
        ):
            reasons.append("live market trade requires explicit user confirmation")
            decision = "needs_confirmation"
            reason_code = "LIVE_TRADE_CONFIRMATION_REQUIRED"
            required_action = "request_user_confirmation"

        if not reasons:
            reasons.append("all policy gates passed")

        return self._finalize_decision(
            request=request,
            now=now,
            approved=decision == "approved",
            decision=decision,
            reason_code=reason_code,
            reasons=reasons,
            required_action=required_action,
            authorization_approved=authorization_approved,
            remaining_amount_usdc=remaining_amount_usdc,
            events=events,
            risk_assessment=risk_assessment,
        )

    def get_decision(self, policy_decision_id: str) -> PolicyDecision | None:
        payload = self.repository.policy_decision(policy_decision_id)
        return PolicyDecision.model_validate(payload) if payload is not None else None

    def get_risk_readiness(self) -> dict[str, bool | str]:
        if (
            self.config.risk_mode == "shadow"
            and not self.config.clink_live_funding
            and not self.config.misttrack_api_key
        ):
            return {"ok": True, "detail": "not_required"}
        if not self.config.misttrack_api_key:
            return {"ok": False, "detail": "not_configured"}
        if self.config.clink_profile == "server":
            if self.risk_rate_limiter is None:
                return {"ok": False, "detail": "redis_unavailable"}
            try:
                self.risk_rate_limiter.check_ready()
            except Exception:
                return {"ok": False, "detail": "redis_unavailable"}
            local_limit = self._acquire_readiness_rate_limit()
            if local_limit is not None:
                return local_limit

        query = urllib.parse.urlencode(
            {"api_key": self.config.misttrack_api_key}
        )
        request = urllib.request.Request(
            f"{self.config.misttrack_base_url}/v1/status?{query}",
            method="GET",
        )
        deadline = Decimal(str(time.monotonic())) + Decimal(
            str(self.config.misttrack_timeout_seconds)
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.config.misttrack_timeout_seconds,
            ) as response:
                remaining = deadline - Decimal(str(time.monotonic()))
                if remaining <= 0:
                    return {"ok": False, "detail": "unavailable"}
                _set_response_read_timeout(response, float(remaining))
                body = _read_response_chunk(
                    response,
                    read_size=self.RISK_READINESS_RESPONSE_LIMIT_BYTES + 1,
                    timeout=float(remaining),
                    budget_is_attempt=False,
                )
                if Decimal(str(time.monotonic())) >= deadline:
                    return {"ok": False, "detail": "unavailable"}
            if (
                not isinstance(body, bytes)
                or len(body) > self.RISK_READINESS_RESPONSE_LIMIT_BYTES
            ):
                return {"ok": False, "detail": "invalid_response"}
            payload = json.loads(body.decode("utf-8"))
            if not isinstance(payload, dict):
                return {"ok": False, "detail": "invalid_response"}
            reachable = (
                payload.get("success") is True
                or payload.get("status") in {"ok", "success"}
                or (type(payload.get("code")) is int and payload.get("code") == 0)
                or payload.get("code") == "0"
            )
            if not reachable:
                return {"ok": False, "detail": "invalid_response"}
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {"ok": False, "detail": "invalid_response"}
        except RiskProviderError as exc:
            detail = (
                exc.category
                if exc.category in self.SAFE_RISK_PROVIDER_ERROR_CATEGORIES
                else "provider_error"
            )
            return {"ok": False, "detail": detail}
        except urllib.error.HTTPError as exc:
            detail = {
                401: "invalid_key",
                403: "invalid_key",
                402: "payment_required",
                429: "rate_limited",
                500: "unavailable",
                502: "unavailable",
                503: "unavailable",
                504: "unavailable",
            }.get(exc.code, "provider_error")
            return {"ok": False, "detail": detail}
        except (urllib.error.URLError, TimeoutError, OSError):
            return {"ok": False, "detail": "unavailable"}
        except Exception:
            return {"ok": False, "detail": "provider_error"}
        return {"ok": True, "detail": "reachable"}

    def _acquire_readiness_rate_limit(self) -> dict[str, bool | str] | None:
        try:
            result = self.risk_rate_limiter.acquire()
        except Exception:
            return {"ok": False, "detail": "redis_unavailable"}
        if not isinstance(result, tuple) or len(result) != 2:
            return {"ok": False, "detail": "redis_unavailable"}
        allowed, retry_after_ms = result
        if (
            type(allowed) is not bool
            or type(retry_after_ms) is not int
            or retry_after_ms < 0
            or (allowed and retry_after_ms != 0)
            or (not allowed and retry_after_ms <= 0)
        ):
            return {"ok": False, "detail": "redis_unavailable"}
        if not allowed:
            return {"ok": False, "detail": "rate_limited"}
        return None

    def _finalize_decision(
        self,
        request: EvaluateActionPolicyRequest,
        now: datetime,
        approved: bool,
        decision: str,
        reason_code: str,
        reasons: list[str],
        required_action: str | None,
        authorization_approved: bool | None,
        remaining_amount_usdc: str | None,
        events: list[dict],
        risk_assessment: dict | None,
    ) -> PolicyDecision:
        events.append(
            {
                "event": "policy_evaluation_completed",
                "decision": decision,
                "reason_code": reason_code,
                "created_at": self._format_time(self._utc_now()),
            }
        )
        policy_decision = PolicyDecision(
            policy_decision_id=f"policy_{uuid4().hex[:12]}",
            action_id=request.action_id,
            approved=approved,
            decision=decision,
            reason_code=reason_code,
            reasons=reasons,
            required_action=required_action,
            user_id=request.user_id,
            agent_id=request.agent_id,
            action_type=request.action_type,
            amount_usdc=self._safe_format_amount(request.amount_usdc),
            authorization_id=request.authorization_id,
            merchant_id=request.merchant_id,
            target_address=request.target_address,
            chain=request.chain,
            authorization_approved=authorization_approved,
            remaining_amount_usdc=remaining_amount_usdc,
            risk_level=request.risk_level,
            risk_score=request.risk_score,
            risk_action=request.risk_action,
            risk_assessment=risk_assessment,
            evaluated_at=self._format_time(now),
            event_log=events,
            metadata=request.metadata,
        )
        self._save_decision(policy_decision)
        return policy_decision

    def _assess_risk_provider(
        self,
        request: EvaluateActionPolicyRequest,
        events: list[dict],
    ) -> dict:
        target_address = self._resolve_target_address(request)
        network = request.chain
        mode = self.config.risk_mode
        if target_address is None or network is None or self.risk_provider is None:
            if self.risk_provider is None:
                error_category = "not_configured"
            elif target_address is None:
                error_category = "invalid_address"
            else:
                error_category = "unsupported_network"
            assessment = self._unavailable_risk_assessment(
                target_address=target_address,
                network=network,
                mode=mode,
                error_category=error_category,
            )
        else:
            try:
                provider_network = (
                    POLYGON_NETWORK
                    if self.config.hosted_rehearsal_enabled
                    and network == AMOY_NETWORK
                    else network
                )
                result = self.risk_provider.assess(
                    subject=target_address,
                    network=provider_network,
                    asset="USDC",
                )
                mapped = map_risk_result(
                    result,
                    hold_score=self.config.risk_hold_score,
                    deny_score=self.config.risk_deny_score,
                )
                expires_at = min(
                    result.expires_at,
                    result.assessed_at
                    + timedelta(seconds=self.config.risk_max_age_seconds),
                )
                assessment = {
                    "provider": result.provider,
                    "provider_endpoint": result.endpoint,
                    "subject": result.subject,
                    "network": network,
                    "asset": result.asset,
                    "coin": result.coin,
                    "score": result.score,
                    "risk_level": result.risk_level,
                    "indicators": list(result.indicators),
                    "risk_details": [dict(detail) for detail in result.risk_details],
                    "hacking_event": result.hacking_event,
                    "decision": mapped.decision,
                    "decision_reasons": list(mapped.reasons),
                    "mode": mode,
                    "enforced": mode == "enforce",
                    "mapping_version": mapped.mapping_version,
                    "hold_score": self.config.risk_hold_score,
                    "deny_score": self.config.risk_deny_score,
                    "assessed_at": self._format_time(result.assessed_at),
                    "expires_at": self._format_time(expires_at),
                    "cache_hit": result.cache_hit,
                    "response_sha256": result.response_sha256,
                }
                if provider_network != network:
                    assessment["provider_network"] = result.network
            except RiskProviderError as exc:
                assessment = self._unavailable_risk_assessment(
                    target_address=target_address,
                    network=network,
                    mode=mode,
                    error_category=exc.category,
                )
            except Exception:
                assessment = self._unavailable_risk_assessment(
                    target_address=target_address,
                    network=network,
                    mode=mode,
                    error_category="provider_error",
                )
        events.append(
            {
                "event": "risk_provider_assessed",
                "provider": assessment.get("provider"),
                "decision": assessment.get("decision"),
                "mapping_version": assessment.get("mapping_version"),
                "mode": mode,
                "enforced": assessment.get("enforced", False),
                "created_at": self._format_time(self._utc_now()),
            }
        )
        return assessment

    def _unavailable_risk_assessment(
        self,
        *,
        target_address: str | None,
        network: str | None,
        mode: str,
        error_category: object,
    ) -> dict:
        safe_category = (
            error_category
            if isinstance(error_category, str)
            and error_category in self.SAFE_RISK_PROVIDER_ERROR_CATEGORIES
            else "provider_error"
        )
        return {
            "provider": self.config.risk_provider,
            "provider_endpoint": "v2/risk_score",
            "subject": target_address,
            "network": network,
            "asset": "USDC",
            "decision": "unavailable",
            "mode": mode,
            "enforced": mode == "enforce",
            "mapping_version": "misttrack-policy-v1",
            "hold_score": self.config.risk_hold_score,
            "deny_score": self.config.risk_deny_score,
            "error_category": safe_category,
        }

    def _build_risk_provider(self) -> RiskProvider | None:
        if (
            self.config.risk_provider != "misttrack"
            or not self.config.misttrack_api_key
        ):
            return None
        cache: RiskCache = InMemoryRiskCache()
        if self.config.clink_profile == "server":
            client = redis.Redis.from_url(
                self.config.clink_redis_url,
                socket_timeout=self.config.clink_redis_operation_timeout_seconds,
                socket_connect_timeout=self.config.clink_redis_operation_timeout_seconds,
            )
            cache = RedisRiskCache(
                client,
                key_prefix=self.REDIS_RISK_CACHE_KEY_PREFIX,
            )
            if (
                self.config.misttrack_rate_limit_requests_per_window is None
                or self.config.misttrack_rate_limit_window_seconds is None
            ):
                raise ValueError("Server MistTrack rate limit is not configured")
            self.risk_rate_limiter = RedisRiskRateLimiter(
                client,
                requests_per_window=(
                    self.config.misttrack_rate_limit_requests_per_window
                ),
                window_seconds=self.config.misttrack_rate_limit_window_seconds,
            )
        return MistTrackProvider(
            api_key=self.config.misttrack_api_key,
            base_url=self.config.misttrack_base_url,
            timeout_seconds=self.config.misttrack_timeout_seconds,
            max_attempts=self.config.misttrack_max_attempts,
            cache=cache,
            cache_fail_closed=self.config.clink_profile == "server",
            cache_ttl_seconds=self.config.risk_cache_ttl_seconds,
            rate_limiter=self.risk_rate_limiter,
        )

    @classmethod
    def _resolve_target_address(cls, request: EvaluateActionPolicyRequest) -> str | None:
        return request.target_address

    def _bind_fundable_payment_request(
        self, request: EvaluateActionPolicyRequest
    ) -> tuple[EvaluateActionPolicyRequest, str | None]:
        if request.action_type not in self.FUNDABLE_ACTION_TYPES:
            return request, None
        if request.action_id is None:
            return request, "fundable policy requires an action_id"
        action = ActionService(config=self.config).get_intent(request.action_id)
        if action is None:
            return request, "fundable policy action is unavailable"
        if (
            action.user_id != request.user_id
            or action.agent_id != request.agent_id
            or action.action_type != request.action_type
        ):
            return request, "fundable policy action identity does not match"
        try:
            action_target = canonicalize_evm_address(action.metadata["destination"])
        except (KeyError, TypeError, ValueError):
            return request, "fundable action is missing a canonical destination"
        action_network = action.metadata.get("network")
        if action_network not in self.config.allowed_evm_networks:
            return request, "fundable action is missing a canonical network"
        try:
            target = canonicalize_evm_address(request.target_address or "")
        except ValueError:
            return request, "fundable policy requires a canonical target_address"
        if request.target_address != target:
            return request, "fundable policy target_address must be canonical"
        if request.chain not in self.config.allowed_evm_networks:
            return request, "fundable policy requires a canonical chain"
        if target != action_target or request.chain != action_network:
            return request, "fundable policy target or network does not match the action"
        metadata_target = request.metadata.get("destination")
        metadata_network = request.metadata.get("network")
        if metadata_target != action_target or metadata_network != action_network:
            return request, "fundable policy metadata does not match the action"
        if request.metadata != action.metadata:
            return request, "fundable policy metadata is not immutable action metadata"
        return (
            request.model_copy(
                update={
                    "target_address": action_target,
                    "chain": action_network,
                    "metadata": dict(action.metadata),
                }
            ),
            None,
        )

    def _check_authorization(self, authorization_id: str, amount_usdc: str) -> dict:
        url = f"{self.config.authorization_service_url}/authorizations/{authorization_id}/check"
        payload = json.dumps({"amount_usdc": amount_usdc}).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json","Authorization":f"Bearer {self.config.clink_internal_api_token}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8")
            return {
                "approved": False,
                "reason": f"authorization service returned {exc.code}: {detail}",
            }
        except urllib.error.URLError as exc:
            return {
                "approved": False,
                "reason": f"authorization service unavailable: {exc}",
            }

    def _save_decision(self, decision: PolicyDecision) -> None:
        self.repository.create_policy_decision(decision.to_dict())

    @staticmethod
    def _parse_amount(value: str) -> Decimal:
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("amount_usdc must be a valid decimal string") from exc
        return amount

    @classmethod
    def _safe_format_amount(cls, value: str) -> str:
        try:
            return cls._format_amount(cls._parse_amount(value))
        except ValueError:
            return str(value)

    @staticmethod
    def _format_amount(value: Decimal) -> str:
        rendered = format(value, "f")
        if "." in rendered:
            rendered = rendered.rstrip("0").rstrip(".")
        return rendered or "0"

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(UTC)

    @staticmethod
    def _format_time(value: datetime) -> str:
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
