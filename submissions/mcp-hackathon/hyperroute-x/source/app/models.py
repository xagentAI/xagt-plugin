"""Pydantic data schemas for Agent DEX Co-Processor API and MCP tool integrations."""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class TokenInfo(BaseModel):
    address: str = Field(..., description="EVM token contract address")
    symbol: str = Field(..., description="Token symbol, e.g. OKB, USDT")
    decimals: int = Field(..., description="Token decimal precision")
    name: Optional[str] = Field(None, description="Token descriptive name")


class RouteSplit(BaseModel):
    pool_address: str = Field(..., description="Liquidity pool contract address")
    protocol: str = Field(..., description="DEX Protocol identifier, e.g. UniswapV3_XLayer")
    fee_tier_bps: int = Field(..., description="Pool fee tier in basis points, e.g. 500 = 0.05%")
    split_percentage: float = Field(..., description="Portion of swap routed through this pool (0-100)")
    expected_amount_out: str = Field(..., description="Calculated token output from this hop (in base units)")


class QuoteRequest(BaseModel):
    token_in: str = Field(..., description="Input token symbol (e.g. 'OKB') or contract address (0x...)")
    token_out: str = Field(..., description="Output token symbol (e.g. 'USDT') or contract address (0x...)")
    amount_in: str = Field(..., description="Amount of token_in to swap (in human readable or wei string, e.g. '1.5' or '1500000000000000000')")
    max_slippage_bps: Optional[int] = Field(50, description="Max acceptable slippage in basis points (50 = 0.5%)")
    chain_id: Optional[int] = Field(196, description="Target EVM chain ID (196 for X Layer)")


class QuoteResponse(BaseModel):
    token_in: TokenInfo
    token_out: TokenInfo
    amount_in_base_units: str
    amount_in_formatted: str
    estimated_amount_out_base_units: str
    estimated_amount_out_formatted: str
    guaranteed_min_amount_out_base_units: str
    guaranteed_min_amount_out_formatted: str
    effective_price: float = Field(..., description="Output tokens per input token")
    price_impact_pct: float = Field(..., description="Estimated price impact percentage")
    gas_estimate: int = Field(..., description="Estimated execution gas units")
    route: List[RouteSplit]
    router_address: str


class BuildTxRequest(BaseModel):
    recipient_wallet: str = Field(..., description="EVM wallet address of the agent or user receiving swapped tokens")
    quote: QuoteResponse = Field(..., description="Approved quote response object from /quote")
    deadline_seconds: Optional[int] = Field(1200, description="Transaction expiration time from now in seconds (default 20 mins)")


class BuildTxResponse(BaseModel):
    to: str = Field(..., description="Target SwapRouter contract address on X Layer")
    data: str = Field(..., description="Hex-encoded ABI calldata ready for eth_sendTransaction")
    value: str = Field("0x0", description="Native token value to send in hex (e.g. if token_in is native)")
    chain_id: int = Field(196, description="Target chain ID")
    gas_limit: int = Field(..., description="Recommended gas limit including safety buffer")
    description: str = Field(..., description="Human/Agent readable execution summary")


class SimulateRequest(BaseModel):
    to: str = Field(..., description="Target contract address to call")
    from_address: str = Field(..., description="Sender EVM wallet address")
    data: str = Field(..., description="Hex-encoded execution calldata")
    value: Optional[str] = Field("0x0", description="Native token value in hex")
    chain_id: Optional[int] = Field(196, description="Target chain ID")


class SimulateResponse(BaseModel):
    success: bool = Field(..., description="True if transaction simulation succeeded without revert")
    gas_used: int = Field(..., description="Gas units consumed by call")
    revert_reason: Optional[str] = Field(None, description="Detailed revert error message if failed")
    simulation_mode: str = Field(..., description="'live_rpc' or 'local_validator'")
    timestamp: int


class HealthResponse(BaseModel):
    status: str = Field("ok", description="Service health status")
    commit: str = Field(..., description="Git review commit SHA")
    version: str = Field(..., description="Version identifier matching commit")
    slug: str = Field(..., description="Official hackathon project slug")
    network: str = Field("xlayer-mainnet", description="Connected network")


class DeploymentProofResponse(BaseModel):
    schemaVersion: int = Field(1, description="Standard verification schema version")
    slug: str = Field(..., description="Official hackathon project slug")
    commit: str = Field(..., description="Git review commit SHA")
