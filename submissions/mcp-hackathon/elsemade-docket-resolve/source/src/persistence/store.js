import { createHash, randomUUID } from "node:crypto";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname } from "node:path";

const EMPTY_STATE = { schemaVersion: 1, cases: {}, events: [], idempotency: {} };

export class CaseStoreError extends Error {
  constructor(code, message, status = 409) {
    super(message);
    this.name = "CaseStoreError";
    this.code = code;
    this.status = status;
  }
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function now() {
  return new Date().toISOString();
}

function caseKey(tenantId, caseId) {
  return `${tenantId}\u0000${caseId}`;
}

function idemKey(tenantId, operation, idempotencyKey) {
  return `${tenantId}\u0000${operation}\u0000${idempotencyKey}`;
}

function mutationKey(tenantId, operation, scope, idempotencyKey) {
  return idemKey(tenantId, operation, scope ? `${scope}:${idempotencyKey}` : idempotencyKey);
}

function requestDigest(value) {
  return createHash("sha256").update(JSON.stringify(value)).digest("hex");
}

function replayOrConflict(state, key, digest) {
  const previous = key && state.idempotency[key];
  if (!previous) return null;
  if (!previous.response) return { ...clone(previous), replayed: true };
  if (previous.requestDigest !== digest) {
    throw new CaseStoreError("IDEMPOTENCY_CONFLICT", "The idempotency key was already used for a different request.", 409);
  }
  return { ...clone(previous.response), replayed: true };
}

function publicCase(record) {
  return clone({
    caseId: record.caseId,
    tenantId: record.tenantId,
    status: record.status,
    agreement: record.agreement,
    evidenceContent: record.evidenceContent,
    evidenceRetrieval: record.evidenceRetrieval,
    review: record.review,
    evaluation: record.evaluation,
    createdAt: record.createdAt,
    updatedAt: record.updatedAt,
    events: record.events,
  });
}

export class CaseStore {
  constructor({ filePath = "data/docket-store.json", clock = now } = {}) {
    this.filePath = filePath;
    this.clock = clock;
    this.writeQueue = Promise.resolve();
    this.idempotencyFlights = new Map();
  }

  async #load() {
    try {
      const parsed = JSON.parse(await readFile(this.filePath, "utf8"));
      return {
        ...EMPTY_STATE,
        ...parsed,
        cases: parsed.cases ?? {},
        events: parsed.events ?? [],
        idempotency: parsed.idempotency ?? {},
      };
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
      return clone(EMPTY_STATE);
    }
  }

