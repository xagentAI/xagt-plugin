-- Migration to add sherwood launchpad and robinhood chain network type

-- 1. Add 'sherwood' to launchpad_id enum
ALTER TYPE launchpad_id ADD VALUE IF NOT EXISTS 'sherwood';

-- 2. Add 'robinhood' to chain_network enum
ALTER TYPE chain_network ADD VALUE IF NOT EXISTS 'robinhood';

-- 3. Update admin_settings to include Sherwood launchpad control status
UPDATE admin_settings
SET value = jsonb_set(
  coalesce(value, '{}'::jsonb), 
  '{launchpadsEnabled,sherwood}', 
  'true'::jsonb
)
WHERE key = 'launch_controls';
