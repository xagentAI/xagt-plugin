"""Local, process-scoped Commerce runtime for the Agentonomy demo.

The runtime composes the existing Marketplace repository, quote service and
purchase service with the demo CoreBridge.  It owns only the local merchant
transport and the presentation of results; authorization, budget reservation,
settlement and receipt signing remain Core responsibilities.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import httpx

from clink_middleware.receipt import verify_clink_receipt
from examples.commerce.core_bridge import CoreBridge
from services.marketplace_repository import MarketplaceRepository
from services.purchase_service import PurchaseService
from services.quote_service import QuoteService
from shared.models import PaymentOption, Provider, ServiceOffering


USER_ID = "commerce-demo-user"
PROVIDER_DOMAIN = "commerce.example"
MERCHANT_BASE = f"https://{PROVIDER_DOMAIN}/services/order-analysis"

_CENT = Decimal("0.01")
_PRICE_030 = Decimal("0.30")
_PRICE_080 = Decimal("0.80")


def _money(value: Any) -> str:
    """Render a decimal amount with the stable precision used by the demo."""

    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("amount must be a decimal") from exc
    if not amount.is_finite():
        raise ValueError("amount must be finite")
    if abs(amount) > Decimal("1000000000000"):
        raise ValueError("amount is out of bounds")
    try:
        return format(amount.quantize(_CENT), ".2f")
    except InvalidOperation as exc:
        raise ValueError("amount precision is invalid") from exc


class _MerchantTransport:
    """In-process merchant HTTP adapter used by the real PurchaseService."""

    def __init__(self, runtime: "CommerceRuntime", *, fail_delivery: bool):
        self.runtime = runtime
        self.fail_delivery = fail_delivery

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.runtime._merchant_delivery_attempts += 1
        try:
            offering = self.runtime._offerings_by_endpoint[str(request.url)]
        except KeyError:
            return httpx.Response(404, json={"error": "merchant endpoint not found"})

        try:
            payload = json.loads(request.content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return httpx.Response(400, json={"error": "request body must be JSON"})

        try:
            receipt = self.runtime._verify_merchant_receipt(
                request,
                offering,
            )
            result = self.runtime._order_analysis(payload)
        except ValueError as exc:
            return httpx.Response(401, json={"error": str(exc)})

        if self.fail_delivery:
            self.runtime._merchant_delivery_failures += 1
            return httpx.Response(
                503,
                json={
                    "error": "simulated merchant delivery failure",
                    "receipt_id": receipt.get("receipt_id"),
                },
            )

        self.runtime._merchant_delivery_successes += 1
        return httpx.Response(200, json=result)


class CommerceRuntime:
    """Compose real Marketplace services with the local CoreBridge."""

    def __init__(self, state_dir: Path, *, fail_delivery: bool = False):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.fail_delivery = fail_delivery
        self._merchant_delivery_attempts = 0
        self._merchant_delivery_successes = 0
        self._merchant_delivery_failures = 0
        self._receipt_signing_key: str | None = None
        self._network: str | None = None
        self._asset: str | None = None
        self._pay_to: str | None = None

        database_url = f"sqlite+pysqlite:///{self.state_dir / 'marketplace.sqlite3'}"
        self.repository = MarketplaceRepository(database_url)

        # CoreBridge is the only Core dependency of this module.  It is a
        # context manager because its local state and simulated grant are
        # process scoped.
        self.core = CoreBridge(self.state_dir)
        self.provider: Provider | None = None
        self.offerings: tuple[ServiceOffering, ...] = ()
        self.quotes: QuoteService | None = None
        self.purchases: PurchaseService | None = None
        self._offerings_by_endpoint: dict[str, ServiceOffering] = {}
        self._merchant_transport: _MerchantTransport | None = None
        self._merchant_client: httpx.Client | None = None
        self._entered = False

    def __enter__(self) -> "CommerceRuntime":
        if not self._entered:
            try:
                entered = self.core.__enter__()
                if entered is not None:
                    self.core = entered
                snapshot = self._core_snapshot_for_setup()
                self._network = snapshot["network"]
                self._asset = snapshot["token"]
                self._pay_to = snapshot["pay_to"]
                self._receipt_signing_key = snapshot["receipt_signing_key"]
                self.provider, self.offerings = self._register_catalog()
                self._offerings_by_endpoint = {
                    offering.endpoint: offering for offering in self.offerings
                }
                self.quotes = QuoteService(
                    self.repository,
                    native_provider_ids={self.provider.provider_id},
                )
                self._merchant_transport = _MerchantTransport(
                    self,
                    fail_delivery=self.fail_delivery,
                )
                self._merchant_client = httpx.Client(
                    transport=httpx.MockTransport(self._merchant_transport),
                )
                self.purchases = PurchaseService(
                    self.repository,
                    self.core,
                    client=self._merchant_client,
                    native_provider_ids={self.provider.provider_id},
                    preview_ttl=300,
                    proxy_context_ttl=900,
                )
                self._entered = True
            except Exception as exc:
                try:
                    self.core.__exit__(type(exc), exc, exc.__traceback__)
                finally:
                    if self._merchant_client is not None:
                        self._merchant_client.close()
                    self.repository.engine.dispose()
                raise
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        try:
            if self._merchant_client is not None:
                self._merchant_client.close()
                self._merchant_client = None
        finally:
            try:
                self.repository.engine.dispose()
            finally:
                if self._entered:
                    self._entered = False
                    self.core.__exit__(exc_type, exc_value, traceback)
        return False

    def _core_snapshot_for_setup(self) -> dict[str, str]:
        snapshot = self.core.snapshot()
        if not isinstance(snapshot, dict):
            raise RuntimeError("Core snapshot is invalid")
        required = {"network", "token", "pay_to", "receipt_signing_key"}
        missing = sorted(key for key in required if key not in snapshot)
        if missing:
            raise RuntimeError(
                "Core snapshot missing required setup fields: " + ", ".join(missing)
            )
        values = {key: snapshot[key] for key in required}
        for key, value in values.items():
            if not isinstance(value, str) or not value.strip():
                raise RuntimeError(f"Core snapshot field {key} is invalid")
        return values

    def _require_started(self) -> None:
        if (
            not self._entered
            or self.provider is None
            or self.quotes is None
            or self.purchases is None
        ):
            raise RuntimeError("CommerceRuntime must be used as a context manager")

    def _register_catalog(self) -> tuple[Provider, tuple[ServiceOffering, ...]]:
        provider = Provider(
            provider_id="commerce_analytics",
            name="Agentonomy Commerce Demo Merchant",
            domain=PROVIDER_DOMAIN,
            source="agentonomy_commerce_demo",
            status="active",
            metadata={"simulation": True},
        )
        common = {
            "provider_id": provider.provider_id,
            "source": "agentonomy_commerce_demo",
            "name": "Order analysis",
            "description": "Compute order count, total and category totals from supplied orders.",
            "method": "POST",
            "input_schema": {
                "type": "object",
                "required": ["orders"],
                "properties": {
                    "orders": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 1000,
                        "items": {
                            "type": "object",
                            "required": ["amount", "category"],
                            "properties": {
                                "amount": {"type": "string"},
                                "category": {"type": "string"},
                            },
                            "additionalProperties": False,
                        },
                    }
                },
                "additionalProperties": False,
            },
            "output_schema": {
                "type": "object",
                "required": ["count", "total", "by_category"],
            },
            "tags": ["analysis", "orders", "commerce"],
            "status": "verified",
            "metadata": {
                "trust_tier": "clink_verified",
                "verification_source": "agentonomy_commerce_demo",
                "simulation": True,
            },
        }
        offerings = (
            ServiceOffering(
                **common,
                source_id=f"POST {MERCHANT_BASE}/0.30",
                endpoint=f"{MERCHANT_BASE}/0.30",
                payment_options=[self._payment("300000", _PRICE_030)],
            ),
            ServiceOffering(
                **common,
                source_id=f"POST {MERCHANT_BASE}/0.80",
                endpoint=f"{MERCHANT_BASE}/0.80",
                payment_options=[self._payment("800000", _PRICE_080)],
            ),
        )
        self.repository.upsert_provider(provider)
        verified_at = datetime.now(UTC)
        for offering in offerings:
            self.repository.upsert_offering(offering, verified_at=verified_at)
        return provider, offerings

    def _payment(self, amount_atomic: str, price_usd: Decimal) -> PaymentOption:
        return PaymentOption(
            scheme="exact",
            network=self._network,
            asset=self._asset,
            amount_atomic=amount_atomic,
            pay_to=self._pay_to,
            price_usd=price_usd,
            metadata={"token": "USDC", "simulation": True},
        )

    def search(self, query: str = "analysis") -> dict[str, Any]:
        """Return the public catalog shape consumed by the Node worker."""

        self._require_started()
        quotes = self.quotes.compare(query)
        items = []
        for quote in quotes:
            payload = quote.model_dump(mode="json")
            payment = payload["payment"]
            offering_id = payload["offering_id"]
            items.append(
                {
                    "offering_id": offering_id,
                    "offer_id": offering_id,
                    "name": payload["name"],
                    "description": self.repository.active_offering(
                        offering_id
                    ).description,
                    "price_usd": _money(payment.get("price_usd")),
                    "payment": payment,
                    "execution_mode": payload["execution_mode"],
                    "payment_capability": payload["payment_capability"],
                    "trust_tier": payload["trust_tier"],
                }
            )
        return {"count": len(items), "items": items}

    def details(self, offering_id: str) -> dict[str, Any]:
        self._require_started()
        offering = self.repository.active_offering(offering_id)
        if not offering:
            raise ValueError("verified offering not found")
        provider = self.repository.get_provider(offering.provider_id)
        quotes = [
            quote.model_dump(mode="json")
            for quote in self.quotes.compare(offering.name)
            if quote.offering_id == offering_id
        ]
        return {
            "offering": offering.model_dump(mode="json"),
            "provider": provider.model_dump(mode="json") if provider else None,
            "reputation": self.repository.reputation(offering_id),
            "quotes": quotes,
        }

    def preview(self, offering_id: str, service_input: dict[str, Any]) -> dict[str, Any]:
        self._require_started()
        self._validate_order_input(service_input)
        preview = self.purchases.create_preview(
            user_id=USER_ID,
            offering_id=offering_id,
            service_input=service_input,
        )
        return preview.model_dump(mode="json")

    def execute(self, preview_id: str) -> dict[str, Any]:
        self._require_started()
        result = self.purchases.execute(preview_id)
        return self._execution_payload(result)

    def purchase(self, purchase_id: str) -> dict[str, Any]:
        self._require_started()
        purchase = self.repository.get_purchase(purchase_id)
        if not purchase:
            raise ValueError("purchase not found")
        payload = purchase.model_dump(mode="json")
        payload["service_result"] = (
            self.purchases.result_for_purchase(purchase_id)
            if purchase.state == "delivered"
            else None
        )
        return payload

    def snapshot(self) -> dict[str, Any]:
        """Return safe public simulation evidence, excluding Core secrets."""

        self._require_started()
        raw = self.core.snapshot()
        if not isinstance(raw, dict):
            raise RuntimeError("Core snapshot is invalid")
        required = {
            "budget_usdc",
            "used_amount_usdc",
            "reserved_amount_usdc",
            "settlement_submissions",
        }
        missing = sorted(key for key in required if key not in raw)
        if missing:
            raise RuntimeError(
                "Core snapshot missing accounting fields: " + ", ".join(missing)
            )
        budget = _money(raw["budget_usdc"])
        used = _money(raw["used_amount_usdc"])
        reserved = _money(raw["reserved_amount_usdc"])
        remaining = _money(Decimal(budget) - Decimal(used) - Decimal(reserved))
        submissions = raw["settlement_submissions"]
        if isinstance(submissions, bool) or not isinstance(submissions, int):
            raise RuntimeError("Core snapshot settlement_submissions is invalid")
        return {
            "simulation": True,
            "real_funds": False,
            "budget_usdc": budget,
            "used_amount_usdc": used,
            "reserved_amount_usdc": reserved,
            "remaining_amount_usdc": remaining,
            "settlement_submissions": submissions,
            # A delivery counter records attempts, including a 503.  The
            # separate success/failure counters make the terminal outcome
            # explicit without hiding a paid-but-undelivered attempt.
            "merchant_deliveries": self._merchant_delivery_attempts,
            "merchant_delivery_attempts": self._merchant_delivery_attempts,
            "merchant_delivery_successes": self._merchant_delivery_successes,
            "merchant_delivery_failures": self._merchant_delivery_failures,
        }

    def revoke(self) -> Any:
        self._require_started()
        return self.core.revoke()

    def _execution_payload(self, result: dict[str, Any]) -> dict[str, Any]:
        purchase = result["purchase"]
        payload = purchase.model_dump(mode="json")
        service_result = result.get("service_result")
        if service_result is None and purchase.state == "delivered":
            service_result = self.purchases.result_for_purchase(purchase.purchase_id)
        payload["service_result"] = service_result
        return payload

    def _verify_merchant_receipt(
        self,
        request: httpx.Request,
        offering: ServiceOffering,
    ) -> dict[str, Any]:
        token = request.headers.get("X-CLINK-PAYMENT-RECEIPT")
        if not token:
            raise ValueError("Clink payment receipt is required")
        if not self._receipt_signing_key:
            raise ValueError("Core receipt verifier is unavailable")
        payment = offering.payment_options[0]
        receipt = verify_clink_receipt(
            token,
            secret=self._receipt_signing_key,
            merchant_id=offering.provider_id,
            resource=offering.endpoint,
        )
        scope = receipt.get("metadata", {}).get("receipt_scope", {})
        purchase_id = request.headers.get("Idempotency-Key")
        if not purchase_id or scope.get("purchase_id") != purchase_id:
            raise ValueError("receipt purchase scope mismatch")
        if scope.get("amount_atomic") != payment.amount_atomic:
            raise ValueError("receipt amount scope mismatch")
        try:
            signed_amount = Decimal(str(scope["amount_usdc"]))
        except (KeyError, InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError("receipt price scope is missing") from exc
        if signed_amount != Decimal(str(payment.price_usd)):
            raise ValueError("receipt price scope mismatch")
        signed_network = scope.get("network") or scope.get("chain")
        if signed_network != payment.network:
            raise ValueError("receipt network scope mismatch")
        receipt_asset = scope.get("asset") or scope.get("token_address")
        if not receipt_asset:
            raise ValueError("receipt asset scope is missing")
        if str(receipt_asset).lower() != payment.asset.lower():
            raise ValueError("receipt asset scope mismatch")
        signed_token = scope.get("token")
        if not signed_token:
            raise ValueError("receipt token scope is missing")
        if str(signed_token).lower() not in {
            "usdc",
            payment.asset.lower(),
        }:
            raise ValueError("receipt token scope mismatch")
        signed_pay_to = scope.get("pay_to") or scope.get("destination")
        if not signed_pay_to:
            raise ValueError("receipt payee scope is missing")
        if str(signed_pay_to).lower() != payment.pay_to.lower():
            raise ValueError("receipt payee scope mismatch")
        if scope.get("resource") != offering.endpoint:
            raise ValueError("receipt resource scope mismatch")
        if str(receipt.get("status", "")).lower() != "settled":
            raise ValueError("receipt is not settled")
        return receipt

    @classmethod
    def _validate_order_input(cls, service_input: dict[str, Any]) -> None:
        if not isinstance(service_input, dict):
            raise ValueError("service_input must be an object")
        orders = service_input.get("orders")
        if not isinstance(orders, list) or not 1 <= len(orders) <= 1000:
            raise ValueError("orders must contain between 1 and 1000 items")
        total = Decimal("0")
        for order in orders:
            if not isinstance(order, dict):
                raise ValueError("each order must be an object")
            category = order.get("category")
            if not isinstance(category, str) or not 1 <= len(category) <= 80:
                raise ValueError("order category is invalid")
            raw_amount = order.get("amount")
            if not isinstance(raw_amount, str) or not 1 <= len(raw_amount) <= 32:
                raise ValueError("order amount is invalid")
            try:
                amount = Decimal(raw_amount)
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise ValueError("order amount is invalid") from exc
            if (
                not amount.is_finite()
                or abs(amount) > Decimal("1000000000000")
                or amount < 0
            ):
                raise ValueError("order amount must be a finite nonnegative decimal with two places")
            try:
                precise = amount.quantize(_CENT)
            except InvalidOperation as exc:
                raise ValueError("order amount is invalid") from exc
            if precise != amount:
                raise ValueError("order amount must be a finite nonnegative decimal with two places")
            total += amount
            if total > Decimal("1000000000000"):
                raise ValueError("order total is out of bounds")

    @classmethod
    def _order_analysis(cls, service_input: dict[str, Any]) -> dict[str, Any]:
        cls._validate_order_input(service_input)
        total = Decimal("0")
        by_category: dict[str, Decimal] = {}
        for order in service_input["orders"]:
            amount = Decimal(str(order["amount"]))
            category = order["category"]
            total += amount
            by_category[category] = by_category.get(category, Decimal("0")) + amount
        return {
            "count": len(service_input["orders"]),
            "total": _money(total),
            "by_category": {
                category: _money(amount)
                for category, amount in by_category.items()
            },
        }
