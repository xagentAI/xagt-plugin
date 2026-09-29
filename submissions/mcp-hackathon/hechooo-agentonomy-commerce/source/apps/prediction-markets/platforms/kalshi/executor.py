from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from typing import Any, Callable
from urllib.parse import urlparse

from platforms.base import PlatformExecutionResult
from shared.config import AppConfig
from shared.schemas import PredictionMarketOrderPreview

KalshiRequester = Callable[[str, str, dict[str, str], dict[str, Any]], dict[str, Any]]


class KalshiExecutor:
    """Kalshi Trade API V2 live-order adapter.

    Clink still owns preview, policy, and confirmation gates. This adapter only
    submits an already-approved preview to Kalshi when the execution service asks.
    """

    platform = "kalshi"
    order_path = "/portfolio/events/orders"

    def __init__(self, config: AppConfig | None = None, requester: KalshiRequester | None = None) -> None:
        self.config = config or AppConfig.from_env()
        self.requester = requester or self._request_json

    def readiness(self) -> PlatformExecutionResult:
        missing: list[str] = []
        warnings: list[str] = []

        if not self.config.kalshi_api_base_url:
            missing.append("KALSHI_API_BASE_URL")
        if not self.config.kalshi_api_key_id:
            missing.append("KALSHI_API_KEY_ID")
        if not (self.config.kalshi_private_key_path or self.config.kalshi_private_key_pem):
            missing.append("KALSHI_PRIVATE_KEY_PATH or KALSHI_PRIVATE_KEY_PEM")
        if self.config.kalshi_order_time_in_force not in {"fill_or_kill", "good_till_canceled", "immediate_or_cancel"}:
            missing.append("KALSHI_ORDER_TIME_IN_FORCE must be fill_or_kill, good_till_canceled, or immediate_or_cancel")
        if self.config.kalshi_self_trade_prevention_type not in {"taker_at_cross", "maker"}:
            missing.append("KALSHI_SELF_TRADE_PREVENTION_TYPE must be taker_at_cross or maker")

        try:
            self._crypto_modules()
        except Exception:
            missing.append("cryptography package")

        if self.config.kalshi_private_key_path or self.config.kalshi_private_key_pem:
            try:
                self._load_private_key()
            except Exception as exc:
                missing.append("valid Kalshi RSA private key")
                warnings.append(f"Kalshi private key could not be loaded: {type(exc).__name__}: {exc}")

        base_url = self.config.kalshi_api_base_url or ""
        if "demo" in base_url:
            warnings.append("KALSHI_API_BASE_URL points to demo; demo credentials and balances are separate from production")

        return PlatformExecutionResult(
            platform=self.platform,
            ready=not missing,
            status="ready" if not missing else "missing_configuration",
            missing=missing,
            warnings=warnings,
            metadata={
                "KALSHI_API_BASE_URL": self.config.kalshi_api_base_url,
                "KALSHI_API_KEY_ID": bool(self.config.kalshi_api_key_id),
                "KALSHI_PRIVATE_KEY_PATH": bool(self.config.kalshi_private_key_path),
                "KALSHI_PRIVATE_KEY_PEM": bool(self.config.kalshi_private_key_pem),
                "KALSHI_ORDER_TIME_IN_FORCE": self.config.kalshi_order_time_in_force,
                "KALSHI_SELF_TRADE_PREVENTION_TYPE": self.config.kalshi_self_trade_prevention_type,
            },
        )

    def submit_order(self, preview: PredictionMarketOrderPreview) -> PlatformExecutionResult:
        readiness = self.readiness()
        if not readiness.ready:
            return readiness.model_copy(update={"submitted": False, "status": "blocked", "reason": "Kalshi execution is not configured"})
        try:
            response = self._submit_limit_order(preview)
        except Exception as exc:
            return PlatformExecutionResult(
                platform=self.platform,
                ready=True,
                submitted=False,
                status="failed",
                reason=f"Kalshi order submission failed: {type(exc).__name__}: {exc}",
            )
        normalized = self._normalize_submit_response(response)
        if not normalized.get("order_id"):
            return PlatformExecutionResult(
                platform=self.platform,
                ready=True,
                submitted=False,
                status="failed",
                reason="Kalshi order submission response did not include order_id",
                raw_response=response,
            )
        return PlatformExecutionResult(
            platform=self.platform,
            ready=True,
            submitted=True,
            order_id=normalized.get("order_id"),
            tx_hash=None,
            status=normalized.get("status") or "submitted",
            raw_response=response,
            metadata=normalized.get("metadata") or {},
        )

    def _submit_limit_order(self, preview: PredictionMarketOrderPreview) -> dict[str, Any]:
        body = self._build_order_body(preview)
        headers = self._auth_headers("POST", self.order_path)
        return self.requester("POST", self.order_path, headers, body)

    def _build_order_body(self, preview: PredictionMarketOrderPreview) -> dict[str, Any]:
        ticker = self._resolve_ticker(preview)
        if not ticker:
            raise ValueError("Kalshi ticker is missing from order preview")

        book_side, yes_price = self._kalshi_book_side_and_price(preview)
        count = self._format_decimal(self._parse_positive_decimal(preview.estimated_contracts, "estimated_contracts"), Decimal("0.01"))
        price = self._format_decimal(yes_price, Decimal("0.0001"))
        body: dict[str, Any] = {
            "ticker": ticker,
            "client_order_id": str((preview.metadata or {}).get("client_order_id") or f"clink-{preview.preview_id}"),
            "side": book_side,
            "count": count,
            "price": price,
            "time_in_force": self.config.kalshi_order_time_in_force,
            "self_trade_prevention_type": self.config.kalshi_self_trade_prevention_type,
            "post_only": self.config.kalshi_post_only,
            "cancel_order_on_pause": self.config.kalshi_cancel_order_on_pause,
            "reduce_only": self.config.kalshi_reduce_only,
            "subaccount": self.config.kalshi_subaccount,
            "exchange_index": self.config.kalshi_exchange_index,
        }
        expiration_time = (preview.metadata or {}).get("kalshi_expiration_time")
        if expiration_time is not None:
            body["expiration_time"] = int(expiration_time)
        return body

    def _auth_headers(self, method: str, path: str) -> dict[str, str]:
        timestamp = str(int(time.time() * 1000))
        signed_path = self._signed_path(path)
        signature = self._sign_text(f"{timestamp}{method.upper()}{signed_path}")
        return {
            "Content-Type": "application/json",
            "KALSHI-ACCESS-KEY": str(self.config.kalshi_api_key_id),
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "KALSHI-ACCESS-SIGNATURE": signature,
        }

    def _request_json(self, method: str, path: str, headers: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.config.kalshi_api_base_url.rstrip('/')}{path}"
        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method=method.upper(),
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                text = response.read().decode("utf-8")
                return json.loads(text) if text else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8")
            raise RuntimeError(f"{exc.code} {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(str(exc)) from exc

    def _sign_text(self, text: str) -> str:
        hashes, padding, _serialization = self._crypto_modules()
        private_key = self._load_private_key()
        signature = private_key.sign(
            text.encode("utf-8"),
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256(),
        )
        return base64.b64encode(signature).decode("utf-8")

    def _load_private_key(self) -> Any:
        _hashes, _padding, serialization = self._crypto_modules()
        if self.config.kalshi_private_key_pem:
            raw = self.config.kalshi_private_key_pem.replace("\\n", "\n").encode("utf-8")
        elif self.config.kalshi_private_key_path:
            with open(self.config.kalshi_private_key_path, "rb") as handle:
                raw = handle.read()
        else:
            raise ValueError("Kalshi private key is not configured")
        return serialization.load_pem_private_key(raw, password=None)

    @staticmethod
    def _crypto_modules() -> tuple[Any, Any, Any]:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding

        return hashes, padding, serialization

    def _signed_path(self, path: str) -> str:
        return urlparse(f"{self.config.kalshi_api_base_url.rstrip('/')}{path}").path

    @staticmethod
    def _kalshi_book_side_and_price(preview: PredictionMarketOrderPreview) -> tuple[str, Decimal]:
        outcome = (preview.outcome or "Yes").strip().lower()
        side = (preview.side or "buy").strip().lower()
        limit_price = KalshiExecutor._parse_positive_decimal(preview.limit_price, "limit_price")
        if limit_price >= Decimal("1"):
            raise ValueError("limit_price must be between 0 and 1")

        if outcome in {"yes", "y"}:
            book_side = "bid" if side == "buy" else "ask"
            yes_price = limit_price
        elif outcome in {"no", "n"}:
            book_side = "ask" if side == "buy" else "bid"
            yes_price = Decimal("1") - limit_price
        else:
            raise ValueError("Kalshi outcome must be Yes or No")
        if yes_price <= 0 or yes_price >= 1:
            raise ValueError("Kalshi yes-leg price must be between 0 and 1")
        return book_side, yes_price

    @staticmethod
    def _resolve_ticker(preview: PredictionMarketOrderPreview) -> str | None:
        metadata = preview.metadata or {}
        raw = preview.market.raw or {}
        for source in [metadata, raw]:
            for key in ["ticker", "market_ticker", "kalshi_ticker"]:
                if source.get(key):
                    return str(source[key])
        return preview.market_id if preview.market_id else None

    @staticmethod
    def _parse_positive_decimal(value: Any, field_name: str) -> Decimal:
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"{field_name} must be a valid decimal") from exc
        if amount <= 0:
            raise ValueError(f"{field_name} must be greater than zero")
        return amount

    @staticmethod
    def _format_decimal(value: Decimal, quantum: Decimal) -> str:
        return str(value.quantize(quantum, rounding=ROUND_DOWN))

    @staticmethod
    def _normalize_submit_response(response: dict[str, Any]) -> dict[str, Any]:
        payload = response.get("order") if isinstance(response.get("order"), dict) else response
        order_id = payload.get("order_id") or payload.get("id")
        metadata = {
            "kalshi_client_order_id": payload.get("client_order_id"),
            "kalshi_fill_count": payload.get("fill_count"),
            "kalshi_remaining_count": payload.get("remaining_count"),
            "kalshi_ts_ms": payload.get("ts_ms"),
        }
        return {
            "order_id": str(order_id) if order_id else None,
            "status": payload.get("status") or "submitted",
            "metadata": {key: value for key, value in metadata.items() if value is not None},
        }
