from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_UP
from typing import Any, Literal

from eth_abi import encode
from eth_utils import keccak


CHAIN_ID = 137
DOMAIN_NAME = "Polymarket CTF Exchange"
DOMAIN_VERSION = "2"
STANDARD_EXCHANGE = "0xE111180000d2663C0091e4f400237545B87B996B"
NEG_RISK_EXCHANGE = "0xe2222d279d744050d28e00520010520000310F59"
PUSD_COLLATERAL = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"
ZERO_BYTES32 = "0x" + "00" * 32
MAX_SAFE_SALT = 9_007_199_254_740_991
UINT256_MAX = (1 << 256) - 1

ORDER_FIELDS = (
    ("salt", "uint256"),
    ("maker", "address"),
    ("signer", "address"),
    ("tokenId", "uint256"),
    ("makerAmount", "uint256"),
    ("takerAmount", "uint256"),
    ("side", "uint8"),
    ("signatureType", "uint8"),
    ("timestamp", "uint256"),
    ("metadata", "bytes32"),
    ("builder", "bytes32"),
)
ORDER_TYPE_STRING = (
    "Order(uint256 salt,address maker,address signer,uint256 tokenId,"
    "uint256 makerAmount,uint256 takerAmount,uint8 side,uint8 signatureType,"
    "uint256 timestamp,bytes32 metadata,bytes32 builder)"
)
TYPED_DATA_SIGN_FIELDS = (
    ("contents", "Order"),
    ("name", "string"),
    ("version", "string"),
    ("chainId", "uint256"),
    ("verifyingContract", "address"),
    ("salt", "bytes32"),
)

_TICK_PRECISION = {
    "0.1": (1, 2, 3),
    "0.01": (2, 2, 4),
    "0.005": (3, 2, 5),
    "0.0025": (4, 2, 6),
    "0.001": (3, 2, 5),
    "0.0001": (4, 2, 6),
}
_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
_HEX_32 = re.compile(r"^0x[0-9a-fA-F]{64}$")
_STANDARD_SIGNATURE = re.compile(r"^0x[0-9a-fA-F]{130}$")
_UINT = re.compile(r"^(?:0|[1-9][0-9]*)$")


class OrderProjectionError(ValueError):
    pass


def _bytes32(value: str, *, field: str) -> bytes:
    if not isinstance(value, str) or not _HEX_32.fullmatch(value):
        raise OrderProjectionError(f"{field} is invalid")
    return bytes.fromhex(value[2:])


def _eip712_domain_separator(domain: dict[str, Any]) -> bytes:
    expected = {"name", "version", "chainId", "verifyingContract"}
    if not isinstance(domain, dict) or set(domain) != expected:
        raise OrderProjectionError("typed data domain is invalid")
    if (
        domain["name"] != DOMAIN_NAME
        or domain["version"] != DOMAIN_VERSION
        or domain["chainId"] != CHAIN_ID
        or not _ADDRESS.fullmatch(str(domain["verifyingContract"]))
    ):
        raise OrderProjectionError("typed data domain is invalid")
    domain_type = (
        "EIP712Domain(string name,string version,uint256 chainId,address "
        "verifyingContract)"
    )
    return keccak(
        encode(
            ["bytes32", "bytes32", "bytes32", "uint256", "address"],
            [
                keccak(text=domain_type),
                keccak(text=domain["name"]),
                keccak(text=domain["version"]),
                domain["chainId"],
                domain["verifyingContract"],
            ],
        )
    )


def _order_contents_hash(message: dict[str, Any]) -> bytes:
    if not isinstance(message, dict) or set(message) != {name for name, _ in ORDER_FIELDS}:
        raise OrderProjectionError("typed data order contents are invalid")
    abi_types = ["bytes32", *(field_type for _, field_type in ORDER_FIELDS)]
    abi_values: list[Any] = [keccak(text=ORDER_TYPE_STRING)]
    for name, field_type in ORDER_FIELDS:
        value = message[name]
        if field_type.startswith("uint"):
            try:
                value = int(value)
            except (TypeError, ValueError):
                raise OrderProjectionError(
                    "typed data order contents are invalid"
                ) from None
        elif field_type == "bytes32":
            value = _bytes32(value, field=name)
        elif field_type == "address" and not _ADDRESS.fullmatch(str(value)):
            raise OrderProjectionError("typed data order contents are invalid")
        abi_values.append(value)
    try:
        return keccak(encode(abi_types, abi_values))
    except (TypeError, ValueError):
        raise OrderProjectionError("typed data order contents are invalid") from None


