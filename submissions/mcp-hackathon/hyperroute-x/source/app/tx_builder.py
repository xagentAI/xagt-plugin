"""Transaction serialization and ABI encoding engine for Agent DEX Co-Processor.
Produces raw, unsigned EVM transaction calldata ready for execution by AI agents.
"""

import time
import re
from typing import Dict, Any
from app.config import XLAYER_CHAIN_ID, DEFAULT_ROUTER_ADDRESS
from app.models import QuoteResponse, BuildTxResponse


# Keccak-256 selector for Uniswap V3 SwapRouter exactInputSingle:
# exactInputSingle((address,address,uint24,address,uint256,uint256,uint256,uint160))
# Selector: 0x414bf382 (or 0x04e45aaf in SwapRouter02)
EXACT_INPUT_SINGLE_SELECTOR = "0x04e45aaf"


def pad_uint256(val: int) -> str:
    """Encode an integer as a 32-byte (64 hex characters) zero-padded string."""
    return f"{val:064x}"


def pad_address(addr: str) -> str:
    """Encode an address as a 32-byte (64 hex characters) zero-padded string."""
    cleaned = addr.strip().lower()
    if cleaned.startswith("0x"):
        cleaned = cleaned[2:]
    return cleaned.zfill(64)


def validate_evm_address(addr: str) -> bool:
    """Check if address is a valid 40-hex-character EVM address."""
    return bool(re.match(r"^0x[a-fA-F0-9]{40}$", addr.strip()))


def build_swap_calldata(
    quote: QuoteResponse,
    recipient_wallet: str,
    deadline_seconds: int = 1200
) -> BuildTxResponse:
    """Build raw, ready-to-sign EVM transaction calldata for the given swap quote."""
    if not validate_evm_address(recipient_wallet):
        raise ValueError(f"Invalid recipient wallet address: {recipient_wallet}")
        
    token_in_addr = quote.token_in.address
    token_out_addr = quote.token_out.address
    amount_in = int(quote.amount_in_base_units)
    amount_out_minimum = int(quote.guaranteed_min_amount_out_base_units)
    deadline = int(time.time()) + deadline_seconds
    fee_tier = quote.route[0].fee_tier_bps * 10  # convert bps to Uniswap fee (e.g. 500 bps = 5000 / 0.05%)
    
    # In SwapRouter02, exactInputSingle takes a tuple:
    # (address tokenIn, address tokenOut, uint24 fee, address recipient, uint256 amountIn, uint256 amountOutMinimum, uint160 sqrtPriceLimitX96)
    # Calldata layout:
    # 0x04e45aaf + 7 ABI-encoded parameters:
    calldata = (
        EXACT_INPUT_SINGLE_SELECTOR
        + pad_address(token_in_addr)
        + pad_address(token_out_addr)
        + pad_uint256(fee_tier)
        + pad_address(recipient_wallet)
        + pad_uint256(amount_in)
        + pad_uint256(amount_out_minimum)
        + pad_uint256(0)  # sqrtPriceLimitX96 = 0 (no limit)
    )
    
    # Gas limit with 20% safety margin over router estimate
    gas_limit = int(quote.gas_estimate * 1.2)
    
    desc = (
        f"Swap {quote.amount_in_formatted} {quote.token_in.symbol} for minimum "
        f"{quote.guaranteed_min_amount_out_formatted} {quote.token_out.symbol} "
        f"on X Layer via Router {quote.router_address[:8]}..."
    )
    
    return BuildTxResponse(
        to=quote.router_address,
        data=calldata,
        value="0x0",
        chain_id=XLAYER_CHAIN_ID,
        gas_limit=gas_limit,
        description=desc
    )


def build_erc20_approve_calldata(
    token_address: str,
    spender_address: str,
    amount_base_units: str
) -> Dict[str, Any]:
    """Helper to build standard ERC-20 approve(spender, amount) calldata."""
    # approve(address,uint256) selector: 0x095ea7b3
    selector = "0x095ea7b3"
    amount = int(amount_base_units)
    calldata = selector + pad_address(spender_address) + pad_uint256(amount)
    
    return {
        "to": token_address,
        "data": calldata,
        "value": "0x0",
        "gas_limit": 65000,
        "chain_id": XLAYER_CHAIN_ID,
        "description": f"Approve {spender_address} to spend {amount_base_units} units on {token_address}"
    }
