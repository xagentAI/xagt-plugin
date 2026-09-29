"""Default-deny Agent tools over existing business implementations.

The stable principal is supplied by the HTTP/MCP admission boundary, never by
tool arguments. v0.1 deliberately has one logical Agent per registered user.
"""

import asyncio
import copy
import hashlib
import json
from decimal import Decimal
from typing import Any

from jsonschema import Draft202012Validator, ValidationError
from mcp import types

from .adapters.http import DownstreamError
from .agent_access_views import owned_account, owned_payment
from .mcp_proxy import DownstreamMcpFailure
from .projections import build_activity_summary, build_balance_summary
from .transfers import (CREATE_SCHEMA, GET_SCHEMA, TRANSFER_NAMES, normalize_create, normalize_query,
                        operation_id, project_transfer)


READ_TOOLS = frozenset({
    "get_clink_account_readiness", "get_clink_balances", "get_clink_activity",
    "search_clink_services", "get_clink_service_details", "compare_clink_service_quotes",
    "get_clink_purchase", "search_prediction_markets", "score_prediction_market_opportunities",
    "build_prediction_market_context", "get_prediction_market_order_preview",
    "get_prediction_market_execution", "get_agentonomy_payment",
    "get_clink_transfer",
})
PAYMENT_TOOLS = frozenset({
    "create_clink_purchase_preview", "execute_clink_purchase",
    "fund_polymarket_from_spending_authorization",
    "create_clink_transfer",
})
_IDENTITY_FIELDS = frozenset({
    "user_id", "agent_id", "tenant_id", "runtime_id", "opc_installation_id",
    "spending_authorization_id", "transaction_hash", "payment_response",
})
_PAYMENT_QUERY_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "kind": {"type": "string", "enum": ["marketplace", "polymarket_funding"]},
        "operation_id": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,256}$"},
    }, "required": ["kind", "operation_id"],
}
_FUND_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "request_id": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"},
        "amount_usdc": {"type": "string", "pattern": r"^[0-9]{1,12}(\.[0-9]{1,6})?$"},
        "user_confirmed": {"type": "boolean", "const": True},
    }, "required": ["request_id", "amount_usdc", "user_confirmed"],
}


def _result(value: dict) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(value, ensure_ascii=False))],
        structuredContent=value,
    )


def _error(code: str, *, uncertain: bool = False) -> types.CallToolResult:
    result = _result({"error": code, "status": "unknown" if uncertain else "rejected", "retry_safe": False})
    result.isError = True
    return result


