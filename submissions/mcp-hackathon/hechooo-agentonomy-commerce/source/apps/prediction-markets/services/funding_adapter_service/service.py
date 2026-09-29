from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Protocol
from uuid import uuid4

from services.funding_adapter_service.repository import (
    BridgeRepository,
    BridgeRepositoryError,
    PostgresBridgeRepository,
    SQLiteBridgeRepository,
)
from services.funding_adapter_service.schemas import (
    CreatePolymarketBridgeDepositRequest,
    PolymarketBridgeDeposit,
    PolymarketBridgeStatus,
    UINT256_MAX_ATOMIC,
)
from shared.config import AppConfig


_MAX_RESPONSE_BYTES = 65_536
_MAX_JSON_DEPTH = 6
_MAX_JSON_NODES = 1_024
_MAX_STRING_LENGTH = 2_048
_MAX_NOTE_LENGTH = 1_024
_DEPOSIT_CLAIM_LEASE_SECONDS = 30
_DEPOSIT_CLAIM_WAIT_SECONDS = 1.0
_DEPOSIT_CLAIM_POLL_SECONDS = 0.01
_USER_AGENT = "ClinkPredictionMarkets/1.0"
_ZERO_ADDRESS = "0x" + "0" * 40
_POLYMARKET_PUSD_TOKEN = "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb"
_POLYGON_USDCE_ONRAMP_TOKEN = "0x2791bca1f2de4661ed88a30c99a7a9449aa84174"
_EVM_ADDRESS_PATTERN = re.compile(r"^0x[0-9a-f]{40}$")
_TX_HASH_PATTERN = re.compile(r"^0x[0-9a-f]{64}$")
_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,95}$")
_CHAIN_ID_PATTERN = re.compile(r"^(0|[1-9][0-9]{0,19})$")
_ATOMIC_AMOUNT_PATTERN = re.compile(r"^[1-9][0-9]{0,77}$")
_BRIDGE_OPAQUE_PATTERN = re.compile(r"^[A-Za-z0-9._:@/+\-=]{1,256}$")
_BRIDGE_STATUSES = {
    "DEPOSIT_DETECTED",
    "PROCESSING",
    "ORIGIN_TX_CONFIRMED",
    "SUBMITTED",
    "COMPLETED",
    "FAILED",
}
_SENSITIVE_KEYS = {
    "apikey",
    "authorization",
    "mnemonic",
    "passphrase",
    "privatekey",
    "refreshtoken",
    "secret",
    "seed",
    "seedphrase",
}


class BridgeAdapterError(RuntimeError):
    pass


class BridgeTransportError(BridgeAdapterError):
    pass


class BridgeClient(Protocol):
    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]: ...

    def get(self, path: str) -> dict[str, Any]: ...


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HttpBridgeClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 20,
        max_response_bytes: int = _MAX_RESPONSE_BYTES,
        opener=None,
    ) -> None:
        parsed = urllib.parse.urlsplit(str(base_url).strip())
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("polymarket bridge base URL must be a clean HTTPS origin")
        self.base_url = str(base_url).rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes
        self.opener = opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            _NoRedirectHandler(),
        )

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            self._url(path),
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": _USER_AGENT,
            },
            method="POST",
        )
        return self._open(request, expected_status=201)

    def get(self, path: str) -> dict[str, Any]:
        request = urllib.request.Request(
            self._url(path),
            headers={"Accept": "application/json", "User-Agent": _USER_AGENT},
            method="GET",
        )
        return self._open(request, expected_status=200)

    def _url(self, path: str) -> str:
        if not path.startswith("/") or path.startswith("//"):
            raise BridgeTransportError("polymarket bridge request failed")
        return f"{self.base_url}{path}"

    def _open(
        self, request: urllib.request.Request, *, expected_status: int
    ) -> dict[str, Any]:
        try:
            with self.opener.open(request, timeout=self.timeout_seconds) as response:
                if response.status != expected_status:
                    raise BridgeTransportError("polymarket bridge request failed")
                content_type = str(response.headers.get("Content-Type") or "")
                if content_type.split(";", 1)[0].strip().lower() != "application/json":
                    raise BridgeTransportError("polymarket bridge request failed")
                length = response.headers.get("Content-Length")
                if length is not None and int(length) > self.max_response_bytes:
                    raise BridgeTransportError("polymarket bridge request failed")
                raw = response.read(self.max_response_bytes + 1)
                if len(raw) > self.max_response_bytes:
                    raise BridgeTransportError("polymarket bridge request failed")
                payload = json.loads(
                    raw.decode("utf-8"),
                    object_pairs_hook=self._reject_duplicate_keys,
                )
                if not isinstance(payload, dict):
                    raise BridgeTransportError("polymarket bridge request failed")
                _validate_safe_json(payload)
                return payload
        except BridgeTransportError:
            raise
        except (
            OSError,
            TimeoutError,
            UnicodeError,
            ValueError,
            json.JSONDecodeError,
            urllib.error.HTTPError,
            urllib.error.URLError,
        ):
            raise BridgeTransportError("polymarket bridge request failed") from None

    @staticmethod
    def _reject_duplicate_keys(pairs):
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result


