import { AppError } from "./errors";

export type ApiKeyRow = {
  id: string;
  token_hash: string;
  label: string;
  scopes: string;
  daily_limit: number;
  expires_at: string;
};

export type MissionRow = {
  id: string;
  api_key_id: string;
  source_url: string;
  destination_url: string;
  source_digest: string;
  objective: string;
  platform: string;
  locale: string;
  target_value: number;
  measurement_window_days: number;
  measurement_started_at: string;
  measurement_due_at: string;
  result_json: string;
  tracking_code: string;
  created_at: string;
  expires_at: string;
};

export type IdempotencyState =
  | { kind: "owner" }
  | { kind: "replay"; status: number; body: string }
  | { kind: "processing" };

export async function reserveIdempotency(
  db: D1Database,
  apiKeyId: string,
  endpoint: string,
  key: string,
  requestHash: string,
  now: string,
): Promise<IdempotencyState> {
  const expiresAt = new Date(new Date(now).getTime() + 24 * 60 * 60 * 1_000).toISOString();
  const inserted = await db
    .prepare(
      `INSERT OR IGNORE INTO idempotency_records
       (api_key_id, endpoint, idempotency_key, request_hash, state, created_at, expires_at)
       VALUES (?, ?, ?, ?, 'processing', ?, ?)`,
    )
    .bind(apiKeyId, endpoint, key, requestHash, now, expiresAt)
    .run();
  if (inserted.meta.changes === 1) return { kind: "owner" };

  const existing = await db
    .prepare(
      `SELECT request_hash, response_status, response_body, state, created_at
       FROM idempotency_records WHERE api_key_id = ? AND endpoint = ? AND idempotency_key = ?`,
    )
    .bind(apiKeyId, endpoint, key)
    .first<{
      request_hash: string;
      response_status: number | null;
      response_body: string | null;
      state: string;
      created_at: string;
    }>();
  if (!existing) throw new AppError("INTERNAL_ERROR", "Idempotency state could not be loaded.", 500, { retryable: true });
  if (existing.request_hash !== requestHash) {
    throw new AppError("IDEMPOTENCY_CONFLICT", "The idempotency key was already used with a different payload.", 409);
  }
  if (existing.state === "complete" && existing.response_status !== null && existing.response_body !== null) {
    return { kind: "replay", status: existing.response_status, body: existing.response_body };
  }
  if (Date.parse(existing.created_at) < Date.parse(now) - 2 * 60_000) {
    const reclaimed = await db
      .prepare(
        `UPDATE idempotency_records SET created_at = ?, expires_at = ?
         WHERE api_key_id = ? AND endpoint = ? AND idempotency_key = ?
           AND state = 'processing' AND request_hash = ? AND created_at = ?`,
      )
      .bind(now, expiresAt, apiKeyId, endpoint, key, requestHash, existing.created_at)
      .run();
    if (reclaimed.meta.changes === 1) return { kind: "owner" };
  }
  return { kind: "processing" };
}

export async function completeIdempotency(
  db: D1Database,
  apiKeyId: string,
  endpoint: string,
  key: string,
  status: number,
  body: string,
): Promise<void> {
  await db
    .prepare(
      `UPDATE idempotency_records SET state = 'complete', response_status = ?, response_body = ?
       WHERE api_key_id = ? AND endpoint = ? AND idempotency_key = ?`,
    )
    .bind(status, body, apiKeyId, endpoint, key)
    .run();
}

export async function releaseIdempotency(
  db: D1Database,
  apiKeyId: string,
  endpoint: string,
  key: string,
): Promise<void> {
  await db
    .prepare(
      `DELETE FROM idempotency_records
       WHERE api_key_id = ? AND endpoint = ? AND idempotency_key = ? AND state = 'processing'`,
    )
    .bind(apiKeyId, endpoint, key)
    .run();
}

export async function loadMission(db: D1Database, missionId: string, apiKeyId?: string): Promise<MissionRow | null> {
  const statement = apiKeyId
    ? db.prepare("SELECT * FROM missions WHERE id = ? AND api_key_id = ?").bind(missionId, apiKeyId)
    : db.prepare("SELECT * FROM missions WHERE id = ?").bind(missionId);
  return statement.first<MissionRow>();
}
