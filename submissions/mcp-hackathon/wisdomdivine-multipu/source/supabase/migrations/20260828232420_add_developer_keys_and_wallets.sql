-- ─── Developer API Keys ─────────────────────────────
CREATE TABLE IF NOT EXISTS developer_api_keys (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  wallet_address TEXT NOT NULL,
  name TEXT NOT NULL,
  api_key TEXT NOT NULL UNIQUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  revoked BOOLEAN NOT NULL DEFAULT false
);

CREATE INDEX IF NOT EXISTS idx_developer_api_keys_wallet ON developer_api_keys (wallet_address);
CREATE INDEX IF NOT EXISTS idx_developer_api_keys_key ON developer_api_keys (api_key);

ALTER TABLE developer_api_keys ENABLE ROW LEVEL SECURITY;
CREATE POLICY developer_api_keys_locked ON developer_api_keys FOR ALL USING (false) WITH CHECK (false);

-- ─── Developer Wallets ──────────────────────────────
CREATE TABLE IF NOT EXISTS developer_wallets (
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

CREATE INDEX IF NOT EXISTS idx_developer_wallets_wallet ON developer_wallets (wallet_address);

ALTER TABLE developer_wallets ENABLE ROW LEVEL SECURITY;
CREATE POLICY developer_wallets_locked ON developer_wallets FOR ALL USING (false) WITH CHECK (false);
