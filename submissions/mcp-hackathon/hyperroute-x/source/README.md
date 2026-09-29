# Agent DEX Co-Processor (Source)

A lightweight execution co-processor and routing engine built for AI agents transacting on X Layer (OKX Layer 2).

## Core Capabilities

- **`GET /health`**: Live health status and Git review commit verification.
- **`GET /.well-known/xagent-verification.json`**: Deployment ownership proof binding.
- **`POST /api/v1/quote`**: Multi-pool optimal routing, price impact estimation, and slippage protection.
- **`POST /api/v1/build-tx`**: Unsigned ABI-encoded calldata serialization (`to`, `data`, `value`, `gas_limit`, `chain_id: 196`).
- **`POST /api/v1/simulate`**: Pre-execution simulation via `eth_call` on X Layer RPC.
- **`GET /api/v1/mcp/tools`**: Standard Model Context Protocol tool definitions for OKX.AI.

## Local Setup and Running

1. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Run the service**:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```

3. **Run tests**:
   ```bash
   pytest
   ```
