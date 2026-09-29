-- ═══════════════════════════════════════════════════
-- Multipu — Database Schema
-- Run this in Supabase SQL Editor to create all tables.
-- ═══════════════════════════════════════════════════

-- ─── Enums ─────────────────────────────────────────
CREATE TYPE launchpad_id AS ENUM ('meteora', 'bags', 'pumpfun', 'fourmeme', 'sherwood');
CREATE TYPE launch_status AS ENUM ('pending', 'confirming', 'live', 'failed');
CREATE TYPE token_status AS ENUM ('active', 'pending', 'failed');
CREATE TYPE chain_network AS ENUM ('devnet', 'testnet', 'mainnet-beta', 'bsc', 'base', 'robinhood');
CREATE TYPE app_phase AS ENUM ('testnet', 'mainnet');

-- ─── Users ─────────────────────────────────────────
-- Auto-created on first sign-in via SIWS.
CREATE TABLE users (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  wallet_address TEXT NOT NULL UNIQUE,
  session_version INT NOT NULL DEFAULT 1,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_users_wallet ON users (wallet_address);

-- ─── Tokens ────────────────────────────────────────
CREATE TABLE tokens (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  wallet_address TEXT NOT NULL,
  name TEXT NOT NULL,
  symbol TEXT NOT NULL,
  decimals INT NOT NULL DEFAULT 9,
  supply TEXT NOT NULL, -- bigint as text to avoid overflow
  description TEXT,
  image_url TEXT,
  network chain_network NOT NULL DEFAULT 'devnet',
  app_phase app_phase NOT NULL DEFAULT 'testnet',
  mint_address TEXT,
  mint_tx TEXT,
  status token_status NOT NULL DEFAULT 'pending',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_tokens_user ON tokens (user_id);
CREATE INDEX idx_tokens_wallet ON tokens (wallet_address);
CREATE INDEX idx_tokens_mint ON tokens (mint_address) WHERE mint_address IS NOT NULL;
CREATE INDEX idx_tokens_env_scope ON tokens (wallet_address, network, app_phase);
CREATE UNIQUE INDEX uq_tokens_mint_network
  ON tokens (mint_address, network)
  WHERE mint_address IS NOT NULL;

-- ─── Launches ──────────────────────────────────────
CREATE TABLE launches (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  token_id UUID NOT NULL REFERENCES tokens(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  wallet_address TEXT NOT NULL,
  launchpad launchpad_id NOT NULL,
  network chain_network NOT NULL DEFAULT 'devnet',
  app_phase app_phase NOT NULL DEFAULT 'testnet',
  status launch_status NOT NULL DEFAULT 'pending',
  pool_address TEXT,
  launch_tx TEXT,
  initial_liquidity NUMERIC(20, 9), -- SOL with lamport precision
  volume_24h NUMERIC(20, 9) DEFAULT 0,
  launched_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

  -- Prevent duplicate launches of same token on same pad
  UNIQUE (token_id, launchpad)
);

CREATE INDEX idx_launches_user ON launches (user_id);
CREATE INDEX idx_launches_token ON launches (token_id);
CREATE INDEX idx_launches_status ON launches (status);
CREATE INDEX idx_launches_env_scope ON launches (wallet_address, network, app_phase);

-- ─── Earnings ──────────────────────────────────────
CREATE TABLE earnings (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  wallet_address TEXT NOT NULL,
  token_id UUID NOT NULL REFERENCES tokens(id) ON DELETE CASCADE,
  launch_id UUID NOT NULL REFERENCES launches(id) ON DELETE CASCADE,
  launchpad launchpad_id NOT NULL,
  network chain_network NOT NULL DEFAULT 'devnet',
  app_phase app_phase NOT NULL DEFAULT 'testnet',
  amount_sol NUMERIC(20, 9) NOT NULL,
  fee_type TEXT NOT NULL DEFAULT 'creator_fee',
  tx_signature TEXT,
  recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_earnings_user ON earnings (user_id);
CREATE INDEX idx_earnings_token ON earnings (token_id);
CREATE INDEX idx_earnings_launch ON earnings (launch_id);
CREATE INDEX idx_earnings_recorded ON earnings (recorded_at DESC);
CREATE INDEX idx_earnings_env_scope ON earnings (wallet_address, network, app_phase);

-- ─── Admin Controls ────────────────────────────────
CREATE TABLE admin_settings (
  key TEXT PRIMARY KEY,
  value JSONB NOT NULL DEFAULT '{}'::jsonb,
  updated_by_wallet TEXT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE admin_audit_logs (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  wallet_address TEXT NOT NULL,
  action TEXT NOT NULL,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_admin_audit_created_at ON admin_audit_logs (created_at DESC);

-- ─── Treasury Transfers (Fee Collection) ────────────
-- Multi-chain: Solana (SOL) and BSC (BNB)
-- Server-side only: all transfers signed and executed server-side.
-- Client NEVER signs or initiates treasury transfers.
CREATE TABLE treasury_transfers (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  chain TEXT NOT NULL, -- 'solana' or 'bsc'
  from_wallet TEXT NOT NULL,
  to_wallet TEXT NOT NULL,
  amount_native DECIMAL(20, 9) NOT NULL, -- SOL or BNB
  amount_lamports BIGINT, -- for Solana only
  signature TEXT,
  fee_type TEXT NOT NULL, -- 'manual_withdrawal', 'protocol_fee_collection', 'refund'
  status TEXT NOT NULL DEFAULT 'pending', -- 'pending', 'confirmed', 'failed'
  reason TEXT,
  error_message TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  confirmed_at TIMESTAMPTZ
);

CREATE INDEX idx_treasury_created_at ON treasury_transfers (created_at DESC);
CREATE INDEX idx_treasury_chain ON treasury_transfers (chain);
CREATE INDEX idx_treasury_from_wallet ON treasury_transfers (from_wallet);
CREATE INDEX idx_treasury_to_wallet ON treasury_transfers (to_wallet);
CREATE INDEX idx_treasury_status ON treasury_transfers (status);

-- ─── RLS Policies ──────────────────────────────────
-- We use wallet_address matching since auth is via iron-session,
-- not Supabase Auth. API routes pass the wallet from the session.

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE launches ENABLE ROW LEVEL SECURITY;
ALTER TABLE earnings ENABLE ROW LEVEL SECURITY;
ALTER TABLE admin_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE admin_audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE treasury_transfers ENABLE ROW LEVEL SECURITY;

-- Users & Earnings: restricted to server service-role
CREATE POLICY users_locked ON users FOR ALL USING (false) WITH CHECK (false);
CREATE POLICY earnings_locked ON earnings FOR ALL USING (false) WITH CHECK (false);

-- Tokens & Launches: public read-only, mutations restricted to service-role
CREATE POLICY tokens_read ON tokens FOR SELECT USING (true);
CREATE POLICY tokens_lock ON tokens FOR INSERT WITH CHECK (false);
CREATE POLICY tokens_update_lock ON tokens FOR UPDATE USING (false) WITH CHECK (false);
CREATE POLICY tokens_delete_lock ON tokens FOR DELETE USING (false);

CREATE POLICY launches_read ON launches FOR SELECT USING (true);
CREATE POLICY launches_lock ON launches FOR INSERT WITH CHECK (false);
CREATE POLICY launches_update_lock ON launches FOR UPDATE USING (false) WITH CHECK (false);
CREATE POLICY launches_delete_lock ON launches FOR DELETE USING (false);

CREATE POLICY admin_settings_locked ON admin_settings FOR ALL USING (false) WITH CHECK (false);
CREATE POLICY admin_audit_logs_locked ON admin_audit_logs FOR ALL USING (false) WITH CHECK (false);
CREATE POLICY treasury_transfers_locked ON treasury_transfers FOR ALL USING (false) WITH CHECK (false);

-- ─── Updated_at Trigger ────────────────────────────
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_users_updated BEFORE UPDATE ON users
FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trg_tokens_updated BEFORE UPDATE ON tokens
FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trg_launches_updated BEFORE UPDATE ON launches
FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trg_admin_settings_updated BEFORE UPDATE ON admin_settings
FOR EACH ROW EXECUTE FUNCTION update_updated_at();

INSERT INTO admin_settings (key, value)
VALUES (
  'launch_controls',
  '{
    "launchesPaused": false,
    "allowlistMode": false,
    "allowedWallets": [],
    "launchpadsEnabled": {
      "meteora": true,
      "bags": true,
      "pumpfun": true,
      "fourmeme": true,
      "sherwood": true
    }
  }'::jsonb
)
ON CONFLICT (key) DO NOTHING;

-- ─── Useful Views ──────────────────────────────────

-- Dashboard stats per user
CREATE OR REPLACE VIEW user_dashboard_stats AS
SELECT
  u.wallet_address,
  t.network,
  t.app_phase,
  COUNT(DISTINCT t.id) AS total_tokens,
  COUNT(DISTINCT l.id) FILTER (WHERE l.status = 'live') AS active_launches,
  COALESCE(SUM(e.amount_sol), 0) AS total_earnings,
  COALESCE(SUM(e.amount_sol) FILTER (
    WHERE e.recorded_at > now() - INTERVAL '24 hours'
  ), 0) AS earnings_today
FROM users u
LEFT JOIN tokens t ON t.user_id = u.id
LEFT JOIN launches l ON l.user_id = u.id AND l.network = t.network AND l.app_phase = t.app_phase
LEFT JOIN earnings e ON e.user_id = u.id AND e.network = t.network AND e.app_phase = t.app_phase
GROUP BY u.wallet_address, t.network, t.app_phase;

-- ─── Developer API Keys ─────────────────────────────
CREATE TABLE developer_api_keys (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  wallet_address TEXT NOT NULL,
  name TEXT NOT NULL,
  api_key TEXT NOT NULL UNIQUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  revoked BOOLEAN NOT NULL DEFAULT false
);

CREATE INDEX idx_developer_api_keys_wallet ON developer_api_keys (wallet_address);
CREATE INDEX idx_developer_api_keys_key ON developer_api_keys (api_key);

ALTER TABLE developer_api_keys ENABLE ROW LEVEL SECURITY;
CREATE POLICY developer_api_keys_locked ON developer_api_keys FOR ALL USING (false) WITH CHECK (false);

-- ─── Developer Wallets ──────────────────────────────
CREATE TABLE developer_wallets (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  wallet_address TEXT NOT NULL,
  network TEXT NOT NULL, -- 'solana' or 'evm'
  public_key TEXT NOT NULL,
  encrypted_private_key TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_user_wallet_network UNIQUE(user_id, network)
);

CREATE INDEX idx_developer_wallets_wallet ON developer_wallets (wallet_address);

ALTER TABLE developer_wallets ENABLE ROW LEVEL SECURITY;
CREATE POLICY developer_wallets_locked ON developer_wallets FOR ALL USING (false) WITH CHECK (false);

