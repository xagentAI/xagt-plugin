"""Small, fail-closed proxy from the Node OPC ingress to Core Account.

The Node is the public origin for OPC clients, but Core remains the authority
for pairing, credentials and installation state.  This client deliberately
keeps the Core bearer private and rewrites the two public URLs before a result
is returned to an OPC device.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

import httpx

from shared.opc_protocol import OpcProtocolError, canonical_opc_origin


_MAX_RESPONSE_BYTES = 64 * 1024
_MAX_PROOF_BYTES = 16 * 1024
_INSTALLATION_ID = re.compile(r"^opc_[0-9a-f]{40}$")
_PAIRING_ID = re.compile(r"^opc_pair_[0-9a-f]{40}$")
_OPC_TOKEN_PREFIX = "agentonomy_opc_v1_"
_SAFE_TOKEN = re.compile(r"^[\x21-\x7e]+$")
_PAIRING_STATUSES = frozenset({"pending", "active"})
_STATUS_VALUES = frozenset(
    {"pending", "active", "consent_required", "revoked", "unpaired"}
)


class OpcCoreError(RuntimeError):
    """A safe public error from the Core OPC dependency."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(message)


class OpcCoreClient:
    """Call Core's internal OPC contract without exposing internal details."""

    def __init__(
        self,
        *,
        account_url: str,
        internal_token: str,
        public_origin: str,
        account_public_origin: str | None = None,
        allow_loopback_http: bool = False,
        timeout_seconds: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._account_url = _internal_account_url(account_url)
        if (
            type(internal_token) is not str
            or not 1 <= len(internal_token) <= 4096
            or not _SAFE_TOKEN.fullmatch(internal_token)
        ):
            raise ValueError("OPC Core internal credential is invalid")
        if type(timeout_seconds) not in {int, float} or not 0 < timeout_seconds <= 60:
            raise ValueError("OPC Core timeout is invalid")
        try:
            self._public_origin = canonical_opc_origin(
                public_origin,
                allow_loopback_http=allow_loopback_http,
            )
            self._account_public_origin = canonical_opc_origin(
                account_public_origin or public_origin,
                allow_loopback_http=allow_loopback_http,
            )
        except OpcProtocolError as exc:
            raise ValueError("OPC public origin is invalid") from exc
        # Keep the internal bearer in the private HTTP client only.  Never put
        # it in a response, exception, repr or public URL.
        self._http = httpx.Client(
            headers={
                "Authorization": f"Bearer {internal_token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=float(timeout_seconds),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    def __repr__(self) -> str:
        return (
            "OpcCoreClient(account_url=<internal>, "
            "public_origin=" + repr(self._public_origin) + ")"
        )

    def close(self) -> None:
        self._http.close()

    def create_pairing(self, proof: str) -> dict[str, Any]:
        result = self._post("pairings", proof, expected_status=201)
        return self._pairing_response(result)

    def issue_token(self, proof: str) -> dict[str, Any]:
        result = self._post("token", proof, expected_status=200)
        return self._token_response(result)

    def status(self, proof: str) -> dict[str, Any]:
        result = self._post("status", proof, expected_status=200)
        return self._status_response(result)

    def revoke(self, proof: str) -> dict[str, Any]:
        result = self._post("revoke", proof, expected_status=200)
        installation_id = _installation(result.get("installation_id"))
        status = result.get("status")
        if status != "revoked":
            raise OpcCoreError(502, "OPC Core response is invalid")
        return {"installation_id": installation_id, "status": status}

    def authenticate(self, access_token: str):
        """Resolve an OPC bearer into the Node's request-scoped principal."""

        if (
            type(access_token) is not str
            or not access_token.startswith(_OPC_TOKEN_PREFIX)
            or not len(_OPC_TOKEN_PREFIX) < len(access_token) <= 512
            or _SAFE_TOKEN.fullmatch(access_token) is None
        ):
            # Use the same exception class as the local C authenticator so the
            # HTTP boundary can return a normal 401 without fallback.
            from .agent_access import AgentAccessUnauthorizedError

            raise AgentAccessUnauthorizedError()
        try:
            result = self._post_json(
                "authenticate",
                {"access_token": access_token},
                expected_status=200,
            )
            return self._principal(result)
        except OpcCoreError as exc:
            if 400 <= exc.status_code < 500:
                from .agent_access import AgentAccessUnauthorizedError

                raise AgentAccessUnauthorizedError() from None
            raise RuntimeError("OPC authentication unavailable") from None

    def _post(self, action: str, proof: str, *, expected_status: int) -> dict[str, Any]:
        if (
            type(proof) is not str
            or not 1 <= len(proof) <= _MAX_PROOF_BYTES
            or _SAFE_TOKEN.fullmatch(proof) is None
        ):
            raise OpcCoreError(400, "OPC proof is invalid")
        return self._post_json(
            action,
            {"proof": proof},
            expected_status=expected_status,
        )

    def _post_json(
        self,
        action: str,
        payload: dict[str, str],
        *,
        expected_status: int,
    ) -> dict[str, Any]:
        try:
            response = self._http.post(
                f"{self._account_url}/internal/opc/{action}",
                json=payload,
            )
        except Exception:
            raise OpcCoreError(503, "OPC Core service unavailable") from None
        if response.is_redirect or 300 <= response.status_code < 400:
            raise OpcCoreError(503, "OPC Core service unavailable")
        try:
            body = response.content
        except httpx.HTTPError:
            raise OpcCoreError(503, "OPC Core service unavailable") from None
        if len(body) > _MAX_RESPONSE_BYTES:
            raise OpcCoreError(502, "OPC Core response is invalid")
        if response.status_code != expected_status:
            if 400 <= response.status_code < 500:
                raise OpcCoreError(response.status_code, "OPC Core request rejected")
            raise OpcCoreError(503, "OPC Core service unavailable")
        try:
            value = response.json()
        except (ValueError, TypeError):
            raise OpcCoreError(502, "OPC Core response is invalid") from None
        if type(value) is not dict:
            raise OpcCoreError(502, "OPC Core response is invalid")
        return value

    def _pairing_response(self, value: dict[str, Any]) -> dict[str, Any]:
        required = {
            "installation_id",
            "pairing_id",
            "verification_uri",
            "expires_at",
            "status",
        }
        if set(value) != required:
            raise OpcCoreError(502, "OPC Core response is invalid")
        installation_id = _installation(value.get("installation_id"))
        pairing_id = value.get("pairing_id")
        if type(pairing_id) is not str or _PAIRING_ID.fullmatch(pairing_id) is None:
            raise OpcCoreError(502, "OPC Core response is invalid")
        expires_at = _timestamp(value.get("expires_at"))
        status = value.get("status")
        if status not in _PAIRING_STATUSES:
            raise OpcCoreError(502, "OPC Core response is invalid")
        path = _account_path(value.get("verification_uri"))
        return {
            "installation_id": installation_id,
            "pairing_id": pairing_id,
            "verification_uri": self._account_public_origin + path,
            "expires_at": expires_at,
            "status": status,
        }

    def _token_response(self, value: dict[str, Any]) -> dict[str, Any]:
        required = {
            "installation_id",
            "access_token",
            "token_type",
            "expires_at",
            "mcp_url",
        }
        if set(value) != required:
            raise OpcCoreError(502, "OPC Core response is invalid")
        installation_id = _installation(value.get("installation_id"))
        token = value.get("access_token")
        if (
            type(token) is not str
            or not token.startswith(_OPC_TOKEN_PREFIX)
            or len(token) <= len(_OPC_TOKEN_PREFIX)
            or len(token) > 512
            or _SAFE_TOKEN.fullmatch(token) is None
            or value.get("token_type") != "Bearer"
        ):
            raise OpcCoreError(502, "OPC Core response is invalid")
        return {
            "installation_id": installation_id,
            "access_token": token,
            "token_type": "Bearer",
            "expires_at": _timestamp(value.get("expires_at")),
            "mcp_url": self._public_origin + "/mcp",
        }

    def _status_response(self, value: dict[str, Any]) -> dict[str, Any]:
        installation_id = _installation(value.get("installation_id"))
        status = value.get("status")
        if type(status) is not str or status not in _STATUS_VALUES:
            raise OpcCoreError(502, "OPC Core response is invalid")
        # Status is intentionally a small public projection.  In particular,
        # do not forward Core wallet/grant identifiers or arbitrary fields.
        result: dict[str, Any] = {
            "installation_id": installation_id,
            "status": status,
        }
        for name in (
            "label",
            "scope",
            "consent_expires_at",
            "created_at",
            "updated_at",
        ):
            if name in value:
                item = value[name]
                if name == "label" and (
                    type(item) is not str or not 1 <= len(item) <= 80
                ):
                    raise OpcCoreError(502, "OPC Core response is invalid")
                if name == "scope" and item != "payments":
                    raise OpcCoreError(502, "OPC Core response is invalid")
                if name.endswith("_at") and item is not None and type(item) is not str:
                    raise OpcCoreError(502, "OPC Core response is invalid")
                result[name] = item
        return result

    @staticmethod
    def _principal(value: dict[str, Any]):
        from .agent_access import RuntimePrincipal

        required = {
            "issuer",
            "installation_id",
            "user_id",
            "agent_id",
            "scope",
            "credential_id",
            "expires_at",
        }
        if not required.issubset(value) or value.get("issuer") != "opc":
            raise OpcCoreError(502, "OPC Core response is invalid")
        installation_id = _installation(value.get("installation_id"))
        user_id = value.get("user_id")
        agent_id = value.get("agent_id")
        scope = value.get("scope")
        credential_id = value.get("credential_id")
        if (
            type(user_id) is not str
            or not 1 <= len(user_id) <= 96
            or type(agent_id) is not str
            or agent_id != "hermes"
            or scope != "payments"
            or type(credential_id) is not str
            or not 1 <= len(credential_id) <= 96
        ):
            raise OpcCoreError(502, "OPC Core response is invalid")
        expires_at = _timestamp(value.get("expires_at"))
        # Core's v0.1 OPC credential is installation-scoped.  Reusing the
        # installation id as the principal runtime id keeps the Node contract
        # non-null while preserving strict isolation.  A future Core contract
        # may provide a separate runtime id without changing this boundary.
        return RuntimePrincipal(
            user_id=user_id,
            agent_id=agent_id,
            runtime_id=installation_id,
            credential_id=credential_id,
            issuer="opc",
            scope=scope,
            expires_at=expires_at,
            opc_installation_id=installation_id,
        )


def _internal_account_url(value: object) -> str:
    if type(value) is not str or not value or len(value) > 2048:
        raise ValueError("OPC Core account URL is invalid")
    if any(ord(character) <= 32 for character in value):
        raise ValueError("OPC Core account URL is invalid")
    try:
        parsed = urlsplit(value)
        parsed.port  # Reject malformed ports too.
    except ValueError as exc:
        raise ValueError("OPC Core account URL is invalid") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("OPC Core account URL is invalid")
    return value.rstrip("/")


def _installation(value: object) -> str:
    if type(value) is not str or _INSTALLATION_ID.fullmatch(value) is None:
        raise OpcCoreError(502, "OPC Core response is invalid")
    return value


def _timestamp(value: object) -> int:
    if type(value) is not int or value < 0:
        raise OpcCoreError(502, "OPC Core response is invalid")
    return value


def _account_path(value: object) -> str:
    if type(value) is not str or len(value) > 2048:
        raise OpcCoreError(502, "OPC Core response is invalid")
    try:
        parsed = urlsplit(value)
    except ValueError:
        raise OpcCoreError(502, "OPC Core response is invalid") from None
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith("/account/")
        or not parsed.path.removeprefix("/account/")
        or any(part in {"", ".", ".."} for part in parsed.path.split("/")[2:])
        or any(ord(character) <= 32 for character in parsed.path)
    ):
        raise OpcCoreError(502, "OPC Core response is invalid")
    return parsed.path


__all__ = ["OpcCoreClient", "OpcCoreError"]
