from __future__ import annotations

import hashlib
import json
import secrets
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from eth_account import Account
from eth_account.messages import encode_defunct

from services.account_binding_service.credential_store import CredentialStore, PolymarketApiCredentials
from services.account_binding_service.schemas import (
    CompletePolymarketBindingSessionRequest,
    CreatePolymarketBindingSessionRequest,
    PolymarketAccountBinding,
    PolymarketBindingSession,
    canonicalize_optional_evm_address,
)
from shared.config import AppConfig


class ClobAuthClient(Protocol):
    def get_server_time(self) -> str: ...

    def derive_api_credentials(self, *, wallet_address: str, signature: str, timestamp: str, nonce: int) -> dict[str, str]: ...


class PolymarketClobAuthError(RuntimeError):
    def __init__(self, status_code: int | None, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"polymarket clob auth failed: {status_code or 'network'} {detail}")


class PolymarketClobAuthClient:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def get_server_time(self) -> str:
        request = urllib.request.Request(
            f"{self.config.polymarket_clob_host.rstrip('/')}/time",
            headers=self._base_headers(),
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                payload = response.read().decode("utf-8").strip()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8")
            raise PolymarketClobAuthError(exc.code, detail) from exc
        except urllib.error.URLError as exc:
            raise PolymarketClobAuthError(None, str(exc)) from exc
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            return payload
        return str(parsed.get("time") or parsed.get("serverTime") or parsed.get("timestamp") or payload)

    def derive_api_credentials(self, *, wallet_address: str, signature: str, timestamp: str, nonce: int) -> dict[str, str]:
        headers = {
            **self._base_headers(),
            "POLY_ADDRESS": wallet_address,
            "POLY_SIGNATURE": signature,
            "POLY_TIMESTAMP": timestamp,
            "POLY_NONCE": str(nonce),
        }
        try:
            return self._request("GET", "/auth/derive-api-key", headers)
        except PolymarketClobAuthError as exc:
            if exc.status_code not in {400, 404}:
                raise
            return self._request("POST", "/auth/api-key", headers)

    def _request(self, method: str, path: str, headers: dict[str, str]) -> dict[str, str]:
        request = urllib.request.Request(
            f"{self.config.polymarket_clob_host.rstrip('/')}{path}",
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8")
            raise PolymarketClobAuthError(exc.code, detail) from exc
        except urllib.error.URLError as exc:
            raise PolymarketClobAuthError(None, str(exc)) from exc
        return {
            "apiKey": payload.get("apiKey") or payload.get("key"),
            "secret": payload.get("secret"),
            "passphrase": payload.get("passphrase"),
            "funderAddress": payload.get("funderAddress") or payload.get("funder"),
            "depositWallet": payload.get("depositWallet") or payload.get("depositWalletAddress"),
            "proxyWallet": payload.get("proxyWallet") or payload.get("proxyWalletAddress"),
        }

    @staticmethod
    def _base_headers() -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": "https://polymarket.com",
            "Referer": "https://polymarket.com/",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0 Safari/537.36"
            ),
        }


