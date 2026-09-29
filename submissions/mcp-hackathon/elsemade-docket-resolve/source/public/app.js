import { retrievalMessage, retrievalTone } from "./retrieval-status.js";

const demoEvidenceUri = (name) => window.location.protocol === "https:"
  ? `${window.location.origin}/fixtures/evidence/${name}.txt`
  : `https://evidence.example.test/${name}.txt`;

const exampleAgreement = {
  agreementId: "agent-build-2026-019",
  amountAtomic: 250000000,
  asset: { symbol: "USDC", decimals: 6 },
  policy: { conflictSpread: 35, criticalFailureCapPercent: 20 },
  criteria: [
    { id: "api-live", description: "Production API is reachable and returns the documented schema.", weight: 50, critical: true, minimumEvidence: 1 },
    { id: "docs", description: "A new agent can reproduce one real call from the documentation.", weight: 30, critical: false, minimumEvidence: 1 },
    { id: "edge-cases", description: "Invalid and conflicting inputs fail safely with useful errors.", weight: 20, critical: false, minimumEvidence: 1 },
  ],
  evidence: [
    { id: "ev-smoke", criterionId: "api-live", kind: "automated_test", uri: demoEvidenceUri("ev-smoke"), digest: "sha256:7a06fea670b648b816b370c13260b8ea0e43fbe40407f783b7b48be78d6b6188", result: "pass" },
    { id: "ev-docs", criterionId: "docs", kind: "artifact", uri: demoEvidenceUri("ev-docs"), digest: "sha256:7fae5aa4fbdcda611ce6166302da0dddda7fe3628ccd702ed9b214e8b07af9b5", result: "pass" },
    { id: "ev-errors", criterionId: "edge-cases", kind: "automated_test", uri: demoEvidenceUri("ev-errors"), digest: "sha256:825a550e10bc7cb366385f3932effcae419432e1f4c21fc860dc1a405f16c0da", result: "pass" },
  ],
  findings: [],
};

const exampleEvidence = [
  { id: "ev-smoke", content: "FIXTURE_SCORE: 100\nThe production smoke test passed twice." },
  { id: "ev-docs", content: "FIXTURE_SCORE: 90\nThe documented call reproduced with one minor wording ambiguity." },
  { id: "ev-errors", content: "FIXTURE_SCORE: 75\nMalformed requests fail safely; one optional boundary case is absent." },
];

const input = document.querySelector("#agreement-input");
const evidenceInput = document.querySelector("#evidence-input");
const tokenInput = document.querySelector("#agent-token");
const createButton = document.querySelector("#create-button");
const reviewButton = document.querySelector("#review-button");
const retrieveButton = document.querySelector("#retrieve-button");
const resolveButton = document.querySelector("#resolve-button");
const resetButton = document.querySelector("#reset-button");
const caseForm = document.querySelector("#case-form");
const requestState = document.querySelector("#request-state");
const resultPanel = document.querySelector(".result-panel");

let currentCaseId = null;
let currentStatus = null;
let currentReviewReady = false;
let busy = false;

function setState(message, kind = "") {
  requestState.textContent = message;
  requestState.className = kind;
}

function newIdempotencyKey(action) {
  const random = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
  return `ui-${action}-${random}`;
}

function parseJson(value, label) {
  try {
    return JSON.parse(value);
  } catch {
    throw new Error(`${label} must be valid JSON. Fix the JSON and try again.`);
  }
}

function formatAmount(atomic, asset) {
  if (atomic === null || atomic === undefined) return "Pending review";
  const raw = BigInt(atomic);
  const base = 10n ** BigInt(asset.decimals);
  const whole = raw / base;
  let fraction = asset.decimals > 0
    ? (raw % base).toString().padStart(asset.decimals, "0").replace(/0+$/, "")
    : "";
  if (fraction) fraction = fraction.padEnd(Math.min(2, asset.decimals), "0");
  return `${whole.toLocaleString()}${fraction ? `.${fraction}` : ""} ${asset.symbol}`;
}

function decisionLabel(decision) {
  return { release_full: "RELEASE", release_partial: "PARTIAL", hold: "HOLD", manual_review: "REVIEW" }[decision] ?? "FILED";
}

function setBusy(value) {
  busy = value;
  createButton.disabled = value;
  resetButton.disabled = value;
  reviewButton.disabled = value || !currentCaseId || currentStatus === "resolved";
  retrieveButton.disabled = value || !currentCaseId || currentStatus === "resolved";
  resolveButton.disabled = value || !currentCaseId || currentStatus !== "reviewed" || !currentReviewReady;
}

async function api(path, { method = "GET", body, idempotency } = {}) {
  const headers = {};
  if (body !== undefined) headers["content-type"] = "application/json";
  if (idempotency) headers["idempotency-key"] = idempotency;
  const token = tokenInput.value.trim();
  if (token) headers.authorization = `Bearer ${token}`;
  const response = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const message = payload?.error?.message ?? `Request failed with status ${response.status}.`;
    throw new Error(`${payload?.error?.code ?? "REQUEST_FAILED"}: ${message}`);
  }
  return payload;
}

