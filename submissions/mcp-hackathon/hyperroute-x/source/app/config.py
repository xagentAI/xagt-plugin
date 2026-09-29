"""Configuration module for HyperRoute X on X Layer.
Provides network settings, contract addresses, token registry, and commit metadata.
"""

import os

# Identification & Commit binding
SERVICE_NAME = "hyperroute-x"
SERVICE_SLUG = "hyperroute-x"
DEFAULT_COMMIT = "e8be87499fdf6f977051fa3b2d1fb0d916322e8d"
GIT_COMMIT = os.getenv("GIT_COMMIT", DEFAULT_COMMIT)

# Network settings (X Layer Mainnet)
XLAYER_CHAIN_ID = int(os.getenv("CHAIN_ID", "196"))
XLAYER_RPC_URL = os.getenv("XLAYER_RPC_URL", "https://rpc.xlayer.tech")

# Official / Reference Routers on X Layer
# Standard Uniswap V3-compatible SwapRouter on X Layer
DEFAULT_ROUTER_ADDRESS = os.getenv("ROUTER_ADDRESS", "0x098d6B00041B1F3415c48b2E15a6b0c2A8F70570")

# Recognized Core Tokens on X Layer
KNOWN_TOKENS = {
    "OKB": {
        "address": "0xdf54b6c6195ea4d948d03bfd818d365cf175cfc2",
        "symbol": "OKB",
        "decimals": 18,
        "name": "OKB Token"
    },
    "USDT": {
        "address": "0x1e4a5963abfd975d8c9021ce480b42188849d41d",
        "symbol": "USDT",
        "decimals": 6,
        "name": "Tether USD"
    },
    "USDC": {
        "address": "0x74b7f16337b0af80263726c4477621d9ba3e8a68",
        "symbol": "USDC",
        "decimals": 6,
        "name": "USD Coin"
    },
    "WETH": {
        "address": "0x5a77f1443d16ee5761d310e38b62f77f726bc71c",
        "symbol": "WETH",
        "decimals": 18,
        "name": "Wrapped Ether"
    },
    "WBTC": {
        "address": "0xea034fb02eb1808c2cc3adbc15f447b93cbe08e1",
        "symbol": "WBTC",
        "decimals": 8,
        "name": "Wrapped BTC"
    }
}