def wrap_deposit_wallet_signature(
    *,
    raw_signature: str,
    typed_data: dict[str, Any],
    signature_type: int = 3,
) -> str:
    """Apply Polymarket's deterministic ERC-7739 Deposit Wallet envelope."""

    if signature_type != 3:
        if not isinstance(raw_signature, str) or not _STANDARD_SIGNATURE.fullmatch(
            raw_signature
        ):
            raise OrderProjectionError("signature is invalid")
        return raw_signature
    if not isinstance(raw_signature, str) or not _STANDARD_SIGNATURE.fullmatch(
        raw_signature
    ):
        raise OrderProjectionError("signature is invalid")
    if not isinstance(typed_data, dict) or set(typed_data) != {
        "domain",
        "types",
        "primaryType",
        "message",
    }:
        raise OrderProjectionError("typed data is invalid")
    types = typed_data.get("types")
    message = typed_data.get("message")
    if (
        typed_data.get("primaryType") != "TypedDataSign"
        or not isinstance(types, dict)
        or set(types) != {"Order", "TypedDataSign"}
        or not isinstance(message, dict)
        or set(message)
        != {"contents", "name", "version", "chainId", "verifyingContract", "salt"}
    ):
        raise OrderProjectionError("typed data is invalid")
    order_fields = types.get("Order")
    outer_fields = types.get("TypedDataSign")
    if (
        not isinstance(order_fields, list)
        or not isinstance(outer_fields, list)
        or any(not isinstance(field, dict) for field in [*order_fields, *outer_fields])
        or tuple((field.get("name"), field.get("type")) for field in order_fields)
        != ORDER_FIELDS
        or tuple((field.get("name"), field.get("type")) for field in outer_fields)
        != TYPED_DATA_SIGN_FIELDS
    ):
        raise OrderProjectionError("typed data order type is invalid")
    contents = message.get("contents")
    if (
        not isinstance(contents, dict)
        or message.get("name") != "DepositWallet"
        or message.get("version") != "1"
        or message.get("chainId") != CHAIN_ID
        or message.get("salt") != ZERO_BYTES32
        or not _ADDRESS.fullmatch(str(message.get("verifyingContract")))
        or str(message["verifyingContract"]).lower()
        != str(contents.get("signer") or "").lower()
        or str(contents.get("maker") or "").lower()
        != str(contents.get("signer") or "").lower()
    ):
        raise OrderProjectionError("deposit wallet typed data is invalid")
    domain_separator = _eip712_domain_separator(typed_data.get("domain"))
    contents_hash = _order_contents_hash(contents)
    order_type_bytes = ORDER_TYPE_STRING.encode("utf-8")
    return (
        raw_signature
        + domain_separator.hex()
        + contents_hash.hex()
        + order_type_bytes.hex()
        + len(order_type_bytes).to_bytes(2, "big").hex()
    )


@dataclass(frozen=True, slots=True)
class OrderProjection:
    canonical_json: str
    projection_sha256: str

    @property
    def payload(self) -> dict[str, Any]:
        return json.loads(self.canonical_json)


def _canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _decimal(value: str, *, field: str) -> Decimal:
    if not isinstance(value, str) or not value or len(value) > 80:
        raise OrderProjectionError(f"{field} is invalid")
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise OrderProjectionError(f"{field} is invalid") from None
    if not result.is_finite() or result <= 0:
        raise OrderProjectionError(f"{field} is invalid")
    return result


def _uint(value: str, *, field: str, maximum: int = UINT256_MAX) -> str:
    if not isinstance(value, str) or not _UINT.fullmatch(value) or int(value) > maximum:
        raise OrderProjectionError(f"{field} is invalid")
    return value


