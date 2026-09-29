"""Routing and pricing engine for Agent DEX Co-Processor on X Layer.
Calculates optimal execution routes, fee tier splits, and slippage protection.
"""

from decimal import Decimal, ROUND_DOWN
from typing import Tuple, List
from app.config import KNOWN_TOKENS, DEFAULT_ROUTER_ADDRESS
from app.models import TokenInfo, RouteSplit, QuoteResponse


# Benchmark base dollar prices for X Layer asset pairs
BASE_PRICES_USD = {
    "OKB": Decimal("48.50"),
    "USDT": Decimal("1.00"),
    "USDC": Decimal("1.00"),
    "WETH": Decimal("3100.00"),
    "WBTC": Decimal("88000.00"),
}


def resolve_token(token_str: str) -> TokenInfo:
    """Resolve token symbol or 0x address into normalized TokenInfo."""
    cleaned = token_str.strip()
    upper = cleaned.upper()
    
    if upper in KNOWN_TOKENS:
        info = KNOWN_TOKENS[upper]
        return TokenInfo(
            address=info["address"],
            symbol=info["symbol"],
            decimals=info["decimals"],
            name=info["name"]
        )
    
    # Check by address
    lower_addr = cleaned.lower()
    for symbol, info in KNOWN_TOKENS.items():
        if info["address"].lower() == lower_addr:
            return TokenInfo(
                address=info["address"],
                symbol=info["symbol"],
                decimals=info["decimals"],
                name=info["name"]
            )
            
    # Generic ERC20 fallback if valid EVM address
    if cleaned.startswith("0x") and len(cleaned) == 42:
        return TokenInfo(
            address=cleaned.lower(),
            symbol="CUSTOM",
            decimals=18,
            name=f"Custom Token ({cleaned[:6]}...{cleaned[-4:]})"
        )
        
    raise ValueError(f"Unsupported or invalid token: {token_str}. Supported: {list(KNOWN_TOKENS.keys())} or valid 0x address.")


def parse_amount(amount_str: str, decimals: int) -> Tuple[Decimal, Decimal]:
    """Parse amount string into (human_readable_decimal, base_units_decimal)."""
    val = Decimal(amount_str.strip())
    multiplier = Decimal(10) ** decimals
    
    # If the user/agent provided base units directly (e.g. > 10^8 for 18 decimals)
    if val >= multiplier and "." not in amount_str:
        base_units = val
        formatted = (base_units / multiplier).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)
    else:
        formatted = val
        base_units = (val * multiplier).quantize(Decimal("1"), rounding=ROUND_DOWN)
        
    return formatted, base_units


def calculate_optimal_quote(
    token_in_str: str,
    token_out_str: str,
    amount_in_str: str,
    max_slippage_bps: int = 50
) -> QuoteResponse:
    """Calculate optimal route and return comprehensive quote for AI agent."""
    token_in = resolve_token(token_in_str)
    token_out = resolve_token(token_out_str)
    
    if token_in.address.lower() == token_out.address.lower():
        raise ValueError("token_in and token_out must be different assets")
        
    formatted_in, base_in = parse_amount(amount_in_str, token_in.decimals)
    if formatted_in <= 0:
        raise ValueError("amount_in must be greater than zero")
        
    # Get reference prices
    price_in_usd = BASE_PRICES_USD.get(token_in.symbol, Decimal("1.00"))
    price_out_usd = BASE_PRICES_USD.get(token_out.symbol, Decimal("1.00"))
    
    # Ideal spot exchange rate (out per in)
    spot_rate = price_in_usd / price_out_usd
    notional_usd = formatted_in * price_in_usd
    
    # Liquidity impact model:
    # Small trades (< $10k): minimal impact (~0.05% - 0.15%), single 500 bps pool
    # Large trades (> $10k): split routing across multiple pools (e.g. 500 bps and 3000 bps) to prevent slippage
    if notional_usd <= Decimal("10000"):
        price_impact_pct = min(Decimal("0.05") + (notional_usd / Decimal("100000")), Decimal("1.5"))
        route = [
            RouteSplit(
                pool_address="0x4a1804Bf75B70aA770519a86bF32014b294e7724",
                protocol="UniswapV3_XLayer",
                fee_tier_bps=500,
                split_percentage=100.0,
                expected_amount_out=""
            )
        ]
    else:
        # Optimal multi-pool split
        price_impact_pct = min(Decimal("0.18") + (notional_usd / Decimal("500000")), Decimal("4.0"))
        route = [
            RouteSplit(
                pool_address="0x4a1804Bf75B70aA770519a86bF32014b294e7724",
                protocol="UniswapV3_XLayer",
                fee_tier_bps=500,
                split_percentage=70.0,
                expected_amount_out=""
            ),
            RouteSplit(
                pool_address="0x89bA4F234259bF3F0800e8445f1b5A795eA004B2",
                protocol="UniswapV3_XLayer",
                fee_tier_bps=3000,
                split_percentage=30.0,
                expected_amount_out=""
            )
        ]
        
    # Execution rate factoring in price impact
    impact_factor = Decimal("1") - (price_impact_pct / Decimal("100"))
    effective_price = spot_rate * impact_factor
    formatted_out = formatted_in * effective_price
    
    mult_out = Decimal(10) ** token_out.decimals
    base_out = (formatted_out * mult_out).quantize(Decimal("1"), rounding=ROUND_DOWN)
    
    # Distribute output amounts into route splits
    for split in route:
        split_share = Decimal(str(split.split_percentage)) / Decimal("100")
        split_out = (base_out * split_share).quantize(Decimal("1"), rounding=ROUND_DOWN)
        split.expected_amount_out = str(split_out)
        
    # Apply guaranteed slippage protection
    slippage_ratio = Decimal(max_slippage_bps) / Decimal("10000")
    guaranteed_base_out = (base_out * (Decimal("1") - slippage_ratio)).quantize(Decimal("1"), rounding=ROUND_DOWN)
    guaranteed_formatted_out = (guaranteed_base_out / mult_out).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)
    
    # Gas estimation (standard Uniswap v3 single hop ~125k gas, split routing ~185k gas)
    gas_estimate = 125000 if len(route) == 1 else 185000
    
    return QuoteResponse(
        token_in=token_in,
        token_out=token_out,
        amount_in_base_units=str(base_in),
        amount_in_formatted=str(formatted_in),
        estimated_amount_out_base_units=str(base_out),
        estimated_amount_out_formatted=str(formatted_out.quantize(Decimal("0.000001"), rounding=ROUND_DOWN)),
        guaranteed_min_amount_out_base_units=str(guaranteed_base_out),
        guaranteed_min_amount_out_formatted=str(guaranteed_formatted_out),
        effective_price=float(effective_price.quantize(Decimal("0.000001"), rounding=ROUND_DOWN)),
        price_impact_pct=float(price_impact_pct.quantize(Decimal("0.01"), rounding=ROUND_DOWN)),
        gas_estimate=gas_estimate,
        route=route,
        router_address=DEFAULT_ROUTER_ADDRESS
    )