class PolymarketAccountBindingService:
    """Creates wallet-signed Polymarket account binding sessions for Hermes-led flows."""

    def __init__(
        self,
        config: AppConfig | None = None,
        storage_file: Path | str | None = None,
        credential_store: CredentialStore | None = None,
        clob_auth_client: ClobAuthClient | None = None,
    ) -> None:
        self.config = config or AppConfig.from_env()
        self.storage_file = Path(storage_file or self.config.account_binding_file)
        self.credential_store = credential_store or CredentialStore(self.config)
        self.clob_auth_client = clob_auth_client or PolymarketClobAuthClient(self.config)

    def create_binding_session(self, request: CreatePolymarketBindingSessionRequest) -> PolymarketBindingSession:
        request = CreatePolymarketBindingSessionRequest.model_validate(
            request.model_dump()
        )
        now = self._utc_now()
        existing_binding = self.latest_binding(request.user_id)
        expires_at = now + timedelta(minutes=max(1, request.expires_in_minutes))
        session_id = f"pm_bind_sess_{uuid4().hex[:12]}"
        nonce = f"pm-bind-{uuid4().hex[:16]}"
        console_token = secrets.token_urlsafe(32)
        console_token_hash = hashlib.sha256(console_token.encode()).hexdigest()
        message = self._build_message(
            session_id=session_id,
            user_id=request.user_id,
            agent_id=request.agent_id,
            wallet_address=request.wallet_address,
            polymarket_deposit_wallet=request.polymarket_deposit_wallet,
            nonce=nonce,
            expires_at=self._format_time(expires_at),
        )
        session = PolymarketBindingSession(
            session_id=session_id,
            user_id=request.user_id,
            agent_id=request.agent_id,
            wallet_address=request.wallet_address,
            polymarket_deposit_wallet=request.polymarket_deposit_wallet,
            message_to_sign=message,
            signing_url=(
                f"{self.config.account_binding_console_base_url.rstrip('/')}/polymarket/"
                f"binding-console/{session_id}?access_token={console_token}"
            ),
            status="pending",
            binding_id=existing_binding.binding_id if existing_binding else None,
            next_action="open_polymarket_binding_console",
            expires_at=self._format_time(expires_at),
            created_at=self._format_time(now),
            metadata={
                **request.metadata,
                "return_url": request.return_url,
                "nonce": nonce,
                "console_token_hash": console_token_hash,
            },
        )
        persisted = session.model_copy(
            update={"signing_url": session.signing_url.split("?", 1)[0]}
        )
        self._save_record("session", persisted.session_id, persisted.model_dump())
        return session

    def complete_binding_session(
        self,
        session_id: str,
        request: CompletePolymarketBindingSessionRequest,
    ) -> PolymarketBindingSession:
        request = CompletePolymarketBindingSessionRequest.model_validate(
            request.model_dump()
        )
        session = self.get_binding_session(session_id)
        if session is None:
            raise ValueError(f"binding session not found: {session_id}")
        if session.status == "completed" and session.next_action != "open_polymarket_account_setup":
            return session
        if self._is_expired(session.expires_at):
            expired = session.model_copy(update={"status": "expired", "reason": "binding session expired", "next_action": "create_new_binding_session"})
            self._save_record("session", expired.session_id, expired.model_dump())
            return expired
        if request.signed_message != session.message_to_sign:
            failed = session.model_copy(
                update={
                    "status": "signature_failed",
                    "reason": "signed message does not match binding session",
                    "next_action": "retry_wallet_signature",
                }
            )
            self._save_record("session", failed.session_id, failed.model_dump())
            return failed
        if not self._signature_matches_wallet(request.wallet_address, request.signed_message, request.signature):
            failed = session.model_copy(
                update={
                    "status": "signature_failed",
                    "reason": "wallet signature did not recover the requested wallet",
                    "next_action": "retry_wallet_signature",
                }
            )
            self._save_record("session", failed.session_id, failed.model_dump())
            return failed

        now = self._format_time(self._utc_now())
        api_key = None
        api_secret = None
        api_passphrase = None
        derived = None
        credential_source = "polymarket_l1_derive"
        if request.clob_auth_signature and request.clob_auth_timestamp:
            derived = self.clob_auth_client.derive_api_credentials(
                wallet_address=request.wallet_address,
                signature=request.clob_auth_signature,
                timestamp=request.clob_auth_timestamp,
                nonce=request.clob_auth_nonce,
            )
            api_key = derived.get("apiKey")
            api_secret = derived.get("secret")
            api_passphrase = derived.get("passphrase")

        has_api_credentials = bool(api_key and api_secret and api_passphrase)
        session_deposit_wallet = session.polymarket_deposit_wallet
        requested_signature_type = (
            "3" if session_deposit_wallet else request.polymarket_signature_type
        )
        deposit_wallet = session_deposit_wallet or request.polymarket_deposit_wallet
        deposit_wallet_source = (
            "session"
            if session_deposit_wallet
            else "request"
            if request.polymarket_deposit_wallet
            else None
        )
        derived_deposit_wallet = (
            self._extract_deposit_wallet(derived) if derived is not None else None
        )
        if not deposit_wallet and derived_deposit_wallet:
            deposit_wallet = derived_deposit_wallet
            deposit_wallet_source = "clob_auth_response"
        account_mode, resolved_signature_type, funder_address, active_deposit_wallet, account_source = self._resolve_polymarket_account_mode(
            requested_signature_type=requested_signature_type,
            wallet_address=request.wallet_address,
            deposit_wallet=deposit_wallet,
            has_api_credentials=has_api_credentials,
        )
        if active_deposit_wallet:
            account_source = deposit_wallet_source
        binding_active = has_api_credentials and account_mode != "unresolved" and bool(funder_address)
        status = "active" if binding_active else "account_mode_unresolved" if has_api_credentials else "credentials_required"
        next_action = (
            "account_binding_active"
            if binding_active
            else "polymarket_account_mode_unresolved"
            if has_api_credentials
            else "sign_polymarket_clob_auth"
        )
        api_key_fingerprint = self._fingerprint(api_key)
        binding = PolymarketAccountBinding(
            binding_id=f"pm_binding_{uuid4().hex[:12]}",
            session_id=session.session_id,
            user_id=session.user_id,
            agent_id=session.agent_id,
            wallet_address=request.wallet_address,
            polymarket_deposit_wallet=active_deposit_wallet,
            funder_address=funder_address,
            account_mode=account_mode,
            polymarket_signature_type=resolved_signature_type,
            has_api_credentials=has_api_credentials,
            api_key_fingerprint=api_key_fingerprint,
            status=status,
            reason=None if binding_active else "Polymarket account mode cannot be resolved automatically." if has_api_credentials else None,
            next_action=next_action,
            created_at=now,
            metadata={
                **session.metadata,
                **request.metadata,
                "credential_source": credential_source if has_api_credentials else None,
                "deposit_wallet_source": deposit_wallet_source,
                "account_mode": account_mode,
                "account_source": account_source,
                "requested_signature_type": requested_signature_type,
                "resolved_signature_type": resolved_signature_type,
            },
        )
        if has_api_credentials:
            credential_record = self.credential_store.save_polymarket_credentials(
                user_id=session.user_id,
                wallet_address=request.wallet_address,
                credentials=PolymarketApiCredentials(
                    api_key=str(api_key),
                    api_secret=str(api_secret),
                    api_passphrase=str(api_passphrase),
                    signature_type=resolved_signature_type,
                    funder_address=funder_address,
                ),
                credential_source=credential_source,
            )
            binding = binding.model_copy(
                update={
                    "api_key_fingerprint": credential_record.api_key_fingerprint
                }
            )
        completed = session.model_copy(
            update={
                "status": "completed",
                "reason": binding.reason,
                "next_action": next_action,
                "completed_at": now,
                "binding_id": binding.binding_id,
                "wallet_address": request.wallet_address,
                "polymarket_deposit_wallet": binding.polymarket_deposit_wallet,
            }
        )
        self._save_record("binding", binding.binding_id, binding.model_dump())
        self._save_record("session", completed.session_id, completed.model_dump())
        return completed

    def get_binding_session(self, session_id: str) -> PolymarketBindingSession | None:
        payload = self._load_latest("session").get(session_id)
        return PolymarketBindingSession(**payload) if payload else None

    def get_binding(self, binding_id: str) -> PolymarketAccountBinding | None:
        payload = self._load_latest("binding").get(binding_id)
        return PolymarketAccountBinding(**payload) if payload else None

    def revoke_binding(
        self,
        binding_id: str,
        *,
        reason: str = "user_requested_unbind",
        metadata: dict[str, Any] | None = None,
    ) -> PolymarketAccountBinding:
        binding = self.get_binding(binding_id)
        if binding is None:
            raise ValueError(f"binding not found: {binding_id}")
        credentials_deleted = self.credential_store.delete_polymarket_credentials(binding.user_id)
        revoked = binding.model_copy(
            update={
                "status": "revoked",
                "reason": reason,
                "next_action": "create_polymarket_account_binding",
                "has_api_credentials": False,
                "api_key_fingerprint": None,
                "metadata": {
                    **binding.metadata,
                    **(metadata or {}),
                    "revoked_at": self._format_time(self._utc_now()),
                    "credential_store_deleted": credentials_deleted,
                },
            }
        )
        self._save_record("binding", revoked.binding_id, revoked.model_dump())
        return revoked

    def latest_binding(self, user_id: str, venue: str = "polymarket") -> PolymarketAccountBinding | None:
        credentials = self.credential_store.get_polymarket_credentials(user_id)
        if credentials is None:
            return None
        latest: PolymarketAccountBinding | None = None
        for payload in self._load_latest("binding").values():
            if (
                not isinstance(payload, dict)
                or payload.get("user_id") != user_id
                or payload.get("venue") != venue
                or payload.get("status") != "active"
            ):
                continue
            try:
                binding = PolymarketAccountBinding(**payload)
            except (TypeError, ValueError):
                latest = None
                continue
            latest = binding
        return latest

    @staticmethod
    def _resolve_polymarket_account_mode(
        *,
        requested_signature_type: str,
        wallet_address: str,
        deposit_wallet: str | None,
        has_api_credentials: bool,
    ) -> tuple[str, str, str | None, str | None, str | None]:
        if not has_api_credentials:
            return "credentials_required", str(requested_signature_type or "auto"), None, None, None

        requested = str(requested_signature_type or "auto").lower()
        if requested in {"auto", "0", "eoa"}:
            return "eoa", "0", wallet_address, None, "connected_wallet"

        if requested in {"1", "2"}:
            if deposit_wallet:
                return "proxy_or_safe", requested, deposit_wallet, deposit_wallet, "clob_auth_response"
            return "unresolved", requested, None, None, None

        if requested == "3":
            if deposit_wallet:
                return "deposit_wallet", "3", deposit_wallet, deposit_wallet, "clob_auth_response"
            return "unresolved", "3", None, None, None

        return "unresolved", requested, None, None, None

    def _save_record(self, record_type: str, record_id: str, payload: dict[str, Any]) -> None:
        self.storage_file.parent.mkdir(parents=True, exist_ok=True)
        with self.storage_file.open("a") as handle:
            handle.write(
                json.dumps(
                    {
                        "record_type": record_type,
                        "record_id": record_id,
                        "payload": payload,
                        "written_at": self._format_time(self._utc_now()),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    def _load_latest(self, record_type: str) -> dict[str, dict[str, Any]]:
        if not self.storage_file.exists():
            return {}
        records: dict[str, dict[str, Any]] = {}
        with self.storage_file.open() as handle:
            for line in handle:
                if not line.strip():
                    continue
                record = json.loads(line)
                if record.get("record_type") == record_type:
                    records[record["record_id"]] = record["payload"]
        return records

    @staticmethod
    def _build_message(
        *,
        session_id: str,
        user_id: str,
        agent_id: str,
        wallet_address: str | None,
        polymarket_deposit_wallet: str | None,
        nonce: str,
        expires_at: str,
    ) -> str:
        return "\n".join(
            [
                "Polymarket Account Binding",
                f"session_id={session_id}",
                f"user_id={user_id}",
                f"agent_id={agent_id}",
                "venue=polymarket",
                f"wallet_address={wallet_address or ''}",
                f"polymarket_deposit_wallet={polymarket_deposit_wallet or ''}",
                "purpose=prediction_market_account_binding",
                f"nonce={nonce}",
                f"expires_at={expires_at}",
            ]
        )

    @staticmethod
    def _signature_matches_wallet(wallet_address: str, message: str, signature: str) -> bool:
        try:
            recovered = Account.recover_message(encode_defunct(text=message), signature=signature)
        except Exception:
            return False
        return recovered.lower() == wallet_address.lower()

    @staticmethod
    def _looks_like_address(value: str | None) -> bool:
        return bool(value and value.startswith("0x") and len(value) == 42)

    @staticmethod
    def _extract_deposit_wallet(payload: dict[str, Any]) -> str | None:
        address_keys = (
            "funder",
            "funderAddress",
            "funder_address",
            "depositWallet",
            "depositWalletAddress",
            "deposit_wallet",
            "deposit_wallet_address",
            "proxyWallet",
            "proxyWalletAddress",
            "proxy_wallet",
            "proxy_wallet_address",
            "safe",
            "safeAddress",
            "safe_address",
        )
        candidates: list[str] = []

        def collect(current: dict[str, Any]) -> None:
            for key in address_keys:
                if key not in current or current[key] is None:
                    continue
                candidate = canonicalize_optional_evm_address(
                    current[key],
                    field_name=f"CLOB {key} address",
                )
                if candidate is not None:
                    candidates.append(candidate)
            for key in ("user", "account", "profile"):
                nested = current.get(key)
                if isinstance(nested, dict):
                    collect(nested)

        collect(payload)
        unique_candidates = set(candidates)
        if len(unique_candidates) > 1:
            raise ValueError("conflicting CLOB address candidates")
        return next(iter(unique_candidates), None)

    @staticmethod
    def _fingerprint(value: str | None) -> str | None:
        if not value:
            return None
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
        return f"sha256:{digest[:12]}"

    @staticmethod
    def _is_expired(expires_at: str) -> bool:
        return datetime.fromisoformat(expires_at.replace("Z", "")) < PolymarketAccountBindingService._utc_now()

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.utcnow()

    @staticmethod
    def _format_time(value: datetime) -> str:
        return value.isoformat() + "Z"
