import pytest
from decimal import Decimal
from app.router_engine import resolve_token, parse_amount, calculate_optimal_quote
from app.tx_builder import build_swap_calldata, validate_evm_address


def test_resolve_token():
    okb = resolve_token("OKB")
    assert okb.symbol == "OKB"
    assert okb.decimals == 18
    assert okb.address.lower() == "0xdf54b6c6195ea4d948d03bfd818d365cf175cfc2".lower()

    usdt = resolve_token("0x1e4a5963abfd975d8c9021ce480b42188849d41d")
    assert usdt.symbol == "USDT"
    assert usdt.decimals == 6

    with pytest.raises(ValueError):
        resolve_token("NONEXISTENT_TOKEN_123")


def test_parse_amount():
    formatted, base = parse_amount("2.5", 18)
    assert formatted == Decimal("2.5")
    assert base == Decimal("2500000000000000000")

    formatted_6, base_6 = parse_amount("100", 6)
    assert formatted_6 == Decimal("100")
    assert base_6 == Decimal("100000000")


def test_calculate_optimal_quote_small():
    quote = calculate_optimal_quote("OKB", "USDT", "1.0", max_slippage_bps=50)
    assert quote.token_in.symbol == "OKB"
    assert quote.token_out.symbol == "USDT"
    assert float(quote.estimated_amount_out_formatted) > 40.0
    assert len(quote.route) == 1
    assert quote.route[0].split_percentage == 100.0
    assert int(quote.guaranteed_min_amount_out_base_units) < int(quote.estimated_amount_out_base_units)


def test_calculate_optimal_quote_split_routing():
    # Large trade ($50k+) triggers split routing
    quote = calculate_optimal_quote("OKB", "USDT", "1200.0", max_slippage_bps=100)
    assert len(quote.route) == 2
    assert quote.route[0].split_percentage == 70.0
    assert quote.route[1].split_percentage == 30.0
    assert quote.gas_estimate == 185000


def test_invalid_quote():
    with pytest.raises(ValueError, match="must be different assets"):
        calculate_optimal_quote("OKB", "OKB", "1.0")

    with pytest.raises(ValueError, match="greater than zero"):
        calculate_optimal_quote("OKB", "USDT", "-5.0")


def test_evm_address_validation():
    assert validate_evm_address("0xdf54b6c6195ea4d948d03bfd818d365cf175cfc2")
    assert not validate_evm_address("0xinvalid")
    assert not validate_evm_address("not_an_address")