function resetCaseView() {
  currentCaseId = null;
  currentStatus = null;
  currentReviewReady = false;
  resultPanel.classList.remove("has-result");
  document.querySelector("#case-id").textContent = "NO CASE";
  document.querySelector("#case-status").textContent = "UNFILED";
  document.querySelector("#evidence-status").textContent = "No evidence retrieved";
  document.querySelector("#review-status").textContent = "No review run";
  document.querySelector("#retrieval-failures-box").hidden = true;
  document.querySelector("#retrieval-summary").textContent = "";
  document.querySelector("#retrieval-failures").replaceChildren();
  document.querySelector("#release-amount").textContent = "—";
  document.querySelector("#hold-amount").textContent = "—";
  document.querySelector("#release-ratio").textContent = "Open a case to calculate";
  document.querySelector("#decision-stamp").textContent = "READY";
  document.querySelector("#ledger-total").textContent = "—";
  document.querySelector("#criteria-ledger").innerHTML = '<p class="empty-state">The proportional ledger will appear here.</p>';
  document.querySelector("#review-findings").innerHTML = '<p class="empty-state">No AI review has been recorded.</p>';
  document.querySelector("#case-events").innerHTML = '<p class="empty-state">Events will appear after the case is opened.</p>';
  setBusy(false);
}

function resetExample() {
  input.value = JSON.stringify(exampleAgreement, null, 2);
  evidenceInput.value = JSON.stringify(exampleEvidence, null, 2);
  resetCaseView();
  setState("Ready to open a case.");
}

function renderLedger(evaluation) {
  const ledger = document.querySelector("#criteria-ledger");
  if (!evaluation?.criteria?.length) {
    ledger.innerHTML = '<p class="empty-state">The proportional ledger will appear here.</p>';
    return;
  }
  ledger.replaceChildren(...evaluation.criteria.map((criterion) => {
    const row = document.createElement("div");
    row.className = "ledger-item";
    const name = document.createElement("div");
    name.className = "criterion-name";
    const title = document.createElement("strong");
    title.textContent = criterion.description;
    const meta = document.createElement("small");
    meta.textContent = `${criterion.weight}% weight · ${criterion.status}${criterion.critical ? " · critical" : ""}`;
    name.append(title, meta);
    const score = document.createElement("span");
    score.className = "score";
    score.textContent = `${criterion.score}`;
    const earned = document.createElement("span");
    earned.className = "earned";
    earned.textContent = formatAmount(criterion.earnedAtomic, evaluation.asset);
    row.append(name, score, earned);
    return row;
  }));
}

function renderReview(review) {
  const target = document.querySelector("#review-findings");
  if (!review?.reviews?.length) {
    target.innerHTML = '<p class="empty-state">No AI review has been recorded.</p>';
    return;
  }
  target.replaceChildren(...review.reviews.map((finding) => {
    const row = document.createElement("article");
    row.className = `review-item${finding.accepted ? " accepted" : " needs-review"}`;
    const head = document.createElement("div");
    head.className = "review-item-head";
    const title = document.createElement("strong");
    title.textContent = finding.criterionId;
    const verdict = document.createElement("span");
    verdict.textContent = `${finding.verdict.replaceAll("_", " ")} · ${Math.round(finding.confidence * 100)}% confidence`;
    head.append(title, verdict);
    const rationale = document.createElement("p");
    rationale.textContent = finding.rationale;
    const citations = document.createElement("small");
    citations.textContent = finding.evidenceCitations.length
      ? `Cites ${finding.evidenceCitations.map((citation) => citation.evidenceId).join(", ")}`
      : "No evidence citation";
    row.append(head, rationale, citations);
    return row;
  }));
}

function renderEvents(events = []) {
  const target = document.querySelector("#case-events");
  if (!events.length) {
    target.innerHTML = '<p class="empty-state">Events will appear after the case is opened.</p>';
    return;
  }
  target.replaceChildren(...events.map((event) => {
    const row = document.createElement("div");
    row.className = "event-item";
    const type = document.createElement("strong");
    type.textContent = event.type;
    const time = document.createElement("small");
    const timestamp = new Intl.DateTimeFormat(undefined, { dateStyle: "short", timeStyle: "short" }).format(new Date(event.createdAt));
    time.textContent = `${event.actor} · ${timestamp}`;
    row.append(type, time);
    return row;
  }));
}

function renderRetrieval(retrieval) {
  const box = document.querySelector("#retrieval-failures-box");
  const target = document.querySelector("#retrieval-failures");
  const errors = retrieval?.errors ?? [];
  if (!errors.length) {
    box.hidden = true;
    target.replaceChildren();
    document.querySelector("#retrieval-summary").textContent = "";
    return;
  }
  box.hidden = false;
  document.querySelector("#retrieval-summary").textContent = `${retrieval.verifiedCount} verified · ${retrieval.failureCount} failed`;
  target.replaceChildren(...errors.map((failure) => {
    const row = document.createElement("article");
    row.className = "retrieval-failure";
    const head = document.createElement("div");
    head.className = "retrieval-failure-head";
    const evidenceId = document.createElement("strong");
    evidenceId.textContent = failure.evidenceId;
    const code = document.createElement("code");
    code.textContent = failure.code;
    head.append(evidenceId, code);
    const message = document.createElement("p");
    message.textContent = failure.message;
    row.append(head, message);
    return row;
  }));
}

