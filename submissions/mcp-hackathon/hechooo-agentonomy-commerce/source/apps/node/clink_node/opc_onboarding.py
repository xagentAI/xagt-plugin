"""Fixed pre-authentication MCP onboarding for one OPC client."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

import anyio
from mcp import types

from .opc_client import OpcClientError


ONBOARDING_TOOL_NAMES = frozenset(
    {
        "get_clink_connection_status",
        "connect_clink_wallet",
        "list_clink_business_tools",
        "call_clink_business_tool",
    }
)
_STATUS_VALUES = frozenset(
    {"pending", "active", "consent_required", "revoked", "unpaired"}
)
_REMOTE_REJECTION_CODES = frozenset(
    {
        "unauthorized",
        "tool_not_allowed",
        "invalid_account_response",
        "invalid_amount",
        "invalid_tool_arguments",
        "owned_object_not_found",
        "service_unavailable",
        "business_request_failed",
        "invalid_business_response",
    }
)
_INSTALLATION_ID_LENGTH = len("opc_") + 40
_NO_ARGUMENTS_SCHEMA = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}
_CALL_BUSINESS_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "minLength": 1, "maxLength": 128},
        # The remote Node owns the actual business-tool schema.
        "arguments": {"type": "object", "additionalProperties": True},
    },
    "required": ["name", "arguments"],
    "additionalProperties": False,
}
_STATUS_NEXT_ACTION = {
    "unpaired": "connect_clink_wallet",
    "pending": "connect_clink_wallet",
    "consent_required": "connect_clink_wallet",
    "revoked": "do_not_reconnect",
    "active": "get_clink_account_readiness",
    "unavailable": "get_clink_connection_status",
}
_TOOL_SPECS = (
    (
        "get_clink_connection_status",
        "Get Clink connection status",
        (
            "Read the OPC device state without wallet consent. An active device "
            "does not prove payment readiness; query get_clink_account_readiness "
            "before business use."
        ),
        _NO_ARGUMENTS_SCHEMA,
        {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True},
    ),
    (
        "connect_clink_wallet",
        "Connect Clink wallet",
        (
            "Open the official Clink wallet-consent flow for this installation; "
            "an active installation opens account management with a fresh linked "
            "session. Opening it does not sign or grant authority."
        ),
        _NO_ARGUMENTS_SCHEMA,
        {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    ),
    (
        "list_clink_business_tools",
        "List Clink business tools",
        (
            "List actual authenticated Clink business-tool definitions. Wallet "
            "consent is required; no catalogue is fabricated."
        ),
        _NO_ARGUMENTS_SCHEMA,
        {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    ),
    (
        "call_clink_business_tool",
        "Call a Clink business tool",
        (
            "Call one authenticated Clink business tool exactly once. The remote "
            "Node validates its schema, owner and policy; query an uncertain "
            "operation instead of replaying it."
        ),
        _CALL_BUSINESS_SCHEMA,
        {"readOnlyHint": False, "openWorldHint": True},
    ),
)


def open_wallet_browser(uri: str) -> bool:
    """Open an account URI with an absolute platform opener and no shell."""

    if type(uri) is not str or not uri or len(uri) > 2048:
        return False
    try:
        parsed = urlsplit(uri)
    except ValueError:
        return False
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        return False
    command = ["/usr/bin/open" if sys.platform == "darwin" else "/usr/bin/xdg-open", uri]
    try:
        completed = subprocess.run(
            command,
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return False
    return completed.returncode == 0


def _result(value: dict[str, Any], *, error: bool = False) -> types.CallToolResult:
    return types.CallToolResult(
        content=[
            types.TextContent(
                type="text",
                text=json.dumps(value, ensure_ascii=False, separators=(",", ":")),
            )
        ],
        structuredContent=value,
        isError=error,
    )


def _error(
    code: str,
    *,
    status: str,
    next_action: str | None = None,
    instructions: str | None = None,
) -> types.CallToolResult:
    value: dict[str, Any] = {"error": code, "status": status, "retry_safe": False}
    if next_action is not None:
        value["next_action"] = next_action
    if instructions is not None:
        value["instructions"] = instructions
    return _result(value, error=True)


def _unknown() -> types.CallToolResult:
    return _error(
        "outcome_unknown",
        status="unknown",
        next_action="query_original_operation",
        instructions=(
            "The business operation outcome is unknown. Query the original "
            "operation by its existing identifier; do not replay or create a "
            "second operation."
        ),
    )


def _project_remote_rejection(response: types.CallToolResult) -> types.CallToolResult | None:
    """Project only a recognized, authoritative Node rejection."""

    value = response.structuredContent
    if not isinstance(value, dict):
        return None
    code = value.get("error")
    if (
        type(code) is not str
        or code not in _REMOTE_REJECTION_CODES
        or value.get("status") != "rejected"
        or value.get("retry_safe") is not False
    ):
        return None
    # Do not forward arbitrary fields or remote content/detail.
    return _error(code, status="rejected")


def _safe_installation_id(value: object) -> str | None:
    if (
        type(value) is str
        and len(value) == _INSTALLATION_ID_LENGTH
        and value.startswith("opc_")
        and all(character in "0123456789abcdef" for character in value[4:])
    ):
        return value
    return None


def _state_installation_id(client: Any) -> str | None:
    state = getattr(client, "state", None)
    return _safe_installation_id(getattr(state, "installation_id", None))


def _unavailable(installation_id: str | None) -> dict[str, Any]:
    value: dict[str, Any] = {"status": "unavailable"}
    if installation_id is not None:
        value["installation_id"] = installation_id
    value.update(
        {
            "next_action": _STATUS_NEXT_ACTION["unavailable"],
            "payment_ready": False,
            "payment_ready_checked": False,
        }
    )
    return value


def _project_status(
    value: object,
    *,
    fallback_installation_id: str | None,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        return _unavailable(fallback_installation_id)
    status = value.get("status")
    if type(status) is not str or status not in _STATUS_VALUES:
        return _unavailable(fallback_installation_id)
    result: dict[str, Any] = {"status": status}
    installation_id = _safe_installation_id(
        value.get("installation_id", fallback_installation_id)
    )
    if installation_id is not None:
        result["installation_id"] = installation_id
    label = value.get("label")
    if type(label) is str and 1 <= len(label) <= 80:
        result["label"] = label
    if value.get("scope") == "payments":
        result["scope"] = "payments"
    for field in ("consent_expires_at", "created_at", "updated_at"):
        item = value.get(field)
        if item is None or (type(item) is str and len(item) <= 2048):
            if field in value:
                result[field] = item
    result.update(
        {
            "next_action": _STATUS_NEXT_ACTION[status],
            "payment_ready": False,
            "payment_ready_checked": False,
        }
    )
    return result


class OpcOnboardingBridge:
    """Fixed onboarding surface around one existing OPC client."""

    def __init__(
        self,
        client: Any,
        browser_opener: Callable[[str], bool] | None = None,
    ) -> None:
        self.client = client
        self.browser_opener = browser_opener or open_wallet_browser
        self._pairing: dict[str, Any] | None = None
        self._connect_lock = anyio.Lock()
        self._connect_inflight: dict[str, Any] | None = None

    async def list_tools(self) -> list[types.Tool]:
        """Return the catalogue without any network request."""

        return [
            types.Tool(
                name=name,
                title=title,
                description=description,
                inputSchema=copy.deepcopy(schema),
                annotations=types.ToolAnnotations(**annotations),
            )
            for name, title, description, schema, annotations in _TOOL_SPECS
        ]

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None,
    ) -> types.CallToolResult:
        if type(name) is not str or name not in ONBOARDING_TOOL_NAMES:
            return _error("TOOL_NOT_FOUND", status="rejected", next_action="list_tools")
        if type(arguments) is not dict:
            return _error("INVALID_ARGUMENTS", status="rejected")
        if name == "get_clink_connection_status":
            return (
                _error("INVALID_ARGUMENTS", status="rejected")
                if arguments
                else _result(await self._connection_status())
            )
        if name == "connect_clink_wallet":
            return (
                _error("INVALID_ARGUMENTS", status="rejected")
                if arguments
                else _result(await self._connect_wallet())
            )
        if name == "list_clink_business_tools":
            return (
                _error("INVALID_ARGUMENTS", status="rejected")
                if arguments
                else await self._list_business_tools()
            )
        return await self._call_business_tool(arguments)

    async def _connection_status(self) -> dict[str, Any]:
        installation_id = _state_installation_id(self.client)
        try:
            value = await anyio.to_thread.run_sync(self.client.status)
        except OpcClientError as exc:
            # Only an explicit transport 404 means the installation is absent.
            if getattr(exc, "status_code", None) == 404:
                return _project_status(
                    {"status": "unpaired", "installation_id": installation_id},
                    fallback_installation_id=installation_id,
                )
            return _unavailable(installation_id)
        except Exception:
            return _unavailable(installation_id)
        return _project_status(value, fallback_installation_id=installation_id)

    def _now(self) -> int:
        clock = getattr(self.client, "_clock", None)
        try:
            return int(clock() if callable(clock) else time.time())
        except Exception:
            return int(time.time())

    def _cached_pairing(self) -> dict[str, Any] | None:
        pairing = self._pairing
        if pairing is None:
            return None
        if type(pairing.get("expires_at")) is not int or pairing["expires_at"] <= self._now():
            self._pairing = None
            return None
        return pairing

    async def _connect_wallet(self) -> dict[str, Any]:
        # Single-flight the complete authoritative-status, pairing-cache,
        # pairing-creation and browser-open lifecycle. Waiting callers receive
        # the first result without creating another pairing or opening another
        # browser tab.
        async with self._connect_lock:
            inflight = self._connect_inflight
            if inflight is None:
                inflight = {
                    "event": anyio.Event(),
                    "result": None,
                    "error": None,
                }
                self._connect_inflight = inflight
                owner = True
            else:
                owner = False
        if not owner:
            await inflight["event"].wait()
            if inflight["error"] is not None:
                # The owner never publishes an exception to waiters. Keep the
                # guard for malformed state, but fail closed if one appears.
                return {
                    "status": "unavailable",
                    "browser_opened": False,
                    "expiry": None,
                    "instructions": self._connect_instructions("unavailable"),
                }
            return copy.deepcopy(inflight["result"])
        fallback = {
            "status": "unavailable",
            "browser_opened": False,
            "expiry": None,
            "instructions": self._connect_instructions("unavailable"),
        }
        result: dict[str, Any] | None = None
        try:
            result = await self._connect_wallet_serialized()
        finally:
            # Cancellation can be active while a synchronous status request is
            # unwinding. Shield the state reset and wakeup so later callers do
            # not wait forever on a stale in-flight operation.
            with anyio.CancelScope(shield=True):
                async with self._connect_lock:
                    inflight["result"] = copy.deepcopy(
                        result if result is not None else fallback
                    )
                    self._connect_inflight = None
                    inflight["event"].set()
        return result if result is not None else fallback

    async def _connect_wallet_serialized(self) -> dict[str, Any]:
        # Always refresh authoritative status before consuming a cached link.
        current = await self._connection_status()
        state = current["status"]
        if state in {"revoked", "unavailable"}:
            return {
                "status": state,
                "browser_opened": False,
                "expiry": None,
                "instructions": self._connect_instructions(state),
            }
        if state == "active":
            # An explicit active-device invocation is account management, not
            # pairing.  Always obtain a fresh linked browser session through
            # the client method; never consume a pending pairing cached by a
            # previous onboarding invocation.
            try:
                response = await anyio.to_thread.run_sync(
                    self.client.open_account_link
                )
            except OpcClientError as exc:
                if getattr(exc, "status_code", None) in {400, 401, 403}:
                    authoritative = await self._connection_status()
                    state = authoritative["status"]
                    if state in {
                        "unpaired",
                        "pending",
                        "consent_required",
                        "revoked",
                    }:
                        return {
                            "status": state,
                            "browser_opened": False,
                            "expiry": None,
                            "instructions": self._connect_instructions(state),
                        }
                return {
                    "status": "unavailable",
                    "browser_opened": False,
                    "expiry": None,
                    "instructions": self._connect_instructions("unavailable"),
                }
            except Exception:
                return {
                    "status": "unavailable",
                    "browser_opened": False,
                    "expiry": None,
                    "instructions": self._connect_instructions("unavailable"),
                }
            pairing = self._validated_pairing(response)
            if pairing is None or pairing["status"] != "active":
                return {
                    "status": "unavailable",
                    "browser_opened": False,
                    "expiry": None,
                    "instructions": self._connect_instructions("unavailable"),
                }
            try:
                opened = await anyio.to_thread.run_sync(
                    self.browser_opener,
                    pairing["verification_uri"],
                )
                browser_opened = type(opened) is bool and opened
            except Exception:
                browser_opened = False
            return {
                "status": "active",
                "browser_opened": browser_opened,
                "expiry": pairing["expires_at"],
                "instructions": self._connect_instructions(
                    "active", browser_opened, management=True
                ),
            }
        pairing = self._cached_pairing()
        if pairing is None:
            try:
                response = await anyio.to_thread.run_sync(self.client.connect)
            except OpcClientError as exc:
                if getattr(exc, "status_code", None) in {400, 401, 403}:
                    authoritative = await self._connection_status()
                    state = authoritative["status"]
                    if state in {"active", "revoked"}:
                        return {
                            "status": state,
                            "browser_opened": False,
                            "expiry": None,
                            "instructions": self._connect_instructions(state),
                        }
                return {
                    "status": "unavailable",
                    "browser_opened": False,
                    "expiry": None,
                    "instructions": self._connect_instructions("unavailable"),
                }
            except Exception:
                return {
                    "status": "unavailable",
                    "browser_opened": False,
                    "expiry": None,
                    "instructions": self._connect_instructions("unavailable"),
                }
            pairing = self._validated_pairing(response)
            if pairing is None:
                return {
                    "status": "unavailable",
                    "browser_opened": False,
                    "expiry": None,
                    "instructions": self._connect_instructions("unavailable"),
                }
            self._pairing = pairing

        try:
            opened = await anyio.to_thread.run_sync(
                self.browser_opener,
                pairing["verification_uri"],
            )
            browser_opened = type(opened) is bool and opened
        except Exception:
            browser_opened = False
        state = pairing["status"]
        return {
            "status": state,
            "browser_opened": browser_opened,
            "expiry": pairing["expires_at"],
            "instructions": self._connect_instructions(state, browser_opened),
        }

    @staticmethod
    def _connect_instructions(
        status: str,
        browser_opened: bool = False,
        *,
        management: bool = False,
    ) -> str:
        if status == "active":
            if management and browser_opened:
                return (
                    "Opened the account-management page for this active device. "
                    "Opening it does not sign or grant authority; review any wallet "
                    "consent manually, then query get_clink_account_readiness "
                    "before business use."
                )
            if management:
                return (
                    "The active device's account-management page could not be "
                    "opened. Run local clink opc account --no-open to display the "
                    "sensitive link. Opening it does not authorize payments; review "
                    "any wallet consent manually, then query "
                    "get_clink_account_readiness before business use."
                )
            return (
                "This device is active. Query get_clink_account_readiness; active "
                "status alone is not payment readiness."
            )
        if status == "revoked":
            return "This device is revoked; do not reconnect it or create new consent."
        if status == "unavailable":
            return (
                "Clink is unavailable. Retry get_clink_connection_status later; "
                "for headless use, run the local clink opc connect command."
            )
        if browser_opened:
            return "Complete wallet consent in the browser; opening it did not authorize payments."
        return (
            "Complete wallet consent locally. If no browser opened, run the local "
            "clink opc connect command for a headless fallback. Opening a page did "
            "not sign or grant authority."
        )

    def _validated_pairing(self, value: object) -> dict[str, Any] | None:
        # OpcClient.connect already validates identity, URI, and response shape.
        if not isinstance(value, dict):
            return None
        status = value.get("status")
        expires_at = value.get("expires_at")
        uri = value.get("verification_uri")
        if (
            type(status) is not str
            or status not in {"pending", "active"}
            or type(expires_at) is not int
            or expires_at <= self._now()
            or type(uri) is not str
            or not uri
        ):
            return None
        return {
            "verification_uri": uri,
            "expires_at": expires_at,
            "status": status,
        }

    async def _list_business_tools(self) -> types.CallToolResult:
        state = (await self._connection_status())["status"]
        if state in {"unpaired", "pending", "consent_required"}:
            return _error(
                "WALLET_AUTHORIZATION_REQUIRED",
                status="authorization_required",
                next_action="connect_clink_wallet",
            )
        if state == "revoked":
            return _error(
                "DEVICE_REVOKED",
                status="revoked",
                next_action="do_not_reconnect",
            )
        if state != "active":
            return _error(
                "CLINK_UNAVAILABLE",
                status="unavailable",
                next_action="get_clink_connection_status",
            )
        try:
            discovered = await self.client.list_tools()
            if not isinstance(discovered, list):
                raise ValueError
            tools = []
            for item in discovered:
                if not isinstance(item, types.Tool):
                    raise ValueError
                if item.name in ONBOARDING_TOOL_NAMES:
                    continue
                tools.append(
                    {
                        "name": item.name,
                        "description": item.description or "",
                        "inputSchema": copy.deepcopy(item.inputSchema),
                    }
                )
        except OpcClientError as exc:
            if getattr(exc, "status_code", None) in {400, 401, 403}:
                authoritative = await self._connection_status()
                if authoritative["status"] == "revoked":
                    return _error(
                        "DEVICE_REVOKED",
                        status="revoked",
                        next_action="do_not_reconnect",
                    )
                return _error(
                    "WALLET_AUTHORIZATION_REQUIRED",
                    status="authorization_required",
                    next_action="connect_clink_wallet",
                )
            return _error(
                "CLINK_UNAVAILABLE",
                status="unavailable",
                next_action="get_clink_connection_status",
            )
        except Exception:
            return _error(
                "CLINK_UNAVAILABLE",
                status="unavailable",
                next_action="get_clink_connection_status",
            )
        return _result({"tools": tools})

    async def _call_business_tool(self, envelope: dict[str, Any]) -> types.CallToolResult:
        if set(envelope) != {"name", "arguments"}:
            return _error("INVALID_ARGUMENTS", status="rejected")
        business_name = envelope["name"]
        business_arguments = envelope["arguments"]
        if (
            type(business_name) is not str
            or not 1 <= len(business_name) <= 128
            or any(ord(character) <= 32 for character in business_name)
            or business_name in ONBOARDING_TOOL_NAMES
            or type(business_arguments) is not dict
        ):
            return _error("INVALID_ARGUMENTS", status="rejected")
        try:
            # Exactly one business dispatch.  Never discover, retry, or replay here.
            response = await self.client.call_tool(
                business_name,
                copy.deepcopy(business_arguments),
            )
        except OpcClientError as exc:
            status_code = getattr(exc, "status_code", None)
            if status_code in {400, 401, 403}:
                state = (await self._connection_status())["status"]
                if state == "revoked":
                    return _error(
                        "DEVICE_REVOKED",
                        status="revoked",
                        next_action="do_not_reconnect",
                    )
                return _error(
                    "WALLET_AUTHORIZATION_REQUIRED",
                    status="authorization_required",
                    next_action="connect_clink_wallet",
                )
            return _error(
                "CLINK_UNAVAILABLE",
                status="unavailable",
                next_action="get_clink_connection_status",
            )
        except Exception:
            return _unknown()
        if not isinstance(response, types.CallToolResult):
            return _unknown()
        if response.isError:
            return _project_remote_rejection(response) or _unknown()
        return response


__all__ = ["ONBOARDING_TOOL_NAMES", "OpcOnboardingBridge", "open_wallet_browser"]
