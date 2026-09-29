-- ═══════════════════════════════════════════════════
-- Multipu — Trading Agents & Copilot Schema
-- ═══════════════════════════════════════════════════

CREATE TYPE agent_status AS ENUM ('active', 'paused', 'completed', 'failed');
CREATE TYPE agent_mode AS ENUM ('paper', 'live');

CREATE TABLE IF NOT EXISTS trading_agents (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  wallet_address TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT,
  prompt TEXT NOT NULL,
  mode agent_mode NOT NULL DEFAULT 'paper',
  status agent_status NOT NULL DEFAULT 'active',
  chain TEXT NOT NULL DEFAULT 'solana',
  launchpads TEXT[] NOT NULL DEFAULT ARRAY['pumpfun', 'meteora'],
  strategy_config JSONB NOT NULL DEFAULT '{}'::jsonb,
  budget_allocated NUMERIC(20, 9) NOT NULL DEFAULT 0.5,
  budget_spent NUMERIC(20, 9) NOT NULL DEFAULT 0,
  total_pnl_pct NUMERIC(10, 4) NOT NULL DEFAULT 0,
  total_trades INT NOT NULL DEFAULT 0,
  successful_trades INT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_trading_agents_user ON trading_agents(user_id);
CREATE INDEX IF NOT EXISTS idx_trading_agents_wallet ON trading_agents(wallet_address);
CREATE INDEX IF NOT EXISTS idx_trading_agents_status ON trading_agents(status);

CREATE TABLE IF NOT EXISTS agent_trades (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  agent_id UUID NOT NULL REFERENCES trading_agents(id) ON DELETE CASCADE,
  token_symbol TEXT NOT NULL,
  token_mint TEXT,
  action TEXT NOT NULL, -- 'buy' | 'sell'
  launchpad TEXT NOT NULL,
  chain TEXT NOT NULL DEFAULT 'solana',
  amount_in NUMERIC(20, 9) NOT NULL,
  amount_out NUMERIC(20, 9) NOT NULL,
  pnl_pct NUMERIC(10, 4),
  pnl_sol NUMERIC(20, 9),
  tx_signature TEXT,
  mode agent_mode NOT NULL DEFAULT 'paper',
  execution_log TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_agent_trades_agent ON agent_trades(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_trades_created ON agent_trades(created_at DESC);