function renderCase(record) {
  currentCaseId = record.caseId;
  currentStatus = record.status;
  currentReviewReady = Boolean(record.review?.readyToResolve);
  resultPanel.classList.add("has-result");
  document.querySelector("#case-id").textContent = record.caseId;
  document.querySelector("#case-status").textContent = record.status.replaceAll("_", " ");
  document.querySelector("#evidence-status").textContent = record.evidenceRetrieval
    ? `${record.evidenceRetrieval.verifiedCount} evidence verified${record.evidenceRetrieval.failureCount ? ` · ${record.evidenceRetrieval.failureCount} failed` : ""}`
    : record.review ? "Evidence notes supplied" : "No external evidence retrieved";
  document.querySelector("#review-status").textContent = record.review
    ? record.review.readyToResolve ? "Review ready" : "Human review required"
    : "No review run";
  renderRetrieval(record.evidenceRetrieval);
  if (record.evaluation) {
    const evaluation = record.evaluation;
    document.querySelector("#decision-stamp").textContent = decisionLabel(evaluation.decision);
    document.querySelector("#release-amount").textContent = formatAmount(evaluation.recommendedReleaseAtomic, evaluation.asset);
    document.querySelector("#hold-amount").textContent = formatAmount(evaluation.recommendedHoldAtomic, evaluation.asset);
    document.querySelector("#release-ratio").textContent = evaluation.settlementRatioBps === null
      ? "Conflicting findings require a human decision"
      : `${(evaluation.settlementRatioBps / 100).toFixed(2)}% of the agreed amount`;
    document.querySelector("#ledger-total").textContent = formatAmount(evaluation.amountAtomic, evaluation.asset);
    renderLedger(evaluation);
  }
  renderReview(record.review);
  renderEvents(record.events);
  setBusy(false);
}

async function openCase() {
  setBusy(true);
  setState("Opening a durable case…");
  try {
    const agreement = parseJson(input.value, "Agreement JSON");
    const created = await api("/v1/cases", { method: "POST", body: { agreement }, idempotency: newIdempotencyKey("create") });
    renderCase(created.case);
    setState("Case opened. Review the cited evidence next.");
  } catch (error) {
    setState(error.message, "error");
    setBusy(false);
  }
}

async function retrieveEvidence() {
  setBusy(true);
  setState("Retrieving and verifying evidence URLs…");
  try {
    const result = await api(`/v1/cases/${encodeURIComponent(currentCaseId)}/retrieve`, { method: "POST", idempotency: newIdempotencyKey("retrieve") });
    const record = await api(`/v1/cases/${encodeURIComponent(currentCaseId)}`);
    renderCase(record);
    setState(retrievalMessage(result.retrieval), retrievalTone(result.retrieval));
  } catch (error) {
    setState(error.message, "error");
    setBusy(false);
  }
}

async function reviewCase() {
  setBusy(true);
  setState("Reviewing cited evidence…");
  try {
    const evidenceContent = parseJson(evidenceInput.value, "Evidence notes");
    const review = await api(`/v1/cases/${encodeURIComponent(currentCaseId)}/review`, {
      method: "POST",
      body: { evidenceContent },
      idempotency: newIdempotencyKey("review"),
    });
    const record = await api(`/v1/cases/${encodeURIComponent(currentCaseId)}`);
    renderCase(record);
    setState(review.readyToResolve ? "Review complete. Resolve the proportional settlement." : "Review complete, but a human decision is required.", review.readyToResolve ? "" : "error");
  } catch (error) {
    setState(error.message, "error");
    setBusy(false);
  }
}

async function resolveCase() {
  setBusy(true);
  setState("Calculating the proportional settlement…");
  try {
    await api(`/v1/cases/${encodeURIComponent(currentCaseId)}/resolve`, { method: "POST", idempotency: newIdempotencyKey("resolve") });
    const record = await api(`/v1/cases/${encodeURIComponent(currentCaseId)}`);
    renderCase(record);
    setState("Settlement recorded. Docket has not moved funds.");
  } catch (error) {
    setState(error.message, "error");
    setBusy(false);
  }
}

createButton.addEventListener("click", openCase);
caseForm.addEventListener("submit", (event) => {
  event.preventDefault();
  if (!busy) openCase();
});
retrieveButton.addEventListener("click", retrieveEvidence);
reviewButton.addEventListener("click", reviewCase);
resolveButton.addEventListener("click", resolveCase);
resetButton.addEventListener("click", resetExample);
resetExample();