class AgentScopedMcpProxy:
    def __init__(self, proxy: Any, context: Any) -> None:
        self.proxy = proxy
        self.context = context

    async def list_tools(self, *, principal: Any = None) -> list[types.Tool]:
        if principal is None or principal.scope not in {"read", "payments"}:
            return []
        allowed = READ_TOOLS | (PAYMENT_TOOLS if principal.scope == "payments" else frozenset())
        tools = []
        try:
            discovered = await self.proxy.list_tools()
        except Exception:
            # Private service discovery failures must not remove the native
            # read-only recovery surface, or expose its credential-bearing URLs.
            discovered = [item.definition for item in getattr(self.proxy, "native_tools", {}).values()]
        for tool in discovered:
            if tool.name not in allowed or tool.name in TRANSFER_NAMES:
                continue
            schema = copy.deepcopy(tool.inputSchema)
            properties = schema.get("properties", {})
            hidden = set(_IDENTITY_FIELDS)
            if tool.name == "execute_clink_purchase":
                hidden.update(set(properties).difference({"preview_id", "user_confirmed"}))
            schema["properties"] = {k: v for k, v in properties.items() if k not in hidden}
            schema["required"] = [k for k in schema.get("required", []) if k not in hidden]
            schema["additionalProperties"] = False
            if tool.name == "fund_polymarket_from_spending_authorization":
                schema = copy.deepcopy(_FUND_SCHEMA)
                description = (
                    "Fund the current user's bound Polymarket account within the Core mandate. "
                    "Use one stable request_id for the user's intent, including after sandbox restart. "
                    "Never change request_id or send a second payment when outcome is unknown; read "
                    "get_agentonomy_payment using the returned operation_id. User setup happens in the wallet app."
                )
            else:
                description = tool.description
            tools.append(tool.model_copy(update={"inputSchema": schema, "description": description}))
        tools.append(types.Tool(
            name="get_agentonomy_payment",
            description=("Read an owned payment and its independently verified Core settlement. "
                         "A submitted transaction is not settled. Never recharge after delivery failure."),
            inputSchema=copy.deepcopy(_PAYMENT_QUERY_SCHEMA),
        ))
        tools.append(types.Tool(
            name="get_clink_transfer",
            description=("Query your original USDC transfer using exactly one of transfer_id or request_id. "
                         "After timeout or loss of the transfer_id, use the original request_id. This cannot initiate payment. "
                         "Only succeeded means independently verified Core settlement; pending is not failure."),
            inputSchema=copy.deepcopy(GET_SCHEMA),
        ))
        if principal.scope == "payments":
            tools.append(types.Tool(
                name="create_clink_transfer",
                description=("Transfer USDC within your explicitly signed transfers Mandate and shared budget. "
                             "Use one stable request_id per intent. On timeout/unknown, query get_clink_transfer "
                             "with the original request_id (or returned transfer_id); never create a replacement payment. "
                             "User wallet authorization occurs in Core; never supply private keys."),
                inputSchema=copy.deepcopy(CREATE_SCHEMA),
            ))
        return tools

    async def call_tool(self, name: str, arguments: dict, *, principal: Any = None) -> types.CallToolResult:
        if principal is None:
            return _error("unauthorized")
        definitions = {tool.name: tool for tool in await self.list_tools(principal=principal)}
        if name not in definitions:
            return _error("tool_not_allowed")
        try:
            Draft202012Validator(definitions[name].inputSchema).validate(arguments)
            if name in TRANSFER_NAMES:
                return await self._call_transfer(name, arguments, principal)
            args = copy.deepcopy(arguments)
            user = principal.user_id
            opc_installation_id = getattr(principal, "opc_installation_id", None)
            if opc_installation_id is not None and name in PAYMENT_TOOLS:
                args["opc_installation_id"] = opc_installation_id
            if name == "get_clink_account_readiness":
                return _result(await asyncio.to_thread(owned_account, self.context, user))
            if name == "get_clink_balances":
                return _result(await asyncio.to_thread(
                    build_balance_summary, self.context.core, self.context.prediction_markets, user, strict_owner=True,
                ))
            if name == "get_clink_activity":
                return _result(await asyncio.to_thread(build_activity_summary, self.context.core, user, args.get("limit", 12)))
            if name == "get_agentonomy_payment":
                return _result(await asyncio.to_thread(owned_payment, self.context, user, args["kind"], args["operation_id"]))
            if name == "get_clink_purchase":
                return _result(await asyncio.to_thread(self.context.marketplace.get_purchase, user_id=user, purchase_id=args["purchase_id"]))
            if name == "get_prediction_market_order_preview":
                return _result(await asyncio.to_thread(self.context.prediction_markets.get_order_preview, user_id=user, preview_id=args["preview_id"]))
            if name == "get_prediction_market_execution":
                return _result(await asyncio.to_thread(self.context.prediction_markets.get_execution, user_id=user, execution_id=args["execution_id"]))
            if name == "execute_clink_purchase":
                preview = await asyncio.to_thread(self.context.marketplace.get_purchase_preview, user_id=user, preview_id=args["preview_id"])
                if preview.get("execution_mode") not in {"clink_allowance", "clink_payer_proxy"}:
                    return _result({"status": "action_required", "action": "wallet_signature_required", "preview_id": args["preview_id"]})
            if name in {"execute_clink_purchase", "fund_polymarket_from_spending_authorization"}:
                hosted = await asyncio.to_thread(self.context.core.hosted_wallet_readiness, user)
                if not isinstance(hosted, dict) or hosted.get("user_id") != user:
                    return _error("invalid_account_response")
                if hosted.get("credential_routing") != "per_wallet" or hosted.get("ready") is not True:
                    return _result({"status": "action_required", "settled": False, "operation_id": None,
                                    "reason_code": hosted.get("reason_code"),
                                    "next_action": "open_account_in_wallet_app" if hosted.get("reason_code") == "WALLET_NOT_READY" else "contact_service_operator"})
            if name == "create_clink_purchase_preview":
                args["user_id"] = user
            if name == "fund_polymarket_from_spending_authorization":
                amount = Decimal(args["amount_usdc"])
                if amount <= 0:
                    return _error("invalid_amount")
                # A restart changes the runtime token, NOT the business idempotency key.
                confirmation_id = "cpm_" + hashlib.sha256((user + "\0" + args["request_id"]).encode()).hexdigest()[:48]
                args = {"user_id": user, "amount_usdc": format(amount, ".6f"),
                        "confirmation_id": confirmation_id, "user_confirmed": True,
                        "resource": "clink://polymarket/funding"}
                if opc_installation_id is not None:
                    args["opc_installation_id"] = opc_installation_id
            response = await self.proxy.call_tool(name, args)
            if isinstance(response, dict):
                response = _result(response)
            if response.isError:
                return _error("business_request_failed", uncertain=name in PAYMENT_TOOLS)
            value = response.structuredContent
            if not isinstance(value, dict):
                text_blocks = [item.text for item in response.content if isinstance(item, types.TextContent)]
                if len(text_blocks) == 1:
                    value = json.loads(text_blocks[0])
            if name == "create_clink_purchase_preview":
                if not isinstance(value, dict) or not isinstance(value.get("preview_id"), str):
                    return _error("invalid_business_response")
                preview = await asyncio.to_thread(self.context.marketplace.get_purchase_preview, user_id=user, preview_id=value["preview_id"])
                return _result(preview)
            if name == "execute_clink_purchase":
                purchase = value.get("purchase") if isinstance(value, dict) else None
                expected_id = "purchase_" + args["preview_id"].removeprefix("preview_")
                if (not isinstance(purchase, dict) or purchase.get("user_id") != user
                        or purchase.get("preview_id") != args["preview_id"]
                        or purchase.get("purchase_id") != expected_id):
                    return _error("invalid_business_response", uncertain=True)
                # Do not forward delivery data from the execution response. Read
                # the durable, ownership-checked purchase after this one attempt.
                owned = await asyncio.to_thread(self.context.marketplace.get_purchase, user_id=user, purchase_id=expected_id)
                if owned.get("preview_id") != args["preview_id"]:
                    return _error("invalid_business_response", uncertain=True)
                owned = dict(owned)
                service_result = owned.pop("service_result", None)
                return _result({"purchase": owned, "service_result": service_result})
            if name == "fund_polymarket_from_spending_authorization" and isinstance(value, dict):
                operation_id = value.get("operation_id")
                if operation_id:
                    projected = await asyncio.to_thread(owned_payment, self.context, user, "polymarket_funding", operation_id)
                else:
                    projected = {"status": value.get("status", "unknown"), "operation_id": None,
                                 "settled": False, "receipt_id": None, "tx_hash": None,
                                 "next_action": "open_account_in_wallet_app" if value.get("status") == "action_required" else "inspect_existing_request"}
                projected["request_id"] = arguments["request_id"]
                return _result(projected)
            return response
        except ValidationError:
            return _error("invalid_tool_arguments")
        except DownstreamError as exc:
            return _error("owned_object_not_found" if exc.status_code in {403, 404} else "service_unavailable", uncertain=name in PAYMENT_TOOLS)
        except (ValueError, KeyError, TypeError):
            return _error("invalid_business_response", uncertain=name in PAYMENT_TOOLS)
        except DownstreamMcpFailure:
            return _error("service_unavailable", uncertain=name in PAYMENT_TOOLS)
        except Exception:
            # Once a business call may have been dispatched, fail closed without
            # returning private service tracebacks or suggesting a new charge.
            return _error("service_unavailable", uncertain=name in PAYMENT_TOOLS)

    async def _call_transfer(self, name: str, arguments: dict, principal: Any) -> types.CallToolResult:
        create = name == "create_clink_transfer"
        try:
            args = normalize_create(arguments) if create else {"transfer_id": normalize_query(
                arguments, user_id=principal.user_id, agent_id=principal.agent_id)}
        except (ValueError, KeyError, TypeError):
            return _error("invalid_tool_arguments")
        owner = {"user_id": principal.user_id, "agent_id": principal.agent_id,
                 "opc_installation_id": getattr(principal, "opc_installation_id", None)}
        expected_id = operation_id(owner["user_id"], owner["agent_id"], args["request_id"]) if create else args["transfer_id"]
        dispatched = False
        try:
            if create:
                hosted = await asyncio.to_thread(self.context.core.hosted_wallet_readiness, owner["user_id"])
                if not isinstance(hosted, dict) or hosted.get("user_id") != owner["user_id"]:
                    return _error("invalid_account_response")
                if hosted.get("credential_routing") != "per_wallet" or hosted.get("ready") is not True:
                    # Do not echo arbitrary upstream data from a preflight failure.
                    wallet_missing = hosted.get("reason_code") == "WALLET_NOT_READY"
                    reason = "WALLET_NOT_READY" if wallet_missing else (
                        "HOSTED_ENROLLMENT_REQUIRED" if hosted.get("reason_code") == "HOSTED_ENROLLMENT_REQUIRED"
                        else "HOSTED_NOT_READY")
                    return _result({"status": "action_required", "settled": False,
                        "reason_code": reason, "next_action": "open_account_in_wallet_app" if wallet_missing else "contact_service_operator"})
                dispatched = True
                value = await asyncio.to_thread(self.context.core.create_direct_transfer, **owner, **args)
            else:
                value = await asyncio.to_thread(self.context.core.get_direct_transfer, **owner, **args)
            projected = project_transfer(value, expected_id=expected_id, expected_request=args if create else None)
            if not create and "request_id" in arguments and projected["request_id"] != arguments["request_id"]:
                raise ValueError("query request mismatch")
            return _result(projected)
        except DownstreamError as exc:
            code = "owned_object_not_found" if not dispatched and exc.status_code in {403, 404} else "service_unavailable"
        except (ValueError, KeyError, TypeError):
            code = "invalid_business_response"
        except Exception:
            code = "service_unavailable"
        result = _error(code, uncertain=dispatched)
        if dispatched:
            value = {**result.structuredContent, "transfer_id": expected_id,
                     "request_id": args["request_id"], "next_action": "query_transfer"}
            result = _result(value)
            result.isError = True
        return result
