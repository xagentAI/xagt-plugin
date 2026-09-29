"""Strict public contract for owner-bound Core USDC transfers, not raw EVM calls."""

import hashlib
import json
import re
from decimal import Decimal


TRANSFER_NAMES = frozenset({"create_clink_transfer", "get_clink_transfer"})
_REQUEST_ID = r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,95}"
_NETWORK = r"eip155:[1-9][0-9]{0,19}"
_ADDRESS = r"0x[0-9a-fA-F]{40}"
_AMOUNT = r"[0-9]{1,14}(?:\.[0-9]{1,6})?"
_TRANSFER_ID = r"transfer_[0-9a-f]{48}"


def _string(pattern):
    return {"type": "string", "pattern": "^" + pattern + "$"}


CREATE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"request_id": _string(_REQUEST_ID), "to_address": _string(_ADDRESS),
                   "network": _string(_NETWORK), "amount_usdc": _string(_AMOUNT)},
    "required": ["request_id", "to_address", "network", "amount_usdc"],
}
GET_SCHEMA = {"type": "object", "additionalProperties": False,
              "properties": {"transfer_id": _string(_TRANSFER_ID), "request_id": _string(_REQUEST_ID)},
              "oneOf": [{"required": ["transfer_id"]}, {"required": ["request_id"]}]}


def _match(value, pattern):
    if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
        raise ValueError("invalid transfer field")
    return value


def transfer_id(value):
    return _match(value, _TRANSFER_ID)


def _address(value):
    value = _match(value, _ADDRESS).lower()
    if int(value[2:], 16) == 0:
        raise ValueError("zero address")
    return value


def _amount(value):
    amount = Decimal(_match(value, _AMOUNT))
    if amount <= 0:
        raise ValueError("nonpositive transfer")
    return format(amount, "f").rstrip("0").rstrip(".") if "." in format(amount, "f") else format(amount, "f")


def normalize_create(arguments):
    if not isinstance(arguments, dict) or set(arguments) != set(CREATE_SCHEMA["required"]):
        raise ValueError("invalid transfer arguments")
    return {"request_id": _match(arguments["request_id"], _REQUEST_ID),
            "to_address": _address(arguments["to_address"]),
            "network": _match(arguments["network"], _NETWORK),
            "amount_usdc": _amount(arguments["amount_usdc"])}


def operation_id(user_id, agent_id, request_id):
    data = json.dumps([user_id, agent_id, request_id], sort_keys=True, separators=(",", ":"))
    return "transfer_" + hashlib.sha256(data.encode()).hexdigest()[:48]


def normalize_query(arguments, *, user_id, agent_id):
    if not isinstance(arguments, dict):
        raise ValueError("invalid query")
    if set(arguments) == {"transfer_id"}:
        return transfer_id(arguments["transfer_id"])
    if set(arguments) == {"request_id"}:
        request_id = _match(arguments["request_id"], _REQUEST_ID)
        return operation_id(user_id, agent_id, request_id)
    raise ValueError("provide exactly one query identifier")


_FIELDS = ("transfer_id", "request_id", "status", "network", "asset", "token_address",
           "to_address", "amount_usdc", "amount_atomic", "reservation_id", "tx_hash",
           "receipt_id", "reason_code", "next_action")
_STATUSES = {"preparing", "reserved", "pending", "succeeded", "failed", "review_required", "attention_required"}


def project_transfer(value, *, expected_id, expected_request=None):
    """Discard extra fields, reject missing/mismatched evidence; never echo secrets."""
    if not isinstance(value, dict) or not set(_FIELDS).issubset(value):
        raise ValueError("invalid transfer response")
    result = {key: value[key] for key in _FIELDS}
    if transfer_id(result["transfer_id"]) != expected_id:
        raise ValueError("transfer identity mismatch")
    result["request_id"] = _match(result["request_id"], _REQUEST_ID)
    result["network"] = _match(result["network"], _NETWORK)
    result["to_address"] = _address(result["to_address"])
    result["token_address"] = _address(result["token_address"])
    result["amount_usdc"] = _amount(result["amount_usdc"])
    atomic = _match(result["amount_atomic"], r"[1-9][0-9]{0,19}")
    if int(atomic) != int(Decimal(result["amount_usdc"]) * 1_000_000):
        raise ValueError("transfer amount mismatch")
    if result["asset"] != "USDC" or result["status"] not in _STATUSES:
        raise ValueError("invalid transfer status")
    if result["next_action"] not in {"query_transfer", "retry_same_request", "contact_operator", "none"}:
        raise ValueError("invalid transfer next action")
    for key in ("reservation_id", "receipt_id"):
        if result[key] is not None:
            _match(result[key], r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}")
    if result["tx_hash"] is not None:
        _match(result["tx_hash"], r"0x[0-9a-fA-F]{64}")
    if result["reason_code"] is not None:
        _match(result["reason_code"], r"[A-Z][A-Z0-9_]{1,79}")
    if result["status"] == "succeeded" and not all(result[key] for key in ("reservation_id", "tx_hash", "receipt_id")):
        raise ValueError("missing settled evidence")
    if expected_request is not None and any(result[key] != expected_request[key] for key in CREATE_SCHEMA["required"]):
        raise ValueError("transfer request mismatch")
    return result