  async #persist(state) {
    await mkdir(dirname(this.filePath), { recursive: true });
    const temporary = `${this.filePath}.${process.pid}.${randomUUID()}.tmp`;
    await writeFile(temporary, `${JSON.stringify(state, null, 2)}\n`, {
      encoding: "utf8",
      mode: 0o600,
    });
    await rename(temporary, this.filePath);
  }

  async #transact(mutator) {
    const operation = this.writeQueue.then(async () => {
      const state = await this.#load();
      const result = await mutator(state);
      await this.#persist(state);
      return result;
    });
    this.writeQueue = operation.catch(() => undefined);
    return operation;
  }

  async getCase({ tenantId, caseId }) {
    const state = await this.#load();
    const record = state.cases[caseKey(tenantId, caseId)];
    return record ? publicCase(record) : null;
  }

  async listCases({ tenantId }) {
    const state = await this.#load();
    return Object.values(state.cases)
      .filter((record) => record.tenantId === tenantId)
      .sort((left, right) => right.updatedAt.localeCompare(left.updatedAt))
      .map(publicCase);
  }

  async runIdempotent({ tenantId, operation, scope, idempotencyKey, request }, task) {
    if (!idempotencyKey) return task();
    const key = mutationKey(tenantId, operation, scope, idempotencyKey);
    const digest = requestDigest(request);
    const active = this.idempotencyFlights.get(key);
    if (active) {
      if (active.requestDigest !== digest) {
        throw new CaseStoreError("IDEMPOTENCY_CONFLICT", "The idempotency key was already used for a different request.", 409);
      }
      return { ...clone(await active.promise), replayed: true };
    }

    const promise = (async () => {
      await this.writeQueue;
      const state = await this.#load();
      const replay = replayOrConflict(state, key, digest);
      return replay ?? task();
    })();
    this.idempotencyFlights.set(key, { requestDigest: digest, promise });
    try {
      return await promise;
    } finally {
      if (this.idempotencyFlights.get(key)?.promise === promise) this.idempotencyFlights.delete(key);
    }
  }

  async createCase({ tenantId, subject, agreement, idempotencyKey }) {
    return this.#transact(async (state) => {
      const replayKey = idempotencyKey && idemKey(tenantId, "create-case", idempotencyKey);
      const replay = replayOrConflict(state, replayKey, requestDigest({ agreement }));
      if (replay) return replay;
      const createdAt = this.clock();
      const caseId = `case_${randomUUID().replaceAll("-", "")}`;
      const record = {
        caseId,
        tenantId,
        status: "open",
        agreement: clone(agreement),
        evidenceContent: [],
        evidenceRetrieval: null,
        review: null,
        evaluation: null,
        createdAt,
        updatedAt: createdAt,
        events: [],
      };
      state.cases[caseKey(tenantId, caseId)] = record;
      const result = this.#event(state, record, "case.created", subject, idempotencyKey, {
        agreementId: agreement.agreementId,
        evidenceCount: agreement.evidence.length,
      });
      if (replayKey) state.idempotency[replayKey] = { requestDigest: requestDigest({ agreement }), response: result };
      return result;
    });
  }

  async saveEvidenceRetrieval({ tenantId, caseId, subject, items, errors, idempotencyKey, request = { caseId } }) {
    return this.#transact(async (state) => {
      const replayKey = idempotencyKey && mutationKey(tenantId, "retrieve-evidence", caseId, idempotencyKey);
      const digest = requestDigest(request);
      const replay = replayOrConflict(state, replayKey, digest);
      if (replay) return replay;
      const record = state.cases[caseKey(tenantId, caseId)];
      if (!record) throw new CaseStoreError("CASE_NOT_FOUND", "The case was not found.", 404);
      if (record.status === "resolved") {
        throw new CaseStoreError("CASE_ALREADY_RESOLVED", "A resolved case cannot be changed.", 409);
      }
      const byId = new Map(record.evidenceContent.map((item) => [item.id, item]));
      for (const item of items) byId.set(item.id, clone(item));
      record.evidenceContent = [...byId.values()];
      record.evidenceRetrieval = {
        attemptedAt: this.clock(),
        verifiedCount: items.filter((item) => item.verified).length,
        failureCount: errors.length,
        errors: clone(errors),
      };
      record.updatedAt = this.clock();
      const persisted = this.#event(state, record, "evidence.retrieved", subject, idempotencyKey, {
        evidenceIds: items.map((item) => item.id),
        verifiedCount: items.filter((item) => item.verified).length,
        failureCount: errors.length,
      });
      const result = {
        ...persisted,
        caseId,
        retrieval: { items: clone(items), errors: clone(errors) },
        persisted,
      };
      if (replayKey) state.idempotency[replayKey] = { requestDigest: digest, response: result };
      return result;
    });
  }

  async saveReview({ tenantId, caseId, subject, review, evidenceContent = [], idempotencyKey, request = { caseId, evidenceContent } }) {
    return this.#transact(async (state) => {
      const replayKey = idempotencyKey && mutationKey(tenantId, "review-case", caseId, idempotencyKey);
      const digest = requestDigest(request);
      const replay = replayOrConflict(state, replayKey, digest);
      if (replay) return replay;
      const record = state.cases[caseKey(tenantId, caseId)];
      if (!record) throw new CaseStoreError("CASE_NOT_FOUND", "The case was not found.", 404);
      if (record.status === "resolved") {
        throw new CaseStoreError("CASE_ALREADY_RESOLVED", "A resolved case cannot be changed.", 409);
      }
      const evidenceById = new Map(record.evidenceContent.map((item) => [item.id, item]));
      for (const item of evidenceContent) evidenceById.set(item.id, clone(item));
      record.evidenceContent = [...evidenceById.values()];
      record.review = clone(review);
      record.agreement = { ...record.agreement, findings: clone(review.findings) };
      record.status = review.readyToResolve ? "reviewed" : "manual_review";
      record.updatedAt = this.clock();
      const persisted = this.#event(state, record, "case.reviewed", subject, idempotencyKey, {
        readyToResolve: review.readyToResolve,
        findingCount: review.findings.length,
        evidenceCount: record.evidenceContent.length,
        evaluationId: review.evaluation.evaluationId,
      });
      const result = { ...clone(review), caseId, persisted };
      if (replayKey) state.idempotency[replayKey] = { requestDigest: digest, response: result };
      return result;
    });
  }

  async saveResolution({ tenantId, caseId, subject, evaluation, idempotencyKey }) {
    return this.#transact(async (state) => {
      const replayKey = idempotencyKey && idemKey(tenantId, "resolve-case", `${caseId}:${idempotencyKey}`);
      const replay = replayOrConflict(state, replayKey, requestDigest({ caseId, evaluation }));
      if (replay) return replay;
      const record = state.cases[caseKey(tenantId, caseId)];
      if (!record) throw new CaseStoreError("CASE_NOT_FOUND", "The case was not found.", 404);
      if (record.status === "resolved") {
        throw new CaseStoreError("CASE_ALREADY_RESOLVED", "A resolved case cannot be changed.", 409);
      }
      if (!record.review?.readyToResolve) {
        throw new CaseStoreError("CASE_REVIEW_NOT_READY", "The case requires human review before it can be resolved.", 409);
      }
      record.evaluation = clone(evaluation);
      record.status = evaluation.decision === "manual_review" ? "manual_review" : "resolved";
      record.updatedAt = this.clock();
      const result = this.#event(state, record, "case.resolved", subject, idempotencyKey, {
        decision: evaluation.decision,
        evaluationId: evaluation.evaluationId,
        recommendedReleaseAtomic: evaluation.recommendedReleaseAtomic,
      });
      if (replayKey) state.idempotency[replayKey] = { requestDigest: requestDigest({ caseId, evaluation }), response: result };
      return result;
    });
  }

  #event(state, record, type, subject, idempotencyKey, payload) {
    const event = {
      eventId: `evt_${randomUUID().replaceAll("-", "")}`,
      type,
      actor: subject,
      idempotencyKey: idempotencyKey ?? null,
      createdAt: this.clock(),
      payload: clone(payload),
    };
    record.events.push(event);
    state.events.push({ tenantId: record.tenantId, caseId: record.caseId, ...event });
    return { case: publicCase(record), event };
  }
}
