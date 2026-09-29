-- Harden RLS policies for sensitive tables

-- Developer API keys & wallets: restrict to service role
DROP POLICY IF EXISTS developer_api_keys_own ON developer_api_keys;
DROP POLICY IF EXISTS developer_api_keys_locked ON developer_api_keys;
CREATE POLICY developer_api_keys_locked ON developer_api_keys FOR ALL USING (false) WITH CHECK (false);

DROP POLICY IF EXISTS developer_wallets_own ON developer_wallets;
DROP POLICY IF EXISTS developer_wallets_locked ON developer_wallets;
CREATE POLICY developer_wallets_locked ON developer_wallets FOR ALL USING (false) WITH CHECK (false);

-- Users & Earnings: restricted to service role
DROP POLICY IF EXISTS users_own ON users;
DROP POLICY IF EXISTS users_locked ON users;
CREATE POLICY users_locked ON users FOR ALL USING (false) WITH CHECK (false);

DROP POLICY IF EXISTS earnings_own ON earnings;
DROP POLICY IF EXISTS earnings_locked ON earnings;
CREATE POLICY earnings_locked ON earnings FOR ALL USING (false) WITH CHECK (false);

-- Tokens: public read-only, write locked
DROP POLICY IF EXISTS tokens_own ON tokens;
DROP POLICY IF EXISTS tokens_read ON tokens;
DROP POLICY IF EXISTS tokens_lock ON tokens;
CREATE POLICY tokens_read ON tokens FOR SELECT USING (true);
CREATE POLICY tokens_lock ON tokens FOR INSERT WITH CHECK (false);

-- Launches: public read-only, write locked
DROP POLICY IF EXISTS launches_own ON launches;
DROP POLICY IF EXISTS launches_read ON launches;
DROP POLICY IF EXISTS launches_lock ON launches;
CREATE POLICY launches_read ON launches FOR SELECT USING (true);
CREATE POLICY launches_lock ON launches FOR INSERT WITH CHECK (false);
