"""Model Context Protocol (MCP) standardized tool schemas for OKX.AI and X-Agent.
Enables autonomous LLM agents to seamlessly discover and execute DEX routing capabilities.
"""

from typing import List, Dict, Any

MCP_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "get_swap_quote",
        "description": (
            "Get mathematically optimal DEX routing quote across liquidity pools on X Layer (OKX L2). "
            "Computes price impact, fee tiers, pool splits, and guaranteed minimum output with slippage protection."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "token_in": {
                    "type": "string",
                    "description": "Symbol (OKB, USDT, USDC, WETH, WBTC) or 0x contract address to swap from."
                },
                "token_out": {
                    "type": "string",
                    "description": "Symbol (OKB, USDT, USDC, WETH, WBTC) or 0x contract address to swap to."
                },
                "amount_in": {
                    "type": "string",
                    "description": "Amount to swap (e.g. '1.5' or '1500000000000000000')."
                },
                "max_slippage_bps": {
                    "type": "integer",
                    "default": 50,
                    "description": "Maximum tolerated slippage in basis points (50 = 0.5%)."
                }
            },
            "required": ["token_in", "token_out", "amount_in"]
        }
    },
    {
        "name": "build_swap_transaction",
        "description": (
            "Serializes an approved swap quote into raw, unsigned EVM transaction calldata. "
            "Returns 'to', 'data', 'value', 'gas_limit', and 'chain_id' ready for an agent's signing wallet."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "recipient_wallet": {
                    "type": "string",
                    "description": "0x EVM wallet address of the agent or user receiving the swapped tokens."
                },
                "quote": {
                    "type": "object",
                    "description": "Full quote response object returned from get_swap_quote."
                },
                "deadline_seconds": {
                    "type": "integer",
                    "default": 1200,
                    "description": "Transaction deadline in seconds from now."
                }
            },
            "required": ["recipient_wallet", "quote"]
        }
    },
    {
        "name": "simulate_swap_transaction",
        "description": (
            "Pre-validates transaction calldata via eth_call against X Layer RPC. "
            "Guarantees the transaction will not revert before the agent pays gas to broadcast it."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Target SwapRouter contract address."
                },
                "from_address": {
                    "type": "string",
                    "description": "Calling agent's EVM wallet address."
                },
                "data": {
                    "type": "string",
                    "description": "Hex-encoded transaction calldata."
                },
                "value": {
                    "type": "string",
                    "default": "0x0",
                    "description": "Native token value in hex."
                }
            },
            "required": ["to", "from_address", "data"]
        }
    }
]


def get_mcp_manifest() -> Dict[str, Any]:
    """Return the complete MCP manifest object for agent ecosystem registration."""
    return {
        "mcpVersion": "1.0.0",
        "serverInfo": {
            "name": "hyperroute-x",
            "title": "HyperRoute X (X Layer)",
            "version": "1.0.0",
            "description": "Autonomous DeFi Routing, ABI Calldata Serialization, and Execution Simulation on X Layer"
        },
        "tools": MCP_TOOLS
    }
