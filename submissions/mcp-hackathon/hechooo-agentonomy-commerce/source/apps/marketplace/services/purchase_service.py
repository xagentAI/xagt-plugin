from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
from eth_account import Account
from eth_account.messages import encode_typed_data

from shared.commerce import (
    Purchase,
    PurchasePreview,
    eligible_payment_options,
    payment_capability,
    purchase_execution_mode,
)
from shared.ephemeral import EphemeralStore


def digest(value):
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=str
    ).encode()
    return "0x" + hashlib.sha256(raw).hexdigest()


class PurchaseExecutionResult(dict):
    """Execution response; replayed terminal purchases intentionally have no result."""

    def __init__(self, purchase, service_result=None):
        super().__init__(purchase=purchase, service_result=service_result)

    def __getattr__(self, name):
        return getattr(self["purchase"], name)


_UNSET = object()


class PurchaseService:
    """Coordinates purchase state while Core remains the only money control plane."""

    def __init__(
        self,
        repository,
        core,
        *,
        preview_ttl=300,
        proxy_context_ttl=86400,
        client=None,
        ephemeral_store=None,
        native_provider_ids=(),
        registry_verified_max_price_usd="0.10",
        public_base_url="http://127.0.0.1:8050",
        eip3009_domains=None,
    ):
        self.repository = repository
        self.core = core
        self.preview_ttl = preview_ttl
        self.proxy_context_ttl = max(preview_ttl, proxy_context_ttl)
        self.client = client or httpx.Client(timeout=30)
        self.inputs = ephemeral_store or EphemeralStore()
        self.native_provider_ids = frozenset(native_provider_ids)
        self.registry_verified_max_price_usd = Decimal(str(registry_verified_max_price_usd))
        self.public_base_url = public_base_url.rstrip("/")
        self.eip3009_domains = eip3009_domains or {}

    def create_preview(
        self,
        *,
        user_id,
        offering_id,
        service_input,
        payment_index=0,
        network=None,
        max_price_usd=None,
        opc_installation_id=None,
    ):
        opc_installation_id = self._opc_installation_id(opc_installation_id)
        offering = self.repository.active_offering(offering_id)
        if not offering:
            raise ValueError("verified offering with active provider not found")
        self._merchant_request_payload(offering, service_input)
        options = eligible_payment_options(
            offering.payment_options,
            network=network,
            max_price_usd=max_price_usd,
        )
        if payment_index < 0 or payment_index >= len(options):
            raise ValueError("payment option does not satisfy preview constraints")
        payment = options[payment_index].model_dump(mode="json")
        trust_tier=offering.metadata.get("trust_tier","clink_verified")
        price=payment.get("price_usd")
        if trust_tier=="registry_verified" and (
            price is None or Decimal(str(price)) > self.registry_verified_max_price_usd
        ):
            raise ValueError("registry-verified offering exceeds the per-purchase price limit")
        mode = purchase_execution_mode(
            trust_tier=trust_tier,
            provider_id=offering.provider_id,
            native_provider_ids=self.native_provider_ids,
        )
        authorization = None
        if mode == "external_x402_signature":
            try:
                incompatibility = self.inputs.get(
                    self._proxy_incompatibility_key(offering_id, digest(payment))
                )
                if incompatibility is None:
                    candidate = self._resolve_authorization_fields(
                        user_id=user_id,
                        execution_mode="clink_payer_proxy",
                        offering=offering,
                        payment=self._canonical_core_payment(payment),
                        opc_installation_id=opc_installation_id,
                    )
                    if (
                        candidate.get("ready")
                        and candidate.get("authorization_rail") == "clink_payer_proxy"
                        and candidate.get("asset_allowance_id")
                    ):
                        mode = "clink_payer_proxy"
                        authorization = candidate
            except Exception:
                authorization = None
        if mode == "clink_allowance":
            try:
                authorization = self._resolve_authorization_fields(
                    user_id=user_id,
                    execution_mode=mode,
                    offering=offering,
                    payment=self._canonical_core_payment(payment),
                    opc_installation_id=opc_installation_id,
                )
            except Exception:
                authorization = {"ready": False, "reason_code": "CORE_AUTHORIZATION_UNAVAILABLE"}
        now = datetime.now(UTC)
        preview_id = "preview_" + secrets.token_hex(6)
        preview = PurchasePreview(
            preview_id=preview_id,
            offering_id=offering_id,
            user_id=user_id,
            quote_hash=digest(payment),
            input_hash=digest(service_input),
            payment=payment,
            execution_mode=mode,
            opc_installation_id=opc_installation_id,
            payment_capability=payment_capability(
                mode,
                authorization=authorization,
            ),
            expires_at=now + timedelta(seconds=self.preview_ttl),
            created_at=now,
        )
        self.repository.save_preview(preview)
        self.inputs.set(preview_id, service_input, self.preview_ttl)
        return preview

    def execute(
        self,
        preview_id,
        *,
        user_confirmed=False,
        spending_authorization_id=None,
        transaction_hash=None,
        payment_response=None,
        opc_installation_id=None,
    ):
        preview = self.repository.get_preview(preview_id)
        if not preview:
            raise ValueError("purchase preview not found")
        if preview.opc_installation_id != self._opc_installation_id(
            opc_installation_id
        ):
            raise ValueError("OPC installation mismatch")
        purchase_id = "purchase_" + preview_id.removeprefix("preview_")
        existing = self.repository.get_purchase(purchase_id)

        has_external_proof = (
            transaction_hash is not None or payment_response is not None
        )
        if has_external_proof:
            if not transaction_hash or payment_response is None:
                raise ValueError(
                    "transaction_hash and payment_response must be provided together"
                )
            return self.complete_external(
                purchase_id,
                transaction_hash=transaction_hash,
                payment_response=payment_response,
            )

        if existing:
            if existing.execution_mode != preview.execution_mode:
                raise ValueError("purchase execution mode mismatch")
            if existing.state in {"delivered", "paid_but_undelivered", "failed"}:
                self.inputs.delete(preview_id)
                return self._response(existing)
            if (
                existing.execution_mode == "external_x402_signature"
                and existing.state in {"signing_required", "payment_submitted"}
            ):
                return self._response(existing)

        offering = self.repository.active_offering(preview.offering_id)
        if not offering:
            raise ValueError("active provider required for purchase execution")
        trust_tier=offering.metadata.get("trust_tier","clink_verified")

        now = datetime.now(UTC)
        seed = Purchase(
            purchase_id=purchase_id,
            preview_id=preview.preview_id,
            offering_id=preview.offering_id,
            user_id=preview.user_id,
            state="preview_created",
            execution_mode=preview.execution_mode,
            input_hash=preview.input_hash,
            created_at=now,
            updated_at=now,
        )
        expected_mode = existing.execution_mode if existing else preview.execution_mode
        purchase, claim_token = self.repository.claim_purchase_execution(
            seed,
            allowed_states={
                "preview_created",
                "confirmation_required",
                "spending_reserved",
                "payment_submitted",
            },
            expected_execution_mode=expected_mode,
        )
        if not claim_token:
            return self._response(purchase)
        entered_state = purchase.state
        if (
            entered_state == "payment_submitted"
            and preview.execution_mode == "clink_allowance"
        ):
            return self._reconcile_submitted_allowance(
                purchase=purchase,
                claim_token=claim_token,
                preview=preview,
                offering=offering,
            )
        expires_at = (
            preview.expires_at
            if preview.expires_at.tzinfo
            else preview.expires_at.replace(tzinfo=UTC)
        )
        if (
            entered_state in {"preview_created", "confirmation_required"}
            and expires_at <= now
        ):
            return self._response(
                self._fail_claimed(
                    purchase,
                    claim_token,
                    "PREVIEW_EXPIRED",
                    input_key=preview_id,
                )
            )
        current = next(
            (
                option.model_dump(mode="json")
                for option in offering.payment_options
                if digest(option.model_dump(mode="json")) == preview.quote_hash
            ),
            None,
        )
        if current is None:
            return self._response(
                self._fail_claimed(
                    purchase, claim_token, "QUOTE_DRIFT", input_key=preview_id
                )
            )
        if (
            preview.execution_mode == "clink_payer_proxy"
            and purchase.reason_code == "PROXY_COMPATIBILITY_RELEASE_PENDING"
        ):
            return self._downgrade_proxy_purchase(
                purchase,
                claim_token,
                preview=preview,
                error=RuntimeError("merchant x402 proxy is incompatible"),
            )
        context_ttl = (
            self.proxy_context_ttl
            if preview.execution_mode == "clink_payer_proxy"
            else max(1, self.preview_ttl)
        )
        service_input = self.inputs.acquire(preview_id, context_ttl)
        if service_input is None:
            return self._handle_missing_input(
                purchase, claim_token, entered_state
            )
        try:
            self._merchant_request_payload(offering, service_input)
        except ValueError:
            return self._response(
                self._fail_claimed(
                    purchase,
                    claim_token,
                    "INVALID_SERVICE_INPUT",
                    input_key=preview_id,
                )
            )

        core_payment = self._canonical_core_payment(current)
        authorization = self._resolve_authorization(
            preview=preview,
            offering=offering,
            payment=core_payment,
        )
        if not authorization.get("ready"):
            session = self.core.create_account_session(preview.user_id)
            blocked = purchase.model_copy(
                update={
                    "metadata": {
                        **purchase.metadata,
                        "account_url": session["account_url"],
                        "account_session_expires_at": session.get("expires_at"),
                        "authorization_next_action": authorization.get("next_action"),
                    },
                    "updated_at": datetime.now(UTC),
                }
            )
            return self._response(
                self._save_claimed(
                    blocked,
                    claim_token,
                    "confirmation_required",
                    authorization.get("reason_code") or "SPENDING_GRANT_REQUIRED",
                )
            )
        if (
            entered_state in {"preview_created", "confirmation_required"}
            and authorization.get("interaction_reason_code")
            == "NOTIFICATION_POLICY_REQUIRES_CONFIRMATION"
            and not user_confirmed
        ):
            return self._response(
                self._save_claimed(
                    purchase,
                    claim_token,
                    "confirmation_required",
                    "NOTIFICATION_POLICY_REQUIRES_CONFIRMATION",
                )
            )
        core_scope = self._core_scope(
            purchase_id=purchase_id,
            preview=preview,
            offering=offering,
            payment=core_payment,
            authorization=authorization,
        )

        if entered_state in {"preview_created", "confirmation_required"}:
            action_id = purchase.action_id
            if not action_id:
                action = self.core.create_action(
                    {
                        "user_id": preview.user_id,
                        "agent_id": "hermes",
                        "action_type": "marketplace_purchase",
                        "amount_usdc": str(current.get("price_usd") or 0),
                        "merchant_id": offering.provider_id,
                        "metadata": core_scope,
                    }
                )
                action_id = action["action_id"]
            policy = self.core.evaluate_policy(
                {
                    "action_id": action_id,
                    "user_id": preview.user_id,
                    "agent_id": "hermes",
                    "action_type": "marketplace_purchase",
                    "amount_usdc": str(current.get("price_usd") or 0),
                    "merchant_id": offering.provider_id,
                    "target_address": core_scope["destination"],
                    "chain": core_scope["network"],
                    "user_confirmed": user_confirmed,
                    # Core has freshly resolved the signed grant above. Only
                    # its explicit silent-purchase decision removes this gate;
                    # absent/unknown interaction state still needs confirmation.
                    "requires_confirmation": (
                        authorization.get("user_interaction_required") is not False
                    ),
                    "metadata": core_scope,
                }
            )
            purchase = purchase.model_copy(
                update={
                    "action_id": action_id,
                    "policy_decision_id": policy["policy_decision_id"],
                    "updated_at": datetime.now(UTC),
                }
            )
            if not policy.get("approved"):
                policy_reason = (
                    policy.get("reason_code") or "USER_CONFIRMATION_REQUIRED"
                )
                policy_metadata = {
                    **purchase.metadata,
                    "policy_required_action": policy.get("required_action"),
                    "policy_reasons": policy.get("reasons") or [],
                }
                return self._response(
                    self._save_claimed(
                        purchase.model_copy(update={"metadata": policy_metadata}),
                        claim_token,
                        "confirmation_required",
                        policy_reason,
                    )
                )
            self.core.update_action(
                action_id,
                {
                    "state": "policy_approved",
                    "policy_decision_id": policy["policy_decision_id"],
                },
            )
            if not purchase.audit_event_ids:
                audit = self.core.audit(
                    {
                        "event_type": "marketplace_purchase_policy_evaluated",
                        "source_service": "clink_marketplace",
                        "action_id": action_id,
                        "user_id": preview.user_id,
                        "agent_id": "hermes",
                        "policy_decision_id": policy["policy_decision_id"],
                        "payload": {
                            **core_scope,
                            "merchant_id": offering.provider_id,
                            "venue": "clink_marketplace",
                        },
                    }
                )
                purchase = purchase.model_copy(
                    update={"audit_event_ids": [audit["event_id"]]}
                )
        if not purchase.reservation_id:
            reserve_payload = {
                "purchase_id": purchase_id,
                "idempotency_key": purchase_id,
                "spending_authorization_id": None,
                "authorization_rail": authorization["authorization_rail"],
                "wallet_identity_id": authorization["wallet_identity_id"],
                "spending_grant_id": authorization["spending_grant_id"],
                "asset_allowance_id": authorization.get("asset_allowance_id"),
                "product": "marketplace",
                "action_id": purchase.action_id,
                "policy_decision_id": purchase.policy_decision_id,
                "merchant_id": offering.provider_id,
                "merchant_trust_tier": offering.metadata.get(
                    "trust_tier", "clink_verified"
                ),
                "quote_hash": preview.quote_hash,
                "amount_usdc": str(current.get("price_usd") or 0),
                "amount_atomic": current["amount_atomic"],
                "network": current["network"],
                "asset": core_scope["asset"],
                "token_address": core_scope.get("token_address"),
                "destination": core_scope["destination"],
                "resource": offering.endpoint,
                "venue": "clink_marketplace",
            }
            if preview.opc_installation_id is not None:
                reserve_payload["opc_installation_id"] = (
                    preview.opc_installation_id
                )
            reserve = self.core.reserve(reserve_payload)
            purchase = purchase.model_copy(
                update={
                    "reservation_id": reserve["reservation_id"],
                    "state": "spending_reserved",
                    "reason_code": None,
                    "updated_at": datetime.now(UTC),
                }
            )
            if preview.execution_mode == "external_x402_signature":
                checkout_token = secrets.token_urlsafe(32)
                checkout_token_hash = hashlib.sha256(checkout_token.encode()).hexdigest()
                signing_url = (
                    f"{self.public_base_url}/x402/checkout/{purchase_id}"
                    f"#token={checkout_token}"
                )
                pending = purchase.model_copy(
                    update={
                        "state": "signing_required",
                        "reason_code": "EXTERNAL_X402_SIGNATURE_REQUIRED",
                        "metadata": {
                            **purchase.metadata,
                            "signing_url": signing_url,
                            "checkout_token_hash": checkout_token_hash,
                            "authorization_resolution": authorization,
                            "signing_payload": {
                                "payment": current,
                                "expires_at": preview.expires_at.isoformat(),
                            }
                        },
                        "updated_at": datetime.now(UTC),
                    }
                )
                self.repository.save_claimed_purchase(
                    pending,
                    claim_token,
                    expected_execution_mode=expected_mode,
                    release_claim=True,
                    expected_states={entered_state},
                )
                return self._response(pending)
            self.repository.save_claimed_purchase(
                purchase,
                claim_token,
                expected_execution_mode=expected_mode,
                expected_states={entered_state},
            )

        if preview.execution_mode == "clink_payer_proxy":
            return self._execute_proxy_purchase(
                purchase=purchase,
                claim_token=claim_token,
                preview=preview,
                offering=offering,
                service_input=service_input,
                payment=current,
                entered_state=entered_state,
            )

        payment_authorization = {
            "payment_authorization": {
                "scheme": current["scheme"],
                "network": current["network"],
                "asset": current["asset"],
                "amount_atomic": current["amount_atomic"],
                "pay_to": current["pay_to"],
            }
        }
        if entered_state == "payment_submitted":
            try:
                settlement = self.core.reconcile(purchase.reservation_id)
                if self._retryable_settlement(settlement):
                    settlement = self.core.settle(
                        purchase.reservation_id, payment_authorization
                    )
            except Exception:
                return self._save_pending_reconciliation(
                    purchase, claim_token, settlement=None
                )
        else:
            purchase = purchase.model_copy(
                update={
                    "state": "payment_submitted",
                    "reason_code": "RECONCILIATION_REQUIRED",
                    "metadata": self._settlement_metadata(
                        purchase,
                        settlement=None,
                        identity={
                            "rail": "clink_allowance",
                            "payment_authorization_hash": digest(
                                payment_authorization["payment_authorization"]
                            ),
                        },
                    ),
                    "updated_at": datetime.now(UTC),
                }
            )
            self.repository.save_claimed_purchase(
                purchase,
                claim_token,
                expected_execution_mode="clink_allowance",
                expected_states={"spending_reserved"},
            )
            try:
                settlement = self.core.settle(
                    purchase.reservation_id, payment_authorization
                )
            except Exception:
                return self._save_pending_reconciliation(
                    purchase, claim_token, settlement=None
                )

        if not self._settled(settlement):
            return self._save_pending_reconciliation(
                purchase, claim_token, settlement=settlement
            )

        receipt_token = base64.urlsafe_b64encode(
            json.dumps(
                settlement.get("receipt", {}), separators=(",", ":")
            ).encode()
        ).decode().rstrip("=")
        started = time.perf_counter()
        try:
            response = self._merchant_request(
                offering,
                service_input,
                headers={
                    "X-CLINK-PAYMENT-RECEIPT": receipt_token,
                    "Idempotency-Key": purchase.purchase_id,
                },
            )
            if not response.is_success:
                raise RuntimeError("merchant delivery failed")
            service_result = self._service_result(response)
        except Exception:
            purchase = purchase.model_copy(
                update={
                    "state": "paid_but_undelivered",
                    "receipt_id": settlement.get("receipt_id")
                    or settlement.get("tx_hash"),
                    "reason_code": "DELIVERY_FAILED",
                    "updated_at": datetime.now(UTC),
                }
            )
            self._finish_terminal(
                purchase,
                claim_token,
                latency_ms=self._latency_ms(started),
                input_key=preview_id,
            )
            return self._response(purchase)
        purchase = purchase.model_copy(
            update={
                "state": "delivered",
                "output_hash": digest(service_result),
                "receipt_id": settlement.get("receipt_id")
                or settlement.get("tx_hash"),
                "reason_code": None,
                "updated_at": datetime.now(UTC),
            }
        )
        self._save_result_mailbox(purchase.purchase_id, service_result)
        self._finish_terminal(
            purchase,
            claim_token,
            latency_ms=self._latency_ms(started),
            input_key=preview_id,
        )
        return self._response(purchase, service_result)

    def _reconcile_submitted_allowance(
        self,
        *,
        purchase,
        claim_token,
        preview,
        offering,
    ):
        """Recover without re-authorizing; retry settlement only when Core proves safe."""
        try:
            settlement = self.core.reconcile(purchase.reservation_id)
        except Exception:
            return self._save_pending_reconciliation(
                purchase, claim_token, settlement=None
            )
        if self._retryable_settlement(settlement):
            payment = preview.payment
            payment_authorization = {
                "payment_authorization": {
                    "scheme": payment["scheme"],
                    "network": payment["network"],
                    "asset": payment["asset"],
                    "amount_atomic": payment["amount_atomic"],
                    "pay_to": payment["pay_to"],
                }
            }
            try:
                settlement = self.core.settle(
                    purchase.reservation_id, payment_authorization
                )
            except Exception:
                return self._save_pending_reconciliation(
                    purchase, claim_token, settlement=None
                )
        if not self._settled(settlement):
            return self._save_pending_reconciliation(
                purchase, claim_token, settlement=settlement
            )

        service_input = self.inputs.acquire(
            preview.preview_id, max(1, self.preview_ttl)
        )
        if service_input is None:
            updated = purchase.model_copy(
                update={
                    "state": "paid_but_undelivered",
                    "receipt_id": settlement.get("receipt_id")
                    or settlement.get("tx_hash"),
                    "reason_code": "INPUT_UNAVAILABLE_AFTER_PAYMENT",
                    "metadata": self._settlement_metadata(
                        purchase, settlement=settlement
                    ),
                    "updated_at": datetime.now(UTC),
                }
            )
            self._finish_terminal(
                updated,
                claim_token,
                latency_ms=0,
                input_key=preview.preview_id,
            )
            return self._response(updated)

        receipt_token = base64.urlsafe_b64encode(
            json.dumps(
                settlement.get("receipt", {}), separators=(",", ":")
            ).encode()
        ).decode().rstrip("=")
        started = time.perf_counter()
        try:
            response = self._merchant_request(
                offering,
                service_input,
                headers={
                    "X-CLINK-PAYMENT-RECEIPT": receipt_token,
                    "Idempotency-Key": purchase.purchase_id,
                },
            )
            if not response.is_success:
                raise RuntimeError("merchant delivery failed")
            service_result = self._service_result(response)
        except Exception:
            updated = purchase.model_copy(
                update={
                    "state": "paid_but_undelivered",
                    "receipt_id": settlement.get("receipt_id")
                    or settlement.get("tx_hash"),
                    "reason_code": "DELIVERY_FAILED",
                    "metadata": self._settlement_metadata(
                        purchase, settlement=settlement
                    ),
                    "updated_at": datetime.now(UTC),
                }
            )
            self._finish_terminal(
                updated,
                claim_token,
                latency_ms=self._latency_ms(started),
                input_key=preview.preview_id,
            )
            return self._response(updated)

        updated = purchase.model_copy(
            update={
                "state": "delivered",
                "output_hash": digest(service_result),
                "receipt_id": settlement.get("receipt_id")
                or settlement.get("tx_hash"),
                "reason_code": None,
                "metadata": self._settlement_metadata(
                    purchase, settlement=settlement
                ),
                "updated_at": datetime.now(UTC),
            }
        )
        self._save_result_mailbox(updated.purchase_id, service_result)
        self._finish_terminal(
            updated,
            claim_token,
            latency_ms=self._latency_ms(started),
            input_key=preview.preview_id,
        )
        return self._response(updated, service_result)

    def _execute_proxy_purchase(
        self,
        *,
        purchase,
        claim_token,
        preview,
        offering,
        service_input,
        payment,
        entered_state,
    ):
        # Once the merchant has returned a paid service result, recovery is a
        # Core-only operation. Never contact the merchant again, even if the
        # cached challenge has expired while finalization was unavailable.
        handoff = self._proxy_handoff(purchase)
        if handoff is not None:
            try:
                settlement = self.core.reconcile(purchase.reservation_id)
            except Exception as exc:
                return self._save_proxy_pending(
                    purchase,
                    claim_token,
                    settlement=None,
                    reason="PROXY_PAYMENT_RECONCILIATION_REQUIRED",
                    error=exc,
                )
            if not self._proxy_handoff_payment_failed(settlement, handoff):
                return self._continue_proxy_purchase(
                    purchase=purchase,
                    claim_token=claim_token,
                    preview=preview,
                    offering=offering,
                    service_input=service_input,
                    challenge=None,
                    settlement=settlement,
                )
            purchase = self._clear_proxy_handoff(
                purchase, claim_token
            )

        try:
            challenge = self._proxy_challenge(
                purchase=purchase,
                preview=preview,
                offering=offering,
                service_input=service_input,
                payment=payment,
            )
        except ValueError as exc:
            if purchase.state == "spending_reserved":
                self.inputs.set(
                    self._proxy_incompatibility_key(
                        preview.offering_id, preview.quote_hash
                    ),
                    {"reason": str(exc)},
                    3600,
                )
                try:
                    self.core.release(
                        purchase.reservation_id,
                        "merchant_x402_proxy_incompatible",
                    )
                except Exception:
                    return self._save_proxy_pending(
                        purchase,
                        claim_token,
                        settlement=None,
                        reason="PROXY_COMPATIBILITY_RELEASE_PENDING",
                        error=exc,
                    )
                return self._response(
                    self._fail_claimed(
                        purchase,
                        claim_token,
                        "MERCHANT_X402_PROXY_INCOMPATIBLE",
                        input_key=preview.preview_id,
                    )
                )
            return self._save_proxy_pending(
                purchase,
                claim_token,
                settlement=None,
                reason="PROXY_CHALLENGE_RETRY_REQUIRED",
                error=exc,
            )
        except Exception as exc:
            if (
                purchase.state == "spending_reserved"
                and self._proxy_incompatibility_error(exc)
            ):
                self.inputs.set(
                    self._proxy_incompatibility_key(
                        preview.offering_id, preview.quote_hash
                    ),
                    {"reason": str(exc)},
                    3600,
                )
                try:
                    self.core.release(
                        purchase.reservation_id,
                        "merchant_x402_proxy_incompatible",
                    )
                except Exception:
                    return self._save_proxy_pending(
                        purchase,
                        claim_token,
                        settlement=None,
                        reason="PROXY_COMPATIBILITY_RELEASE_PENDING",
                        error=exc,
                    )
                return self._response(
                    self._fail_claimed(
                        purchase,
                        claim_token,
                        "MERCHANT_X402_PROXY_INCOMPATIBLE",
                        input_key=preview.preview_id,
                    )
                )
            return self._save_proxy_pending(
                purchase,
                claim_token,
                settlement=None,
                reason="PROXY_CHALLENGE_RETRY_REQUIRED",
                error=exc,
            )

        payment_authorization = {
            "payment_authorization": {
                "scheme": payment["scheme"],
                "network": payment["network"],
                "asset": payment["asset"],
                "amount_atomic": payment["amount_atomic"],
                "pay_to": payment["pay_to"],
            }
        }

        try:
            if entered_state == "payment_submitted":
                settlement = self.core.reconcile(purchase.reservation_id)
            else:
                settlement = {"state": "spending_reserved"}

            if settlement.get("state") in {"spending_reserved", "payer_funded"}:
                failed_hashes = list(
                    settlement.get("failed_merchant_tx_hashes", [])
                )
                prepared = self.core.proxy_prepare(
                    purchase.reservation_id,
                    {"payment_requirement": challenge["core_requirement"]},
                )
                settlement = {
                    **prepared,
                    "failed_merchant_tx_hashes": (
                        prepared.get("failed_merchant_tx_hashes")
                        or failed_hashes
                    ),
                }
        except Exception as exc:
            if (
                purchase.state == "spending_reserved"
                and self._proxy_incompatibility_error(exc)
            ):
                return self._downgrade_proxy_purchase(
                    purchase,
                    claim_token,
                    preview=preview,
                    error=exc,
                )
            return self._save_proxy_pending(
                purchase,
                claim_token,
                settlement=None,
                reason="PROXY_PREPARE_RETRY_REQUIRED",
                error=exc,
            )

        if purchase.state == "spending_reserved":
            purchase = purchase.model_copy(
                update={
                    "state": "payment_submitted",
                    "reason_code": "PAYER_REIMBURSEMENT_PENDING",
                    "metadata": self._settlement_metadata(
                        purchase,
                        settlement=None,
                        identity={
                            "rail": "clink_payer_proxy",
                            "payment_authorization_hash": digest(
                                payment_authorization["payment_authorization"]
                            ),
                        },
                    ),
                    "updated_at": datetime.now(UTC),
                }
            )
            self.repository.save_claimed_purchase(
                purchase,
                claim_token,
                expected_execution_mode="clink_payer_proxy",
                expected_states={"spending_reserved"},
            )

        try:
            if settlement.get("state") == "proxy_authorization_ready":
                settlement = self.core.settle(
                    purchase.reservation_id,
                    payment_authorization,
                )
        except Exception as exc:
            return self._save_proxy_pending(
                purchase,
                claim_token,
                settlement=None,
                reason="PAYER_REIMBURSEMENT_RECONCILIATION_REQUIRED",
                error=exc,
            )

        return self._continue_proxy_purchase(
            purchase=purchase,
            claim_token=claim_token,
            preview=preview,
            offering=offering,
            service_input=service_input,
            challenge=challenge,
            settlement=settlement,
        )

    def _continue_proxy_purchase(
        self,
        *,
        purchase,
        claim_token,
        preview,
        offering,
        service_input,
        challenge,
        settlement,
    ):
        handoff_key = self._proxy_handoff_key(purchase.purchase_id)
        handoff = self._proxy_handoff(purchase)
        if handoff is not None and not self._settled(settlement):
            try:
                final = self.core.proxy_finalize(
                    purchase.reservation_id,
                    {
                        "transaction_hash": handoff["transaction_hash"],
                        "payment_response": handoff["payment_response"],
                    },
                )
            except Exception as exc:
                return self._save_proxy_pending(
                    purchase,
                    claim_token,
                    settlement=settlement,
                    reason="PROXY_PAYMENT_RECONCILIATION_REQUIRED",
                    error=exc,
                )
            if not self._settled(final):
                return self._save_proxy_pending(
                    purchase,
                    claim_token,
                    settlement=final,
                    reason="PROXY_PAYMENT_RECONCILIATION_REQUIRED",
                )
            return self._finish_proxy_delivery(
                purchase,
                claim_token,
                preview=preview,
                settlement=final,
                service_result=handoff.get("service_result", _UNSET),
                output_hash=handoff.get("output_hash"),
            )
        if self._settled(settlement):
            if handoff is None:
                return self._save_proxy_pending(
                    purchase,
                    claim_token,
                    settlement=settlement,
                    reason="PROXY_DELIVERY_RESULT_UNAVAILABLE",
                )
            return self._finish_proxy_delivery(
                purchase,
                claim_token,
                preview=preview,
                settlement=settlement,
                service_result=handoff.get("service_result", _UNSET),
                output_hash=handoff.get("output_hash"),
            )
        if not self._proxy_funded(settlement):
            return self._save_proxy_pending(
                purchase,
                claim_token,
                settlement=settlement,
                reason="PAYER_REIMBURSEMENT_RECONCILIATION_REQUIRED",
            )

        try:
            # The merchant authorization is intentionally short-lived. Ask
            # Core to return the current authorization immediately before
            # submission; Core reuses a valid one and rotates an expired one.
            failed_hashes = list(
                settlement.get("failed_merchant_tx_hashes", [])
            )
            prepared = self.core.proxy_prepare(
                purchase.reservation_id,
                {"payment_requirement": challenge["core_requirement"]},
            )
            if failed_hashes and not prepared.get("failed_merchant_tx_hashes"):
                prepared = {
                    **prepared,
                    "failed_merchant_tx_hashes": failed_hashes,
                }
            payment_payload = dict(prepared["payment_payload"])
            payment_payload["resource"] = challenge["payment_required"]["resource"]
            payment_payload["accepted"] = challenge["accepted"]
            payment_header = self._encode_payment_header(payment_payload)
            payment_attempt = len(
                {
                    str(tx_hash).lower()
                    for tx_hash in settlement.get(
                        "failed_merchant_tx_hashes", []
                    )
                    if tx_hash
                }
            )
            started = time.perf_counter()
            response = self._merchant_request(
                offering,
                service_input,
                headers={
                    "PAYMENT-SIGNATURE": payment_header,
                    "Idempotency-Key": (
                        f"{purchase.purchase_id}:payment:{payment_attempt}"
                    ),
                },
            )
            if not response.is_success:
                raise RuntimeError(
                    f"merchant rejected Clink payer payment: HTTP {response.status_code}"
                )
            merchant_settlement = self._decode_payment_header(
                response.headers.get("PAYMENT-RESPONSE")
                or response.headers.get("X-PAYMENT-RESPONSE")
            )
            transaction_hash = (
                merchant_settlement.get("transaction")
                or merchant_settlement.get("transactionHash")
                or merchant_settlement.get("txHash")
            )
            if not transaction_hash:
                raise ValueError("merchant payment response omitted transaction hash")
            authorization = payment_payload["payload"]["authorization"]
            proof = {
                **merchant_settlement,
                "network": challenge["accepted"]["network"],
                "asset": challenge["accepted"]["asset"],
                "amount_atomic": str(challenge["accepted"]["amount"]),
                "pay_to": challenge["accepted"]["payTo"],
                "nonce": authorization["nonce"],
                "valid_after": authorization["validAfter"],
                "valid_before": authorization["validBefore"],
            }
            service_result = self._service_result(response)
            durable_handoff = {
                "transaction_hash": transaction_hash,
                "payment_response": proof,
                "output_hash": digest(service_result),
            }
            purchase = purchase.model_copy(
                update={
                    "metadata": {
                        **purchase.metadata,
                        "proxy_handoff": durable_handoff,
                    },
                    "updated_at": datetime.now(UTC),
                }
            )
            self.repository.save_claimed_purchase(
                purchase,
                claim_token,
                expected_execution_mode="clink_payer_proxy",
                expected_states={"payment_submitted"},
            )
            self.inputs.set(
                handoff_key,
                {
                    **durable_handoff,
                    "service_result": service_result,
                },
                max(self.preview_ttl, 3600),
            )
            final = self.core.proxy_finalize(
                purchase.reservation_id,
                {
                    "transaction_hash": transaction_hash,
                    "payment_response": proof,
                },
            )
        except Exception as exc:
            return self._save_proxy_pending(
                purchase,
                claim_token,
                settlement=settlement,
                reason="PROXY_PAYMENT_RETRY_REQUIRED",
                error=exc,
            )

        if not self._settled(final):
            return self._save_proxy_pending(
                purchase,
                claim_token,
                settlement=final,
                reason="PROXY_PAYMENT_RECONCILIATION_REQUIRED",
            )
        return self._finish_proxy_delivery(
            purchase,
            claim_token,
            preview=preview,
            settlement=final,
            service_result=service_result,
            latency_ms=self._latency_ms(started),
        )

    def _proxy_challenge(
        self, *, purchase, preview, offering, service_input, payment
    ):
        key = self._proxy_challenge_key(purchase.purchase_id)
        stored = self.inputs.get(key)
        if stored is not None:
            return stored
        response = self._merchant_request(
            offering,
            service_input,
            headers={"Idempotency-Key": purchase.purchase_id},
        )
        if response.status_code != 402:
            raise ValueError("merchant did not return an x402 payment challenge")
        payment_required = self._decode_payment_header(
            response.headers.get("PAYMENT-REQUIRED")
            or response.headers.get("X-PAYMENT-REQUIRED")
        )
        if payment_required.get("x402Version") != 2:
            raise ValueError("merchant must use x402 v2")
        resource = payment_required.get("resource")
        if not isinstance(resource, dict) or resource.get("url") != offering.endpoint:
            raise ValueError("merchant x402 resource does not match the selected offering")
        accepted = self._matching_requirement(payment_required, payment)
        extra = accepted.get("extra") or {}
        if extra.get("assetTransferMethod", "eip3009") != "eip3009":
            raise ValueError("Clink payer proxy requires EIP-3009")
        network = str(accepted["network"])
        domain = {**self.eip3009_domains.get(network, {}), **extra}
        if not domain.get("name") or not domain.get("version"):
            raise ValueError("EIP-3009 token domain is not configured")
        challenge = {
            "payment_required": payment_required,
            "accepted": accepted,
            "core_requirement": {
                "scheme": "exact",
                "network": accepted["network"],
                "asset": self._evm_address(accepted["asset"]),
                "amount_atomic": str(accepted["amount"]),
                "pay_to": self._evm_address(accepted["payTo"]),
                "resource": offering.endpoint,
                "token_name": domain["name"],
                "token_version": str(domain["version"]),
            },
        }
        # The reservation has already locked these exact merchant terms. Keep
        # the challenge for bounded recovery so a confirmed failed merchant
        # transaction can rotate its nonce without asking the user to restart.
        self.inputs.set(key, challenge, self.proxy_context_ttl)
        return challenge

    def _finish_proxy_delivery(
        self,
        purchase,
        claim_token,
        *,
        preview,
        settlement,
        service_result,
        output_hash=None,
        latency_ms=0,
    ):
        result_available = service_result is not _UNSET
        metadata = dict(purchase.metadata)
        metadata.pop("proxy_handoff", None)
        purchase = purchase.model_copy(update={"metadata": metadata})
        updated = purchase.model_copy(
            update={
                "state": (
                    "delivered" if result_available else "paid_but_undelivered"
                ),
                "output_hash": (
                    digest(service_result) if result_available else output_hash
                ),
                "receipt_id": settlement.get("receipt_id")
                or settlement.get("tx_hash"),
                "reason_code": (
                    None
                    if result_available
                    else "PROXY_DELIVERY_RESULT_UNAVAILABLE"
                ),
                "metadata": self._settlement_metadata(
                    purchase, settlement=settlement
                ),
                "updated_at": datetime.now(UTC),
            }
        )
        if result_available:
            self._save_result_mailbox(purchase.purchase_id, service_result)
        self._finish_terminal(
            updated,
            claim_token,
            latency_ms=latency_ms,
            input_key=preview.preview_id,
        )
        self.inputs.delete(self._proxy_handoff_key(purchase.purchase_id))
        self.inputs.delete(self._proxy_challenge_key(purchase.purchase_id))
        return self._response(
            updated, service_result if result_available else None
        )

    def _save_proxy_pending(
        self,
        purchase,
        claim_token,
        *,
        settlement,
        reason,
        error=None,
    ):
        metadata = self._settlement_metadata(
            purchase, settlement=settlement
        )
        if error is not None:
            metadata["proxy_error"] = {
                "type": type(error).__name__,
                "message": str(error),
            }
        waiting = purchase.model_copy(
            update={
                "state": "payment_submitted",
                "reason_code": reason,
                "metadata": metadata,
                "updated_at": datetime.now(UTC),
            }
        )
        self.repository.save_claimed_purchase(
            waiting,
            claim_token,
            expected_execution_mode="clink_payer_proxy",
            release_claim=True,
            expected_states={purchase.state},
        )
        return self._response(waiting)

    def prepare_external_checkout(
        self, purchase_id, *, checkout_token, payer_address
    ):
        purchase, preview, offering = self._checkout_context(
            purchase_id, checkout_token
        )
        payer = self._evm_address(payer_address)
        authorization = purchase.metadata.get("authorization_resolution") or {}
        wallet_identity_id = authorization.get("wallet_identity_id")
        identities = self.core.wallet_identities(preview.user_id)
        identity = next(
            (
                item
                for item in identities
                if item.get("wallet_identity_id") == wallet_identity_id
            ),
            None,
        )
        if not identity or self._evm_address(identity.get("wallet_address")) != payer:
            raise ValueError("connected wallet does not match the authorized wallet")
        reservation = self.core.reservation(purchase.reservation_id)
        if reservation.get("authorization_rail") not in {None, "external_x402"}:
            raise ValueError("reservation is not an external x402 authorization")
        nonce = reservation.get("nonce")
        valid_after = reservation.get("valid_after")
        valid_before = reservation.get("valid_before")
        if not nonce or valid_after is None or valid_before is None:
            raise ValueError("Core external x402 challenge is unavailable")
        service_input = self.inputs.acquire(
            purchase.preview_id, max(1, self.preview_ttl)
        )
        if service_input is None:
            raise ValueError("purchase input is no longer available")
        response = self._merchant_request(
            offering,
            service_input,
            headers={"Idempotency-Key": purchase.purchase_id},
        )
        if response.status_code != 402:
            raise ValueError("merchant did not return an x402 payment challenge")
        payment_required = self._decode_payment_header(
            response.headers.get("PAYMENT-REQUIRED")
            or response.headers.get("X-PAYMENT-REQUIRED")
        )
        if payment_required.get("x402Version") != 2:
            raise ValueError("merchant must use x402 v2")
        resource = payment_required.get("resource")
        if not isinstance(resource, dict) or resource.get("url") != offering.endpoint:
            raise ValueError("merchant x402 resource does not match the selected offering")
        accepted = self._matching_requirement(payment_required, preview.payment)
        transfer_method = (accepted.get("extra") or {}).get(
            "assetTransferMethod", "eip3009"
        )
        if transfer_method != "eip3009":
            raise ValueError("browser checkout currently requires EIP-3009")
        network = str(accepted["network"])
        try:
            chain_id = int(network.split(":", 1)[1])
        except (IndexError, ValueError) as exc:
            raise ValueError("invalid EVM payment network") from exc
        domain_config = {
            **self.eip3009_domains.get(network, {}),
            **(accepted.get("extra") or {}),
        }
        if not domain_config.get("name") or not domain_config.get("version"):
            raise ValueError("EIP-3009 token domain is not configured")
        authorization = {
            "from": payer,
            "to": self._evm_address(accepted["payTo"]),
            "value": str(accepted["amount"]),
            "validAfter": str(valid_after),
            "validBefore": str(valid_before),
            "nonce": nonce,
        }
        typed_data = {
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"},
                ],
                "TransferWithAuthorization": [
                    {"name": "from", "type": "address"},
                    {"name": "to", "type": "address"},
                    {"name": "value", "type": "uint256"},
                    {"name": "validAfter", "type": "uint256"},
                    {"name": "validBefore", "type": "uint256"},
                    {"name": "nonce", "type": "bytes32"},
                ],
            },
            "primaryType": "TransferWithAuthorization",
            "domain": {
                "name": domain_config["name"],
                "version": str(domain_config["version"]),
                "chainId": chain_id,
                "verifyingContract": self._evm_address(accepted["asset"]),
            },
            "message": authorization,
        }
        checkout = {
            "payer_address": payer,
            "payment_required": payment_required,
            "payment": accepted,
            "authorization": authorization,
            "typed_data": typed_data,
        }
        ttl = max(
            1,
            int(
                (
                    (preview.expires_at if preview.expires_at.tzinfo else preview.expires_at.replace(tzinfo=UTC))
                    - datetime.now(UTC)
                ).total_seconds()
            ),
        )
        self.inputs.set(f"x402_checkout:{purchase_id}", checkout, ttl)
        return {
            "purchase_id": purchase_id,
            "payment": accepted,
            "typed_data": typed_data,
            "expires_at": preview.expires_at.isoformat(),
        }

    def complete_external_checkout(
        self, purchase_id, *, checkout_token, payer_address, signature
    ):
        purchase, _preview, offering = self._checkout_context(
            purchase_id, checkout_token
        )
        payer = self._evm_address(payer_address)
        checkout = self.inputs.pop(f"x402_checkout:{purchase_id}")
        if not checkout or checkout.get("payer_address") != payer:
            raise ValueError("x402 checkout challenge is missing or expired")
        try:
            signable = encode_typed_data(full_message=checkout["typed_data"])
            recovered = Account.recover_message(
                signable, signature=signature
            ).lower()
        except Exception as exc:
            raise ValueError("invalid x402 wallet signature") from exc
        if recovered != payer:
            raise ValueError("x402 signature payer mismatch")
        payment_payload = {
            "x402Version": 2,
            "resource": checkout["payment_required"].get("resource"),
            "accepted": checkout["payment"],
            "payload": {
                "signature": signature,
                "authorization": checkout["authorization"],
            },
        }
        payment_header = self._encode_payment_header(payment_payload)
        service_input = self.inputs.acquire(
            purchase.preview_id, max(1, self.preview_ttl)
        )
        if service_input is None:
            raise ValueError("purchase input is no longer available")
        response = self._merchant_request(
            offering,
            service_input,
            headers={
                "PAYMENT-SIGNATURE": payment_header,
                "Idempotency-Key": purchase.purchase_id,
            },
        )
        if not response.is_success:
            raise ValueError(f"merchant rejected x402 payment: HTTP {response.status_code}")
        settlement = self._decode_payment_header(
            response.headers.get("PAYMENT-RESPONSE")
            or response.headers.get("X-PAYMENT-RESPONSE")
        )
        transaction_hash = (
            settlement.get("transaction")
            or settlement.get("transactionHash")
            or settlement.get("txHash")
        )
        if not transaction_hash:
            raise ValueError("merchant payment response omitted transaction hash")
        payment = checkout["payment"]
        proof = {
            **settlement,
            "network": payment["network"],
            "asset": payment["asset"],
            "amount_atomic": str(payment["amount"]),
            "pay_to": payment["payTo"],
            "nonce": checkout["authorization"]["nonce"],
            "valid_after": checkout["authorization"]["validAfter"],
            "valid_before": checkout["authorization"]["validBefore"],
        }
        service_result = self._service_result(response)
        handoff_key = self._external_handoff_key(purchase_id)
        self.inputs.set(
            handoff_key,
            {
                "transaction_hash": transaction_hash,
                "payment_response": proof,
                "service_result": service_result,
            },
            max(self.preview_ttl, 3600),
        )
        result = self.complete_external(
            purchase_id,
            transaction_hash=transaction_hash,
            payment_response=proof,
            service_result=service_result,
        )
        if result.state in {"delivered", "paid_but_undelivered", "failed"}:
            self.inputs.delete(f"x402_checkout:{purchase_id}")
            self.inputs.delete(handoff_key)
        return result

    def complete_external(
        self,
        purchase_id,
        *,
        transaction_hash,
        payment_response,
        service_result=_UNSET,
    ):
        purchase = self.repository.get_purchase(purchase_id)
        if purchase and purchase.state in {
            "delivered",
            "paid_but_undelivered",
            "failed",
        }:
            self.inputs.delete(purchase.preview_id)
            return self._response(purchase)
        offering = (
            self.repository.active_offering(purchase.offering_id)
            if purchase
            else None
        )
        if purchase and not offering:
            raise ValueError("active provider required for purchase execution")
        if purchase and purchase.execution_mode != "external_x402_signature":
            raise ValueError("purchase execution mode mismatch")
        if not purchase or purchase.state not in {
            "signing_required",
            "payment_submitted",
        }:
            raise ValueError("external purchase is not awaiting payment")
        purchase, claim_token = self.repository.claim_purchase_execution(
            purchase,
            allowed_states={"signing_required", "payment_submitted"},
            expected_execution_mode="external_x402_signature",
        )
        if not claim_token:
            return self._response(purchase)
        entered_state = purchase.state
        service_input = self.inputs.acquire(
            purchase.preview_id, max(1, self.preview_ttl)
        )
        if service_input is None:
            return self._handle_missing_input(
                purchase, claim_token, entered_state
            )

        identity = {
            "rail": "external_x402_signature",
            "transaction_hash": transaction_hash,
            "payment_response_hash": digest(payment_response),
        }
        if entered_state == "payment_submitted":
            try:
                result = self.core.reconcile(purchase.reservation_id)
            except Exception:
                return self._save_pending_reconciliation(
                    purchase, claim_token, settlement=None
                )
            if self._retryable_settlement(result):
                purchase = purchase.model_copy(
                    update={
                        "reason_code": "EXTERNAL_PAYMENT_RECONCILIATION_REQUIRED",
                        "metadata": self._settlement_metadata(
                            purchase, settlement=result, identity=identity
                        ),
                        "updated_at": datetime.now(UTC),
                    }
                )
                self.repository.save_claimed_purchase(
                    purchase,
                    claim_token,
                    expected_execution_mode="external_x402_signature",
                    expected_states={"payment_submitted"},
                )
                try:
                    result = self.core.external_finalize(
                        purchase.reservation_id,
                        {
                            "transaction_hash": transaction_hash,
                            "payment_response": payment_response,
                        },
                    )
                except Exception:
                    return self._save_pending_reconciliation(
                        purchase, claim_token, settlement=None
                    )
            elif not self._settled(result):
                return self._save_pending_reconciliation(
                    purchase, claim_token, settlement=result
                )
        else:
            purchase = purchase.model_copy(
                update={
                    "state": "payment_submitted",
                    "reason_code": "EXTERNAL_PAYMENT_RECONCILIATION_REQUIRED",
                    "metadata": self._settlement_metadata(
                        purchase, settlement=None, identity=identity
                    ),
                    "updated_at": datetime.now(UTC),
                }
            )
            self.repository.save_claimed_purchase(
                purchase,
                claim_token,
                expected_execution_mode="external_x402_signature",
                expected_states={"signing_required"},
            )
            try:
                result = self.core.external_finalize(
                    purchase.reservation_id,
                    {
                        "transaction_hash": transaction_hash,
                        "payment_response": payment_response,
                    },
                )
            except Exception:
                return self._save_pending_reconciliation(
                    purchase, claim_token, settlement=None
                )

        if not self._settled(result):
            return self._save_pending_reconciliation(
                purchase, claim_token, settlement=result
            )

        started = time.perf_counter()
        receipt_reference = (
            result.get("receipt_id") or result.get("tx_hash") or transaction_hash
        )
        try:
            delivery_proof = result.get("external_payment_response") or payment_response
            if service_result is _UNSET:
                proof = base64.urlsafe_b64encode(
                    json.dumps(delivery_proof, separators=(",", ":")).encode()
                ).decode().rstrip("=")
                response = self._merchant_request(
                    offering,
                    service_input,
                    headers={
                        "PAYMENT-RESPONSE": proof,
                        "Idempotency-Key": purchase.purchase_id,
                    },
                )
                if not response.is_success:
                    raise RuntimeError("merchant delivery failed")
                service_result = self._service_result(response)
            updated = purchase.model_copy(
                update={
                    "state": "delivered",
                    "output_hash": digest(service_result),
                    "receipt_id": receipt_reference,
                    "reason_code": None,
                    "updated_at": datetime.now(UTC),
                }
            )
        except Exception:
            service_result = None
            updated = purchase.model_copy(
                update={
                    "state": "paid_but_undelivered",
                    "receipt_id": receipt_reference,
                    "reason_code": "DELIVERY_FAILED",
                    "updated_at": datetime.now(UTC),
                }
            )
        if updated.state == "delivered" and service_result is not None:
            self._save_result_mailbox(purchase.purchase_id, service_result)
        self._finish_terminal(
            updated,
            claim_token,
            latency_ms=self._latency_ms(started),
            input_key=purchase.preview_id,
        )
        return self._response(updated, service_result)

    def _checkout_context(self, purchase_id, checkout_token):
        purchase = self.repository.get_purchase(purchase_id)
        if not purchase or purchase.state != "signing_required":
            raise ValueError("external purchase is not awaiting wallet signature")
        if purchase.execution_mode != "external_x402_signature":
            raise ValueError("purchase execution mode mismatch")
        supplied = hashlib.sha256(checkout_token.encode()).hexdigest()
        expected = purchase.metadata.get("checkout_token_hash", "")
        if not expected or not secrets.compare_digest(supplied, expected):
            raise ValueError("invalid checkout token")
        preview = self.repository.get_preview(purchase.preview_id)
        if not preview:
            raise ValueError("purchase preview not found")
        expires_at = preview.expires_at if preview.expires_at.tzinfo else preview.expires_at.replace(tzinfo=UTC)
        if expires_at <= datetime.now(UTC):
            raise ValueError("purchase preview expired")
        offering = self.repository.active_offering(purchase.offering_id)
        if not offering:
            raise ValueError("active provider required for purchase execution")
        return purchase, preview, offering

    def _resolve_authorization(self, *, preview, offering, payment):
        return self._resolve_authorization_fields(
            user_id=preview.user_id,
            execution_mode=preview.execution_mode,
            offering=offering,
            payment=payment,
            opc_installation_id=preview.opc_installation_id,
        )

    def _resolve_authorization_fields(
        self,
        *,
        user_id,
        execution_mode,
        offering,
        payment,
        opc_installation_id=None,
    ):
        rail = {
            "clink_allowance": "native_allowance",
            "clink_payer_proxy": "clink_payer_proxy",
            "external_x402_signature": "external_x402",
        }[execution_mode]
        token_address = None
        spender_address = None
        if rail == "external_x402":
            token_address = self._evm_address(payment["asset"])
        else:
            readiness = self.core.funding_readiness()
            if rail == "clink_payer_proxy":
                supported_assets = readiness.get("supported_assets") or {}
                configured_asset = supported_assets.get(payment["network"])
                payer_address = readiness.get("payer_address")
                configured_spender = readiness.get("spender_address")
                if (
                    readiness.get("universal_payer_ready") is not True
                    or readiness.get("automatic_payment_rail")
                    != "clink_payer_proxy"
                    or not payer_address
                    or not configured_spender
                    or self._evm_address(payer_address)
                    != self._evm_address(configured_spender)
                    or not configured_asset
                    or self._evm_address(configured_asset)
                    != self._evm_address(payment["asset"])
                ):
                    raise ValueError(
                        "Core Universal Payer is not ready for this network and asset"
                    )
            hosted_advertised = any(
                (
                    readiness.get("settlement_rail") == "clink_hosted_executor",
                    readiness.get("automatic_payment_rail")
                    == "clink_hosted_executor",
                    readiness.get("hosted_facilitator_enabled") is True,
                )
            )
            if rail == "native_allowance" and hosted_advertised:
                if (
                    readiness.get("status") != "ready"
                    or readiness.get("live_funding_enabled") is not True
                    or readiness.get("hosted_facilitator_enabled") is not True
                    or readiness.get("hosted_facilitator_ready") is not True
                    or readiness.get("settlement_rail")
                    != "clink_hosted_executor"
                    or readiness.get("automatic_payment_rail")
                    != "clink_hosted_executor"
                ):
                    raise ValueError("Core Hosted executor is not ready")
                supported_assets = readiness.get("supported_assets") or {}
                spender_addresses = readiness.get("spender_addresses") or {}
                configured_asset = supported_assets.get(payment["network"])
                spender_address = spender_addresses.get(payment["network"])
                if (
                    not configured_asset
                    or not spender_address
                    or self._evm_address(configured_asset)
                    != self._evm_address(payment["asset"])
                ):
                    raise ValueError(
                        "Core Hosted executor is unavailable for this network and asset"
                    )
            else:
                spender_address = readiness.get("spender_address")
            if not spender_address:
                raise ValueError("Core native allowance spender is unavailable")
            if isinstance(payment.get("asset"), str) and payment["asset"].startswith("0x"):
                token_address = self._evm_address(payment["asset"])
        payload = {
            "user_id": user_id,
            "agent_id": "hermes",
            "authorization_rail": rail,
            "product": "marketplace",
            "venue": "clink_marketplace",
            "merchant": offering.provider_id,
            "merchant_trust_tier": offering.metadata.get(
                "trust_tier", "clink_verified"
            ),
            "network": payment["network"],
            "token_address": token_address,
            "asset": payment["asset"],
            "spender_address": spender_address,
            "amount_usdc": str(payment.get("price_usd") or 0),
            "destination": payment["pay_to"],
            "resource": offering.endpoint,
        }
        if opc_installation_id is not None:
            payload["opc_installation_id"] = opc_installation_id
        authorization = self.core.resolve_authorization(payload)
        if (
            opc_installation_id is not None
            and (
                not isinstance(authorization, dict)
                or authorization.get("opc_installation_id")
                != opc_installation_id
            )
        ):
            raise ValueError("Core OPC authorization mismatch")
        return authorization

    @classmethod
    def _canonical_core_payment(cls, payment):
        canonical = dict(payment)
        if str(payment.get("network", "")).startswith("eip155:"):
            canonical["asset"] = cls._evm_address(payment["asset"])
            canonical["pay_to"] = cls._evm_address(payment["pay_to"])
        return canonical

    @staticmethod
    def _core_scope(*, purchase_id, preview, offering, payment, authorization):
        scope = {
            "purchase_id": purchase_id,
            "quote_hash": preview.quote_hash,
            "network": payment["network"],
            "asset": payment["asset"],
            "amount_atomic": payment["amount_atomic"],
            "destination": payment["pay_to"],
            "resource": offering.endpoint,
            "authorization_rail": authorization["authorization_rail"],
            "product": "marketplace",
            "merchant_trust_tier": offering.metadata.get(
                "trust_tier", "clink_verified"
            ),
            "wallet_identity_id": authorization["wallet_identity_id"],
            "spending_grant_id": authorization["spending_grant_id"],
        }
        if authorization["authorization_rail"] in {
            "native_allowance",
            "clink_payer_proxy",
        }:
            scope["asset_allowance_id"] = authorization["asset_allowance_id"]
        else:
            scope["token_address"] = payment["asset"]
        if preview.opc_installation_id is not None:
            scope["opc_installation_id"] = preview.opc_installation_id
        return scope

    @staticmethod
    def _opc_installation_id(value):
        if value is None:
            return None
        if (
            not isinstance(value, str)
            or len(value) != 44
            or not value.startswith("opc_")
        ):
            raise ValueError("OPC installation id is invalid")
        try:
            int(value[4:], 16)
        except ValueError as exc:
            raise ValueError("OPC installation id is invalid") from exc
        if value != value.lower():
            raise ValueError("OPC installation id is invalid")
        return value

    @staticmethod
    def _decode_payment_header(value):
        if not value:
            raise ValueError("x402 payment header is missing")
        try:
            padded = value + "=" * (-len(value) % 4)
            decoded = base64.urlsafe_b64decode(padded.encode())
            payload = json.loads(decoded)
        except Exception as exc:
            raise ValueError("x402 payment header is invalid") from exc
        if not isinstance(payload, dict):
            raise ValueError("x402 payment header is invalid")
        return payload

    @staticmethod
    def _encode_payment_header(value):
        return base64.urlsafe_b64encode(
            json.dumps(value, separators=(",", ":")).encode()
        ).decode().rstrip("=")

    @classmethod
    def _matching_requirement(cls, payment_required, locked):
        accepts = payment_required.get("accepts")
        if not isinstance(accepts, list):
            raise ValueError("merchant x402 challenge has no payment requirements")
        expected = {
            "scheme": str(locked["scheme"]).lower(),
            "network": str(locked["network"]).lower(),
            "amount": str(int(str(locked["amount_atomic"]))),
            "asset": str(locked["asset"]).lower(),
            "payTo": cls._evm_address(locked["pay_to"]),
        }
        for item in accepts:
            if not isinstance(item, dict):
                continue
            try:
                candidate = {
                    "scheme": str(item["scheme"]).lower(),
                    "network": str(item["network"]).lower(),
                    "amount": str(int(str(item["amount"]))),
                    "asset": str(item["asset"]).lower(),
                    "payTo": cls._evm_address(item["payTo"]),
                }
            except (KeyError, TypeError, ValueError):
                continue
            if candidate == expected:
                return item
        raise ValueError("merchant x402 challenge drifted from the locked quote")

    @staticmethod
    def _merchant_request_payload(offering, service_input):
        if (
            offering.source == "cdp_bazaar"
            and isinstance(service_input, dict)
            and service_input.get("type") == "http"
            and service_input.get("bodyType") == "json"
        ):
            requested_method = str(
                service_input.get("method", offering.method)
            ).upper()
            if requested_method != offering.method.upper():
                raise ValueError(
                    "Bazaar request method does not match the selected offering"
                )
            if "body" not in service_input:
                raise ValueError("Bazaar JSON request body is missing")
            if service_input["body"] is None:
                return {"content": b"null"}
            return {"json": service_input["body"]}
        return {"json": service_input}

    def _merchant_request(self, offering, service_input, *, headers):
        request_payload = self._merchant_request_payload(offering, service_input)
        request_headers = dict(headers)
        if "content" in request_payload:
            request_headers.setdefault("Content-Type", "application/json")
        return self.client.request(
            offering.method,
            offering.endpoint,
            **request_payload,
            headers=request_headers,
        )

    @staticmethod
    def _evm_address(value):
        if not isinstance(value, str) or len(value) != 42 or not value.startswith("0x"):
            raise ValueError("invalid EVM address")
        try:
            int(value[2:], 16)
        except ValueError as exc:
            raise ValueError("invalid EVM address") from exc
        return value.lower()

    def process_finalization(self, item):
        return self.core.finalize(
            item["payload"]["reservation_id"],
            {
                "delivery_status": item["payload"]["delivery_status"],
                "output_hash": item["payload"].get("output_hash"),
            },
        )

    def process_reconciliation(self, purchase, claim_token):
        if purchase.execution_mode == "clink_payer_proxy":
            preview = self.repository.get_preview(purchase.preview_id)
            if not preview:
                return self._save_proxy_pending(
                    purchase,
                    claim_token,
                    settlement=None,
                    reason="PROXY_DELIVERY_CONTEXT_UNAVAILABLE",
                )
            if purchase.reason_code == "PROXY_COMPATIBILITY_RELEASE_PENDING":
                return self._downgrade_proxy_purchase(
                    purchase,
                    claim_token,
                    preview=preview,
                    error=RuntimeError("merchant x402 proxy is incompatible"),
                )
            handoff = self._proxy_handoff(purchase)
            if handoff is not None:
                try:
                    settlement = self.core.reconcile(purchase.reservation_id)
                except Exception as exc:
                    return self._save_proxy_pending(
                        purchase,
                        claim_token,
                        settlement=None,
                        reason="PROXY_PAYMENT_RECONCILIATION_REQUIRED",
                        error=exc,
                    )
                if not self._proxy_handoff_payment_failed(settlement, handoff):
                    return self._continue_proxy_purchase(
                        purchase=purchase,
                        claim_token=claim_token,
                        preview=preview,
                        offering=None,
                        service_input=None,
                        challenge=None,
                        settlement=settlement,
                    )
                purchase = self._clear_proxy_handoff(
                    purchase, claim_token
                )
            offering = self.repository.active_offering(purchase.offering_id)
            service_input = self.inputs.acquire(
                purchase.preview_id, self.proxy_context_ttl
            )
            if not offering or service_input is None:
                return self._save_proxy_pending(
                    purchase,
                    claim_token,
                    settlement=None,
                    reason="PROXY_DELIVERY_CONTEXT_UNAVAILABLE",
                )
            return self._execute_proxy_purchase(
                purchase=purchase,
                claim_token=claim_token,
                preview=preview,
                offering=offering,
                service_input=service_input,
                payment=preview.payment,
                entered_state="payment_submitted",
            )

        settlement = self.core.reconcile(purchase.reservation_id)
        if self._retryable_settlement(settlement) and purchase.execution_mode == "clink_allowance":
            preview = self.repository.get_preview(purchase.preview_id)
            if not preview:
                raise ValueError("purchase preview not found for reconciliation")
            payment = preview.payment
            settlement = self.core.settle(
                purchase.reservation_id,
                {
                    "payment_authorization": {
                        "scheme": payment["scheme"],
                        "network": payment["network"],
                        "asset": payment["asset"],
                        "amount_atomic": payment["amount_atomic"],
                        "pay_to": payment["pay_to"],
                    }
                },
            )
        if self._settled(settlement) and purchase.execution_mode == "external_x402_signature":
            handoff_key = self._external_handoff_key(purchase.purchase_id)
            handoff = self.inputs.get(handoff_key)
            if handoff is not None:
                if not self._handoff_matches_settlement(
                    purchase, settlement, handoff
                ):
                    updated = purchase.model_copy(
                        update={
                            "reason_code": "PAYMENT_HANDOFF_MISMATCH",
                            "metadata": self._settlement_metadata(
                                purchase, settlement=settlement
                            ),
                            "updated_at": datetime.now(UTC),
                        }
                    )
                    self.repository.save_claimed_purchase(
                        updated,
                        claim_token,
                        expected_execution_mode=purchase.execution_mode,
                        release_claim=True,
                        expected_states={"payment_submitted"},
                    )
                    return updated
                service_result = handoff["service_result"]
                updated = purchase.model_copy(
                    update={
                        "state": "delivered",
                        "output_hash": digest(service_result),
                        "receipt_id": settlement.get("receipt_id")
                        or settlement.get("tx_hash")
                        or handoff.get("transaction_hash"),
                        "reason_code": None,
                        "metadata": self._settlement_metadata(
                            purchase, settlement=settlement
                        ),
                        "updated_at": datetime.now(UTC),
                    }
                )
                self._save_result_mailbox(
                    purchase.purchase_id, service_result
                )
                self._finish_terminal(
                    updated,
                    claim_token,
                    latency_ms=0,
                    input_key=purchase.preview_id,
                )
                self.inputs.delete(handoff_key)
                self.inputs.delete(f"x402_checkout:{purchase.purchase_id}")
                return self._response(updated, service_result)
        reason = "PAYMENT_RECONCILIATION_PENDING"
        if self._settled(settlement):
            reason = "PAYMENT_SETTLED_DELIVERY_RETRY_REQUIRED"
        elif self._manual_review_required(settlement):
            reason = "PAYMENT_MANUAL_REVIEW_REQUIRED"
        elif self._retryable_settlement(settlement):
            reason = "EXTERNAL_PAYMENT_RETRY_REQUIRED"
        updated = purchase.model_copy(
            update={
                "reason_code": reason,
                "metadata": self._settlement_metadata(
                    purchase, settlement=settlement
                ),
                "updated_at": datetime.now(UTC),
            }
        )
        self.repository.save_claimed_purchase(
            updated,
            claim_token,
            expected_execution_mode=purchase.execution_mode,
            release_claim=True,
            expected_states={"payment_submitted"},
        )
        return updated

    @staticmethod
    def _external_handoff_key(purchase_id):
        return f"x402_handoff:{purchase_id}"

    @staticmethod
    def _proxy_handoff_key(purchase_id):
        return f"x402_proxy_handoff:{purchase_id}"

    @staticmethod
    def _proxy_challenge_key(purchase_id):
        return f"x402_proxy_challenge:{purchase_id}"

    @staticmethod
    def _proxy_incompatibility_key(offering_id, quote_hash):
        return f"x402_proxy_incompatible:{offering_id}:{quote_hash}"

    def _proxy_handoff(self, purchase):
        volatile = self.inputs.get(
            self._proxy_handoff_key(purchase.purchase_id)
        )
        if volatile is not None:
            return volatile
        durable = purchase.metadata.get("proxy_handoff")
        return dict(durable) if isinstance(durable, dict) else None

    @staticmethod
    def _proxy_handoff_payment_failed(settlement, handoff):
        if not settlement or settlement.get("state") != "payer_funded":
            return False
        handoff_hash = str(handoff.get("transaction_hash") or "").lower()
        failed_hashes = {
            str(value).lower()
            for value in settlement.get("failed_merchant_tx_hashes", [])
        }
        return bool(handoff_hash and handoff_hash in failed_hashes)

    def _clear_proxy_handoff(self, purchase, claim_token):
        metadata = dict(purchase.metadata)
        metadata.pop("proxy_handoff", None)
        updated = purchase.model_copy(
            update={
                "metadata": metadata,
                "updated_at": datetime.now(UTC),
            }
        )
        self.repository.save_claimed_purchase(
            updated,
            claim_token,
            expected_execution_mode="clink_payer_proxy",
            expected_states={"payment_submitted"},
        )
        self.inputs.delete(self._proxy_handoff_key(purchase.purchase_id))
        return updated

    def _downgrade_proxy_purchase(
        self,
        purchase,
        claim_token,
        *,
        preview,
        error,
    ):
        self.inputs.set(
            self._proxy_incompatibility_key(
                preview.offering_id, preview.quote_hash
            ),
            {"reason": str(error)},
            3600,
        )
        try:
            self.core.release(
                purchase.reservation_id,
                "merchant_x402_proxy_incompatible",
            )
        except Exception:
            return self._save_proxy_pending(
                purchase,
                claim_token,
                settlement=None,
                reason="PROXY_COMPATIBILITY_RELEASE_PENDING",
                error=error,
            )
        return self._response(
            self._fail_claimed(
                purchase,
                claim_token,
                "MERCHANT_X402_PROXY_INCOMPATIBLE",
                input_key=preview.preview_id,
            )
        )

    @staticmethod
    def _proxy_incompatibility_error(error):
        return (
            getattr(error, "status_code", None) == 409
            and getattr(error, "code", None) == "PROXY_INCOMPATIBLE"
        )

    @staticmethod
    def _result_mailbox_key(purchase_id):
        return f"purchase_result:{purchase_id}"

    def _save_result_mailbox(self, purchase_id, service_result):
        self.inputs.set(
            self._result_mailbox_key(purchase_id),
            service_result,
            max(self.preview_ttl, 900),
        )

    def result_for_purchase(self, purchase_id):
        return self.inputs.get(self._result_mailbox_key(purchase_id))

    @staticmethod
    def _handoff_matches_settlement(purchase, settlement, handoff):
        settlement_metadata = dict(purchase.metadata.get("settlement") or {})
        expected_tx_hash = str(
            settlement_metadata.get("transaction_hash") or ""
        ).lower()
        handoff_tx_hash = str(handoff.get("transaction_hash") or "").lower()
        settled_tx_hash = str(settlement.get("tx_hash") or "").lower()
        expected_proof_hash = settlement_metadata.get("payment_response_hash")
        handoff_proof = handoff.get("payment_response")
        if not expected_tx_hash or handoff_tx_hash != expected_tx_hash:
            return False
        if settled_tx_hash and settled_tx_hash != expected_tx_hash:
            return False
        return bool(
            expected_proof_hash
            and handoff_proof is not None
            and digest(handoff_proof) == expected_proof_hash
        )

    def _handle_missing_input(self, purchase, claim_token, entered_state):
        if entered_state == "payment_submitted":
            try:
                settlement = self.core.reconcile(purchase.reservation_id)
            except Exception:
                return self._save_pending_reconciliation(
                    purchase, claim_token, settlement=None
                )
            if settlement.get("state") in {"settled", "finalized"}:
                updated = purchase.model_copy(
                    update={
                        "state": "paid_but_undelivered",
                        "receipt_id": settlement.get("receipt_id")
                        or settlement.get("tx_hash"),
                        "reason_code": "INPUT_UNAVAILABLE_AFTER_PAYMENT",
                        "updated_at": datetime.now(UTC),
                    }
                )
                self._finish_terminal(
                    updated,
                    claim_token,
                    latency_ms=0,
                    input_key=purchase.preview_id,
                )
                return self._response(updated)
            if not self._retryable_settlement(settlement):
                return self._save_pending_reconciliation(
                    purchase, claim_token, settlement=settlement
                )
        if purchase.reservation_id:
            try:
                self.core.release(
                    purchase.reservation_id, "marketplace_input_unavailable"
                )
            except Exception:
                waiting = purchase.model_copy(
                    update={
                        "reason_code": "INPUT_UNAVAILABLE_RELEASE_PENDING",
                        "updated_at": datetime.now(UTC),
                    }
                )
                self.repository.save_claimed_purchase(
                    waiting,
                    claim_token,
                    expected_execution_mode=purchase.execution_mode,
                    release_claim=True,
                    expected_states={purchase.state},
                )
                return self._response(waiting)
        return self._response(
            self._fail_claimed(
                purchase,
                claim_token,
                "INPUT_UNAVAILABLE",
                input_key=purchase.preview_id,
            )
        )

    def _save_pending_reconciliation(self, purchase, claim_token, *, settlement):
        reason = (
            "PAYMENT_MANUAL_REVIEW_REQUIRED"
            if self._manual_review_required(settlement)
            else "PAYMENT_RECONCILIATION_PENDING"
        )
        waiting = purchase.model_copy(
            update={
                "reason_code": reason,
                "metadata": self._settlement_metadata(
                    purchase, settlement=settlement
                ),
                "updated_at": datetime.now(UTC),
            }
        )
        self.repository.save_claimed_purchase(
            waiting,
            claim_token,
            expected_execution_mode=purchase.execution_mode,
            release_claim=True,
            expected_states={"payment_submitted"},
        )
        return self._response(waiting)

    @staticmethod
    def _settled(settlement):
        return bool(settlement and settlement.get("state") in {"settled", "finalized"})

    @staticmethod
    def _proxy_funded(settlement):
        return bool(
            settlement
            and settlement.get("state") in {"payer_funded", "proxy_payment_ready"}
        )

    @staticmethod
    def _retryable_settlement(settlement):
        return bool(
            settlement
            and settlement.get("state") in {"spending_reserved", "payment_submitted"}
            and settlement.get("reconciliation_status") == "retryable"
            and settlement.get("next_action") == "retry_settlement"
            and settlement.get("tx_hash") is None
            and settlement.get("receipt_id") is None
            and settlement.get("receipt") is None
        )

    @staticmethod
    def _manual_review_required(settlement):
        return bool(
            settlement
            and settlement.get("reconciliation_status")
            == "manual_review_required"
        )

    @staticmethod
    def _settlement_metadata(purchase, *, settlement, identity=None):
        existing = dict(purchase.metadata)
        details = dict(existing.get("settlement") or {})
        details.update(identity or {})
        if settlement:
            details.update(
                {
                    key: settlement.get(key)
                    for key in (
                        "state",
                        "reconciliation_status",
                        "next_action",
                        "settlement_rail",
                        "tx_hash",
                        "reconciliation_attempts",
                        "reconciliation_started_at",
                        "last_reconciliation_at",
                        "operator_reconciliation_attempts",
                        "last_operator_reconciliation_at",
                        "manual_review_reason",
                        "manual_review_required_at",
                    )
                    if settlement.get(key) is not None
                }
            )
        details["checked_at"] = datetime.now(UTC).isoformat()
        existing["settlement"] = details
        return existing

    def _fail_claimed(self, purchase, claim_token, reason, *, input_key):
        updated = self._save_claimed(
            purchase, claim_token, "failed", reason
        )
        self.inputs.delete(input_key)
        return updated

    def _save_claimed(self, purchase, claim_token, state, reason):
        expected_state = purchase.state
        updated = purchase.model_copy(
            update={
                "state": state,
                "reason_code": reason,
                "updated_at": datetime.now(UTC),
            }
        )
        self.repository.save_claimed_purchase(
            updated,
            claim_token,
            expected_execution_mode=purchase.execution_mode,
            release_claim=True,
            expected_states={expected_state},
        )
        return updated

    @staticmethod
    def _outcome_dimensions(state):
        return {
            "delivered": {"payment_success": 100, "delivery_success": 100},
            "paid_but_undelivered": {
                "payment_success": 100,
                "delivery_success": 0,
            },
            "failed": {"payment_success": 0},
        }[state]

    def _finish_terminal(self, purchase, claim_token, *, latency_ms, input_key):
        self._save_terminal(purchase, claim_token, latency_ms=latency_ms)
        self._finalize_terminal(purchase)
        self.inputs.delete(input_key)

    def _save_terminal(self, purchase, claim_token, *, latency_ms):
        finalization = {
            "target_state": purchase.state,
            "payload": {
                "reservation_id": purchase.reservation_id,
                "delivery_status": purchase.state,
                "output_hash": purchase.output_hash,
            },
        }
        self.repository.save_purchase_with_reputation_event(
            purchase,
            purchase.state,
            self._outcome_dimensions(purchase.state),
            claim_token=claim_token,
            expected_execution_mode=purchase.execution_mode,
            latency_ms=latency_ms,
            finalization=finalization,
            expected_states={"payment_submitted"},
        )

    def _finalize_terminal(self, purchase):
        try:
            self.core.finalize(
                purchase.reservation_id,
                {
                    "delivery_status": purchase.state,
                    "output_hash": purchase.output_hash,
                },
            )
            self.repository.complete_finalization_for_purchase(
                purchase.purchase_id
            )
        except Exception:
            pass

    @staticmethod
    def _response(purchase, service_result=None):
        return PurchaseExecutionResult(purchase, service_result)

    @staticmethod
    def _service_result(response):
        return (
            response.json()
            if "json" in response.headers.get("content-type", "")
            else response.text
        )

    @staticmethod
    def _latency_ms(started):
        return round((time.perf_counter() - started) * 1000)
