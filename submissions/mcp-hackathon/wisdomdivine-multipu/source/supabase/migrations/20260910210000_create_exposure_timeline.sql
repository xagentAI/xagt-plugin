-- ═══════════════════════════════════════════════════
-- Multipu — Exposure Timeline & Analytics Schema
-- ═══════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS exposure_timeline (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  wallet_address TEXT,
  metric_name TEXT NOT NULL DEFAULT 'exposure',
  value NUMERIC(20, 2) NOT NULL,
  label TEXT,
  recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_exposure_wallet ON exposure_timeline(wallet_address);
CREATE INDEX IF NOT EXISTS idx_exposure_recorded_at ON exposure_timeline(recorded_at ASC);

-- Enable RLS
ALTER TABLE exposure_timeline ENABLE ROW LEVEL SECURITY;

-- Allow public / authenticated read
CREATE POLICY "Allow public read exposure_timeline"
  ON exposure_timeline FOR SELECT
  USING (true);

-- Allow service role full access
CREATE POLICY "Allow service role full access exposure_timeline"
  ON exposure_timeline FOR ALL
  USING (true)
  WITH CHECK (true);

-- Seed initial exposure timeline data reflecting market & launch reach
INSERT INTO exposure_timeline (metric_name, value, label, recorded_at)
VALUES
  ('exposure', 4820, '1 Dec', now() - interval '35 days'),
  ('exposure', 4210, '5 Dec', now() - interval '31 days'),
  ('exposure', 5640, '9 Dec', now() - interval '27 days'),
  ('exposure', 5100, '13 Dec', now() - interval '23 days'),
  ('exposure', 6450, '17 Dec', now() - interval '19 days'),
  ('exposure', 5820, '21 Dec', now() - interval '15 days'),
  ('exposure', 6120, '25 Dec', now() - interval '11 days'),
  ('exposure', 4980, '28 Dec', now() - interval '8 days'),
  ('exposure', 5420, '31 Dec', now() - interval '5 days'),
  ('exposure', 6950, '2 Jan', now() - interval '4 days'),
  ('exposure', 7890, '4 Jan', now() - interval '2 days'),
  ('exposure', 9284, '6 Jan', now() - interval '1 day'),
  ('exposure', 11450, '7 Jan', now() - interval '12 hours'),
  ('exposure', 10120, '8 Jan', now() - interval '6 hours'),
  ('exposure', 9284, 'Today', now())
ON CONFLICT DO NOTHING;
