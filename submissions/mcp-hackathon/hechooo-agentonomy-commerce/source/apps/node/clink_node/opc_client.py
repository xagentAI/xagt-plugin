from __future__ import annotations

import base64
import json
import os
import secrets
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import anyio
import httpx

from .secrets import RestrictedFileSecretStore

if TYPE_CHECKING:
    from shared.hosted_facilitator_protocol import DeviceSigningKey


_MAX_RESPONSE_BYTES = 64 * 1024
_TOKEN_REFRESH_WINDOW_SECONDS = 60
_TOKEN_TTL_SECONDS = 300
_PROOF_ACTIONS = frozenset({"pair", "token", "revoke", "status"})
_STATUS_VALUES = frozenset(
    {"pending", "active", "consent_required", "revoked", "unpaired"}
)


class OpcClientError(RuntimeError):
    """A bounded client-side or remote OPC error safe to show locally."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        if status_code is not None and (
            type(status_code) is not int or not 100 <= status_code <= 599
        ):
            raise ValueError("OPC HTTP status must be numeric")
        self.status_code = status_code
        super().__init__(message)


@dataclass(frozen=True)
class OpcClientState:
    origin: str
    label: str
    installation_id: str
    private_key_der: bytes
    allow_loopback_http: bool = False

    @property
    def device_key(self) -> DeviceSigningKey:
        from shared.hosted_facilitator_protocol import DeviceSigningKey

        return DeviceSigningKey.from_pkcs8_der(self.private_key_der)


class OpcClientStateStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._requests = RestrictedFileSecretStore(
            self.path.with_name(self.path.name + ".requests")
        )

    def pending_request_id(self, action: str) -> str:
        if action not in _PROOF_ACTIONS:
            raise ValueError("OPC proof action is invalid")
        with self._requests._lock():
            values = self._requests._load_unlocked()
            if not set(values).issubset(_PROOF_ACTIONS):
                raise PermissionError("OPC request journal is invalid")
            encoded = values.get(action)
            if encoded is not None:
                return self._decode_request_id(encoded)
            request_id = str(uuid4())
            values[action] = base64.urlsafe_b64encode(
                request_id.encode("ascii")
            ).decode("ascii")
            self._requests._save_unlocked(values)
            return request_id

    def complete_request(self, action: str, request_id: str) -> None:
        if action not in _PROOF_ACTIONS:
            raise ValueError("OPC proof action is invalid")
        expected = base64.urlsafe_b64encode(request_id.encode("ascii")).decode(
            "ascii"
        )
        with self._requests._lock():
            values = self._requests._load_unlocked()
            if not set(values).issubset(_PROOF_ACTIONS):
                raise PermissionError("OPC request journal is invalid")
            if values.get(action) != expected:
                return
            del values[action]
            self._requests._save_unlocked(values)

    @staticmethod
    def _decode_request_id(encoded: str) -> str:
        try:
            raw = base64.b64decode(encoded, altchars=b"-_", validate=True)
            request_id = raw.decode("ascii")
        except (UnicodeDecodeError, ValueError) as exc:
            raise PermissionError("OPC request journal is invalid") from exc
        if len(request_id) != 36:
            raise PermissionError("OPC request journal is invalid")
        try:
            if str(UUID(request_id)) != request_id:
                raise ValueError
        except ValueError as exc:
            raise PermissionError("OPC request journal is invalid") from exc
        return request_id

    def create(
        self,
        *,
        origin: str,
        label: str,
        allow_loopback_http: bool = False,
    ) -> OpcClientState:
        from shared.hosted_facilitator_protocol import DeviceSigningKey
        from shared.opc_protocol import canonical_opc_origin, installation_id

        canonical = canonical_opc_origin(
            origin, allow_loopback_http=allow_loopback_http
        )
        if type(label) is not str or not label or len(label) > 80:
            raise ValueError("OPC installation label is invalid")
        key = DeviceSigningKey.generate()
        state = OpcClientState(
            origin=canonical,
            label=label,
            installation_id=installation_id(key.public_jwk),
            private_key_der=key.pkcs8_der,
            allow_loopback_http=allow_loopback_http,
        )
        self._write_new(state)
        return state

    def load(self) -> OpcClientState:
        from shared.opc_protocol import canonical_opc_origin, installation_id

        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        try:
            descriptor = os.open(self.path, flags)
        except (OSError, ValueError) as exc:
            raise PermissionError("OPC client state cannot be opened safely") from exc
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
                raise PermissionError("OPC client state must be an owner-only regular file")
            raw = os.read(descriptor, _MAX_RESPONSE_BYTES + 1)
        finally:
            os.close(descriptor)
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise PermissionError("OPC client state is too large")
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise PermissionError("OPC client state is invalid") from exc
        if type(value) is not dict or set(value) != {
            "version",
            "origin",
            "label",
            "installation_id",
            "private_key_der",
            "allow_loopback_http",
        }:
            raise PermissionError("OPC client state is invalid")
        if value.get("version") != 1 or type(value.get("allow_loopback_http")) is not bool:
            raise PermissionError("OPC client state is invalid")
        try:
            private_der = base64.b64decode(
                value["private_key_der"], altchars=b"-_", validate=True
            )
            state = OpcClientState(
                origin=canonical_opc_origin(
                    value["origin"],
                    allow_loopback_http=value["allow_loopback_http"],
                ),
                label=value["label"],
                installation_id=value["installation_id"],
                private_key_der=private_der,
                allow_loopback_http=value["allow_loopback_http"],
            )
        except Exception as exc:
            raise PermissionError("OPC client state is invalid") from exc
        if state.installation_id != installation_id(state.device_key.public_jwk):
            raise PermissionError("OPC client state identity does not match its key")
        return state

    def _write_new(self, state: OpcClientState) -> None:
        from shared.hosted_facilitator_protocol import canonical_json_bytes

        parent = self.path.parent
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        parent_meta = os.lstat(parent)
        if not stat.S_ISDIR(parent_meta.st_mode) or stat.S_IMODE(parent_meta.st_mode) & 0o077:
            raise PermissionError("OPC state directory must be owner-only")
        payload = canonical_json_bytes(
            {
                "version": 1,
                "origin": state.origin,
                "label": state.label,
                "installation_id": state.installation_id,
                "private_key_der": base64.b64encode(state.private_key_der).decode("ascii"),
                "allow_loopback_http": state.allow_loopback_http,
            }
        )
        temporary = parent / f".{self.path.name}.{secrets.token_hex(8)}.tmp"
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0)
        )
        descriptor = os.open(temporary, flags, 0o600)
        try:
            os.write(descriptor, payload)
            os.fsync(descriptor)
        except BaseException:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            raise
        finally:
            os.close(descriptor)
        try:
            os.link(temporary, self.path, follow_symlinks=False)
        except FileExistsError:
            raise FileExistsError(f"OPC client state already exists: {self.path}") from None
        finally:
            temporary.unlink(missing_ok=True)


class OpcClient:
    def __init__(
        self,
        store: OpcClientStateStore,
        *,
        origin: str | None = None,
        label: str | None = None,
        allow_loopback_http: bool = False,
        clock: Callable[[], int] | None = None,
        transport: httpx.BaseTransport | None = None,
        mcp_client_factory: Callable[..., Any] | None = None,
    ) -> None:
        from shared.opc_protocol import canonical_opc_origin

        try:
            state = store.load()
        except FileNotFoundError:
            raise
        except PermissionError:
            if store.path.exists() or origin is None or label is None:
                raise
            state = store.create(
                origin=origin,
                label=label,
                allow_loopback_http=allow_loopback_http,
            )
        if origin is not None:
            expected = canonical_opc_origin(
                origin, allow_loopback_http=allow_loopback_http
            )
            if expected != state.origin:
                raise ValueError("OPC client is already bound to another origin")
        self.state = state
        self._store: OpcClientStateStore | None = store
        self._clock = clock if clock is not None else lambda: int(time.time())
        self._http = httpx.Client(
            base_url=state.origin,
            timeout=10.0,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )
        self._mcp_client_factory = mcp_client_factory or self._default_mcp_client
        self._access_token: str | None = None
        self._access_token_expires_at = 0
        self._mcp_url: str | None = None

    @classmethod
    def from_state(
        cls,
        state: OpcClientState,
        *,
        clock: Callable[[], int] | None = None,
        transport: httpx.BaseTransport | None = None,
        mcp_client_factory: Callable[..., Any] | None = None,
    ) -> "OpcClient":
        instance = cls.__new__(cls)
        instance.state = state
        instance._store = None
        instance._clock = clock if clock is not None else lambda: int(time.time())
        instance._http = httpx.Client(
            base_url=state.origin,
            timeout=10.0,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )
        instance._mcp_client_factory = mcp_client_factory or instance._default_mcp_client
        instance._access_token = None
        instance._access_token_expires_at = 0
        instance._mcp_url = None
        return instance

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "OpcClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def connect(self) -> dict[str, Any]:
        from shared.opc_protocol import canonical_opc_origin

        result, request_id = self._proof_request(
            "pair", expected_status=201, label=self.state.label
        )
        now = self._clock()
        required = {
            "installation_id",
            "pairing_id",
            "verification_uri",
            "expires_at",
            "status",
        }
        verification_uri = result.get("verification_uri")
        expires_at = result.get("expires_at")
        try:
            parsed_uri = urlsplit(verification_uri) if isinstance(verification_uri, str) else None
            verification_origin = (
                f"{parsed_uri.scheme}://{parsed_uri.netloc}" if parsed_uri is not None else ""
            )
            canonical_verification_origin = canonical_opc_origin(
                verification_origin,
                allow_loopback_http=self.state.allow_loopback_http,
            )
        except ValueError:
            parsed_uri = None
            verification_origin = ""
            canonical_verification_origin = ""
        if (
            set(result) != required
            or result.get("installation_id") != self.state.installation_id
            or type(result.get("pairing_id")) is not str
            or not result["pairing_id"]
            or len(result["pairing_id"]) > 128
            or parsed_uri is None
            or canonical_verification_origin != verification_origin
            or not parsed_uri.path.startswith("/account/")
            or parsed_uri.username is not None
            or parsed_uri.password is not None
            or parsed_uri.query
            or parsed_uri.fragment
            or type(expires_at) is not int
            or result.get("status") not in {"pending", "active"}
            or expires_at > now + 900
        ):
            raise OpcClientError("OPC pairing response is invalid")
        if expires_at <= now:
            self._complete_request("pair", request_id)
            raise OpcClientError("OPC pairing response is expired")
        self._complete_request("pair", request_id)
        return result

    def open_account_link(self) -> dict[str, Any]:
        """Open management for this installation's existing active account."""

        status = self.status()
        if not isinstance(status, dict) or status.get("status") != "active":
            raise OpcClientError(
                "An active OPC installation is required for account management"
            )
        link = self.connect()
        if not isinstance(link, dict) or link.get("status") != "active":
            raise OpcClientError(
                "OPC account authority changed; query status before continuing"
            )
        return link

    def status(self) -> dict[str, Any]:
        result, request_id = self._proof_request("status", expected_status=200)
        allowed = {
            "installation_id",
            "status",
            "label",
            "scope",
            "consent_expires_at",
            "created_at",
            "updated_at",
        }
        if (
            not set(result).issubset(allowed)
            or not {"installation_id", "status"}.issubset(result)
            or result.get("installation_id") != self.state.installation_id
            or result.get("status") not in _STATUS_VALUES
            or ("label" in result and (
                type(result["label"]) is not str
                or not 1 <= len(result["label"]) <= 80
            ))
            or ("scope" in result and result["scope"] != "payments")
            or any(
                name in result
                and result[name] is not None
                and type(result[name]) is not str
                for name in ("consent_expires_at", "created_at", "updated_at")
            )
        ):
            raise OpcClientError("OPC status response is invalid")
        self._complete_request("status", request_id)
        return result

    def revoke(self) -> dict[str, Any]:
        result, request_id = self._proof_request("revoke", expected_status=200)
        if (
            set(result) != {"installation_id", "status"}
            or result.get("installation_id") != self.state.installation_id
            or result.get("status") != "revoked"
        ):
            raise OpcClientError("OPC revoke response is invalid")
        self._access_token = None
        self._access_token_expires_at = 0
        self._mcp_url = None
        self._complete_request("revoke", request_id)
        return result

    def access_token(self) -> str:
        from shared.opc_protocol import OPC_MAX_CLOCK_SKEW_SECONDS

        now = self._clock()
        if (
            self._access_token is not None
            and self._access_token_expires_at - now > _TOKEN_REFRESH_WINDOW_SECONDS
        ):
            return self._access_token
        result, request_id = self._proof_request("token", expected_status=200)
        required = {
            "installation_id",
            "access_token",
            "token_type",
            "expires_at",
            "mcp_url",
        }
        if set(result) != required:
            raise OpcClientError("OPC token response is invalid")
        token = result.get("access_token")
        expires_at = result.get("expires_at")
        expected_mcp = f"{self.state.origin}/mcp"
        if (
            result.get("installation_id") != self.state.installation_id
            or result.get("token_type") != "Bearer"
            or type(token) is not str
            or not 1 <= len(token) <= 8192
            or any(ord(character) <= 32 or ord(character) > 126 for character in token)
            or type(expires_at) is not int
            or result.get("mcp_url") != expected_mcp
            or expires_at
            > now + _TOKEN_TTL_SECONDS + OPC_MAX_CLOCK_SKEW_SECONDS
        ):
            raise OpcClientError("OPC token response is invalid")
        if expires_at <= now + _TOKEN_REFRESH_WINDOW_SECONDS:
            self._complete_request("token", request_id)
            raise OpcClientError("OPC token response is expired")
        self._complete_request("token", request_id)
        self._access_token = token
        self._access_token_expires_at = expires_at
        self._mcp_url = expected_mcp
        return token

    async def list_tools(self):
        # Token minting uses the synchronous httpx client. Keep that setup off
        # the event loop while retaining the remote MCP client's async calls.
        client = await anyio.to_thread.run_sync(self._remote_mcp_client)
        return await client.list_tools()

    async def call_tool(self, name: str, arguments: dict[str, Any]):
        # Intentionally exactly one downstream call. An unknown payment outcome
        # must be recovered by reading the original operation, never replayed.
        client = await anyio.to_thread.run_sync(self._remote_mcp_client)
        return await client.call_tool(name, arguments)

    async def serve_stdio(self) -> None:
        from mcp.server import stdio
        from mcp.server.lowlevel import Server
        from .opc_onboarding import OpcOnboardingBridge

        server = Server("Agentonomy OPC bridge", version="0.1.0")
        bridge = OpcOnboardingBridge(self)

        @server.list_tools()
        async def list_tools():
            return await bridge.list_tools()

        @server.call_tool(validate_input=False)
        async def call_tool(name: str, arguments: dict[str, Any]):
            return await bridge.call_tool(name, arguments)

        async with stdio.stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
                raise_exceptions=True,
            )

    def _remote_mcp_client(self):
        token = self.access_token()
        if self._mcp_url is None:
            raise OpcClientError("OPC MCP endpoint is unavailable")
        return self._mcp_client_factory(
            self._mcp_url,
            {"Authorization": f"Bearer {token}"},
        )

    @staticmethod
    def _default_mcp_client(url: str, headers: dict[str, str]):
        from .mcp_proxy import StreamableHttpMcpClient

        return StreamableHttpMcpClient(url, headers=headers)

    def _proof_request(
        self,
        action: str,
        *,
        expected_status: int,
        label: str | None = None,
    ) -> tuple[dict[str, Any], str]:
        from shared.hosted_facilitator_protocol import canonical_json_bytes
        from shared.opc_protocol import sign_opc_proof

        request_id = (
            self._store.pending_request_id(action)
            if self._store is not None
            else str(uuid4())
        )
        proof = sign_opc_proof(
            self.state.device_key,
            origin=self.state.origin,
            action=action,
            request_id=request_id,
            now=self._clock(),
            label=label,
            allow_loopback_http=self.state.allow_loopback_http,
        )
        try:
            request = self._http.build_request(
                "POST",
                f"/v1/opc/{'pairings' if action == 'pair' else action}",
                headers={"Accept": "application/json", "Content-Type": "application/json"},
                content=canonical_json_bytes({"proof": proof}),
            )
            response = self._http.send(request, stream=True)
        except httpx.HTTPError as exc:
            raise OpcClientError("OPC service is unavailable") from exc
        try:
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > _MAX_RESPONSE_BYTES:
                    raise OpcClientError(
                        "OPC response is too large",
                        status_code=response.status_code,
                    )
            if response.status_code != expected_status:
                raise OpcClientError(
                    f"OPC request rejected with HTTP {response.status_code}",
                    status_code=response.status_code,
                )
            try:
                result = json.loads(bytes(body).decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise OpcClientError(
                    "OPC response is invalid",
                    status_code=response.status_code,
                ) from exc
            if type(result) is not dict:
                raise OpcClientError(
                    "OPC response is invalid",
                    status_code=response.status_code,
                )
            return result, request_id
        finally:
            response.close()

    def _complete_request(self, action: str, request_id: str) -> None:
        if self._store is not None:
            self._store.complete_request(action, request_id)