class PolymarketFundingAdapterService:
    """Strict, user-scoped Polymarket Bridge V2 adapter."""

    def __init__(
        self,
        config: AppConfig | None = None,
        bridge_client: BridgeClient | None = None,
        repository: BridgeRepository | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.config = config or AppConfig.from_env()
        self._validate_config()
        self.bridge_client = bridge_client or HttpBridgeClient(
            self.config.polymarket_bridge_api_url
        )
        self.repository = repository or self._repository_from_config()
        self.clock = clock or (lambda: datetime.now(UTC))

    def create_deposit_address(
        self, request: CreatePolymarketBridgeDepositRequest
    ) -> PolymarketBridgeDeposit:
        existing_binding = self._repository_call(
            lambda: self.repository.find_deposit_target_for_binding(
                user_id=request.user_id,
                binding_id=request.binding_id,
            ),
            "bridge target lookup failed",
        )
        if existing_binding is not None:
            if existing_binding.venue_wallet_address != request.venue_wallet_address:
                raise BridgeAdapterError("bridge binding context conflict")
            return existing_binding

        claim_token = f"pm_claim_{uuid4().hex}"
        claimed_at = self._utc_now()
        claim_result = self._repository_call(
            lambda: self.repository.try_claim_deposit_creation(
                user_id=request.user_id,
                binding_id=request.binding_id,
                venue_wallet_address=request.venue_wallet_address,
                claim_token=claim_token,
                claimed_at=claimed_at,
                lease_expires_at=claimed_at
                + timedelta(seconds=_DEPOSIT_CLAIM_LEASE_SECONDS),
            ),
            "bridge target claim failed",
        )
        if claim_result == "context_conflict":
            raise BridgeAdapterError("bridge binding context conflict")
        if claim_result == "busy":
            deadline = time.monotonic() + _DEPOSIT_CLAIM_WAIT_SECONDS
            while time.monotonic() < deadline:
                existing_binding = self._repository_call(
                    lambda: self.repository.find_deposit_target_for_binding(
                        user_id=request.user_id,
                        binding_id=request.binding_id,
                    ),
                    "bridge target lookup failed",
                )
                if existing_binding is not None:
                    if (
                        existing_binding.venue_wallet_address
                        != request.venue_wallet_address
                    ):
                        raise BridgeAdapterError("bridge binding context conflict")
                    return existing_binding
                time.sleep(_DEPOSIT_CLAIM_POLL_SECONDS)
            raise BridgeAdapterError("bridge target creation is in progress")
        if claim_result != "acquired":
            raise BridgeAdapterError("bridge target claim failed")

        try:
            raw = self.bridge_client.post(
                "/deposit", {"address": request.venue_wallet_address}
            )
            bridge_address = self._parse_deposit_response(raw)
            now = self._utc_now()
            deposit = PolymarketBridgeDeposit(
                deposit_id=self._stable_id(
                    "pm_deposit",
                    request.user_id,
                    request.binding_id,
                    request.venue_wallet_address,
                    bridge_address,
                ),
                user_id=request.user_id,
                binding_id=request.binding_id,
                venue_wallet_address=request.venue_wallet_address,
                bridge_address=bridge_address,
                source_network="eip155:137",
                source_token_address=self._source_token,
                destination_network="eip155:137",
                destination_token_address=self._destination_token,
                status="ready",
                created_at=now,
            )
            return self._repository_call(
                lambda: self.repository.save_deposit_target(deposit),
                "bridge target could not be persisted",
            )
        finally:
            try:
                self.repository.release_deposit_creation_claim(
                    user_id=request.user_id,
                    binding_id=request.binding_id,
                    claim_token=claim_token,
                )
            except BridgeRepositoryError:
                pass

    def get_bridge_status(
        self,
        *,
        user_id: str,
        binding_id: str,
        venue_wallet_address: str,
        bridge_address: str,
        expected_amount_atomic: str,
        not_before_time_ms: int,
        expected_bridge_tx_hash: str | None = None,
    ) -> PolymarketBridgeStatus:
        normalized_user_id = self._canonical_id(user_id)
        normalized_binding_id = self._canonical_id(binding_id)
        normalized_wallet = self._canonical_address(venue_wallet_address)
        normalized_bridge = self._canonical_address(bridge_address)
        normalized_expected_amount = self._canonical_amount_atomic(
            expected_amount_atomic
        )
        normalized_not_before = self._canonical_time_ms(not_before_time_ms)
        normalized_expected_bridge_hash = (
            self._canonical_tx_hash(expected_bridge_tx_hash)
            if expected_bridge_tx_hash is not None
            else None
        )
        target = self._repository_call(
            lambda: self.repository.get_deposit_target(
                user_id=normalized_user_id,
                binding_id=normalized_binding_id,
                venue_wallet_address=normalized_wallet,
                bridge_address=normalized_bridge,
            ),
            "bridge target lookup failed",
        )
        if target is None:
            raise BridgeAdapterError("bridge target is unavailable")

        raw = self.bridge_client.get(f"/status/{normalized_bridge}?limit=50")
        transaction = self._select_status_transaction(
            raw,
            expected_amount_atomic=normalized_expected_amount,
            not_before_time_ms=normalized_not_before,
            expected_bridge_tx_hash=normalized_expected_bridge_hash,
        )
        now = self._utc_now()
        observation = PolymarketBridgeStatus(
            observation_id=self._stable_id(
                "pm_bridge_observation",
                normalized_user_id,
                normalized_binding_id,
                normalized_bridge,
                str(transaction.get("txHash") or "no_tx"),
                transaction["status"],
                transaction["fromAmountBaseUnit"],
                now.isoformat(),
            ),
            user_id=normalized_user_id,
            binding_id=normalized_binding_id,
            venue_wallet_address=normalized_wallet,
            bridge_address=normalized_bridge,
            source_network=target.source_network,
            source_token_address=target.source_token_address,
            destination_network=target.destination_network,
            destination_token_address=transaction["toTokenAddress"],
            status=transaction["status"],
            tx_hash=transaction.get("txHash"),
            amount_atomic=transaction["fromAmountBaseUnit"],
            checked_at=now,
            bridge_created_time_ms=transaction.get("createdTimeMs"),
        )
        return self._repository_call(
            lambda: self.repository.save_bridge_observation(observation),
            "bridge observation could not be persisted",
        )

    def get_deposit_target(
        self,
        *,
        user_id: str,
        binding_id: str,
        venue_wallet_address: str,
        bridge_address: str,
    ) -> PolymarketBridgeDeposit | None:
        return self._repository_call(
            lambda: self.repository.get_deposit_target(
                user_id=self._canonical_id(user_id),
                binding_id=self._canonical_id(binding_id),
                venue_wallet_address=self._canonical_address(venue_wallet_address),
                bridge_address=self._canonical_address(bridge_address),
            ),
            "bridge target lookup failed",
        )

    def get_bridge_observation(
        self,
        *,
        user_id: str,
        binding_id: str,
        venue_wallet_address: str,
        bridge_address: str,
        expected_tx_hash: str | None = None,
    ) -> PolymarketBridgeStatus | None:
        return self._repository_call(
            lambda: self.repository.get_bridge_observation(
                user_id=self._canonical_id(user_id),
                binding_id=self._canonical_id(binding_id),
                venue_wallet_address=self._canonical_address(venue_wallet_address),
                bridge_address=self._canonical_address(bridge_address),
                expected_tx_hash=(
                    self._canonical_tx_hash(expected_tx_hash)
                    if expected_tx_hash is not None
                    else None
                ),
            ),
            "bridge observation lookup failed",
        )

    @staticmethod
    def _repository_call(operation: Callable[[], Any], message: str) -> Any:
        failed = False
        try:
            return operation()
        except BridgeRepositoryError:
            failed = True
        if failed:
            raise BridgeAdapterError(message)
        raise AssertionError("unreachable")

    def _repository_from_config(self) -> BridgeRepository:
        if self.config.profile == "personal":
            return SQLiteBridgeRepository(
                self.config.polymarket_bridge_database_path
            )
        if self.config.profile == "server":
            return PostgresBridgeRepository(
                str(self.config.prediction_markets_database_url)
            )
        raise BridgeAdapterError("prediction markets repository profile is invalid")

    def _validate_config(self) -> None:
        try:
            source_token = self._canonical_address(
                self.config.polymarket_bridge_source_token_address
            )
            destination_token = self._canonical_address(
                self.config.polymarket_pusd_token_address
            )
        except BridgeAdapterError:
            raise BridgeAdapterError("polymarket bridge configuration is invalid") from None
        if (
            self.config.polymarket_bridge_source_chain_id != 137
            or self.config.polymarket_bridge_destination_chain_id != 137
            or source_token == _ZERO_ADDRESS
            or destination_token == _ZERO_ADDRESS
        ):
            raise BridgeAdapterError("polymarket bridge configuration is invalid")
        self._source_token = source_token
        self._destination_token = destination_token
        self._reported_destination_tokens = {destination_token}
        if destination_token == _POLYMARKET_PUSD_TOKEN:
            # Polymarket's collateral onramp wraps Polygon USDC.e into pUSD.
            # Bridge status can report that immediate USDC.e hop; finalization
            # still requires the exact venue buying-power increase.
            self._reported_destination_tokens.add(_POLYGON_USDCE_ONRAMP_TOKEN)

    def _parse_deposit_response(self, raw: dict[str, Any]) -> str:
        try:
            _validate_safe_json(raw)
            if set(raw) - {"address", "note", "warnings"} or "address" not in raw:
                raise ValueError
            address = raw["address"]
            if not isinstance(address, dict):
                raise ValueError
            if set(address) - {"evm", "svm", "btc", "tron"} or "evm" not in address:
                raise ValueError
            for value in address.values():
                if value is not None and (
                    not isinstance(value, str) or not 1 <= len(value) <= 256
                ):
                    raise ValueError
            note = raw.get("note")
            if note is not None and (
                not isinstance(note, str) or len(note) > _MAX_NOTE_LENGTH
            ):
                raise ValueError
            if "warnings" in raw:
                warnings = raw["warnings"]
                if not isinstance(warnings, list) or len(warnings) != 1:
                    raise ValueError
                for warning in warnings:
                    if (
                        not isinstance(warning, dict)
                        or set(warning) != {"code", "message"}
                        or warning.get("code") != "missing_builder_code"
                        or not isinstance(warning.get("message"), str)
                        or not 1 <= len(warning["message"]) <= _MAX_NOTE_LENGTH
                    ):
                        raise ValueError
            bridge_address = self._canonical_address(address["evm"])
            if bridge_address == _ZERO_ADDRESS:
                raise ValueError
            return bridge_address
        except (BridgeAdapterError, TypeError, ValueError):
            raise BridgeAdapterError("polymarket bridge response is invalid") from None

    def _select_status_transaction(
        self,
        raw: dict[str, Any],
        *,
        expected_amount_atomic: str,
        not_before_time_ms: int,
        expected_bridge_tx_hash: str | None,
    ) -> dict[str, Any]:
        try:
            _validate_safe_json(raw)
            if set(raw) != {"transactions", "nextCursor"}:
                raise ValueError
            transactions = raw["transactions"]
            cursor = raw["nextCursor"]
            if not isinstance(transactions, list) or len(transactions) > 50:
                raise ValueError
            if cursor is not None and (
                not isinstance(cursor, str) or not 1 <= len(cursor) <= 256
            ):
                raise ValueError
            parsed = [self._parse_status_transaction(item) for item in transactions]
        except (BridgeAdapterError, TypeError, ValueError):
            raise BridgeAdapterError("polymarket bridge response is invalid") from None

        scoped: list[dict[str, Any]] = []
        for transaction in parsed:
            if (
                transaction["fromChainId"] != "137"
                or transaction["toChainId"] != "137"
            ):
                continue
            try:
                source_token = self._canonical_address(
                    transaction["fromTokenAddress"]
                )
                destination_token = self._canonical_address(
                    transaction["toTokenAddress"]
                )
                tx_hash = transaction.get("txHash")
                if tx_hash is not None:
                    tx_hash = self._canonical_tx_hash(tx_hash)
            except BridgeAdapterError:
                raise BridgeAdapterError(
                    "polymarket bridge response is invalid"
                ) from None
            if (
                source_token != self._source_token
                or destination_token not in self._reported_destination_tokens
            ):
                continue
            scoped.append(
                {
                    **transaction,
                    "fromTokenAddress": source_token,
                    "toTokenAddress": destination_token,
                    "txHash": tx_hash,
                }
            )

        matches = [
            transaction
            for transaction in scoped
            if transaction["fromAmountBaseUnit"] == expected_amount_atomic
            and transaction.get("createdTimeMs") is not None
            and transaction["createdTimeMs"] >= not_before_time_ms
        ]
        if expected_bridge_tx_hash is not None:
            # Bridge V2 reports the destination transaction hash after completion,
            # while Core records the source transfer hash. Preserve exact-match
            # preference for compatible responses, then require one uniquely
            # scoped candidate from a fully enumerated status page below.
            exact_matches = [
                transaction
                for transaction in matches
                if transaction.get("txHash") == expected_bridge_tx_hash
            ]
            if len(exact_matches) == 1:
                return exact_matches[0]
            if len(exact_matches) > 1:
                raise BridgeAdapterError(
                    "expected bridge transaction is unavailable"
                )

        if cursor is not None:
            raise BridgeAdapterError("expected bridge transaction is unavailable")
        if len(matches) != 1:
            raise BridgeAdapterError("expected bridge transaction is unavailable")
        return matches[0]

    def _parse_status_transaction(self, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise ValueError
        required = {
            "fromChainId",
            "fromTokenAddress",
            "fromAmountBaseUnit",
            "toChainId",
            "toTokenAddress",
            "status",
        }
        if set(raw) - (required | {"txHash", "createdTimeMs"}) or not required.issubset(raw):
            raise ValueError
        from_chain_id = self._canonical_chain_id(raw["fromChainId"])
        to_chain_id = self._canonical_chain_id(raw["toChainId"])
        source_token = self._canonical_bridge_opaque(raw["fromTokenAddress"])
        destination_token = self._canonical_bridge_opaque(raw["toTokenAddress"])
        amount_atomic = raw["fromAmountBaseUnit"]
        if not isinstance(amount_atomic, str) or not _ATOMIC_AMOUNT_PATTERN.fullmatch(
            amount_atomic
        ):
            raise ValueError
        status = raw["status"]
        if not isinstance(status, str) or status not in _BRIDGE_STATUSES:
            raise ValueError
        tx_hash = raw.get("txHash")
        if tx_hash is not None:
            tx_hash = self._canonical_bridge_opaque(tx_hash)
        if status == "COMPLETED" and tx_hash is None:
            raise ValueError
        created_time = raw.get("createdTimeMs")
        if created_time is not None and (
            isinstance(created_time, bool)
            or not isinstance(created_time, int)
            or created_time < 0
        ):
            raise ValueError
        return {
            "fromChainId": from_chain_id,
            "fromTokenAddress": source_token,
            "fromAmountBaseUnit": amount_atomic,
            "toChainId": to_chain_id,
            "toTokenAddress": destination_token,
            "status": status,
            "txHash": tx_hash,
            "createdTimeMs": created_time,
        }

    @staticmethod
    def _canonical_id(value: str) -> str:
        normalized = str(value).strip()
        if not _ID_PATTERN.fullmatch(normalized):
            raise BridgeAdapterError("bridge scope is invalid")
        return normalized

    @staticmethod
    def _canonical_address(value: str) -> str:
        normalized = str(value).strip().lower()
        if not _EVM_ADDRESS_PATTERN.fullmatch(normalized):
            raise BridgeAdapterError("bridge scope is invalid")
        return normalized

    @staticmethod
    def _canonical_tx_hash(value: str) -> str:
        normalized = str(value).strip().lower()
        if not _TX_HASH_PATTERN.fullmatch(normalized):
            raise BridgeAdapterError("bridge scope is invalid")
        return normalized

    @staticmethod
    def _canonical_bridge_opaque(value: Any) -> str:
        if not isinstance(value, str) or not _BRIDGE_OPAQUE_PATTERN.fullmatch(value):
            raise BridgeAdapterError("bridge response value is invalid")
        return value

    @staticmethod
    def _canonical_chain_id(value: Any) -> str:
        if not isinstance(value, str) or not _CHAIN_ID_PATTERN.fullmatch(value):
            raise BridgeAdapterError("bridge scope is invalid")
        return value

    @staticmethod
    def _canonical_amount_atomic(value: str) -> str:
        normalized = str(value).strip()
        if (
            not _ATOMIC_AMOUNT_PATTERN.fullmatch(normalized)
            or len(normalized) == len(UINT256_MAX_ATOMIC)
            and normalized > UINT256_MAX_ATOMIC
        ):
            raise BridgeAdapterError("bridge scope is invalid")
        return normalized

    @staticmethod
    def _canonical_time_ms(value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise BridgeAdapterError("bridge scope is invalid")
        return value

    @staticmethod
    def _stable_id(prefix: str, *parts: str) -> str:
        digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:32]
        return f"{prefix}_{digest}"

    def _utc_now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise BridgeAdapterError("bridge clock is invalid")
        return value.astimezone(UTC)


def _validate_safe_json(value: Any) -> None:
    nodes = 0

    def visit(item: Any, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > _MAX_JSON_NODES or depth > _MAX_JSON_DEPTH:
            raise ValueError("JSON response exceeds limits")
        if isinstance(item, dict):
            for key, nested in item.items():
                if not isinstance(key, str) or not 1 <= len(key) <= 64:
                    raise ValueError("JSON key is invalid")
                normalized_key = re.sub(r"[^a-z0-9]", "", key.lower())
                if normalized_key in _SENSITIVE_KEYS:
                    raise ValueError("sensitive JSON field")
                visit(nested, depth + 1)
            return
        if isinstance(item, list):
            for nested in item:
                visit(nested, depth + 1)
            return
        if isinstance(item, str):
            if len(item) > _MAX_STRING_LENGTH:
                raise ValueError("JSON string exceeds limits")
            lowered = item.lower()
            if lowered.startswith("bearer ") or "begin private key" in lowered:
                raise ValueError("sensitive JSON value")
            return
        if item is not None and not isinstance(item, (bool, int)):
            raise ValueError("JSON scalar type is invalid")

    visit(value, 0)