def _address(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not _ADDRESS.fullmatch(value):
        raise OrderProjectionError(f"{field} is invalid")
    return value


def _wallet_identity(
    mode: str, maker_wallet: str, account_signer: str
) -> tuple[str, str, int]:
    maker = _address(maker_wallet, field="maker_wallet")
    signer = _address(account_signer, field="account_signer")
    if mode == "deposit_wallet":
        return maker, maker, 3
    if mode == "eoa":
        if maker.lower() != signer.lower():
            raise OrderProjectionError("EOA maker and signer must match")
        return maker, maker, 0
    if mode == "proxy":
        if maker.lower() == signer.lower():
            raise OrderProjectionError("proxy maker and signer must differ")
        return maker, signer, 1
    if mode == "safe":
        if maker.lower() == signer.lower():
            raise OrderProjectionError("Safe maker and signer must differ")
        return maker, signer, 2
    raise OrderProjectionError("wallet_mode is invalid")


def _atomic_amounts(
    *, side: str, price: str, size: str, tick_size: str, min_order_size: str
) -> tuple[str, str]:
    if tick_size not in _TICK_PRECISION:
        raise OrderProjectionError("tick_size is invalid")
    price_decimals, size_decimals, amount_decimals = _TICK_PRECISION[tick_size]
    price_value = _decimal(price, field="price")
    size_value = _decimal(size, field="size")
    minimum = _decimal(min_order_size, field="min_order_size")
    tick = Decimal(tick_size)
    if price_value >= 1 or price_value % tick != 0:
        raise OrderProjectionError("price does not conform to tick_size")
    if price_value.as_tuple().exponent < -price_decimals:
        raise OrderProjectionError("price precision is invalid")
    rounded_size = size_value.quantize(
        Decimal(1).scaleb(-size_decimals), rounding=ROUND_DOWN
    )
    if rounded_size < minimum:
        raise OrderProjectionError("size is below min_order_size")
    product = price_value * rounded_size
    intermediate = product.quantize(
        Decimal(1).scaleb(-(amount_decimals + 4)), rounding=ROUND_UP
    )
    usd_amount = intermediate.quantize(
        Decimal(1).scaleb(-amount_decimals), rounding=ROUND_DOWN
    )
    shares_atomic = int(rounded_size * 1_000_000)
    usd_atomic = int(usd_amount * 1_000_000)
    if shares_atomic <= 0 or usd_atomic <= 0:
        raise OrderProjectionError("order amounts are invalid")
    if side == "BUY":
        return str(usd_atomic), str(shares_atomic)
    if side == "SELL":
        return str(shares_atomic), str(usd_atomic)
    raise OrderProjectionError("side is invalid")


def build_order_projection(
    *,
    wallet_mode: Literal["deposit_wallet", "proxy", "safe", "eoa"] | str,
    maker_wallet: str,
    account_signer: str,
    token_id: str,
    side: Literal["BUY", "SELL"] | str,
    price: str,
    size: str,
    tick_size: str,
    min_order_size: str,
    neg_risk: bool,
    salt: str,
    timestamp_ms: str,
    order_type: Literal["GTC", "GTD"] | str,
    expiration: str,
    metadata: str = ZERO_BYTES32,
    builder: str = ZERO_BYTES32,
    provenance: dict[str, str] | None = None,
) -> OrderProjection:
    maker, signer, signature_type = _wallet_identity(
        wallet_mode, maker_wallet, account_signer
    )
    token = _uint(token_id, field="token_id")
    salt_value = _uint(salt, field="salt", maximum=MAX_SAFE_SALT)
    timestamp = _uint(timestamp_ms, field="timestamp_ms")
    if timestamp == "0":
        raise OrderProjectionError("timestamp_ms is invalid")
    if not isinstance(neg_risk, bool):
        raise OrderProjectionError("neg_risk is invalid")
    if not _HEX_32.fullmatch(metadata) or not _HEX_32.fullmatch(builder):
        raise OrderProjectionError("metadata or builder is invalid")
    maker_amount, taker_amount = _atomic_amounts(
        side=side,
        price=price,
        size=size,
        tick_size=tick_size,
        min_order_size=min_order_size,
    )
    if order_type == "GTC":
        if expiration != "0":
            raise OrderProjectionError("GTC expiration must be zero")
    elif order_type == "GTD":
        _uint(expiration, field="expiration")
        if expiration == "0":
            raise OrderProjectionError("GTD expiration must be positive")
    else:
        raise OrderProjectionError("order_type is invalid")
    exchange = NEG_RISK_EXCHANGE if neg_risk else STANDARD_EXCHANGE
    signed_order = {
        "salt": salt_value,
        "maker": maker,
        "signer": signer,
        "tokenId": token,
        "makerAmount": maker_amount,
        "takerAmount": taker_amount,
        "side": 0 if side == "BUY" else 1,
        "signatureType": signature_type,
        "timestamp": timestamp,
        "metadata": metadata,
        "builder": builder,
    }
    types: dict[str, list[dict[str, str]]] = {
        "Order": [{"name": name, "type": field_type} for name, field_type in ORDER_FIELDS]
    }
    if wallet_mode == "deposit_wallet":
        types["TypedDataSign"] = [
            {"name": name, "type": field_type}
            for name, field_type in TYPED_DATA_SIGN_FIELDS
        ]
        primary_type = "TypedDataSign"
        message: dict[str, Any] = {
            "contents": signed_order,
            "name": "DepositWallet",
            "version": "1",
            "chainId": CHAIN_ID,
            "verifyingContract": maker,
            "salt": ZERO_BYTES32,
        }
    else:
        primary_type = "Order"
        message = signed_order
    wire_order = {
        **signed_order,
        "salt": int(salt_value),
        "side": side,
        "expiration": expiration,
    }
    payload = {
        "typed_data": {
            "domain": {
                "name": DOMAIN_NAME,
                "version": DOMAIN_VERSION,
                "chainId": CHAIN_ID,
                "verifyingContract": exchange,
            },
            "types": types,
            "primaryType": primary_type,
            "message": message,
        },
        "order": wire_order,
        "orderType": order_type,
        "exchange": exchange,
        "collateral": PUSD_COLLATERAL,
        "tickSize": tick_size,
        "minOrderSize": min_order_size,
        "negRisk": neg_risk,
    }
    if provenance is not None:
        allowed_provenance = {
            "preview_id",
            "market_id",
            "core_action_id",
            "core_policy_decision_id",
            "funding_operation_id",
        }
        if set(provenance) != allowed_provenance or any(
            not isinstance(value, str) or not value or len(value) > 128
            for value in provenance.values()
        ):
            raise OrderProjectionError("order provenance is invalid")
        payload["provenance"] = dict(provenance)
    canonical = _canonical_json(payload)
    return OrderProjection(
        canonical_json=canonical,
        projection_sha256=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    )


def validate_signed_order(
    projection: OrderProjection, submitted: dict[str, Any]
) -> dict[str, Any]:
    if not isinstance(submitted, dict) or set(submitted) != {"order", "orderType"}:
        raise OrderProjectionError("signed order envelope is invalid")
    order = submitted.get("order")
    if not isinstance(order, dict):
        raise OrderProjectionError("signed order is invalid")
    expected_payload = projection.payload
    expected_order = expected_payload["order"]
    if set(order) != {*expected_order, "signature"}:
        raise OrderProjectionError("signed order does not match projection")
    signature = order.get("signature")
    deposit_signature_hex_length = 2 * (
        65 + 32 + 32 + len(ORDER_TYPE_STRING.encode("utf-8")) + 2
    )
    valid_signature = bool(
        isinstance(signature, str)
        and (
            (
                expected_order["signatureType"] == 3
                and re.fullmatch(
                    rf"0x[0-9a-fA-F]{{{deposit_signature_hex_length}}}", signature
                )
            )
            or (
                expected_order["signatureType"] != 3
                and _STANDARD_SIGNATURE.fullmatch(signature)
            )
        )
    )
    if not valid_signature:
        raise OrderProjectionError("signed order signature is invalid")
    unsigned = {key: value for key, value in order.items() if key != "signature"}
    if (
        unsigned != expected_order
        or submitted.get("orderType") != expected_payload["orderType"]
    ):
        raise OrderProjectionError("signed order does not match projection")
    return json.loads(json.dumps(submitted))
