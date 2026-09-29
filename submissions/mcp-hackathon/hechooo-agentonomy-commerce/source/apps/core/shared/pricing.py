import os
from decimal import Decimal, InvalidOperation


DEFAULT_PRODUCT_PRICE = Decimal("0.00001")


def get_product_price_decimal() -> Decimal:
    raw_value = os.getenv("PRODUCT_PRICE", format(DEFAULT_PRODUCT_PRICE, "f")).strip()
    try:
        parsed = Decimal(raw_value)
    except InvalidOperation:
        return DEFAULT_PRODUCT_PRICE
    if parsed <= 0:
        return DEFAULT_PRODUCT_PRICE
    return parsed


def get_product_price_str() -> str:
    return format(get_product_price_decimal(), "f")


def get_product_price_float() -> float:
    return float(get_product_price_decimal())


def format_usdc(value: object) -> str:
    try:
        normalized = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return str(value)
    rendered = format(normalized, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"
