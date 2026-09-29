from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Protocol

from platforms.kalshi.executor import KalshiExecutor
from platforms.polymarket.executor import PolymarketExecutor
from shared.config import AppConfig
from shared.schemas import (
    VenueAccountBalance,
    VenueAccountSnapshot,
    VenueFill,
    VenueOpenOrder,
    VenuePosition,
)


class VenueAccountSyncAdapter(Protocol):
    platform: str

    def fetch_account_snapshot(self) -> VenueAccountSnapshot: ...


class PolymarketVenueAccountAdapter:
    platform = "polymarket"

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or AppConfig.from_env()
        self.executor = PolymarketExecutor(self.config)

    def fetch_account_snapshot(self) -> VenueAccountSnapshot:
        captured_at = self._utc_now()
        readiness = self.executor.readiness()
        if not readiness.ready:
            return VenueAccountSnapshot(
                platform=self.platform,
                status="not_configured",
                captured_at=captured_at,
                warnings=readiness.missing + readiness.warnings,
                raw={"readiness": readiness.model_dump()},
            )
        try:
            client = self._client()
            raw_orders, order_warnings = self._safe_client_call(client, ["get_orders", "get_order_book_orders"])
            raw_trades, trade_warnings = self._safe_client_call(client, ["get_trades", "get_trade_history"])
            raw_positions, position_warnings = self._safe_client_call(client, ["get_positions"])
            raw_balance, balance_warnings = self._safe_client_call(client, ["get_balance_allowance", "get_balance"])
            return VenueAccountSnapshot(
                platform=self.platform,
                status="ok",
                captured_at=captured_at,
                balances=self._normalize_balances(raw_balance, captured_at),
                open_orders=self._normalize_orders(raw_orders, captured_at),
                fills=self._normalize_fills(raw_trades, captured_at),
                positions=self._normalize_positions(raw_positions, captured_at),
                warnings=order_warnings + trade_warnings + position_warnings + balance_warnings,
                raw={
                    "orders": raw_orders,
                    "trades": raw_trades,
                    "positions": raw_positions,
                    "balance": raw_balance,
                },
            )
        except Exception as exc:
            return VenueAccountSnapshot(
                platform=self.platform,
                status="error",
                captured_at=captured_at,
                warnings=[f"{type(exc).__name__}: {exc}"],
            )

    def _client(self) -> Any:
        from py_clob_client_v2.client import ClobClient

        client = ClobClient(
            self.config.polymarket_clob_host,
            self.config.polymarket_chain_id,
        )
        raise RuntimeError("Polymarket account sync requires user-level credentials; global sync has no user_id")
        return client

    @staticmethod
    def _safe_client_call(client: Any, method_names: list[str]) -> tuple[Any, list[str]]:
        warnings: list[str] = []
        for method_name in method_names:
            method = getattr(client, method_name, None)
            if not callable(method):
                continue
            try:
                return method(), warnings
            except TypeError:
                try:
                    return method({}), warnings
                except Exception as exc:
                    warnings.append(f"{method_name} failed: {type(exc).__name__}: {exc}")
            except Exception as exc:
                warnings.append(f"{method_name} failed: {type(exc).__name__}: {exc}")
        warnings.append(f"none of {method_names} are available")
        return None, warnings

    def _normalize_balances(self, raw: Any, captured_at: str) -> list[VenueAccountBalance]:
        payload = self._first_payload(raw)
        if not payload:
            return []
        total = payload.get("balance") or payload.get("total") or payload.get("collateral") or "0"
        available = payload.get("available") or payload.get("available_balance") or total
        locked = payload.get("locked") or payload.get("locked_balance") or "0"
        return [
            VenueAccountBalance(
                platform=self.platform,
                currency="USDC",
                total=self._money(total),
                available=self._money(available),
                locked=self._money(locked),
                updated_at=captured_at,
                raw=payload,
            )
        ]

    def _normalize_orders(self, raw: Any, captured_at: str) -> list[VenueOpenOrder]:
        orders = []
        for item in self._items(raw, ["orders", "data", "results"]):
            order_id = item.get("order_id") or item.get("orderID") or item.get("id")
            if not order_id:
                continue
            status = str(item.get("status") or item.get("state") or "open").lower()
            orders.append(
                VenueOpenOrder(
                    platform=self.platform,
                    order_id=str(order_id),
                    market_id=str(item.get("market_id") or item.get("market") or item.get("asset_id") or ""),
                    title=item.get("question") or item.get("title") or item.get("market"),
                    outcome=str(item.get("outcome") or item.get("side") or "Yes"),
                    side=self._side(item.get("side") or item.get("type") or "buy"),
                    status=status,
                    contracts=self._decimal_string(item.get("size") or item.get("original_size") or "0"),
                    filled_contracts=self._decimal_string(item.get("size_matched") or item.get("filled_size") or "0"),
                    limit_price=self._decimal_string(item.get("price") or "0"),
                    avg_price=self._decimal_string(item.get("avg_price")) if item.get("avg_price") is not None else None,
                    cost_basis_usd=self._money((self._decimal(item.get("size_matched") or "0") * self._decimal(item.get("price") or "0"))),
                    created_at=item.get("created_at") or item.get("createdAt"),
                    updated_at=item.get("updated_at") or item.get("updatedAt") or captured_at,
                    raw=item,
                )
            )
        return orders

    def _normalize_fills(self, raw: Any, captured_at: str) -> list[VenueFill]:
        fills = []
        for item in self._items(raw, ["trades", "fills", "data", "results"]):
            fill_id = item.get("fill_id") or item.get("trade_id") or item.get("id")
            if not fill_id:
                continue
            contracts = self._decimal(item.get("size") or item.get("shares") or "0")
            price = self._decimal(item.get("price") or "0")
            fills.append(
                VenueFill(
                    platform=self.platform,
                    fill_id=str(fill_id),
                    order_id=str(item.get("order_id") or item.get("orderID") or "") or None,
                    market_id=str(item.get("market_id") or item.get("asset_id") or item.get("market") or ""),
                    outcome=str(item.get("outcome") or "Yes"),
                    side=self._side(item.get("side") or item.get("type") or "buy"),
                    contracts=self._decimal_string(contracts),
                    price=self._decimal_string(price),
                    amount_usd=self._money(contracts * price),
                    fee_usd=self._money(item.get("fee") or "0"),
                    filled_at=item.get("created_at") or item.get("createdAt") or captured_at,
                    raw=item,
                )
            )
        return fills

    def _normalize_positions(self, raw: Any, captured_at: str) -> list[VenuePosition]:
        positions = []
        for item in self._items(raw, ["positions", "data", "results"]):
            position_id = item.get("position_id") or item.get("id") or item.get("asset_id") or item.get("market_id")
            if not position_id:
                continue
            contracts = self._decimal(item.get("size") or item.get("shares") or item.get("contracts") or "0")
            entry_price = self._decimal(item.get("entry_price") or item.get("avg_price") or item.get("price") or "0")
            mark_price = self._decimal(item.get("mark_price") or item.get("current_price") or entry_price)
            cost_basis = self._decimal(item.get("cost_basis") or item.get("cost_basis_usd") or contracts * entry_price)
            current_value = self._decimal(item.get("current_value") or item.get("current_value_usd") or contracts * mark_price)
            positions.append(
                VenuePosition(
                    platform=self.platform,
                    position_id=str(position_id),
                    market_id=str(item.get("market_id") or item.get("market") or item.get("asset_id") or ""),
                    title=item.get("question") or item.get("title") or item.get("market"),
                    outcome=str(item.get("outcome") or "Yes"),
                    side=self._side(item.get("side") or "buy"),
                    status=str(item.get("status") or "open"),
                    order_id=str(item.get("order_id") or "") or None,
                    contracts=self._decimal_string(contracts),
                    entry_price=self._decimal_string(entry_price),
                    mark_price=self._decimal_string(mark_price),
                    cost_basis_usd=self._money(cost_basis),
                    current_value_usd=self._money(current_value),
                    unrealized_pnl_usd=self._money(item.get("unrealized_pnl") or item.get("unrealized_pnl_usd") or current_value - cost_basis),
                    realized_pnl_usd=self._money(item.get("realized_pnl") or item.get("realized_pnl_usd") or "0"),
                    updated_at=item.get("updated_at") or item.get("updatedAt") or captured_at,
                    raw=item,
                )
            )
        return positions

    @staticmethod
    def _first_payload(raw: Any) -> dict[str, Any]:
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, list) and raw and isinstance(raw[0], dict):
            return raw[0]
        return {}

    @staticmethod
    def _items(raw: Any, keys: list[str]) -> list[dict[str, Any]]:
        if isinstance(raw, list):
            return [item for item in raw if isinstance(item, dict)]
        if isinstance(raw, dict):
            for key in keys:
                value = raw.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
            return [raw]
        return []

    @staticmethod
    def _side(value: Any) -> str:
        return "sell" if str(value).lower() in {"sell", "ask"} else "buy"

    @staticmethod
    def _decimal(value: Any) -> Decimal:
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return Decimal("0")

    @classmethod
    def _money(cls, value: Any) -> str:
        return str(cls._decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    @classmethod
    def _decimal_string(cls, value: Any) -> str:
        return format(cls._decimal(value).normalize(), "f")

    @staticmethod
    def _utc_now() -> str:
        return datetime.utcnow().isoformat() + "Z"


class KalshiVenueAccountAdapter:
    platform = "kalshi"

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or AppConfig.from_env()
        self.executor = KalshiExecutor(self.config)

    def fetch_account_snapshot(self) -> VenueAccountSnapshot:
        captured_at = datetime.utcnow().isoformat() + "Z"
        readiness = self.executor.readiness()
        if not readiness.ready:
            return VenueAccountSnapshot(
                platform=self.platform,
                status="not_configured",
                captured_at=captured_at,
                warnings=readiness.missing + readiness.warnings,
                raw={"readiness": readiness.model_dump()},
            )
        warnings: list[str] = []
        raw_balance = self._safe_get("/portfolio/balance", warnings)
        raw_orders = self._safe_get("/portfolio/orders", warnings)
        raw_fills = self._safe_get("/portfolio/fills", warnings)
        raw_positions = self._safe_get("/portfolio/positions", warnings)
        return VenueAccountSnapshot(
            platform=self.platform,
            status="ok" if not [warning for warning in warnings if "failed" in warning] else "partial",
            captured_at=captured_at,
            balances=self._normalize_balances(raw_balance, captured_at),
            open_orders=self._normalize_orders(raw_orders, captured_at),
            fills=self._normalize_fills(raw_fills, captured_at),
            positions=self._normalize_positions(raw_positions, captured_at),
            warnings=warnings,
            raw={"balance": raw_balance, "orders": raw_orders, "fills": raw_fills, "positions": raw_positions},
        )

    def _safe_get(self, path: str, warnings: list[str]) -> dict[str, Any]:
        try:
            return self._request_json(path)
        except Exception as exc:
            warnings.append(f"{path} failed: {type(exc).__name__}: {exc}")
            return {}

    def _request_json(self, path: str) -> dict[str, Any]:
        url = f"{self.config.kalshi_api_base_url.rstrip('/')}{path}"
        request = urllib.request.Request(url, headers=self.executor._auth_headers("GET", path), method="GET")
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                text = response.read().decode("utf-8")
                return json.loads(text) if text else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8")
            raise RuntimeError(f"{exc.code} {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(str(exc)) from exc

    def _normalize_balances(self, raw: dict[str, Any], captured_at: str) -> list[VenueAccountBalance]:
        if not raw:
            return []
        balance = raw.get("balance") if isinstance(raw.get("balance"), dict) else raw
        total = self._amount(balance.get("portfolio_value") or balance.get("balance") or balance.get("total") or 0)
        available = self._amount(balance.get("available_balance") or balance.get("available") or total)
        locked = max(Decimal("0"), total - available)
        return [
            VenueAccountBalance(
                platform=self.platform,
                currency="USD",
                total=self._money(total),
                available=self._money(available),
                locked=self._money(locked),
                updated_at=captured_at,
                raw=raw,
            )
        ]

    def _normalize_orders(self, raw: dict[str, Any], captured_at: str) -> list[VenueOpenOrder]:
        orders = []
        for item in self._items(raw, ["orders", "data", "results"]):
            order_id = item.get("order_id") or item.get("id")
            if not order_id:
                continue
            count = self._amount(item.get("count") or item.get("remaining_count") or 0, cents=False)
            filled = self._amount(item.get("fill_count") or 0, cents=False)
            price = self._price(item.get("price") or item.get("yes_price") or 0)
            orders.append(
                VenueOpenOrder(
                    platform=self.platform,
                    order_id=str(order_id),
                    market_id=str(item.get("ticker") or item.get("market_ticker") or ""),
                    title=item.get("title") or item.get("event_title"),
                    outcome="Yes",
                    side="buy" if str(item.get("side") or "bid").lower() == "bid" else "sell",
                    status=str(item.get("status") or "open").lower(),
                    contracts=self._decimal_string(count),
                    filled_contracts=self._decimal_string(filled),
                    limit_price=self._decimal_string(price),
                    avg_price=self._decimal_string(self._price(item.get("avg_price"))) if item.get("avg_price") is not None else None,
                    cost_basis_usd=self._money(filled * price),
                    created_at=item.get("created_time") or item.get("created_at"),
                    updated_at=item.get("updated_time") or item.get("updated_at") or captured_at,
                    raw=item,
                )
            )
        return orders

    def _normalize_fills(self, raw: dict[str, Any], captured_at: str) -> list[VenueFill]:
        fills = []
        for item in self._items(raw, ["fills", "data", "results"]):
            fill_id = item.get("trade_id") or item.get("fill_id") or item.get("id")
            if not fill_id:
                continue
            contracts = self._amount(item.get("count") or item.get("contracts") or 0, cents=False)
            price = self._price(item.get("price") or item.get("yes_price") or 0)
            fills.append(
                VenueFill(
                    platform=self.platform,
                    fill_id=str(fill_id),
                    order_id=str(item.get("order_id") or "") or None,
                    market_id=str(item.get("ticker") or item.get("market_ticker") or ""),
                    outcome="Yes",
                    side="buy" if str(item.get("side") or "bid").lower() == "bid" else "sell",
                    contracts=self._decimal_string(contracts),
                    price=self._decimal_string(price),
                    amount_usd=self._money(contracts * price),
                    fee_usd=self._money(self._amount(item.get("fee") or 0)),
                    filled_at=item.get("created_time") or item.get("filled_at") or captured_at,
                    raw=item,
                )
            )
        return fills

    def _normalize_positions(self, raw: dict[str, Any], captured_at: str) -> list[VenuePosition]:
        positions = []
        for item in self._items(raw, ["positions", "market_positions", "data", "results"]):
            ticker = str(item.get("ticker") or item.get("market_ticker") or item.get("market_id") or "")
            if not ticker:
                continue
            contracts = self._amount(item.get("position") or item.get("contracts") or item.get("count") or 0, cents=False)
            entry_price = self._price(item.get("avg_price") or item.get("entry_price") or 0)
            mark_price = self._price(item.get("market_exposure_price") or item.get("mark_price") or item.get("current_price") or entry_price)
            cost_basis = self._amount(item.get("cost_basis") or item.get("cost_basis_usd") or contracts * entry_price)
            current_value = self._amount(item.get("current_value") or item.get("current_value_usd") or contracts * mark_price)
            positions.append(
                VenuePosition(
                    platform=self.platform,
                    position_id=str(item.get("position_id") or f"kalshi_{ticker}"),
                    market_id=ticker,
                    title=item.get("title") or item.get("event_title"),
                    outcome="Yes",
                    side="buy" if contracts >= 0 else "sell",
                    status=str(item.get("status") or "open"),
                    contracts=self._decimal_string(abs(contracts)),
                    entry_price=self._decimal_string(entry_price),
                    mark_price=self._decimal_string(mark_price),
                    cost_basis_usd=self._money(cost_basis),
                    current_value_usd=self._money(current_value),
                    unrealized_pnl_usd=self._money(item.get("unrealized_pnl") or item.get("unrealized_pnl_usd") or current_value - cost_basis),
                    realized_pnl_usd=self._money(item.get("realized_pnl") or item.get("realized_pnl_usd") or "0"),
                    updated_at=item.get("updated_time") or item.get("updated_at") or captured_at,
                    raw=item,
                )
            )
        return positions

    @staticmethod
    def _items(raw: dict[str, Any], keys: list[str]) -> list[dict[str, Any]]:
        for key in keys:
            value = raw.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return []

    @classmethod
    def _amount(cls, value: Any, cents: bool = True) -> Decimal:
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, ValueError):
            amount = Decimal("0")
        if cents and amount == amount.to_integral_value() and abs(amount) >= 100:
            return amount / Decimal("100")
        return amount

    @classmethod
    def _price(cls, value: Any) -> Decimal:
        amount = cls._amount(value, cents=False)
        if amount > 1:
            return amount / Decimal("100")
        return amount

    @classmethod
    def _money(cls, value: Any) -> str:
        return str(cls._amount(value, cents=False).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    @classmethod
    def _decimal_string(cls, value: Any) -> str:
        return format(cls._amount(value, cents=False).normalize(), "f")


def default_venue_adapters(config: AppConfig | None = None) -> list[VenueAccountSyncAdapter]:
    resolved = config or AppConfig.from_env()
    return [
        PolymarketVenueAccountAdapter(resolved),
        KalshiVenueAccountAdapter(resolved),
    ]
