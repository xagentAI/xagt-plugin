import type { AuthContext } from "./auth";
import { nowIso, secureCode, sha256Hex } from "./crypto";
import {
  completeIdempotency,
  loadMission,
  releaseIdempotency,
  reserveIdempotency,
  type MissionRow,
} from "./db";
import { AppError } from "./errors";
import { generateMission } from "./generation";
import type { CreateMissionInput, Objective, OutcomeInput } from "./schemas";
import { fetchSourceEvidence } from "./source";
import { assertSafeLandingPage, trackedDestination } from "./url-safety";

const WINDOW_DAYS: Record<Objective, number> = {
  leads: 14,
  signups: 7,
  purchases: 30,
  revenue: 30,
};

type StoredMissionResult = {
  mission: {
    id: string;
    title: string;
    hypothesis: string;
    objective: Objective;
    platform: string;
    locale: string;
    audience: string;
    primaryMetric: Objective;
    targetValue: number;
    targetCurrency?: string;
    measurementWindowDays: number;
    measurementStartedAt: string;
    measurementDueAt: string;
  };
  asset: { format: string; title: string; body: string; cta: string };
  evidence: Array<{
    id: string;
    sectionId: string;
    quote: string;
    sourceUrl: string;
    confidence: number;
  }>;
  claimMap: Array<{ claim: string; evidenceIds: string[] }>;
  validation: unknown;
  tracking: { code: string; destinationUrl: string; trackedUrl: string };
  provenance: {
    requestId: string;
    generatedAt: string;
    sourceDigest: string;
    providerAttempts: number;
    model: string;
    commit: string;
  };
  sideEffects: { persisted: true; published: false; externalAccountsModified: false };
};

export type OperationResult = { status: number; body: string; replayed: boolean };

function parsedMission(row: MissionRow): StoredMissionResult {
  try {
    return JSON.parse(row.result_json) as StoredMissionResult;
  } catch {
    throw new AppError("INTERNAL_ERROR", "Stored mission data is invalid.", 500);
  }
}

