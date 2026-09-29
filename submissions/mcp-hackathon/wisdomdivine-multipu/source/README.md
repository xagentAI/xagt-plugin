# Multipu

Multipu is an open-source multi-chain token launch orchestrator, algorithmic trading terminal, and real-time decentralized exchange interface. It enables creators and traders to deploy once, launch across multiple platforms simultaneously, monitor live market signals, and manage cross-chain liquidity from a unified dashboard.

---

## Features

- **Multi-Chain Token Orchestrator**: Deploy bonding curves and liquidity pools simultaneously across Solana (Pump.fun, Meteora, Bags), BNB Chain (Four.meme), and Robinhood Chain (Pons).
- **Trading Terminal & DEX Explorer**: Real-time bonding curve trackers, candlestick charts, liquidity monitors, and order execution.
- **Autonomous Strategy Signals**: Algorithmic momentum scoring, volume surge alerts, and KeeperHub cross-chain arbitrage signals.
- **Unified Multi-Chain Balances**: Live balance monitoring for Solana (SOL), BNB Chain (BNB), and Robinhood Chain (ETH).
- **Non-Custodial Web3 Authentication**: Sign-In with Solana (SIWS) and Sign-In with Blockchain (SIWB) session verification via cryptographically signed challenges.
- **Programmatic Treasury Management**: Dual-chain automated fee routing powered by Privy Server Wallets without storing raw private keys on the server.
- **Developer API & MCP Integration**: REST endpoints and Model Context Protocol sidecars for autonomous agent trading and portfolio automation.

---

## Supported Ecosystems

| Network | Native Asset | Supported Protocols |
| :--- | :--- | :--- |
| **Solana** | `SOL` | Pump.fun, Meteora, Bags, Raydium |
| **BNB Smart Chain (BSC)** | `BNB` | Four.meme, PancakeSwap |
| **Robinhood Chain** | `ETH` | Pons DEX & Launchpad |

---

## Architecture Overview

```
multipu/
├── app/                  # Next.js App Router routes & API endpoints
│   ├── api/              # Secure REST APIs (auth, launches, trades, signals)
│   ├── dashboard/        # Main trading terminal, explorer, token manager & API keys
│   └── launch/           # Unified multi-chain token launch wizard
├── components/           # UI components, modals, canvas hero & design system
├── hooks/                # React hooks for auth, wallet balances, and API queries
├── lib/                  # Core modules (Solana/EVM clients, Treasury, Privy, Supabase)
└── sql/                  # PostgreSQL / Supabase schema definitions
```

---

## Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/wisdomnova/multipu.git
cd multipu
```

### 2. Install dependencies

```bash
npm install
```

### 3. Configure environment variables

Copy the template configuration file:

```bash
cp .env.example .env.local
```

Open `.env.local` and configure your credentials:
- `SESSION_SECRET`: A secure random 32+ character string.
- `NEXT_PUBLIC_SUPABASE_URL` & `NEXT_PUBLIC_SUPABASE_ANON_KEY`: Your Supabase database credentials.
- `SUPABASE_SERVICE_KEY`: Service role key for admin operations.
- `PRIVY_APP_ID` & `PRIVY_APP_SECRET`: For programmatic treasury management.

### 4. Initialize the database

Execute `sql/schema.sql` inside your Supabase project's SQL Editor to set up the necessary tables, indexes, and row-level policies.

### 5. Run the development server

```bash
npm run dev
```

The application will be available at `http://localhost:3000`.

---

## Production Build

To test and produce an optimized production bundle:

```bash
npm run build
npm run start
```

---

## Security Model

- **Non-Custodial Keys**: No private keys are held for user accounts. Transactions are signed directly by connected wallets or isolated inside secure MPC hardware enclaves (Privy).
- **Cryptographic Challenge-Response**: Nonce generation on server, wallet signature verification, and httpOnly encrypted session cookies (`iron-session`).
- **CSRF & Rate Limiting**: Request origin validation and IP-based rate limiting on mutating API endpoints.
- **Rollout Phase Gates**: Explicit network and environment gates (`testnet` vs `mainnet`) to prevent accidental mainnet transactions during development.

---

## License

This project is licensed under the MIT License.
