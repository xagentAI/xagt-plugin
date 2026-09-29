from __future__ import annotations

import json
import importlib.util
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

import requests

from services.deposit_wallet_service.schemas import (
    PolymarketDepositWalletReadiness,
    PolymarketDepositWalletState,
    PreparePolymarketDepositWalletRequest,
)
from shared.config import AppConfig


class BuilderRelayerClient(Protocol):
    def derive_deposit_wallet(self, owner_wallet: str) -> dict[str, Any]: ...

    def deploy_deposit_wallet(self, owner_wallet: str) -> dict[str, Any]: ...

    def get_transaction(self, transaction_id: str) -> dict[str, Any]: ...

    def is_deposit_wallet_deployed(self, deposit_wallet: str) -> bool: ...


class HttpBuilderRelayerClient:
    """Thin relayer wrapper.

    The official SDK owns exact builder-auth signing. In production this class is
    intentionally conservative: it only supports deployments when the caller
    provides an SDK-backed client or a relayer-compatible deployment endpoint.
    """

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def derive_deposit_wallet(self, owner_wallet: str) -> dict[str, Any]:
        if self.config.polymarket_deposit_wallet_address:
            return {
                "deposit_wallet": self.config.polymarket_deposit_wallet_address,
                "owner_wallet": owner_wallet,
                "source": "configured_deposit_wallet_address",
            }
        try:
            from py_builder_relayer_client import client as relayer_client_module
            from py_builder_relayer_client.builder.derive import derive_beacon_deposit_wallet, derive_uups_deposit_wallet
            from py_builder_relayer_client.config import get_contract_config
            from py_builder_relayer_client.constants.constants import ZERO_ADDRESS
        except ImportError as exc:
            raise RuntimeError("py-builder-relayer-client is required to derive a deposit wallet") from exc

        contract_config = get_contract_config(self.config.polymarket_chain_id)
        relayer = relayer_client_module.RelayClient(
            self.config.polymarket_relayer_url,
            self.config.polymarket_chain_id,
            rpc_url=self.config.polymarket_rpc_url,
        )
        uups_wallet = derive_uups_deposit_wallet(
            owner_wallet,
            contract_config.deposit_wallet_factory,
            contract_config.deposit_wallet_implementation,
        )
        beacon = relayer._get_deposit_wallet_factory_beacon(contract_config.deposit_wallet_factory)
        if beacon.lower() == ZERO_ADDRESS.lower():
            deposit_wallet = uups_wallet
            derivation_shape = "uups"
        elif relayer._is_contract_deployed(uups_wallet):
            deposit_wallet = uups_wallet
            derivation_shape = "existing_uups"
        else:
            deposit_wallet = derive_beacon_deposit_wallet(
                owner_wallet,
                contract_config.deposit_wallet_factory,
                beacon,
            )
            derivation_shape = "beacon"
        return {
            "deposit_wallet": deposit_wallet,
            "owner_wallet": owner_wallet,
            "account_mode": "deposit_wallet",
            "source": "polymarket_builder_relayer_deterministic_derivation",
            "derivation_shape": derivation_shape,
            "factory": contract_config.deposit_wallet_factory,
            "beacon": beacon,
        }

    def deploy_deposit_wallet(self, owner_wallet: str) -> dict[str, Any]:
        request_path = "/submit"
        endpoint = f"{self.config.polymarket_relayer_url.rstrip('/')}{request_path}"
        payload = {
            "type": "WALLET-CREATE",
            "from": owner_wallet,
            "to": self.config.polymarket_deposit_wallet_factory_address,
        }
        headers = self._relayer_headers("POST", request_path, payload)
        if not headers:
            raise RuntimeError("builder relayer auth headers are not configured")
        request_headers = {
            **headers,
            "Content-Type": "application/json",
            "User-Agent": "ClinkPredictionMarkets/1.0 (+https://github.com/HEchooo/clink-prediction-markets)",
        }
        try:
            response = requests.post(endpoint, headers=request_headers, json=payload, timeout=30)
            if response.status_code != 200:
                response_body = response.text
                error = RuntimeError(f"Polymarket relayer returned {response.status_code}: {response_body}")
                error.diagnostics = self._relayer_error_diagnostics(
                    http_status=response.status_code,
                    response_body=response_body,
                    response_headers=dict(response.headers.items()),
                    endpoint=endpoint,
                    method="POST",
                    headers=request_headers,
                    body=payload,
                )
                raise error
            raw = response.json()
        except requests.HTTPError as exc:
            response = exc.response
            status_code = response.status_code if response else 0
            response_body = response.text if response else str(exc)
            error = RuntimeError(f"Polymarket relayer returned {status_code}: {response_body}")
            error.diagnostics = self._relayer_error_diagnostics(
                http_status=status_code,
                response_body=response_body,
                response_headers=dict(response.headers.items()) if response else {},
                endpoint=endpoint,
                method="POST",
                headers=request_headers,
                body=payload,
            )
            raise error from exc
        except requests.RequestException as exc:
            raise RuntimeError(f"Polymarket relayer unavailable: {exc}") from exc
        except ValueError as exc:
            raise RuntimeError(f"Polymarket relayer returned non-JSON response: {exc}") from exc
        return raw

    def get_transaction(self, transaction_id: str) -> dict[str, Any]:
        endpoint = f"{self.config.polymarket_relayer_url.rstrip('/')}/transaction"
        response = requests.get(endpoint, params={"id": transaction_id}, timeout=30)
        if response.status_code != 200:
            raise RuntimeError(f"Polymarket relayer transaction lookup returned {response.status_code}: {response.text}")
        raw = response.json()
        if isinstance(raw, list):
            return raw[0] if raw else {}
        if isinstance(raw, dict):
            return raw
        return {"raw": raw}

    def is_deposit_wallet_deployed(self, deposit_wallet: str) -> bool:
        try:
            from py_builder_relayer_client import client as relayer_client_module
        except ImportError as exc:
            raise RuntimeError("py-builder-relayer-client is required to inspect deposit wallet deployment") from exc

        relayer = relayer_client_module.RelayClient(
            self.config.polymarket_relayer_url,
            self.config.polymarket_chain_id,
            rpc_url=self.config.polymarket_rpc_url,
        )
        return bool(relayer._is_contract_deployed(deposit_wallet))

    def _relayer_headers(self, method: str, request_path: str, body: dict[str, Any]) -> dict[str, str]:
        if self.config.polymarket_relayer_api_key and self.config.polymarket_relayer_api_key_address:
            return {
                "RELAYER_API_KEY": self.config.polymarket_relayer_api_key,
                "RELAYER_API_KEY_ADDRESS": self.config.polymarket_relayer_api_key_address,
            }
        return self._builder_headers(method, request_path, body)

    def _builder_headers(self, method: str, request_path: str, body: dict[str, Any]) -> dict[str, str]:
        try:
            from py_builder_signing_sdk.config import BuilderApiKeyCreds, BuilderConfig
        except ImportError as exc:
            raise RuntimeError("py-builder-signing-sdk is required to sign builder relayer requests") from exc

        builder_config = BuilderConfig(
            local_builder_creds=BuilderApiKeyCreds(
                key=self.config.polymarket_builder_api_key,
                secret=self.config.polymarket_builder_secret,
                passphrase=self.config.polymarket_builder_passphrase,
            )
        )
        headers = builder_config.generate_builder_headers(method, request_path, str(body))
        if headers is None:
            return {}
        return headers.to_dict()

    def _relayer_error_diagnostics(
        self,
        *,
        http_status: int,
        response_body: str,
        response_headers: dict[str, str],
        endpoint: str,
        method: str,
        headers: dict[str, str],
        body: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "http_status": http_status,
            "response_body": response_body,
            "response_headers": self._selected_response_headers(response_headers),
            "request": {
                "endpoint": endpoint,
                "method": method,
                "credential_mode": self._credential_mode(),
                "headers": self._redacted_headers(headers),
                "body_shape": {key: body.get(key) for key in ("type", "from", "to")},
            },
        }

    def _credential_mode(self) -> str:
        if self.config.polymarket_relayer_api_key and self.config.polymarket_relayer_api_key_address:
            return "relayer_api_key"
        return "builder_api_key"

    @staticmethod
    def _selected_response_headers(headers: dict[str, str]) -> dict[str, str]:
        selected = {"cf-ray", "server", "content-type"}
        return {
            key.lower(): value
            for key, value in headers.items()
            if key.lower() in selected
        }

    @staticmethod
    def _redacted_headers(headers: dict[str, str]) -> dict[str, str]:
        redacted_keys = {
            "relayer_api_key",
            "poly_builder_api_key",
            "poly_builder_signature",
            "poly_builder_passphrase",
        }
        safe: dict[str, str] = {}
        for key, value in headers.items():
            normalized = key.lower()
            if normalized in redacted_keys:
                safe[normalized] = "<redacted>"
            else:
                safe[normalized] = value
        return safe


