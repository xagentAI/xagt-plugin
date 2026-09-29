from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlsplit

import requests

from shared.models import PaymentOption, Provider, ServiceOffering

RegistryPage = dict[str, Any]


class CdpBazaarAdapter:
    SOURCE = "cdp_bazaar"
    DEFAULT_SEARCH_URL = "https://api.cdp.coinbase.com/platform/v2/x402/discovery/search"
    DEFAULT_RESOURCES_URL = "https://api.cdp.coinbase.com/platform/v2/x402/discovery/resources"
    NETWORK_ALIASES = {
        "base": "eip155:8453",
        "base-sepolia": "eip155:84532",
        "polygon": "eip155:137",
        "polygon-amoy": "eip155:80002",
    }

    def __init__(
        self,
        *,
        search_url: str = DEFAULT_SEARCH_URL,
        resources_url: str = DEFAULT_RESOURCES_URL,
        session: requests.Session | None = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        self.search_url = search_url
        self.resources_url = resources_url
        self.session = session or requests.Session()
        self.timeout_seconds = timeout_seconds

    def fetch_page(self, *, offset: int = 0, limit: int = 100, etag: str | None = None) -> RegistryPage:
        headers = {"If-None-Match": etag} if etag else {}
        response = self.session.get(
            self.resources_url,
            params={"type": "http", "limit": limit, "offset": offset},
            headers=headers,
            timeout=self.timeout_seconds,
        )
        if response.status_code == 304:
            return {"items": [], "offset": offset, "total": offset, "etag": etag, "not_modified": True}
        response.raise_for_status()
        payload = response.json()
        pagination = payload.get("pagination", {})
        items = payload.get("items", [])
        if not isinstance(items, list):
            raise ValueError("Bazaar inventory response is invalid")
        if not isinstance(pagination, dict) or "offset" not in pagination or "total" not in pagination:
            raise ValueError("Bazaar inventory pagination is invalid")
        try:
            # Bazaar pages without count use the returned item list as the canonical count.
            page_offset=int(pagination["offset"]);total=int(pagination["total"]);count=int(pagination.get("count",len(items)))
        except (TypeError,ValueError) as exc:
            raise ValueError("Bazaar inventory pagination is invalid") from exc
        if page_offset!=offset:
            raise ValueError("Bazaar inventory pagination offset does not match request")
        if total<0 or count!=len(items) or total<page_offset+count:
            raise ValueError("Bazaar inventory pagination is invalid")
        return {
            "items": items,
            "offset": page_offset,
            "count": count,
            "limit": pagination.get("limit", limit),
            "total": total,
            "etag": response.headers.get("etag"),
        }

    def search(
        self,
        query: str,
        *,
        network: str | None = None,
        max_usd_price: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        if not 1 <= limit <= 20:
            raise ValueError("Bazaar search limit must be between 1 and 20")
        params: dict[str, Any] = {"query": query, "limit": limit}
        if network:
            params["network"] = network
        if max_usd_price:
            params["maxUsdPrice"] = max_usd_price
        response = self.session.get(
            self.search_url,
            params=params,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        resources = payload.get("resources", [])
        if not isinstance(resources, list):
            raise ValueError("Bazaar response resources must be a list")
        return resources

    def normalize_resource(self, resource: dict[str, Any]) -> tuple[Provider, ServiceOffering]:
        endpoint = str(resource["resource"])
        hostname = urlsplit(endpoint).hostname
        if not hostname:
            raise ValueError("Bazaar resource has no hostname")

        service_name = str(resource.get("serviceName") or hostname)
        provider = Provider(
            name=service_name,
            domain=hostname.lower(),
            source=self.SOURCE,
            metadata={"last_updated": resource.get("lastUpdated")},
        )

        bazaar = resource.get("extensions", {}).get("bazaar", {})
        info = bazaar.get("info", {}) if isinstance(bazaar, dict) else {}
        input_info = info.get("input", {}) if isinstance(info, dict) else {}
        schema = bazaar.get("schema", {}) if isinstance(bazaar, dict) else {}
        schema_properties = schema.get("properties", {}) if isinstance(schema, dict) else {}

        payments = [self._normalize_payment(item) for item in resource.get("accepts", [])]
        method=str(input_info.get("method") or "GET")
        offering = ServiceOffering(
            provider_id=provider.provider_id,
            source=self.SOURCE,
            source_id=f"{method} {endpoint}",
            name=service_name,
            description=str(resource.get("description") or ""),
            endpoint=endpoint,
            method=method,
            input_schema=schema_properties.get("input", {}),
            output_schema=schema_properties.get("output", {}),
            tags=[str(tag) for tag in resource.get("tags", [])],
            payment_options=payments,
            metadata={
                "x402_version": resource.get("x402Version"),
                "quality": resource.get("quality", {}),
                "bazaar_info": info,
            },
        )
        return provider, offering

    def fetch(self, query: str = "agent service") -> dict[str, Any]:
        response=self.session.get(self.search_url,params={"query":query,"limit":20},timeout=self.timeout_seconds)
        response.raise_for_status();payload=response.json();items=[]
        for resource in payload.get("resources",[]):
            provider,offering=self.normalize_resource(resource);items.append((provider,offering,str(resource.get("resource"))))
        return {"items":items,"cursor":payload.get("nextCursor"),"etag":response.headers.get("etag")}

    @staticmethod
    def _normalize_payment(item: dict[str, Any]) -> PaymentOption:
        extra = item.get("extra") if isinstance(item.get("extra"), dict) else {}
        price = extra.get("totalUsd")
        amount = item.get("amount")
        amount_source = "amount"
        if amount in {None, ""}:
            amount = item.get("maxAmountRequired")
            amount_source = "maxAmountRequired"
        network = str(item.get("network") or "")
        try:
            price_usd = Decimal(str(price)) if price is not None else None
        except InvalidOperation:
            price_usd = None
        return PaymentOption(
            scheme=str(item.get("scheme") or "exact"),
            network=CdpBazaarAdapter.NETWORK_ALIASES.get(network, network),
            asset=str(item.get("asset") or ""),
            amount_atomic=str(amount or "0"),
            pay_to=str(item.get("payTo") or ""),
            max_timeout_seconds=item.get("maxTimeoutSeconds"),
            price_usd=price_usd,
            metadata={"extra": extra, "amount_source": amount_source},
        )