export async function createMissionOperation(
  env: Env,
  auth: AuthContext,
  input: CreateMissionInput,
  idemKey: string,
  requestId: string,
): Promise<OperationResult> {
  const endpoint = "POST:/v1/missions";
  const requestHash = await sha256Hex(JSON.stringify(input));
  const reserved = await reserveIdempotency(env.DB, auth.apiKeyId, endpoint, idemKey, requestHash, nowIso());
  if (reserved.kind === "replay") return { status: reserved.status, body: reserved.body, replayed: true };
  if (reserved.kind === "processing") {
    throw new AppError("REQUEST_IN_PROGRESS", "A request with this idempotency key is still processing.", 409, {
      retryable: true,
    });
  }

  try {
    const sourceStarted = Date.now();
    const source = await fetchSourceEvidence(input.sourceUrl);
    console.log(
      JSON.stringify({
        event: "source_validation",
        requestId,
        status: "passed",
        durationMs: Date.now() - sourceStarted,
      }),
    );
    const generatedResult = await generateMission(env, input, source);
    console.log(
      JSON.stringify({
        event: "mission_validation",
        requestId,
        providerAttempts: generatedResult.providerAttempts,
        schemaValid: true,
        evidenceExactMatch: generatedResult.quality.evidenceExactMatch,
        qualityPassed: generatedResult.quality.passed,
      }),
    );
    const generatedAt = nowIso();
    const missionId = `gm_${secureCode(12)}`;
    const trackingCode = secureCode(18);
    const targetValue = input.targetValue ?? 1;
    const windowDays = WINDOW_DAYS[input.objective];
    const dueAt = new Date(Date.parse(generatedAt) + windowDays * 86_400_000).toISOString();
    const expiresAt = new Date(Date.parse(generatedAt) + 30 * 86_400_000).toISOString();
    const landingPage = assertSafeLandingPage(source.finalUrl, input.landingPage ?? source.finalUrl).toString();
    const destinationUrl = trackedDestination(landingPage, generatedResult.generated.mission.platform, missionId);
    const trackedUrl = `${env.APP_BASE_URL.replace(/\/$/, "")}/r/${trackingCode}`;
    const asset = {
      ...generatedResult.generated.asset,
      body: generatedResult.generated.asset.body.replace("{{TRACKING_URL}}", trackedUrl),
      cta: generatedResult.generated.asset.cta.replace("{{TRACKING_URL}}", trackedUrl),
    };

    const stored: StoredMissionResult = {
      mission: {
        id: missionId,
        ...generatedResult.generated.mission,
        objective: input.objective,
        locale: input.locale,
        targetValue,
        ...(input.objective === "revenue" ? { targetCurrency: input.targetCurrency ?? "USD" } : {}),
        measurementWindowDays: windowDays,
        measurementStartedAt: generatedAt,
        measurementDueAt: dueAt,
      },
      asset,
      evidence: generatedResult.generated.evidence.map((evidence) => ({
        ...evidence,
        sourceUrl: source.finalUrl,
      })),
      claimMap: generatedResult.generated.claimMap,
      validation: generatedResult.quality,
      tracking: { code: trackingCode, destinationUrl, trackedUrl },
      provenance: {
        requestId,
        generatedAt,
        sourceDigest: source.digest,
        providerAttempts: generatedResult.providerAttempts,
        model: env.LLM_MODEL,
        commit: env.COMMIT_SHA,
      },
      sideEffects: { persisted: true, published: false, externalAccountsModified: false },
    };
    const body = JSON.stringify(stored);
    await env.DB.prepare(
      `INSERT INTO missions
       (id, api_key_id, source_url, destination_url, source_digest, objective, platform, locale,
        target_value, measurement_window_days, measurement_started_at, measurement_due_at,
        result_json, tracking_code, created_at, expires_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    )
      .bind(
        missionId,
        auth.apiKeyId,
        source.finalUrl,
        destinationUrl,
        source.digest,
        input.objective,
        generatedResult.generated.mission.platform,
        input.locale,
        targetValue,
        windowDays,
        generatedAt,
        dueAt,
        body,
        trackingCode,
        generatedAt,
        expiresAt,
      )
      .run();
    await completeIdempotency(env.DB, auth.apiKeyId, endpoint, idemKey, 201, body);
    return { status: 201, body, replayed: false };
  } catch (error) {
    await releaseIdempotency(env.DB, auth.apiKeyId, endpoint, idemKey);
    throw error;
  }
}

type Attribution = {
  clicks: number;
  leads: number;
  signups: number;
  purchases: number;
  revenue: number;
  currencies: string[];
};

async function attributionFor(db: D1Database, missionId: string): Promise<Attribution> {
  const [clickRow, outcomeRows] = await Promise.all([
    db.prepare("SELECT COALESCE(SUM(clicks), 0) AS clicks FROM tracking_daily WHERE mission_id = ?")
      .bind(missionId)
      .first<{ clicks: number }>(),
    db.prepare(
      `SELECT outcome_type, COALESCE(SUM(quantity), 0) AS quantity,
              COALESCE(SUM(value), 0) AS total_value, GROUP_CONCAT(DISTINCT currency) AS currencies
       FROM outcome_events WHERE mission_id = ? GROUP BY outcome_type`,
    )
      .bind(missionId)
      .all<{ outcome_type: string; quantity: number; total_value: number; currencies: string | null }>(),
  ]);
  const attribution: Attribution = {
    clicks: Number(clickRow?.clicks ?? 0),
    leads: 0,
    signups: 0,
    purchases: 0,
    revenue: 0,
    currencies: [],
  };
  for (const row of outcomeRows.results) {
    if (row.outcome_type === "lead") attribution.leads = Number(row.quantity);
    if (row.outcome_type === "signup") attribution.signups = Number(row.quantity);
    if (row.outcome_type === "purchase") attribution.purchases = Number(row.quantity);
    if (row.outcome_type === "revenue") attribution.revenue = Number(row.total_value);
    if (row.currencies) attribution.currencies.push(...row.currencies.split(","));
  }
  attribution.currencies = [...new Set(attribution.currencies)].sort();
  return attribution;
}

function verdictFor(row: MissionRow, attribution: Attribution): { verdict: string; measuredValue: number; nextAction: string } {
  const measuredValue =
    row.objective === "leads"
      ? attribution.leads
      : row.objective === "signups"
        ? attribution.signups
        : row.objective === "purchases"
          ? attribution.purchases
          : attribution.revenue;
  if (measuredValue >= row.target_value) {
    return {
      verdict: "won",
      measuredValue,
      nextAction: "Preserve the evidence-backed angle and scale distribution with a fresh tracked mission.",
    };
  }
  if (Date.now() < Date.parse(row.measurement_due_at)) {
    return {
      verdict: "running",
      measuredValue,
      nextAction: "Keep the mission running until the measurement window closes; record attributable outcomes as they occur.",
    };
  }
  const hasCredibleOutcome = attribution.leads + attribution.signups + attribution.purchases + attribution.revenue > 0;
  if (hasCredibleOutcome) {
    return {
      verdict: "lost",
      measuredValue,
      nextAction: "Use the observed response to revise the hook or audience while retaining only claims supported by the source.",
    };
  }
  return {
    verdict: "inconclusive",
    measuredValue,
    nextAction: "Verify the tracking path and outcome reporting before changing the growth hypothesis.",
  };
}

export async function getMissionOperation(env: Env, auth: AuthContext, missionId: string): Promise<Record<string, unknown>> {
  const row = await loadMission(env.DB, missionId, auth.apiKeyId);
  if (!row) throw new AppError("MISSION_NOT_FOUND", "Mission not found.", 404);
  const attribution = await attributionFor(env.DB, missionId);
  const verdict = verdictFor(row, attribution);
  return {
    ...parsedMission(row),
    attribution,
    outcome: {
      verdict: verdict.verdict,
      measuredValue: verdict.measuredValue,
      targetValue: row.target_value,
      measurementDueAt: row.measurement_due_at,
      nextAction: verdict.nextAction,
    },
  };
}

export async function recordOutcomeOperation(
  env: Env,
  auth: AuthContext,
  missionId: string,
  input: OutcomeInput,
  idemKey: string,
): Promise<OperationResult> {
  const endpoint = `POST:/v1/missions/${missionId}/outcomes`;
  const requestHash = await sha256Hex(JSON.stringify(input));
  const reserved = await reserveIdempotency(env.DB, auth.apiKeyId, endpoint, idemKey, requestHash, nowIso());
  if (reserved.kind === "replay") return { status: reserved.status, body: reserved.body, replayed: true };
  if (reserved.kind === "processing") {
    throw new AppError("REQUEST_IN_PROGRESS", "A request with this idempotency key is still processing.", 409, { retryable: true });
  }
  try {
    const mission = await loadMission(env.DB, missionId, auth.apiKeyId);
    if (!mission) throw new AppError("MISSION_NOT_FOUND", "Mission not found.", 404);
    const occurredAt = input.occurredAt ?? nowIso();
    const occurredAtMs = Date.parse(occurredAt);
    if (occurredAtMs > Date.now() + 5 * 60_000) {
      throw new AppError("INVALID_REQUEST", "occurredAt cannot be in the future.", 400);
    }
    if (occurredAtMs < Date.parse(mission.measurement_started_at) || occurredAtMs > Date.parse(mission.measurement_due_at)) {
      throw new AppError("OUTCOME_OUTSIDE_WINDOW", "occurredAt must fall inside the mission measurement window.", 422);
    }
    const storedMission = parsedMission(mission);
    const targetCurrency = storedMission.mission.targetCurrency ?? (mission.objective === "revenue" ? "USD" : undefined);
    if (input.type === "revenue" && targetCurrency && input.currency !== targetCurrency) {
      throw new AppError(
        "CURRENCY_MISMATCH",
        `Revenue outcomes for this mission must use ${targetCurrency}.`,
        422,
      );
    }
    const inserted = await env.DB.prepare(
      `INSERT OR IGNORE INTO outcome_events
       (id, mission_id, event_id, outcome_type, quantity, value, currency, occurred_at, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    )
      .bind(
        `out_${secureCode(12)}`,
        missionId,
        input.eventId,
        input.type,
        input.quantity,
        input.value ?? null,
        input.currency ?? null,
        occurredAt,
        nowIso(),
      )
      .run();
    if (inserted.meta.changes !== 1) {
      const existing = await env.DB.prepare(
        `SELECT outcome_type, quantity, value, currency, occurred_at
         FROM outcome_events WHERE mission_id = ? AND event_id = ?`,
      )
        .bind(missionId, input.eventId)
        .first<{ outcome_type: string; quantity: number; value: number | null; currency: string | null; occurred_at: string }>();
      const matches =
        existing?.outcome_type === input.type &&
        Number(existing.quantity) === input.quantity &&
        (existing.value ?? undefined) === input.value &&
        (existing.currency ?? undefined) === input.currency &&
        (input.occurredAt === undefined || existing.occurred_at === input.occurredAt);
      if (!matches) {
        throw new AppError("IDEMPOTENCY_CONFLICT", "eventId was already recorded with different outcome data.", 409);
      }
    }
    const current = await getMissionOperation(env, auth, missionId);
    const body = JSON.stringify({
      recorded: inserted.meta.changes === 1,
      duplicate: inserted.meta.changes !== 1,
      missionId,
      eventId: input.eventId,
      attribution: current.attribution,
      outcome: current.outcome,
    });
    await completeIdempotency(env.DB, auth.apiKeyId, endpoint, idemKey, 200, body);
    return { status: 200, body, replayed: false };
  } catch (error) {
    await releaseIdempotency(env.DB, auth.apiKeyId, endpoint, idemKey);
    throw error;
  }
}

export async function recordTrackingClick(env: Env, trackingCode: string): Promise<string> {
  const mission = await env.DB.prepare("SELECT id, destination_url FROM missions WHERE tracking_code = ?")
    .bind(trackingCode)
    .first<{ id: string; destination_url: string }>();
  if (!mission) throw new AppError("MISSION_NOT_FOUND", "Tracking link not found.", 404);
  const day = new Date().toISOString().slice(0, 10);
  await env.DB.prepare(
    `INSERT INTO tracking_daily (mission_id, event_day, clicks) VALUES (?, ?, 1)
     ON CONFLICT(mission_id, event_day) DO UPDATE SET clicks = clicks + 1`,
  )
    .bind(mission.id, day)
    .run();
  return mission.destination_url;
}