class PolymarketDepositWalletService:
    """Resolves whether an EOA can be upgraded to a deposit-wallet funding path."""

    def __init__(
        self,
        config: AppConfig | None = None,
        relayer_client: BuilderRelayerClient | None = None,
        storage_file: Path | str | None = None,
    ) -> None:
        self.config = config or AppConfig.from_env()
        self.uses_default_relayer_client = relayer_client is None
        self.relayer_client = relayer_client or HttpBuilderRelayerClient(self.config)
        self.storage_file = Path(storage_file or self.config.deposit_wallet_state_file)

    def check_readiness(self, *, user_id: str, owner_wallet: str | None = None) -> PolymarketDepositWalletReadiness:
        missing = self._missing_config()
        state = self._latest_state_for_user(user_id, owner_wallet)
        if state is None and owner_wallet:
            state = self._latest_state_for_owner(owner_wallet)
        if missing:
            return PolymarketDepositWalletReadiness(
                user_id=user_id,
                owner_wallet=owner_wallet or (state.owner_wallet if state else None),
                deposit_wallet=state.deposit_wallet if state else None,
                status="credentials_missing",
                ready=False,
                can_use_x402=False,
                missing=missing,
                reason="Polymarket builder relayer credentials are required before Clink can derive or deploy a deposit wallet.",
                next_action="configure_builder_relayer",
                relayer_url_configured=bool(self.config.polymarket_relayer_url),
                builder_credentials_configured=False,
                state=state,
                metadata={"credential_mode": self._credential_mode()},
            )

        sdk_missing = self._missing_sdk_packages()
        if sdk_missing:
            return PolymarketDepositWalletReadiness(
                user_id=user_id,
                owner_wallet=owner_wallet or (state.owner_wallet if state else None),
                deposit_wallet=state.deposit_wallet if state else None,
                status="sdk_missing",
                ready=False,
                can_use_x402=False,
                missing=sdk_missing,
                reason="Polymarket deposit-wallet preparation requires the official builder relayer SDK. Clink will not guess builder signatures or submit unsigned relayer calls.",
                next_action="install_builder_relayer_sdk",
                relayer_url_configured=True,
                builder_credentials_configured=True,
                state=state,
                metadata={
                    "required_packages": sdk_missing,
                    "credential_mode": self._credential_mode(),
                    "why": "derive/deploy deposit wallet must use Polymarket builder relayer signing",
                },
            )

        if state and state.status in {"derived", "submitted", "deployed", "funded", "ready"}:
            if state.status == "derived" and state.deposit_wallet:
                state = self._reconcile_derived_state(state)
            if state.status == "submitted" and not state.deposit_wallet:
                state = self._backfill_submitted_deposit_wallet(state)
            if state.status == "submitted" and state.deposit_wallet:
                state = self._reconcile_submitted_state(state)
            ready = state.status in {"deployed", "funded", "ready"}
            return PolymarketDepositWalletReadiness(
                user_id=user_id,
                owner_wallet=state.owner_wallet,
                deposit_wallet=state.deposit_wallet,
                status=state.status,
                ready=ready,
                can_use_x402=ready and bool(state.deposit_wallet),
                missing=[],
                reason=state.reason,
                next_action=state.next_action,
                relayer_url_configured=True,
                builder_credentials_configured=True,
                state=state,
                metadata={"credential_mode": self._credential_mode()},
            )

        return PolymarketDepositWalletReadiness(
            user_id=user_id,
            owner_wallet=owner_wallet,
            status="not_prepared",
            ready=False,
            can_use_x402=False,
            missing=[],
            reason="No Polymarket deposit wallet has been derived for this user yet.",
            next_action="prepare_polymarket_deposit_wallet",
            relayer_url_configured=True,
            builder_credentials_configured=True,
            state=state,
            metadata={"credential_mode": self._credential_mode()},
        )

    def prepare_deposit_wallet(self, request: PreparePolymarketDepositWalletRequest) -> PolymarketDepositWalletState:
        now = self._format_time(self._utc_now())
        if not self._looks_like_address(request.owner_wallet):
            state = PolymarketDepositWalletState(
                user_id=request.user_id,
                owner_wallet=request.owner_wallet,
                status="blocked",
                reason="owner_wallet must be a 0x-prefixed EVM address",
                next_action="bind_polymarket_wallet",
                created_at=now,
                updated_at=now,
                metadata=request.metadata,
            )
            self._save_state(state)
            return state

        missing = self._missing_config()
        if missing:
            state = PolymarketDepositWalletState(
                user_id=request.user_id,
                owner_wallet=request.owner_wallet,
                status="blocked",
                reason=f"missing builder relayer configuration: {', '.join(missing)}",
                next_action="configure_builder_relayer",
                created_at=now,
                updated_at=now,
                metadata={**request.metadata, "missing": missing},
            )
            self._save_state(state)
            return state

        sdk_missing = self._missing_sdk_packages()
        if sdk_missing:
            state = PolymarketDepositWalletState(
                user_id=request.user_id,
                owner_wallet=request.owner_wallet,
                status="blocked",
                reason="official Polymarket builder relayer SDK is required before Clink can derive or deploy a deposit wallet",
                next_action="install_builder_relayer_sdk",
                created_at=now,
                updated_at=now,
                metadata={**request.metadata, "missing": sdk_missing},
            )
            self._save_state(state)
            return state

        mode = request.mode.lower()
        if mode not in {"derive", "deploy"}:
            raise ValueError("mode must be derive or deploy")

        if mode == "derive":
            try:
                raw = self.relayer_client.derive_deposit_wallet(request.owner_wallet)
            except Exception as exc:
                state = PolymarketDepositWalletState(
                    user_id=request.user_id,
                    owner_wallet=request.owner_wallet,
                    status="failed",
                    reason=f"deposit wallet derive failed: {type(exc).__name__}: {exc}",
                    next_action="inspect_builder_relayer_error",
                    can_use_x402=False,
                    created_at=now,
                    updated_at=now,
                    metadata=request.metadata,
                )
                self._save_state(state)
                return state
            deposit_wallet = self._extract_deposit_wallet(raw)
            status = "derived" if self._looks_like_address(deposit_wallet) else "failed"
            state = PolymarketDepositWalletState(
                user_id=request.user_id,
                owner_wallet=request.owner_wallet,
                deposit_wallet=deposit_wallet,
                status=status,
                reason=None if status == "derived" else "builder relayer did not return a deposit wallet address",
                next_action="deploy_polymarket_deposit_wallet" if status == "derived" else "inspect_builder_relayer_response",
                can_use_x402=status == "derived",
                created_at=now,
                updated_at=now,
                raw_response=raw,
                metadata=request.metadata,
            )
            self._save_state(state)
            return state

        previous = self._latest_state_for_user(request.user_id, request.owner_wallet)
        try:
            raw = self.relayer_client.deploy_deposit_wallet(request.owner_wallet)
        except Exception as exc:
            metadata = dict(request.metadata)
            diagnostics = getattr(exc, "diagnostics", None)
            if diagnostics:
                metadata["relayer_error"] = diagnostics
            state = PolymarketDepositWalletState(
                user_id=request.user_id,
                owner_wallet=request.owner_wallet,
                status="failed",
                reason=f"deposit wallet deploy failed: {type(exc).__name__}: {exc}",
                next_action="inspect_builder_relayer_error",
                can_use_x402=False,
                created_at=now,
                updated_at=now,
                metadata=metadata,
            )
            self._save_state(state)
            return state
        returned_deposit_wallet = self._extract_deposit_wallet(raw)
        deposit_wallet = returned_deposit_wallet or (previous.deposit_wallet if previous else None)
        status = "deployed" if self._looks_like_address(returned_deposit_wallet) else "submitted"
        can_use_x402 = status == "deployed" and bool(deposit_wallet)
        state = PolymarketDepositWalletState(
            user_id=request.user_id,
            owner_wallet=request.owner_wallet,
            deposit_wallet=deposit_wallet,
            status=status,
            reason=None if status == "deployed" else "relayer accepted deployment but deposit wallet address was not returned yet",
            next_action="fund_polymarket_deposit_wallet" if status == "deployed" else "poll_polymarket_relayer_transaction",
            can_use_x402=can_use_x402,
            transaction_id=raw.get("transactionID") or raw.get("transaction_id"),
            relayer_state=raw.get("state"),
            created_at=now,
            updated_at=now,
            raw_response=raw,
            metadata=request.metadata,
        )
        self._save_state(state)
        return state

    def _missing_config(self) -> list[str]:
        missing: list[str] = []
        if not self.config.polymarket_relayer_url:
            missing.append("POLYMARKET_RELAYER_URL")
        if self._has_builder_credentials() or self._has_relayer_api_key_credentials():
            return missing
        missing.append("POLYMARKET_BUILDER_API_KEY or POLYMARKET_RELAYER_API_KEY")
        missing.append("POLYMARKET_BUILDER_SECRET or POLYMARKET_RELAYER_API_KEY_ADDRESS")
        missing.append("POLYMARKET_BUILDER_PASS_PHRASE or POLYMARKET_RELAYER_API_KEY_ADDRESS")
        return missing

    def _has_builder_credentials(self) -> bool:
        return bool(
            self.config.polymarket_builder_api_key
            and self.config.polymarket_builder_secret
            and self.config.polymarket_builder_passphrase
        )

    def _has_relayer_api_key_credentials(self) -> bool:
        return bool(self.config.polymarket_relayer_api_key and self.config.polymarket_relayer_api_key_address)

    def _credential_mode(self) -> str:
        if self._has_builder_credentials():
            return "builder_api_key"
        if self._has_relayer_api_key_credentials():
            return "relayer_api_key"
        return "missing"

    def _missing_sdk_packages(self) -> list[str]:
        if not self.uses_default_relayer_client:
            return []
        if self.config.polymarket_deposit_wallet_address:
            return []

        missing: list[str] = []
        if not self._module_available(("py_builder_relayer_client", "builder_relayer_client")):
            missing.append("py-builder-relayer-client")
        if not self._module_available(("py_builder_signing_sdk", "builder_signing_sdk")):
            missing.append("py-builder-signing-sdk")
        return missing

    @staticmethod
    def _module_available(module_names: tuple[str, ...]) -> bool:
        return any(importlib.util.find_spec(module_name) is not None for module_name in module_names)

    def _save_state(self, state: PolymarketDepositWalletState) -> None:
        self.storage_file.parent.mkdir(parents=True, exist_ok=True)
        with self.storage_file.open("a") as handle:
            handle.write(json.dumps(state.model_dump(), ensure_ascii=False) + "\n")

    def _latest_state_for_user(self, user_id: str, owner_wallet: str | None = None) -> PolymarketDepositWalletState | None:
        if not self.storage_file.exists():
            return None
        latest: PolymarketDepositWalletState | None = None
        with self.storage_file.open() as handle:
            for line in handle:
                if not line.strip():
                    continue
                state = PolymarketDepositWalletState(**json.loads(line))
                if state.user_id != user_id:
                    continue
                if owner_wallet and state.owner_wallet.lower() != owner_wallet.lower():
                    continue
                latest = state
        return latest

    def _latest_state_for_owner(
        self,
        owner_wallet: str,
    ) -> PolymarketDepositWalletState | None:
        if not self.storage_file.exists():
            return None
        latest: PolymarketDepositWalletState | None = None
        with self.storage_file.open() as handle:
            for line in handle:
                if not line.strip():
                    continue
                state = PolymarketDepositWalletState(**json.loads(line))
                if state.owner_wallet.lower() == owner_wallet.lower():
                    latest = state
        return latest

    def _latest_state_with_deposit_wallet(
        self,
        user_id: str,
        owner_wallet: str | None = None,
    ) -> PolymarketDepositWalletState | None:
        if not self.storage_file.exists():
            return None
        latest: PolymarketDepositWalletState | None = None
        with self.storage_file.open() as handle:
            for line in handle:
                if not line.strip():
                    continue
                state = PolymarketDepositWalletState(**json.loads(line))
                if state.user_id != user_id:
                    continue
                if owner_wallet and state.owner_wallet.lower() != owner_wallet.lower():
                    continue
                if self._looks_like_address(state.deposit_wallet):
                    latest = state
        return latest

    def _backfill_submitted_deposit_wallet(self, state: PolymarketDepositWalletState) -> PolymarketDepositWalletState:
        previous = self._latest_state_with_deposit_wallet(state.user_id, state.owner_wallet)
        if not previous or not previous.deposit_wallet:
            return state
        return state.model_copy(
            update={
                "deposit_wallet": previous.deposit_wallet,
                "metadata": {
                    **state.metadata,
                    "deposit_wallet_backfilled_from_state": previous.status,
                },
            }
        )

    def _reconcile_derived_state(
        self, state: PolymarketDepositWalletState
    ) -> PolymarketDepositWalletState:
        if not state.deposit_wallet:
            return state
        try:
            deployed = self.relayer_client.is_deposit_wallet_deployed(
                state.deposit_wallet
            )
        except Exception as exc:
            return state.model_copy(
                update={
                    "metadata": {
                        **state.metadata,
                        "derived_deployment_check_error": type(exc).__name__,
                    }
                }
            )
        if not deployed:
            return state

        reconciled = state.model_copy(
            update={
                "status": "deployed",
                "reason": None,
                "next_action": "fund_polymarket_deposit_wallet",
                "can_use_x402": True,
                "updated_at": self._format_time(self._utc_now()),
                "metadata": {
                    **state.metadata,
                    "deposit_wallet_deployed_by_chain_code": True,
                },
            }
        )
        self._save_state(reconciled)
        return reconciled

    def _reconcile_submitted_state(self, state: PolymarketDepositWalletState) -> PolymarketDepositWalletState:
        if not state.transaction_id or not state.deposit_wallet:
            return state
        try:
            transaction = self.relayer_client.get_transaction(state.transaction_id)
            deployed = self.relayer_client.is_deposit_wallet_deployed(state.deposit_wallet)
        except Exception as exc:
            return state.model_copy(
                update={
                    "metadata": {
                        **state.metadata,
                        "submitted_reconciliation_error": f"{type(exc).__name__}: {exc}",
                    }
                }
            )

        relayer_state = transaction.get("state") or state.relayer_state
        transaction_hash = transaction.get("transactionHash") or transaction.get("transaction_hash")
        if relayer_state in {"STATE_CONFIRMED", "STATE_MINED", "STATE_EXECUTED"} and deployed:
            now = self._format_time(self._utc_now())
            reconciled = state.model_copy(
                update={
                    "status": "deployed",
                    "reason": None,
                    "next_action": "fund_polymarket_deposit_wallet",
                    "can_use_x402": True,
                    "relayer_state": relayer_state,
                    "updated_at": now,
                    "raw_response": {
                        **state.raw_response,
                        **transaction,
                    },
                    "metadata": {
                        **state.metadata,
                        "deposit_wallet_deployed_by_relayer_confirmation": True,
                        "transactionHash": transaction_hash,
                    },
                }
            )
            self._save_state(reconciled)
            return reconciled

        return state.model_copy(
            update={
                "relayer_state": relayer_state,
                "raw_response": {
                    **state.raw_response,
                    **transaction,
                    "deposit_wallet_code_deployed": deployed,
                },
            }
        )

    @staticmethod
    def _extract_deposit_wallet(payload: dict[str, Any]) -> str | None:
        for key in ("deposit_wallet", "depositWallet", "depositWalletAddress", "wallet", "walletAddress", "address"):
            value = payload.get(key)
            if PolymarketDepositWalletService._looks_like_address(value):
                return value
        nested = payload.get("result") or payload.get("data")
        if isinstance(nested, dict):
            return PolymarketDepositWalletService._extract_deposit_wallet(nested)
        return None

    @staticmethod
    def _looks_like_address(value: str | None) -> bool:
        return isinstance(value, str) and value.startswith("0x") and len(value) == 42

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.utcnow()

    @staticmethod
    def _format_time(value: datetime) -> str:
        return value.isoformat() + "Z"
