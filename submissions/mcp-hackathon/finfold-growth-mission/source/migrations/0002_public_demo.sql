PRAGMA foreign_keys = ON;

-- Internal key for the public read-only demo route. The raw token was generated
-- locally, hashed, and discarded without ever being issued or recorded, so this
-- row can hold demo missions but can never authenticate a request.
INSERT INTO api_keys (id, token_hash, label, scopes, daily_limit, expires_at, created_at)
VALUES (
  'key_public_demo',
  'c1d345d594afe4fd586669417bb7396c32ea560c76f5503915a5344ed58c4a2c',
  'public-demo',
  'mission:create mission:read',
  1,
  '2027-01-01T00:00:00.000Z',
  '2026-09-30T00:00:00.000Z'
);
