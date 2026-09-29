from __future__ import annotations

import json
import re
from typing import Any

from platforms.base import PlatformExecutionResult
from services.account_binding_service.credential_store import CredentialStore, PolymarketApiCredentials
from shared.config import AppConfig
from shared.schemas import PredictionMarketOrderPreview


class _L2AddressSigner:
    """Expose only the bound EOA address required by pinned L2 HMAC headers."""

    __slots__ = ("_address",)

    def __init__(self, address: str) -> None:
        self._address = address

    def address(self) -> str:
        return self._address


class PolymarketExecutor:
    """py-clob-client adapter adapted from the verified clink-polymarket execution path."""

    platform = "polymarket"

    def __init__(self, config: AppConfig | None = None, credential_store: CredentialStore | None = None) -> None:
        self.config = config or AppConfig.from_env()
        self.credential_store = credential_store or CredentialStore(self.config)

    def readiness(self, user_id: str | None = None) -> PlatformExecutionResult:
        missing: list[str] = []
        warnings: list[str] = []
        mode = self.config.polymarket_execution_mode
        if not self.config.polymarket_clob_host:
            missing.append("POLYMARKET_CLOB_HOST")
        if mode != "browser_signed":
            missing.append("POLYMARKET_EXECUTION_MODE=browser_signed")
        if str(self.config.polymarket_signature_type) not in {"0", "1", "2", "3"}:
            warnings.append("POLYMARKET_SIGNATURE_TYPE must be 0, 1, 2, or 3")
        if self.config.polymarket_chain_id != 137:
            missing.append("POLYMARKET_CHAIN_ID=137")
        credentials = self.credential_store.get_polymarket_credentials(user_id) if user_id else None
        if user_id and credentials is None:
            missing.append("polymarket account binding credentials")
        try:
            import py_clob_client_v2  # noqa: F401
        except Exception:
            missing.append("py-clob-client package")
        return PlatformExecutionResult(
            platform=self.platform,
            ready=not missing,
            status="ready" if not missing else "missing_configuration",
            missing=missing,
            warnings=warnings,
            metadata={
                "POLYMARKET_EXECUTION_MODE": mode,
                "POLYMARKET_CLOB_HOST": self.config.polymarket_clob_host,
                "POLYMARKET_API_CREDS": (credentials is not None) if user_id else "per_user_binding_required",
                "POLYMARKET_CREDENTIAL_SOURCE": "credential_store" if credentials else None,
                "POLYMARKET_SIGNATURE_TYPE": self.config.polymarket_signature_type,
                "POLYMARKET_CHAIN_ID": self.config.polymarket_chain_id,
            },
        )

    def submit_order(self, preview: PredictionMarketOrderPreview) -> PlatformExecutionResult:
        return PlatformExecutionResult(
            platform=self.platform,
            ready=True,
            submitted=False,
            status="needs_browser_signature",
            reason="Polymarket production mode requires a browser-signed order session",
            metadata={"next_action": "create_browser_signed_polymarket_order_session", "preview_id": preview.preview_id},
        )

    def submit_signed_order(
        self,
        signed_order: dict[str, Any],
        order_type: str = "FAK",
        user_id: str | None = None,
        *,
        binding_id: str | None = None,
        owner_address: str | None = None,
        wallet_address: str | None = None,
        client_order_id: str | None = None,
        order_projection: dict[str, Any] | None = None,
    ) -> PlatformExecutionResult:
        if not user_id:
            return PlatformExecutionResult(
                platform=self.platform,
                ready=False,
                submitted=False,
                status="blocked",
                reason="Polymarket signed-order submission requires user_id for credential lookup",
                missing=["user_id"],
            )
        if (
            not isinstance(binding_id, str)
            or not binding_id.strip()
            or not isinstance(owner_address, str)
            or not owner_address.strip()
            or not isinstance(wallet_address, str)
            or not wallet_address.strip()
            or not isinstance(client_order_id, str)
            or not client_order_id.strip()
            or not isinstance(order_projection, dict)
        ):
            return self._scoped_credentials_blocked()
        readiness = self.readiness(user_id=user_id)
        if not readiness.ready:
            return readiness.model_copy(
                update={
                    "status": "blocked",
                    "reason": "create_polymarket_account_binding before signed-order submission",
                }
            )
        credentials = self.credential_store.get_polymarket_credentials(user_id)
        if credentials is None:
            return PlatformExecutionResult(
                platform=self.platform,
                ready=False,
                submitted=False,
                status="blocked",
                reason="create_polymarket_account_binding before signed-order submission",
                missing=["polymarket account binding credentials"],
            )
        if (
            not isinstance(credentials.wallet_address, str)
            or credentials.wallet_address.lower() != owner_address.lower()
            or not isinstance(credentials.funder_address, str)
            or credentials.funder_address.lower() != wallet_address.lower()
        ):
            return self._scoped_credentials_blocked()
        try:
            recovery_id = self.official_order_id(order_projection)
        except ValueError:
            return PlatformExecutionResult(
                platform=self.platform,
                ready=False,
                submitted=False,
                status="blocked",
                reason="Polymarket order projection is invalid",
            )
        if client_order_id.lower() != recovery_id:
            return PlatformExecutionResult(
                platform=self.platform,
                ready=False,
                submitted=False,
                status="blocked",
                reason="Polymarket order recovery ID does not match the signed order",
            )
        try:
            response = self._post_signed_order_with_credentials(signed_order, order_type, credentials)
        except Exception as exc:
            if not self._is_definite_rejection(exc):
                return PlatformExecutionResult(
                    platform=self.platform,
                    ready=True,
                    submitted=False,
                    status="unknown",
                    reason="Polymarket order submission outcome is unknown",
                    metadata={
                        "client_order_id": recovery_id,
                        "recovery_mode": "status_only",
                    },
                )
            return PlatformExecutionResult(
                platform=self.platform,
                ready=True,
                submitted=False,
                status="rejected",
                reason="Polymarket signed order submission was rejected",
                metadata={"client_order_id": recovery_id},
            )
        response_order_id = response.get("order_id")
        if (
            not isinstance(response_order_id, str)
            or response_order_id.lower() != recovery_id
        ):
            return PlatformExecutionResult(
                platform=self.platform,
                ready=True,
                submitted=False,
                status="unknown",
                reason="Polymarket order submission outcome is unknown",
                metadata={
                    "client_order_id": recovery_id,
                    "recovery_mode": "status_only",
                },
            )
        return PlatformExecutionResult(
            platform=self.platform,
            ready=True,
            submitted=True,
            order_id=response.get("order_id"),
            tx_hash=response.get("tx_hash"),
            status=response.get("status") or "submitted",
            raw_response=response.get("raw_response"),
            metadata={
                "client_order_id": recovery_id
            },
        )

    def reconcile_signed_order(
        self,
        *,
        user_id: str,
        binding_id: str,
        owner_address: str,
        wallet_address: str,
        client_order_id: str,
    ) -> PlatformExecutionResult:
        if (
            not user_id
            or not binding_id
            or not owner_address
            or not wallet_address
            or not client_order_id
        ):
            return self._scoped_credentials_blocked()
        credentials = self.credential_store.get_polymarket_credentials(user_id)
        if (
            credentials is None
            or not isinstance(credentials.wallet_address, str)
            or credentials.wallet_address.lower() != str(owner_address).lower()
            or not isinstance(credentials.funder_address, str)
            or credentials.funder_address.lower() != str(wallet_address).lower()
        ):
            return self._scoped_credentials_blocked()
        try:
            response = self._get_order_with_credentials(client_order_id, credentials)
        except Exception:
            return PlatformExecutionResult(
                platform=self.platform,
                ready=True,
                submitted=False,
                status="unknown",
                reason="Polymarket order status is unavailable",
                metadata={
                    "client_order_id": client_order_id,
                    "recovery_mode": "status_only",
                },
            )
        payload = response if isinstance(response, dict) else {}
        response_order_id = payload.get("id") or payload.get("orderID")
        if response_order_id is not None and (
            not isinstance(response_order_id, str)
            or response_order_id.lower() != client_order_id.lower()
        ):
            return PlatformExecutionResult(
                platform=self.platform,
                ready=True,
                submitted=False,
                status="unknown",
                reason="Polymarket order status is unavailable",
                metadata={
                    "client_order_id": client_order_id,
                    "recovery_mode": "status_only",
                },
            )
        venue_status = str(payload.get("status") or payload.get("state") or "unknown").lower()
        known = venue_status not in {"", "unknown", "not_found"}
        return PlatformExecutionResult(
            platform=self.platform,
            ready=True,
            submitted=known,
            order_id=str(payload.get("id") or payload.get("orderID") or client_order_id),
            status="submitted" if known else "unknown",
            reason=None if known else "Polymarket order status is unavailable",
            metadata={
                "client_order_id": client_order_id,
                "venue_order_status": venue_status,
                "recovery_mode": "status_only",
            },
        )

    @staticmethod
    def official_order_id(order_projection: dict[str, Any]) -> str:
        try:
            from py_clob_client_v2.order_utils.exchange_order_builder_v2 import (
                ExchangeOrderBuilderV2,
            )
            from py_clob_client_v2.order_utils.model.ctf_exchange_v2_typed_data import (
                EIP712_DOMAIN,
            )

            typed_data = order_projection["typed_data"]
            types = typed_data["types"]
            message = typed_data["message"]
            order_message = (
                message["contents"]
                if typed_data.get("primaryType") == "TypedDataSign"
                else message
            )
            canonical_typed_data = {
                "domain": typed_data["domain"],
                "types": {
                    "EIP712Domain": EIP712_DOMAIN,
                    "Order": types["Order"],
                },
                "primaryType": "Order",
                "message": order_message,
            }
            result = ExchangeOrderBuilderV2.build_order_hash(
                None, canonical_typed_data
            )
        except (AttributeError, ImportError, KeyError, TypeError, ValueError):
            raise ValueError("Polymarket order projection is invalid") from None
        if (
            not isinstance(result, str)
            or len(result) != 66
            or not result.startswith("0x")
        ):
            raise ValueError("Polymarket order projection is invalid")
        return result.lower()

    @staticmethod
    def _is_definite_rejection(exc: Exception) -> bool:
        status_code = getattr(exc, "status_code", None)
        if status_code not in {400, 422}:
            return False
        detail = getattr(exc, "error_msg", None)
        if not isinstance(detail, dict):
            return False
        error_code = detail.get("error_code") or detail.get("code")
        return error_code in {
            "INVALID_ORDER",
            "INVALID_SIGNATURE",
            "INVALID_ORDER_SIGNATURE",
            "INVALID_ORDER_TYPE",
            "INVALID_MARKET",
            "INVALID_TOKEN_ID",
            "INVALID_PRICE",
            "INVALID_SIZE",
            "INSUFFICIENT_BALANCE_OR_ALLOWANCE",
        }

    def _scoped_credentials_blocked(self) -> PlatformExecutionResult:
        return PlatformExecutionResult(
            platform=self.platform,
            ready=False,
            submitted=False,
            status="blocked",
            reason="Polymarket account scope does not match stored credentials",
            missing=["scoped polymarket account binding credentials"],
        )

    @staticmethod
    def _submit_order_with_client(
        client: Any,
        preview: PredictionMarketOrderPreview,
        token_id: str,
        order_types: tuple[Any, Any, Any] | None = None,
    ) -> dict[str, Any]:
        if order_types is None:
            from py_clob_client_v2.clob_types import (
                MarketOrderArgs,
                OrderArgs,
                OrderType,
            )
        else:
            MarketOrderArgs, OrderArgs, OrderType = order_types
        side = "BUY" if (preview.side or "buy").lower() == "buy" else "SELL"
        if side == "BUY":
            order_args = MarketOrderArgs(
                token_id=str(token_id),
                amount=float(preview.amount_usd),
                side=side,
                price=float(preview.worst_case_price or preview.limit_price),
                order_type=OrderType.FAK,
            )
            signed_order = client.create_market_order(order_args)
            return PolymarketExecutor._normalize_submit_response(client.post_order(signed_order, OrderType.FAK))

        order_args = OrderArgs(price=float(preview.limit_price), size=float(preview.estimated_contracts), side=side, token_id=str(token_id))
        signed_order = client.create_order(order_args)
        return PolymarketExecutor._normalize_submit_response(client.post_order(signed_order, OrderType.GTC))

    def _api_creds(self, credentials: PolymarketApiCredentials) -> Any:
        from py_clob_client_v2.clob_types import ApiCreds

        return ApiCreds(
            api_key=credentials.api_key,
            api_secret=credentials.api_secret,
            api_passphrase=credentials.api_passphrase,
        )

    def _post_signed_order_with_credentials(
        self,
        signed_order: dict[str, Any],
        order_type: str,
        credentials: PolymarketApiCredentials,
    ) -> dict[str, Any]:
        from py_clob_client_v2.clob_types import OrderType

        client = self._l2_client(credentials)
        normalized_type = str(order_type or "FAK").upper()
        clob_order_type = getattr(OrderType, normalized_type, OrderType.FAK)
        sdk_order = self._signed_order_v2(signed_order, credentials)
        return self._normalize_submit_response(
            client.post_order(sdk_order, clob_order_type)
        )

    def _get_order_with_credentials(
        self,
        order_id: str,
        credentials: PolymarketApiCredentials,
    ) -> dict[str, Any]:
        client = self._l2_client(credentials)
        response = client.get_order(order_id)
        return response if isinstance(response, dict) else {}

    def _l2_client(self, credentials: PolymarketApiCredentials) -> Any:
        from py_clob_client_v2.client import ClobClient

        owner = self._credential_address(
            credentials.wallet_address,
            field_name="credential owner wallet",
        )
        funder = self._credential_address(
            credentials.funder_address,
            field_name="credential funder wallet",
        )
        if str(credentials.signature_type) != "3":
            raise ValueError("Polymarket credential signature type is invalid")
        client = ClobClient(
            self.config.polymarket_clob_host,
            self.config.polymarket_chain_id,
            creds=self._api_creds(credentials),
            signature_type=3,
            funder=funder,
            retry_on_error=False,
        )
        client.signer = _L2AddressSigner(owner)
        client.mode = client._get_client_mode()
        return client

    @classmethod
    def _signed_order_v2(
        cls,
        signed_order: dict[str, Any],
        credentials: PolymarketApiCredentials,
    ) -> Any:
        from py_clob_client_v2.order_utils.model.order_data_v2 import SignedOrderV2
        from py_clob_client_v2.order_utils.model.side import Side
        from py_clob_client_v2.order_utils.model.signature_type_v2 import (
            SignatureTypeV2,
        )

        if not isinstance(signed_order, dict):
            raise ValueError("Polymarket signed order is invalid")
        try:
            side_value = signed_order["side"]
            side = (
                Side.BUY
                if side_value in {0, "0", "BUY", "buy"}
                else Side.SELL
                if side_value in {1, "1", "SELL", "sell"}
                else None
            )
            signature_type = SignatureTypeV2(int(signed_order["signatureType"]))
            funder = cls._credential_address(
                credentials.funder_address,
                field_name="credential funder wallet",
            )
            maker = cls._credential_address(
                str(signed_order["maker"]),
                field_name="signed order maker",
            )
            signer = cls._credential_address(
                str(signed_order["signer"]),
                field_name="signed order signer",
            )
            if (
                side is None
                or signature_type != SignatureTypeV2.POLY_1271
                or maker != funder
                or signer != funder
            ):
                raise ValueError("Polymarket signed order scope is invalid")
            return SignedOrderV2(
                salt=str(signed_order["salt"]),
                maker=maker,
                signer=signer,
                tokenId=str(signed_order["tokenId"]),
                makerAmount=str(signed_order["makerAmount"]),
                takerAmount=str(signed_order["takerAmount"]),
                side=side,
                signatureType=signature_type,
                timestamp=str(signed_order["timestamp"]),
                metadata=str(signed_order["metadata"]),
                builder=str(signed_order["builder"]),
                expiration=str(signed_order["expiration"]),
                signature=str(signed_order["signature"]),
            )
        except (KeyError, TypeError, ValueError):
            raise ValueError("Polymarket signed order is invalid") from None

    @staticmethod
    def _credential_address(value: str | None, *, field_name: str) -> str:
        normalized = str(value or "").strip().lower()
        if not re.fullmatch(r"0x[0-9a-f]{40}", normalized):
            raise ValueError(f"{field_name} is invalid")
        return normalized

    @staticmethod
    def _resolve_token_id(preview: PredictionMarketOrderPreview) -> str | None:
        metadata = preview.metadata or {}
        for key in ["token_id", "clob_token_id"]:
            if metadata.get(key):
                return str(metadata[key])
        raw = preview.market.raw or {}
        for key in ["token_id", "clob_token_id"]:
            if raw.get(key):
                return str(raw[key])
        token_ids = PolymarketExecutor._parse_string_list(
            raw.get("clobTokenIds") or raw.get("clob_token_ids") or metadata.get("clob_token_ids")
        )
        if not token_ids:
            return None
        outcome = (preview.outcome or "Yes").lower()
        outcomes = PolymarketExecutor._parse_string_list(raw.get("outcomes") or metadata.get("outcomes")) or ["Yes", "No"]
        outcomes = [str(item).lower() for item in outcomes]
        if outcome in outcomes:
            index = outcomes.index(outcome)
            if index < len(token_ids):
                return str(token_ids[index])
        if outcome == "no" and len(token_ids) > 1:
            return str(token_ids[1])
        return str(token_ids[0])

    @staticmethod
    def _parse_string_list(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value if str(item)]
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                return [str(item) for item in parsed if str(item)]
            return [item.strip() for item in value.split(",") if item.strip()]
        return []

    @staticmethod
    def _normalize_submit_response(response: Any) -> dict[str, Any]:
        if hasattr(response, "model_dump"):
            payload = response.model_dump()
        elif hasattr(response, "dict"):
            payload = response.dict()
        elif isinstance(response, dict):
            payload = response
        else:
            payload = {"raw": str(response)}
        hashes = payload.get("transactionsHashes") or payload.get("transactionHashes") or payload.get("tx_hashes") or []
        if isinstance(hashes, str):
            hashes = [hashes]
        order_id = payload.get("orderID") or payload.get("order_id") or payload.get("id")
        tx_hash = payload.get("txHash") or payload.get("tx_hash") or (hashes[0] if hashes else None)
        return {
            "order_id": str(order_id) if order_id else None,
            "tx_hash": str(tx_hash) if tx_hash else None,
            "status": payload.get("status") or payload.get("state") or "submitted",
            "raw_response": payload,
        }
