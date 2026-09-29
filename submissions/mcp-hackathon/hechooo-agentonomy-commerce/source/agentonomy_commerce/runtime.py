"""Persistent review composition. Import only inside the Marketplace worker."""
from __future__ import annotations

from pathlib import Path
from datetime import UTC, datetime

import httpx

from agentonomy_commerce.merchant import ReviewMerchant, reconcile_csv
from agentonomy_commerce.storage import SQLiteStore
from agentonomy_commerce.transport import LoopbackMerchantTransport
from examples.commerce.core_bridge import CoreBridge
from examples.commerce.marketplace import CommerceRuntime, USER_ID
from services.purchase_service import PurchaseService, digest
from services.quote_service import QuoteService
from shared.models import PaymentOption, Provider, ServiceOffering


OFFERING_ID = "csv-reconciliation-v1"
RESOURCE = "https://merchant.agentonomy.invalid/v1/reconcile"


class ReviewRuntime(CommerceRuntime):
    def __init__(self, state_dir: Path, merchant_port: int):
        super().__init__(state_dir)
        self.core = CoreBridge(self.state_dir, persistent=True)
        self.store = SQLiteStore(self.state_dir / "review-values.sqlite3")
        self.merchant_port = merchant_port
        self.merchant = None

    def __enter__(self):
        try:
            self.core.__enter__()
            snapshot = self._core_snapshot_for_setup()
            self._network = snapshot["network"]
            self._asset = snapshot["token"]
            self._pay_to = snapshot["pay_to"]
            self._receipt_signing_key = snapshot["receipt_signing_key"]
            self.merchant = ReviewMerchant(
                self.state_dir / "merchant", receipt_secret=self._receipt_signing_key,
                network=self._network, token=self._asset, pay_to=self._pay_to,
                port=self.merchant_port, expected_input_hash=self._expected_input_hash,
                resource=RESOURCE,
            )
            self.merchant.__enter__()
            self.provider, self.offerings = self._register_catalog()
            self.quotes = QuoteService(self.repository, native_provider_ids={self.provider.provider_id})
            self._merchant_client = httpx.Client(
                transport=LoopbackMerchantTransport(RESOURCE, self.merchant.endpoint),
                timeout=15, trust_env=False, follow_redirects=False,
            )
            self.purchases = PurchaseService(
                self.repository, self.core, client=self._merchant_client, ephemeral_store=self.store,
                native_provider_ids={self.provider.provider_id}, preview_ttl=300, proxy_context_ttl=900,
            )
            self._entered = True
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            if self._merchant_client is not None:
                self._merchant_client.close()
            if self.merchant is not None:
                self.merchant.__exit__(exc_type, exc_value, traceback)
        finally:
            try:
                self.core.close()
            finally:
                self.repository.engine.dispose()
                self._entered = False
        return False

    def _expected_input_hash(self, purchase_id):
        purchase = self.repository.get_purchase(purchase_id)
        return purchase.input_hash if purchase is not None else None

    def _register_catalog(self):
        provider = Provider(
            provider_id="commerce_analytics", name="Agentonomy CSV Reconciliation",
            domain="merchant.agentonomy.invalid", source="agentonomy_review", status="active",
            metadata={"settlement_mode": "simulated", "service_transport": "http"},
        )
        offering = ServiceOffering(
            offering_id=OFFERING_ID, provider_id=provider.provider_id, source="agentonomy_review",
            source_id="POST " + RESOURCE,
            name="CSV expense reconciliation", endpoint=RESOURCE, method="POST",
            description="Reconcile transaction CSV, remove exact duplicate records and return income, expense, "
                        "net and category totals. One currency per file; no financial advice.",
            input_schema={"type": "object", "required": ["csv_text"], "additionalProperties": False,
                          "properties": {"csv_text": {"type": "string", "maxLength": 131072}}},
            output_schema={"type": "object", "required": ["unique_transaction_count", "net_totals"]},
            tags=["csv", "reconciliation", "expense", "commerce"], status="verified",
            metadata={"trust_tier": "clink_verified", "verification_source": "first_party_review_service",
                      "settlement_mode": "simulated", "service_transport": "http"},
            payment_options=[PaymentOption(scheme="exact", network=self._network, asset=self._asset,
                                           amount_atomic="300000", pay_to=self._pay_to, price_usd="0.30",
                                           metadata={"token": "USDC", "simulation": True})],
        )
        self.repository.upsert_provider(provider)
        self.repository.upsert_offering(offering, verified_at=datetime.now(UTC))
        return provider, (offering,)

    def search(self, query=""):
        result = super().search(query)
        for item in result["items"]:
            item["input_format"] = "CSV: transaction_id,date,description,amount,currency,category"
        return result

    def preview(self, offering_id, csv_text, idempotency_key):
        self._require_started()
        if offering_id != OFFERING_ID:
            raise KeyError("offering not found")
        reconcile_csv(csv_text)
        service_input = {"csv_text": csv_text}
        request_hash = digest({"offering_id": offering_id, "service_input": service_input})
        cache_key = "preview_request:" + idempotency_key
        previous = self.store.get(cache_key)
        if previous is not None:
            if previous["request_hash"] != request_hash:
                raise ValueError("idempotency_conflict")
            preview = self.repository.get_preview(previous["preview_id"])
            if preview is None:
                raise RuntimeError("persisted preview reference is missing")
            return preview.model_dump(mode="json")
        preview = self.purchases.create_preview(user_id=USER_ID, offering_id=offering_id, service_input=service_input)
        self.store.set(cache_key, {"request_hash": request_hash, "preview_id": preview.preview_id}, 30 * 86400)
        return preview.model_dump(mode="json")

    def purchase(self, purchase_id):
        if self.repository.get_purchase(purchase_id) is None:
            raise KeyError("purchase not found")
        return super().purchase(purchase_id)

    def execute(self, preview_id):
        if self.repository.get_preview(preview_id) is None:
            raise KeyError("preview not found")
        return super().execute(preview_id)

    def snapshot(self):
        raw = super().snapshot()
        for key in ("merchant_delivery_attempts", "merchant_delivery_successes", "merchant_delivery_failures"):
            raw.pop(key, None)
        raw["merchant_deliveries"] = self.merchant.delivery_count
        raw["merchant_delivery_metric"] = "unique_successful_orders"
        raw["result_retention_seconds"] = 7 * 86400
        return raw
