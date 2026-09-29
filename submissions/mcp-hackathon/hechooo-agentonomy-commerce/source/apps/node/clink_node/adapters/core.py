from __future__ import annotations

from .ownership import object_id, require_owner

from typing import Any
from urllib.parse import urlsplit

import httpx

from .http import DownstreamError, JsonHttpClient, ProxyResponse, proxy_http_request
from ..transfers import normalize_create, transfer_id as validate_transfer_id


AccountProxyResponse = ProxyResponse


class CoreHttpAdapter:
    def __init__(
        self,
        *,
        account_url: str,
        action_url: str,
        policy_url: str,
        audit_url: str,
        funding_url: str,
        internal_token: str,
        public_base_url: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.account_url = account_url.rstrip("/")
        self.action_url = action_url.rstrip("/")
        self.policy_url = policy_url.rstrip("/")
        self.audit_url = audit_url.rstrip("/")
        self.funding_url = funding_url.rstrip("/")
        self.public_base_url = (
            public_base_url.rstrip("/") if public_base_url else None
        )
        self.transport = transport
        self.http = JsonHttpClient(
            "core",
            internal_token=internal_token,
            transport=transport,
        )

    def health(self) -> dict[str, Any]:
        services = {
            "account": self.account_url,
            "action": self.action_url,
            "policy": self.policy_url,
            "audit": self.audit_url,
            "funding": self.funding_url,
        }
        return {
            "status": "ok",
            "services": {
                name: self.http.get(f"{url}/healthz")
                for name, url in services.items()
            },
        }

    def account_readiness(self, user_id: str) -> dict[str, Any]:
        return self.http.get(
            f"{self.account_url}/internal/account-readiness",
            params={"user_id": user_id},
        )

    def wallet_balances(self, user_id: str) -> dict[str, Any]:
        return self.http.get(
            f"{self.account_url}/internal/account-balances",
            params={"user_id": user_id},
        )

    def get_payment_reservation(
        self, *, user_id: str, reservation_id: str, purchase_id: str,
    ) -> dict[str, Any]:
        reservation_id = object_id(reservation_id)
        payload = self.http.get(f"{self.funding_url}/funding/spending-reservations/{reservation_id}")
        require_owner(payload, user_id=user_id, id_field="reservation_id",
                      expected_id=reservation_id, service="core")
        if payload.get("purchase_id") != purchase_id:
            raise DownstreamError("core", 404, "owned object not found")
        return {name: payload.get(name) for name in ("state", "receipt_id", "tx_hash")}

    def hosted_wallet_readiness(self, user_id: str) -> dict[str, Any]:
        return self.http.get(
            f"{self.funding_url}/funding/hosted-wallet-readiness",
            params={"user_id": user_id},
        )

    def create_direct_transfer(self, *, user_id: str, agent_id: str,
                               request_id: str, to_address: str, network: str,
                               amount_usdc: str, opc_installation_id: str | None = None) -> dict[str, Any]:
        body = normalize_create({"request_id": request_id, "to_address": to_address,
                                 "network": network, "amount_usdc": amount_usdc})
        body.update(user_id=user_id, agent_id=agent_id)
        if opc_installation_id is not None:
            body["opc_installation_id"] = opc_installation_id
        return self.http.post(f"{self.funding_url}/funding/transfers", body)

    def get_direct_transfer(self, *, user_id: str, agent_id: str, transfer_id: str,
                            opc_installation_id: str | None = None) -> dict[str, Any]:
        transfer_id = validate_transfer_id(transfer_id)
        params = {"user_id": user_id, "agent_id": agent_id}
        if opc_installation_id is not None:
            params["opc_installation_id"] = opc_installation_id
        return self.http.get(f"{self.funding_url}/funding/transfers/{transfer_id}", params=params)

    def create_account_session(self, user_id: str) -> dict[str, Any]:
        result = self.http.post(
            f"{self.account_url}/internal/account-sessions",
            {"user_id": user_id},
        )
        account_url = result.get("account_url")
        if self.public_base_url and isinstance(account_url, str):
            parsed = urlsplit(account_url)
            if parsed.path == "/account" or parsed.path.startswith(
                "/account/"
            ):
                suffix = parsed.path
                if parsed.query:
                    suffix += f"?{parsed.query}"
                if parsed.fragment:
                    suffix += f"#{parsed.fragment}"
                result["account_url"] = f"{self.public_base_url}{suffix}"
        return result

    def proxy_account_request(
        self,
        *,
        method: str,
        path: str,
        query: str,
        headers: list[tuple[str, str]],
        body: bytes,
    ) -> AccountProxyResponse:
        if path != "/account" and not path.startswith("/account/"):
            raise ValueError("only public Core Account routes may be proxied")
        return proxy_http_request(
            service="core-account",
            base_url=self.account_url,
            method=method,
            path=path,
            query=query,
            headers=headers,
            body=body,
            transport=self.transport,
        )

    def audit_summary(
        self,
        user_id: str,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        return self.http.get_list(
            f"{self.audit_url}/audit/summary",
            params={"user_id": user_id, "limit": limit},
        )
