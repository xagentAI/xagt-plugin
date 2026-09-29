"use strict";

const STORAGE_KEYS = Object.freeze({
  clientNonce: "agentonomy.miniapp.client_nonce",
  csrf: "agentonomy.miniapp.csrf_token",
  scope: "agentonomy.miniapp.storage_scope",
  draft: "agentonomy.miniapp.draft",
  currentClientMessage: "agentonomy.miniapp.current_client_message_id",
  scroll: "agentonomy.miniapp.scroll_top",
  returnMarker: "agentonomy.miniapp.return_marker",
  fundingAmount: "agentonomy.miniapp.polymarket.funding_amount",
  fundingIdempotency: "agentonomy.miniapp.polymarket.funding_idempotency_key",
  fundingOperation: "agentonomy.miniapp.polymarket.funding_operation_id",
  fundingCreateUncertain: "agentonomy.miniapp.polymarket.funding_create_uncertain",
  fundingRecoveryStatus: "agentonomy.miniapp.polymarket.funding_recovery_status",
  fundingPreparedMessage: "agentonomy.miniapp.polymarket.funding_prepared_message_id",
  fundingMessageAmount: "agentonomy.miniapp.polymarket.funding_message_amount",
  signingPreview: "agentonomy.miniapp.polymarket.signing_preview_id",
  signingSession: "agentonomy.miniapp.polymarket.signing_session_id",
  signingSessionPreview: "agentonomy.miniapp.polymarket.signing_session_preview_id",
  signingUnknownPreview: "agentonomy.miniapp.polymarket.signing_unknown_preview_id",
});

const TERMINAL_RUN_STATUSES = new Set([
  "completed",
  "failed",
  "stopped",
  "cancelled",
  "canceled",
  "error",
]);

const STREAM_EVENT_TYPES = [
  "token",
  "message.delta",
  "tool",
  "tool.started",
  "tool.completed",
  "run.completed",
  "run.failed",
  "run.stopped",
  "run.cancelled",
  "run.canceled",
  "run.error",
  "done",
  "error",
];

const LIVE_OPERATION_ID = /^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$/;
const LIVE_IDEMPOTENCY_KEY = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const STABLE_STORAGE_SCOPE = /^[A-Za-z0-9_-]{43}$/;
const FUNDING_AMOUNT = /^(?:0|[1-9][0-9]*)(?:\.[0-9]{1,6})?$/;
const CANONICAL_FUNDING_AMOUNT = /^(?:0|[1-9][0-9]*)\.[0-9]{6}$/;
const FUNDING_MESSAGE_PATTERNS = Object.freeze([
  /^(?:请\s*)?(?:帮我\s*)?(?:确认\s*)?(?:现在\s*)?(?:给\s*polymarket\s*)?(?:充值|入金)\s*((?:0|[1-9][0-9]*)(?:\.[0-9]{1,6})?)\s*(?:usdc|u)(?:\s*(?:到|至|给)\s*polymarket)?\s*(?:吧)?[。！!]*$/iu,
  /^确认(?:创建并执行|执行)(?:本次)?\s*((?:0|[1-9][0-9]*)(?:\.[0-9]{1,6})?)\s*(?:usdc|u)\s*polymarket\s*funding(?:\s+operation)?[。！!]*$/iu,
  /^(?:please\s+)?(?:confirm(?:\s+and\s+execute)?\s+)?(?:fund|funding|deposit)\s+(?:polymarket\s+)?((?:0|[1-9][0-9]*)(?:\.[0-9]{1,6})?)\s*(?:usdc|u)(?:\s+(?:to|into)\s+polymarket)?[.!]*$/iu,
  /^(?:please\s+)?confirm(?:\s+and\s+execute)?\s+((?:0|[1-9][0-9]*)(?:\.[0-9]{1,6})?)\s*(?:usdc|u)\s+polymarket\s+funding(?:\s+operation)?[.!]*$/iu,
]);
const SIGNING_CAPABILITY = /^[A-Za-z0-9_-]{1,256}$/;
const FUNDING_AUTO_ACTIONS = new Set([
  "confirm",
  "processing",
  "check_core_status",
  "check_bridge_status",
  "finalize",
]);
const FUNDING_PREPARE_TOOLS = new Set([
  "prepare_polymarket_funding_ui",
  "mcp__clink_node__prepare_polymarket_funding_ui",
]);
const FUNDING_MANUAL_ACTIONS = new Set([
  "manual_review",
  "manual_reconcile_inflight",
]);
const FUNDING_RECOVERY_STORAGE_KEYS = new Set([
  STORAGE_KEYS.fundingAmount,
  STORAGE_KEYS.fundingIdempotency,
  STORAGE_KEYS.fundingOperation,
  STORAGE_KEYS.fundingCreateUncertain,
  STORAGE_KEYS.fundingRecoveryStatus,
]);
const LEGACY_FUNDING_MUTATION_KEYS = Object.freeze([
  STORAGE_KEYS.fundingIdempotency,
  STORAGE_KEYS.fundingOperation,
  STORAGE_KEYS.fundingCreateUncertain,
  STORAGE_KEYS.fundingRecoveryStatus,
]);
const LEGACY_SCOPE_RECONCILIATION = "legacy_scope_unresolved";
const FUNDING_AUTO_MAX_ATTEMPTS = 24;
const FUNDING_AUTO_MAX_MS = 60_000;
const FUNDING_AUTO_DELAY_MS = 2_500;


class MiniAppRequestError extends Error {
  constructor(status, reason) {
    super("miniapp_request_failed");
    this.name = "MiniAppRequestError";
    this.status = status;
    this.reason = reason;
  }
}


function encodeNonce(bytes) {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
  let output = "";
  let buffer = 0;
  let bits = 0;
  for (const value of bytes) {
    buffer = (buffer << 8) | value;
    bits += 8;
    while (bits >= 6) {
      bits -= 6;
      output += alphabet[(buffer >>> bits) & 63];
    }
  }
  if (bits > 0) output += alphabet[(buffer << (6 - bits)) & 63];
  return output;
}


function newClientNonce(cryptoApi) {
  const bytes = new Uint8Array(16);
  cryptoApi.getRandomValues(bytes);
  return encodeNonce(bytes);
}


function newClientMessageId(cryptoApi) {
  if (typeof cryptoApi.randomUUID === "function") {
    return cryptoApi.randomUUID();
  }
  const bytes = new Uint8Array(16);
  cryptoApi.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, "0"));
  return [
    hex.slice(0, 4).join(""),
    hex.slice(4, 6).join(""),
    hex.slice(6, 8).join(""),
    hex.slice(8, 10).join(""),
    hex.slice(10).join(""),
  ].join("-");
}


async function defaultStorageScope(cryptoApi, csrf) {
  if (!cryptoApi?.subtle || typeof TextEncoder === "undefined") return "";
  const digest = await cryptoApi.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(csrf),
  );
  return Array.from(new Uint8Array(digest), (value) =>
    value.toString(16).padStart(2, "0")
  ).join("");
}


function createMiniApp(dependencies = {}) {
  const documentApi = dependencies.document || globalThis.document;
  const windowApi = dependencies.window || globalThis.window;
  const fetchApi = dependencies.fetch || globalThis.fetch.bind(globalThis);
  const EventSourceApi = dependencies.EventSource || globalThis.EventSource;
  const sessionStore = dependencies.sessionStorage || globalThis.sessionStorage;
  const localStore = dependencies.localStorage || globalThis.localStorage;
  const cryptoApi = dependencies.crypto || globalThis.crypto;
  const setTimeoutApi = dependencies.setTimeout || globalThis.setTimeout;
  const clearTimeoutApi = dependencies.clearTimeout || globalThis.clearTimeout;
  const nowApi = dependencies.now || Date.now;
  const deriveStorageScope = dependencies.deriveStorageScope || (
    (csrf) => defaultStorageScope(cryptoApi, csrf)
  );

  const elements = {
    transcript: documentApi.getElementById("miniapp-transcript"),
    composer: documentApi.getElementById("miniapp-composer"),
    input: documentApi.getElementById("miniapp-input"),
    send: documentApi.getElementById("miniapp-send"),
    status: documentApi.getElementById("miniapp-status"),
    toolProgress: documentApi.getElementById("miniapp-tool-progress"),
    toolProgressToggle: documentApi.getElementById("miniapp-tool-progress-toggle"),
    toolProgressSummary: documentApi.getElementById("miniapp-tool-progress-summary"),
    toolProgressList: documentApi.getElementById("miniapp-tool-progress-list"),
    identity: documentApi.getElementById("miniapp-identity"),
    operations: documentApi.getElementById("miniapp-operations"),
    operationsToggle: documentApi.getElementById("miniapp-operations-toggle"),
    operationsClose: documentApi.getElementById("miniapp-operations-close"),
    logout: documentApi.getElementById("miniapp-logout"),
    fundingAmount: documentApi.getElementById("polymarket-funding-amount"),
    fundingConfirm: documentApi.getElementById("polymarket-funding-confirm"),
    fundingStatus: documentApi.getElementById("polymarket-funding-status"),
    signingPreview: documentApi.getElementById("polymarket-signing-preview"),
    signingOpen: documentApi.getElementById("polymarket-signing-open"),
    signingCheck: documentApi.getElementById("polymarket-signing-check"),
    signingStatus: documentApi.getElementById("polymarket-signing-status"),
  };
  const hasLegacyLiveOperationSurface = [
    elements.fundingAmount,
    elements.fundingConfirm,
    elements.fundingStatus,
    elements.signingPreview,
    elements.signingOpen,
    elements.signingCheck,
    elements.signingStatus,
  ].every(Boolean);

  let wired = false;
  let sendPromise = null;
  let eventSource = null;
  let streamingTurn = null;
  const recoveryFlights = new Map();
  const runPollTimers = new Map();
  let explicitRetryAllowed = false;
  let storageScope = "";
  let stableFundingScopeReady = false;
  let pendingLegacyFundingScope = "";
  let provisionalClientMessageId = null;
  let subjectOperationPending = false;
  let liveOperationPromise = null;
  let liveOperationsDisabled = !hasLegacyLiveOperationSurface;
  let liveOperationGeneration = 0;
  let fundingProjection = null;
  let fundingTerminalVerifiedOperationId = null;
  let fundingAutoTimer = null;
  let fundingAutoOperationId = null;
  let fundingAutoAttempts = 0;
  let fundingAutoStartedAt = 0;
  let pendingFundingIntent = null;
  let preparedSigningWalletSurface = null;
  let conversationGeneration = 0;
  let sessionEpoch = 0;
  const toolProgressItems = new Map();

  function telegramWebApp() {
    return windowApi?.Telegram?.WebApp || null;
  }

  function conversationSessionReady() {
    const webApp = telegramWebApp();
    return !webApp?.initData || stableFundingScopeReady;
  }

  function requireConversationSession() {
    if (conversationSessionReady()) return true;
    setStatus(
      "Secure sign-in is unavailable. Reopen Agentonomy from Telegram.",
      true,
    );
    return false;
  }

  function telegramExternalLinkApi() {
    const telegram = telegramWebApp();
    if (
      typeof telegram?.openLink !== "function" ||
      typeof telegram?.isVersionAtLeast !== "function"
    ) return null;
    try {
      return telegram.isVersionAtLeast("6.1") === true ? telegram : null;
    } catch (_error) {
      return null;
    }
  }

  function openWalletSurfaceNow(url) {
    const telegram = telegramExternalLinkApi();
    if (telegram) telegram.openLink(url);
    else windowApi.location.assign(url);
  }

  function setStatus(text, warning = false) {
    elements.status.textContent = text;
    elements.status.classList.toggle("warning", warning);
  }

  function setToolProgressExpanded(expanded) {
    const isExpanded = Boolean(expanded) && toolProgressItems.size > 0;
    elements.toolProgressToggle.setAttribute("aria-expanded", String(isExpanded));
    elements.toolProgressList.hidden = !isExpanded;
  }

  function resetToolProgress() {
    toolProgressItems.clear();
    elements.toolProgressList.replaceChildren();
    elements.toolProgressSummary.textContent = "";
    elements.toolProgress.hidden = true;
    setToolProgressExpanded(false);
  }

  function safeToolLabel(data) {
    const candidate = typeof data.tool === "string"
      ? data.tool
      : typeof data.name === "string" ? data.name : "operation";
    if (!candidate || candidate !== candidate.trim() || candidate.length > 128) {
      return "operation";
    }
    return candidate;
  }

  function updateToolProgress(label, status) {
    let entry = toolProgressItems.get(label);
    if (!entry) {
      entry = { element: documentApi.createElement("li"), status: "running" };
      toolProgressItems.set(label, entry);
      elements.toolProgressList.append(entry.element);
    }
    entry.status = status;
    entry.element.textContent = (
      `${label} · ${status === "completed" ? "Completed" : "Running"}`
    );
    elements.toolProgress.hidden = false;
    elements.toolProgressSummary.textContent = (
      `Working · ${toolProgressItems.size} ${toolProgressItems.size === 1 ? "operation" : "operations"}`
    );
    setToolProgressExpanded(true);
  }

  function finishToolProgress(runStatus) {
    if (toolProgressItems.size === 0) return;
    const normalizedStatus = runStatus === "canceled"
      ? "cancelled"
      : runStatus === "error" ? "failed" : runStatus;
    const hasIncompleteTool = Array.from(toolProgressItems.values()).some(
      (entry) => entry.status !== "completed",
    );
    const incompleteLabels = {
      completed: "No completion received",
      failed: "Interrupted",
      stopped: "Stopped",
      cancelled: "Cancelled",
    };
    for (const [label, entry] of toolProgressItems) {
      if (entry.status === "completed") continue;
      entry.status = normalizedStatus;
      entry.element.textContent = (
        `${label} · ${incompleteLabels[normalizedStatus] || "Interrupted"}`
      );
    }
    const count = `${toolProgressItems.size} ${toolProgressItems.size === 1 ? "operation" : "operations"}`;
    const summaries = {
      completed: hasIncompleteTool
        ? `Run completed · ${count}`
        : `Completed ${count}`,
      failed: `Run failed · ${count}`,
      stopped: `Run stopped · ${count}`,
      cancelled: `Run cancelled · ${count}`,
    };
    elements.toolProgressSummary.textContent = summaries[normalizedStatus] || `Run ended · ${count}`;
    setToolProgressExpanded(false);
  }

  function csrfToken() {
    return sessionStore.getItem(STORAGE_KEYS.csrf) || "";
  }

  async function establishStorageScope(
    token = csrfToken(),
    stableScope = null,
    expectedSessionEpoch = null,
  ) {
    if (
      expectedSessionEpoch !== null &&
      expectedSessionEpoch !== sessionEpoch
    ) return false;
    const previousScope = storageScope;
    let legacyScopeDerived = false;
    if (!token) {
      storageScope = "";
      stableFundingScopeReady = false;
      pendingLegacyFundingScope = "";
      sessionStore.removeItem(STORAGE_KEYS.scope);
      if (previousScope) {
        cancelFundingAutoProgress();
        removeLocal(STORAGE_KEYS.fundingPreparedMessage);
        removeLocal(STORAGE_KEYS.fundingMessageAmount);
      }
      return true;
    }
    try {
      const savedStableScope = sessionStore.getItem(STORAGE_KEYS.scope);
      const cachedStableScope = stableScope === null
        ? STABLE_STORAGE_SCOPE.test(savedStableScope || "")
          ? savedStableScope
          : ""
        : "";
      const serverStableScope = stableScope !== null &&
        STABLE_STORAGE_SCOPE.test(stableScope)
        ? stableScope
        : "";
      const derived = serverStableScope || cachedStableScope || (
        stableScope === null ? await deriveStorageScope(token) : ""
      );
      if (
        expectedSessionEpoch !== null &&
        expectedSessionEpoch !== sessionEpoch
      ) return false;
      legacyScopeDerived = !serverStableScope && !cachedStableScope;
      storageScope = typeof derived === "string" && derived.length <= 128
        ? derived
        : "";
      stableFundingScopeReady = Boolean(
        serverStableScope && storageScope === serverStableScope,
      );
    } catch (_error) {
      storageScope = "";
      stableFundingScopeReady = false;
    }
    if (storageScope) {
      sessionStore.setItem(STORAGE_KEYS.scope, storageScope);
      if (legacyScopeDerived) {
        pendingLegacyFundingScope = storageScope;
      } else if (stableFundingScopeReady && pendingLegacyFundingScope) {
        const legacyScope = pendingLegacyFundingScope;
        pendingLegacyFundingScope = "";
        if (legacyFundingMutationExists(legacyScope)) {
          writeLocal(STORAGE_KEYS.fundingCreateUncertain, "true");
          writeLocal(
            STORAGE_KEYS.fundingRecoveryStatus,
            LEGACY_SCOPE_RECONCILIATION,
          );
        }
      }
      if (provisionalClientMessageId) {
        writeLocal(STORAGE_KEYS.currentClientMessage, provisionalClientMessageId);
        provisionalClientMessageId = null;
      }
    } else {
      stableFundingScopeReady = false;
      sessionStore.removeItem(STORAGE_KEYS.scope);
    }
    if (previousScope && previousScope !== storageScope) {
      cancelFundingAutoProgress();
      subjectOperationPending = false;
      preparedSigningWalletSurface = null;
      fundingProjection = null;
      fundingTerminalVerifiedOperationId = null;
      removeLocal(STORAGE_KEYS.fundingPreparedMessage);
      removeLocal(STORAGE_KEYS.fundingMessageAmount);
    }
    return true;
  }

  function localEnvelope(raw) {
    try {
      const envelope = JSON.parse(raw);
      return envelope &&
        typeof envelope === "object" &&
        typeof envelope.scope === "string" &&
        typeof envelope.value === "string"
        ? envelope
        : null;
    } catch (_error) {
      return null;
    }
  }

  function localStorageKey(key) {
    return FUNDING_RECOVERY_STORAGE_KEYS.has(key) && storageScope
      ? `${key}:${storageScope}`
      : key;
  }

  function legacyFundingMutationExists(scope) {
    if (!scope || scope.length > 128) return false;
    return LEGACY_FUNDING_MUTATION_KEYS.some((key) => {
      const namespaced = localEnvelope(
        localStore.getItem(`${key}:${scope}`),
      );
      if (namespaced?.scope === scope) return true;
      return localEnvelope(localStore.getItem(key))?.scope === scope;
    });
  }

  function readLocal(key) {
    if (!storageScope) return null;
    const physicalKey = localStorageKey(key);
    let raw = localStore.getItem(physicalKey);
    if (raw === null && FUNDING_RECOVERY_STORAGE_KEYS.has(key)) {
      const legacyRaw = localStore.getItem(key);
      const legacyEnvelope = localEnvelope(legacyRaw);
      if (legacyEnvelope?.scope === storageScope) {
        localStore.setItem(physicalKey, legacyRaw);
        localStore.removeItem(key);
        raw = legacyRaw;
      }
    }
    const envelope = localEnvelope(raw);
    return envelope?.scope === storageScope ? envelope.value : null;
  }

  function writeLocal(key, value) {
    if (!storageScope) return;
    localStore.setItem(localStorageKey(key), JSON.stringify({
      scope: storageScope,
      value: String(value),
    }));
  }

  function removeLocal(key) {
    if (!FUNDING_RECOVERY_STORAGE_KEYS.has(key)) {
      localStore.removeItem(key);
      return;
    }
    if (!storageScope) return;
    localStore.removeItem(localStorageKey(key));
    const legacyRaw = localStore.getItem(key);
    if (localEnvelope(legacyRaw)?.scope === storageScope) {
      localStore.removeItem(key);
    }
  }

  function currentClientMessageId() {
    return readLocal(STORAGE_KEYS.currentClientMessage) || (
      storageScope ? null : provisionalClientMessageId
    );
  }

  function currentStateMatches(clientMessageId, generation) {
    return generation === conversationGeneration &&
      currentClientMessageId() === clientMessageId;
  }

  function setCurrentClientMessage(clientMessageId) {
    if (currentClientMessageId() !== clientMessageId) conversationGeneration += 1;
    if (storageScope) {
      provisionalClientMessageId = null;
      writeLocal(STORAGE_KEYS.currentClientMessage, clientMessageId);
    } else {
      provisionalClientMessageId = clientMessageId;
    }
    return conversationGeneration;
  }

  function clearCurrentClientMessage(clientMessageId, generation) {
    if (!currentStateMatches(clientMessageId, generation)) return null;
    removeLocal(STORAGE_KEYS.currentClientMessage);
    provisionalClientMessageId = null;
    conversationGeneration += 1;
    return conversationGeneration;
  }

  function clientNonce() {
    let nonce = sessionStore.getItem(STORAGE_KEYS.clientNonce);
    if (!nonce) {
      nonce = newClientNonce(cryptoApi);
      sessionStore.setItem(STORAGE_KEYS.clientNonce, nonce);
    }
    return nonce;
  }

  async function requestJson(path, options = {}) {
    const response = await fetchApi(path, {
      credentials: "same-origin",
      cache: "no-store",
      ...options,
    });
    if (response.status === 204) return null;
    let payload = null;
    try {
      payload = await response.json();
    } catch (_error) {
      throw new MiniAppRequestError(response.status, "miniapp_unavailable");
    }
    if (!response.ok) {
      const reason = payload && typeof payload.detail === "string"
        ? payload.detail
        : "miniapp_unavailable";
      throw new MiniAppRequestError(response.status, reason);
    }
    return payload;
  }

  async function revokeStaleSessionExchange(csrfTokenValue) {
    if (typeof csrfTokenValue !== "string" || !csrfTokenValue) return;
    try {
      await requestJson("/miniapp/api/session", {
        method: "DELETE",
        headers: { "X-Agentonomy-CSRF": csrfTokenValue },
      });
    } catch (_error) {
      // A newer cookie will reject this stale token; no local state is restored.
    }
  }

  async function exchangeSession(initData, expectedSessionEpoch = null) {
    const result = await requestJson("/miniapp/api/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        init_data: initData,
        client_nonce: clientNonce(),
      }),
    });
    if (
      !result ||
      typeof result.csrf_token !== "string" ||
      typeof result.storage_scope !== "string" ||
      !STABLE_STORAGE_SCOPE.test(result.storage_scope)
    ) {
      throw new MiniAppRequestError(503, "miniapp_unavailable");
    }
    if (
      expectedSessionEpoch !== null &&
      expectedSessionEpoch !== sessionEpoch
    ) {
      await revokeStaleSessionExchange(result.csrf_token);
      return null;
    }
    sessionStore.setItem(STORAGE_KEYS.csrf, result.csrf_token);
    const established = await establishStorageScope(
      result.csrf_token,
      result.storage_scope,
      expectedSessionEpoch,
    );
    const stale = expectedSessionEpoch !== null &&
      expectedSessionEpoch !== sessionEpoch;
    if (!established || stale) {
      if (stale) await revokeStaleSessionExchange(result.csrf_token);
      return null;
    }
    const savedDraft = readLocal(STORAGE_KEYS.draft);
    if (!elements.input.value && savedDraft) elements.input.value = savedDraft;
    else if (elements.input.value) writeLocal(STORAGE_KEYS.draft, elements.input.value);
    const username = result.user && typeof result.user.username === "string"
      ? result.user.username
      : null;
    elements.identity.textContent = username ? `@${username}` : "Telegram account";
    return result;
  }

  function showStableFundingScopeRequired() {
    if (!hasLegacyLiveOperationSurface) return;
    setCardStatus(
      elements.fundingStatus,
      "Reopen Agentonomy from Telegram to safely restore funding.",
      true,
    );
    updateLiveOperationControls();
  }

  async function ensureStableFundingScope(webApp, expectedSessionEpoch = null) {
    if (stableFundingScopeReady) return true;
    if (!webApp || !webApp.initData) {
      showStableFundingScopeRequired();
      return false;
    }
    try {
      const exchanged = await exchangeSession(
        webApp.initData,
        expectedSessionEpoch,
      );
      if (!exchanged) return false;
    } catch (_error) {
      if (
        expectedSessionEpoch !== null &&
        expectedSessionEpoch !== sessionEpoch
      ) return false;
      showStableFundingScopeRequired();
      return false;
    }
    if (!stableFundingScopeReady) {
      showStableFundingScopeRequired();
      return false;
    }
    return true;
  }

  function roleLabel(role) {
    if (role === "user") return "You";
    if (role === "tool") return "Operation";
    return "Agentonomy";
  }

  function accountAction(content) {
    if (typeof content !== "string") return null;
    const matches = [...content.matchAll(/https?:\/\/[^\s<>"']+/giu)];
    if (matches.length !== 1) return null;
    const raw = matches[0][0].replace(/[\])},.!?;:。，；！？`）】》」』]+$/u, "");
    try {
      const expectedOrigin = new URL(windowApi.location.origin).origin;
      const parsed = new URL(raw);
      const rawAuthority = raw.match(/^https?:\/\/([^/?#]*)/iu)?.[1] || "";
      if (
        parsed.origin !== expectedOrigin ||
        rawAuthority.includes("@") ||
        parsed.username ||
        parsed.password ||
        (parsed.pathname !== "/account" && !parsed.pathname.startsWith("/account/"))
      ) return null;
      return {
        url: parsed.href,
        content: content.replace(raw, "").replace(/[:：]\s*$/u, "").trim(),
      };
    } catch (_error) {
      return null;
    }
  }

  function renderTurn(role, content, options = {}) {
    const safeRole = role === "user" ? "user" : role === "tool" ? "tool" : "assistant";
    const turn = documentApi.createElement("article");
    turn.className = `chat-turn ${safeRole}`;
    if (options.streaming) {
      turn.classList.add("streaming");
    }
    const label = documentApi.createElement("span");
    label.className = "turn-label";
    label.textContent = roleLabel(safeRole);
    const body = documentApi.createElement("p");
    body.className = "turn-content";
    const action = safeRole === "assistant" ? accountAction(content) : null;
    body.textContent = action?.content ?? (typeof content === "string" ? content : "");
    turn.append(label, body);
    if (action) {
      const button = documentApi.createElement("button");
      button.className = "turn-action";
      button.type = "button";
      button.textContent = "Open Clink spending account";
      button.addEventListener("click", () => {
        saveReturnState();
        openWalletSurfaceNow(action.url);
      });
      turn.append(button);
    }
    elements.transcript.append(turn);
    return { turn, body };
  }

  function renderHistory(messages) {
    elements.transcript.replaceChildren();
    const safeMessages = Array.isArray(messages) ? messages : [];
    if (safeMessages.length === 0) {
      renderTurn(
        "assistant",
        "Your continuous thread is ready. Tell Agentonomy what you want to do.",
      );
    }
    for (const message of safeMessages) {
      renderTurn(message && message.role, message && message.content);
    }
    streamingTurn = null;
    restoreScroll();
  }

  function restoreScroll() {
    const value = Number.parseInt(readLocal(STORAGE_KEYS.scroll) || "", 10);
    if (Number.isFinite(value) && value >= 0) elements.transcript.scrollTop = value;
  }

  function saveReturnState() {
    writeLocal(STORAGE_KEYS.draft, elements.input.value);
    writeLocal(STORAGE_KEYS.scroll, elements.transcript.scrollTop);
    writeLocal(STORAGE_KEYS.returnMarker, Date.now());
  }

  function validLiveId(value) {
    return typeof value === "string" && LIVE_OPERATION_ID.test(value);
  }

  function savedLiveId(key) {
    const value = readLocal(key);
    if (!value) return null;
    if (validLiveId(value)) return value;
    removeLocal(key);
    return null;
  }

  function canonicalFundingAmount(value) {
    if (typeof value !== "string") return null;
    const normalized = value.trim();
    if (
      !normalized ||
      normalized.length > 78 ||
      !FUNDING_AMOUNT.test(normalized)
    ) return null;
    const [whole, fraction = ""] = normalized.split(".");
    if (whole.length + 6 > 78) return null;
    const canonical = `${whole}.${fraction.padEnd(6, "0")}`;
    return canonical === "0.000000" ? null : canonical;
  }

  function clearPreparedFundingMessage(clientMessageId = null) {
    const preparedMessageId = readLocal(STORAGE_KEYS.fundingPreparedMessage);
    if (clientMessageId === null || preparedMessageId === clientMessageId) {
      removeLocal(STORAGE_KEYS.fundingPreparedMessage);
    }
    const binding = fundingMessageAmountBinding();
    if (
      clientMessageId === null ||
      binding?.client_message_id === clientMessageId
    ) removeLocal(STORAGE_KEYS.fundingMessageAmount);
  }

  function fundingMessageAmountBinding() {
    const raw = readLocal(STORAGE_KEYS.fundingMessageAmount);
    if (!raw) return null;
    try {
      const binding = JSON.parse(raw);
      if (
        !binding ||
        typeof binding !== "object" ||
        !validLiveId(binding.client_message_id) ||
        canonicalFundingAmount(binding.amount) !== binding.amount
      ) throw new Error("invalid_funding_message_amount");
      return binding;
    } catch (_error) {
      removeLocal(STORAGE_KEYS.fundingMessageAmount);
      return null;
    }
  }

  function messageFundingAmount(message) {
    if (typeof message !== "string") return null;
    const candidates = [];
    for (const pattern of FUNDING_MESSAGE_PATTERNS) {
      const match = message.match(pattern);
      if (match) candidates.push(match[1]);
    }
    if (candidates.length !== 1) return null;
    return canonicalFundingAmount(candidates[0]);
  }

  function latestAssistantFundingAmount(output) {
    if (typeof output !== "string" || !output.trim()) return null;
    const candidates = [];
    const tokenPattern = /https?:\/\/[^\s<>"']+/giu;
    for (const match of output.matchAll(tokenPattern)) {
      const before = output.slice(0, match.index);
      if (/(?:href|src)\s*=\s*["']?$/iu.test(before)) return null;
      const candidate = match[0].replace(
        /[\])},.!?;:。，；！？`）】》」』]+$/u,
        "",
      );
      if (candidate) candidates.push(candidate);
    }
    if (candidates.length !== 1) return null;
    const candidate = candidates[0];
    try {
      const rawAuthority = candidate.match(/^https?:\/\/([^/?#]*)/iu)?.[1] || "";
      const rawBeforeFragment = candidate.split("#", 1)[0];
      const expectedOrigin = new URL(windowApi.location.origin).origin;
      const parsed = new URL(candidate);
      const fragmentMatch = parsed.hash.match(
        /^#funding=((?:0|[1-9][0-9]*)\.[0-9]{6})$/u,
      );
      if (
        !["http:", "https:"].includes(parsed.protocol) ||
        rawAuthority.includes("@") ||
        rawBeforeFragment.includes("?") ||
        parsed.origin !== expectedOrigin ||
        parsed.username ||
        parsed.password ||
        parsed.pathname !== "/miniapp/" ||
        parsed.search ||
        !fragmentMatch ||
        canonicalFundingAmount(fragmentMatch[1]) !== fragmentMatch[1]
      ) return null;
      return fragmentMatch[1];
    } catch (_error) {
      return null;
    }
  }

  function compactFundingAmount(value) {
    const canonical = canonicalFundingAmount(value);
    if (!canonical) return "";
    return canonical.replace(/\.0+$/, "").replace(/(\.[0-9]*?)0+$/, "$1");
  }

  function cancelFundingAutoProgress(resetBudget = true) {
    if (fundingAutoTimer !== null) {
      clearTimeoutApi(fundingAutoTimer);
      fundingAutoTimer = null;
    }
    if (resetBudget) {
      fundingAutoOperationId = null;
      fundingAutoAttempts = 0;
      fundingAutoStartedAt = 0;
    }
  }

  function consumeFundingFragment() {
    if (!hasLegacyLiveOperationSurface) return;
    const hash = typeof windowApi?.location?.hash === "string"
      ? windowApi.location.hash
      : "";
    if (!hash) return;
    let intent = null;
    try {
      const entries = [...new URLSearchParams(hash.slice(1)).entries()];
      if (entries.length === 1 && entries[0][0] === "funding") {
        const value = entries[0][1];
        if (value === "") intent = { amount: null };
        else if (
          CANONICAL_FUNDING_AMOUNT.test(value) &&
          canonicalFundingAmount(value) === value
        ) intent = { amount: value };
      }
    } catch (_error) {
      intent = null;
    }
    let fragmentCleared = false;
    if (typeof windowApi?.history?.replaceState === "function") {
      const pathname = typeof windowApi.location.pathname === "string"
        ? windowApi.location.pathname
        : "/miniapp/";
      const search = typeof windowApi.location.search === "string"
        ? windowApi.location.search
        : "";
      try {
        windowApi.history.replaceState(null, "", pathname + search);
        fragmentCleared = true;
      } catch (_error) {
        fragmentCleared = false;
      }
    }
    if (!fragmentCleared || !intent) return;
    pendingFundingIntent = intent;
    applyPendingFundingIntent();
  }

  function applyPendingFundingIntent() {
    if (!hasLegacyLiveOperationSurface) return;
    if (!pendingFundingIntent) return;
    openOperations(true);
    if (!stableFundingScopeReady) {
      setCardStatus(
        elements.fundingStatus,
        "Reopen Agentonomy from Telegram to safely restore funding.",
        true,
      );
      updateLiveOperationControls();
      return;
    }
    if (pendingFundingIntent.amount !== null) {
      const existingOperation = savedLiveId(STORAGE_KEYS.fundingOperation);
      const createUncertain = readLocal(STORAGE_KEYS.fundingCreateUncertain);
      if (!existingOperation && createUncertain !== "true") {
        const previousAmount = readLocal(STORAGE_KEYS.fundingAmount);
        if (previousAmount && previousAmount !== pendingFundingIntent.amount) {
          removeLocal(STORAGE_KEYS.fundingIdempotency);
        }
        elements.fundingAmount.value = pendingFundingIntent.amount;
        writeLocal(STORAGE_KEYS.fundingAmount, pendingFundingIntent.amount);
      }
    }
    if (storageScope || pendingFundingIntent.amount === null) {
      pendingFundingIntent = null;
    }
    updateLiveOperationControls();
  }

  function humanStage(value, fallback = "unknown") {
    if (typeof value !== "string" || !value) return fallback;
    return value.replaceAll("_", " ");
  }

  function setCardStatus(element, text, warning = false) {
    element.textContent = text;
    element.classList.toggle("warning", warning);
  }

  function showLegacyFundingReconciliationBlock() {
    setCardStatus(
      elements.fundingStatus,
      "A previous funding request needs reconciliation. No new funding was started.",
      true,
    );
  }

  function captureLiveOperationContext(options = {}) {
    return {
      generation: liveOperationGeneration,
      scope: storageScope,
      previewId: options.previewId || null,
      fundingAmount: options.fundingAmount || null,
    };
  }

  function liveOperationContextMatches(context) {
    if (!hasLegacyLiveOperationSurface) return false;
    if (
      !context ||
      context.generation !== liveOperationGeneration ||
      context.scope !== storageScope
    ) return false;
    if (
      context.previewId !== null &&
      (
        elements.signingPreview.value.trim() !== context.previewId ||
        readLocal(STORAGE_KEYS.signingPreview) !== context.previewId
      )
    ) return false;
    return context.fundingAmount === null || (
      elements.fundingAmount.value.trim() === context.fundingAmount &&
      readLocal(STORAGE_KEYS.fundingAmount) === context.fundingAmount
    );
  }

  function fundingOperationContextMatches(context, operationId) {
    return liveOperationContextMatches(context) &&
      savedLiveId(STORAGE_KEYS.fundingOperation) === operationId;
  }

  function fundingCreateContextMatches(
    context,
    amount,
    idempotencyKey,
  ) {
    return liveOperationContextMatches(context) &&
      savedLiveId(STORAGE_KEYS.fundingOperation) === null &&
      readLocal(STORAGE_KEYS.fundingAmount) === amount &&
      readLocal(STORAGE_KEYS.fundingIdempotency) === idempotencyKey &&
      readLocal(STORAGE_KEYS.fundingCreateUncertain) === "true";
  }

  function updateLiveOperationControls() {
    if (!hasLegacyLiveOperationSurface) return;
    const pending = liveOperationPromise !== null;
    const operationId = stableFundingScopeReady
      ? savedLiveId(STORAGE_KEYS.fundingOperation)
      : null;
    const canonicalAmount = canonicalFundingAmount(elements.fundingAmount.value);
    const createUncertain = stableFundingScopeReady &&
      readLocal(STORAGE_KEYS.fundingCreateUncertain) === "true";
    const recoveryHeld = stableFundingScopeReady &&
      Boolean(readLocal(STORAGE_KEYS.fundingRecoveryStatus));
    const previewId = elements.signingPreview.value.trim();
    const sessionId = conversationSessionReady()
      ? savedLiveId(STORAGE_KEYS.signingSession)
      : null;
    const sessionPreview = conversationSessionReady()
      ? readLocal(STORAGE_KEYS.signingSessionPreview)
      : null;
    const unknownPreview = conversationSessionReady()
      ? readLocal(STORAGE_KEYS.signingUnknownPreview)
      : null;
    const signingSurfaceReady = (
      preparedSigningWalletSurface?.previewId === previewId
    );
    elements.fundingAmount.disabled = (
      liveOperationsDisabled || !stableFundingScopeReady || pending ||
      fundingAutoTimer !== null ||
      Boolean(operationId) || createUncertain
    );
    elements.signingPreview.disabled = liveOperationsDisabled || pending;
    let fundingLabel = "Enter funding amount";
    let fundingDisabled = (
      liveOperationsDisabled || !stableFundingScopeReady || pending ||
      fundingAutoTimer !== null
    );
    if (createUncertain && !operationId) {
      fundingLabel = readLocal(STORAGE_KEYS.fundingRecoveryStatus) ===
        LEGACY_SCOPE_RECONCILIATION
        ? "Funding reconciliation required"
        : "Check funding status";
      fundingDisabled = true;
    } else if (!operationId) {
      if (canonicalAmount) {
        fundingLabel = `Confirm and fund ${compactFundingAmount(canonicalAmount)} USDC`;
      } else fundingDisabled = true;
    } else if (
      fundingProjection &&
      fundingProjection.operation_id === operationId &&
      fundingProjectionIsTerminal(fundingProjection)
    ) {
      fundingLabel = fundingProjection.status === "finalized"
        ? "Funding complete"
        : "Funding stopped";
      fundingDisabled = true;
    } else if (fundingAutoTimer !== null) {
      fundingLabel = "Funding in progress…";
    } else if (
      recoveryHeld ||
      !fundingProjection ||
      fundingProjection.operation_id !== operationId ||
      FUNDING_MANUAL_ACTIONS.has(fundingProjection.next_action)
    ) {
      fundingLabel = "Check funding status";
    } else {
      fundingLabel = "Continue funding";
    }
    elements.fundingConfirm.textContent = fundingLabel;
    elements.fundingConfirm.disabled = fundingDisabled;
    elements.signingOpen.disabled = (
      liveOperationsDisabled || pending || !validLiveId(previewId) ||
      previewId === unknownPreview ||
      Boolean(sessionId && sessionPreview === previewId && !signingSurfaceReady)
    );
    elements.signingCheck.disabled = (
      liveOperationsDisabled || pending || !sessionId
    );
  }

  function disableLiveOperations() {
    cancelFundingAutoProgress();
    liveOperationGeneration += 1;
    liveOperationsDisabled = true;
    preparedSigningWalletSurface = null;
    if (!hasLegacyLiveOperationSurface) return;
    setCardStatus(
      elements.fundingStatus,
      "Live Polymarket funding is unavailable in this environment.",
      true,
    );
    setCardStatus(
      elements.signingStatus,
      "Live Polymarket order signing is unavailable in this environment.",
      true,
    );
    updateLiveOperationControls();
  }

  function withLiveOperationFlight(action) {
    if (!hasLegacyLiveOperationSurface || liveOperationsDisabled) {
      return Promise.resolve(null);
    }
    if (liveOperationPromise) return liveOperationPromise;
    let actionResult;
    try {
      actionResult = action();
    } catch (error) {
      actionResult = Promise.reject(error);
    }
    const tracked = Promise.resolve(actionResult).finally(() => {
      if (liveOperationPromise === tracked) {
        liveOperationPromise = null;
        updateLiveOperationControls();
      }
    });
    liveOperationPromise = tracked;
    updateLiveOperationControls();
    return tracked;
  }

  function renderFundingProjection(result, expectedOperationId = null) {
    if (!result || !validLiveId(result.operation_id)) {
      throw new Error("invalid_funding_projection");
    }
    const savedOperation = savedLiveId(STORAGE_KEYS.fundingOperation);
    if (
      (expectedOperationId && result.operation_id !== expectedOperationId) ||
      (savedOperation && result.operation_id !== savedOperation)
    ) {
      throw new Error("invalid_funding_projection");
    }
    writeLocal(STORAGE_KEYS.fundingOperation, result.operation_id);
    fundingProjection = result;
    fundingTerminalVerifiedOperationId = null;
    if (
      fundingProjectionIsTerminal(result) ||
      FUNDING_MANUAL_ACTIONS.has(result.next_action)
    ) cancelFundingAutoProgress();
    setCardStatus(
      elements.fundingStatus,
      [
        `Funding ${humanStage(result.status)}`,
        `Chain ${humanStage(result.chain_status)}`,
        `Bridge ${humanStage(result.bridge_status)}`,
        `Buying power ${humanStage(result.buying_power_status)}`,
      ].join(" · "),
      ["failed", "unknown", "manual_review"].includes(result.status),
    );
    updateLiveOperationControls();
    return result;
  }

  function fundingProjectionIsTerminal(result) {
    return Boolean(
      result && (
        result.status === "finalized" && result.next_action === "complete" ||
        ["failed", "released"].includes(result.status) &&
          result.next_action === "terminal"
      )
    );
  }

  function handleLiveOperationNotFound(error) {
    if (error instanceof MiniAppRequestError && error.status === 404) {
      disableLiveOperations();
      return true;
    }
    return false;
  }

  function fundingRecoveryAllowsAutomatic(result, markRecovery = false) {
    if (
      readLocal(STORAGE_KEYS.fundingRecoveryStatus) ===
      LEGACY_SCOPE_RECONCILIATION
    ) {
      showLegacyFundingReconciliationBlock();
      return false;
    }
    if (markRecovery) {
      const heldStatus = readLocal(STORAGE_KEYS.fundingRecoveryStatus);
      if (!heldStatus) {
        writeLocal(STORAGE_KEYS.fundingRecoveryStatus, result.status || "unknown");
      } else if (
        heldStatus !== "unknown" &&
        heldStatus !== result.status
      ) {
        removeLocal(STORAGE_KEYS.fundingRecoveryStatus);
      }
      return false;
    }
    const heldStatus = readLocal(STORAGE_KEYS.fundingRecoveryStatus);
    if (!heldStatus) return true;
    if (heldStatus === "unknown") {
      writeLocal(STORAGE_KEYS.fundingRecoveryStatus, result.status || "unknown");
      return false;
    }
    if (heldStatus === result.status) return false;
    removeLocal(STORAGE_KEYS.fundingRecoveryStatus);
    return true;
  }

  function fundingCanAdvanceAutomatically(result) {
    return Boolean(
      stableFundingScopeReady && result &&
      validLiveId(result.operation_id) &&
      result.operation_id === savedLiveId(STORAGE_KEYS.fundingOperation) &&
      FUNDING_AUTO_ACTIONS.has(result.next_action) &&
      !readLocal(STORAGE_KEYS.fundingRecoveryStatus) &&
      readLocal(STORAGE_KEYS.fundingCreateUncertain) !== "true"
    );
  }

  function handleFundingReadError(error) {
    cancelFundingAutoProgress();
    if (handleLiveOperationNotFound(error)) return;
    if (
      error instanceof MiniAppRequestError &&
      [401, 403].includes(error.status)
    ) {
      setCardStatus(
        elements.fundingStatus,
        "Your funding session cannot be verified. Reopen Agentonomy from Telegram.",
        true,
      );
    } else {
      setCardStatus(
        elements.fundingStatus,
        "Funding status is temporarily unavailable. Nothing was submitted again.",
        true,
      );
    }
    updateLiveOperationControls();
  }

  async function fetchFundingStatus(options = {}) {
    if (!stableFundingScopeReady) return null;
    const operationId = savedLiveId(STORAGE_KEYS.fundingOperation);
    if (!operationId || liveOperationsDisabled) return null;
    const requestContext = captureLiveOperationContext();
    try {
      const result = await requestJson(
        `/miniapp/api/operations/polymarket/funding/${encodeURIComponent(operationId)}`,
        { headers: { "Accept": "application/json" } },
      );
      if (!fundingOperationContextMatches(requestContext, operationId)) {
        return null;
      }
      const projection = renderFundingProjection(result, operationId);
      fundingTerminalVerifiedOperationId = fundingProjectionIsTerminal(projection)
        ? projection.operation_id
        : null;
      const automaticAllowed = fundingRecoveryAllowsAutomatic(
        projection,
        options.markRecovery === true,
      );
      updateLiveOperationControls();
      if (options.scheduleAutomatic === true && automaticAllowed) {
        scheduleFundingAutoProgress(projection);
      }
      return projection;
    } catch (error) {
      if (!fundingOperationContextMatches(requestContext, operationId)) {
        return null;
      }
      handleFundingReadError(error);
      return null;
    }
  }

  function handleFundingCreateError(error) {
    cancelFundingAutoProgress();
    const definitivelyRejected = (
      error instanceof MiniAppRequestError &&
      [400, 401, 403, 404, 422, 429].includes(error.status)
    );
    if (!definitivelyRejected) {
      writeLocal(STORAGE_KEYS.fundingCreateUncertain, "true");
      setCardStatus(
        elements.fundingStatus,
        "Funding creation is uncertain. It was not repeated; server-side reconciliation is required.",
        true,
      );
      updateLiveOperationControls();
      return;
    }
    removeLocal(STORAGE_KEYS.fundingCreateUncertain);
    removeLocal(STORAGE_KEYS.fundingIdempotency);
    removeLocal(STORAGE_KEYS.fundingAmount);
    if (handleLiveOperationNotFound(error)) return;
    if (error.status === 400 || error.status === 422) {
      setCardStatus(
        elements.fundingStatus,
        "Correct the USDC amount, then confirm funding again.",
        true,
      );
    } else if ([401, 403].includes(error.status)) {
      setCardStatus(
        elements.fundingStatus,
        "Reopen Agentonomy from Telegram before confirming funding.",
        true,
      );
    } else {
      setCardStatus(
        elements.fundingStatus,
        "Funding was not accepted. Nothing was submitted automatically.",
        true,
      );
    }
    updateLiveOperationControls();
  }

  async function createFundingOperation() {
    if (liveOperationsDisabled || !stableFundingScopeReady) return null;
    const existingOperation = savedLiveId(STORAGE_KEYS.fundingOperation);
    if (existingOperation) return fetchFundingStatus();
    if (readLocal(STORAGE_KEYS.fundingCreateUncertain) === "true") {
      if (
        readLocal(STORAGE_KEYS.fundingRecoveryStatus) ===
        LEGACY_SCOPE_RECONCILIATION
      ) showLegacyFundingReconciliationBlock();
      else {
        setCardStatus(
          elements.fundingStatus,
          "Funding creation is uncertain. It was not repeated and will not be repeated automatically.",
          true,
        );
      }
      updateLiveOperationControls();
      return null;
    }
    const amount = canonicalFundingAmount(elements.fundingAmount.value);
    if (!amount) {
      setCardStatus(
        elements.fundingStatus,
        "Enter a positive USDC decimal with no more than six decimal places.",
        true,
      );
      return null;
    }
    elements.fundingAmount.value = amount;
    let idempotencyKey = readLocal(STORAGE_KEYS.fundingIdempotency);
    if (!idempotencyKey || !LIVE_IDEMPOTENCY_KEY.test(idempotencyKey)) {
      idempotencyKey = newClientMessageId(cryptoApi);
      writeLocal(STORAGE_KEYS.fundingIdempotency, idempotencyKey);
    }
    writeLocal(STORAGE_KEYS.fundingAmount, amount);
    const requestContext = captureLiveOperationContext({
      fundingAmount: amount,
    });
    setCardStatus(elements.fundingStatus, "Starting funding once…");
    writeLocal(STORAGE_KEYS.fundingCreateUncertain, "true");
    try {
      const result = await requestJson(
        "/miniapp/api/operations/polymarket/funding",
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Agentonomy-CSRF": csrfToken(),
          },
          body: JSON.stringify({
            amount_usdc: amount,
            idempotency_key: idempotencyKey,
          }),
        },
      );
      if (!fundingCreateContextMatches(
        requestContext,
        amount,
        idempotencyKey,
      )) return null;
      const projection = renderFundingProjection(result);
      removeLocal(STORAGE_KEYS.fundingCreateUncertain);
      return projection;
    } catch (error) {
      if (!fundingCreateContextMatches(
        requestContext,
        amount,
        idempotencyKey,
      )) return null;
      handleFundingCreateError(error);
      return null;
    }
  }

  async function continueFundingOperation(expectedOperationId = null) {
    if (liveOperationsDisabled || !stableFundingScopeReady) return null;
    const operationId = savedLiveId(STORAGE_KEYS.fundingOperation);
    if (!operationId || (expectedOperationId && operationId !== expectedOperationId)) {
      cancelFundingAutoProgress();
      setCardStatus(elements.fundingStatus, "Funding status must be checked first.", true);
      return null;
    }
    const requestContext = captureLiveOperationContext();
    setCardStatus(elements.fundingStatus, "Continuing this funding operation once…");
    try {
      const result = await requestJson(
        `/miniapp/api/operations/polymarket/funding/${encodeURIComponent(operationId)}/continue`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Agentonomy-CSRF": csrfToken(),
          },
          body: JSON.stringify({}),
        },
      );
      if (!fundingOperationContextMatches(requestContext, operationId)) {
        return null;
      }
      return renderFundingProjection(result, operationId);
    } catch (error) {
      if (!fundingOperationContextMatches(requestContext, operationId)) {
        return null;
      }
      cancelFundingAutoProgress();
      if (handleLiveOperationNotFound(error)) return null;
      if (
        error instanceof MiniAppRequestError &&
        [400, 401, 403].includes(error.status)
      ) {
        const message = error.status === 400
          ? "Funding could not continue. Check the funding details."
          : "Your funding session cannot be verified. Reopen Agentonomy from Telegram.";
        setCardStatus(elements.fundingStatus, message, true);
        updateLiveOperationControls();
        return null;
      }
      writeLocal(
        STORAGE_KEYS.fundingRecoveryStatus,
        fundingProjection?.status || "unknown",
      );
      setCardStatus(
        elements.fundingStatus,
        "Funding continuation is uncertain. Checking status without repeating it…",
        true,
      );
      await fetchFundingStatus({ markRecovery: true });
      updateLiveOperationControls();
      return null;
    }
  }

  function scheduleFundingAutoProgress(result) {
    if (
      !stableFundingScopeReady ||
      !fundingCanAdvanceAutomatically(result) ||
      liveOperationsDisabled
    ) {
      cancelFundingAutoProgress();
      updateLiveOperationControls();
      return;
    }
    if (fundingAutoTimer !== null) return;
    if (fundingAutoOperationId !== result.operation_id) {
      fundingAutoOperationId = result.operation_id;
      fundingAutoAttempts = 0;
      fundingAutoStartedAt = nowApi();
    }
    if (
      fundingAutoAttempts >= FUNDING_AUTO_MAX_ATTEMPTS ||
      nowApi() - fundingAutoStartedAt >= FUNDING_AUTO_MAX_MS
    ) {
      cancelFundingAutoProgress();
      setCardStatus(
        elements.fundingStatus,
        "Automatic progress paused. Tap Continue funding to check and continue safely.",
        true,
      );
      updateLiveOperationControls();
      return;
    }
    const operationId = result.operation_id;
    const generation = liveOperationGeneration;
    const scope = storageScope;
    fundingAutoTimer = setTimeoutApi(async () => {
      fundingAutoTimer = null;
      if (
        generation !== liveOperationGeneration ||
        scope !== storageScope ||
        operationId !== savedLiveId(STORAGE_KEYS.fundingOperation) ||
        liveOperationsDisabled ||
        !stableFundingScopeReady
      ) {
        cancelFundingAutoProgress();
        updateLiveOperationControls();
        return;
      }
      fundingAutoAttempts += 1;
      await withLiveOperationFlight(async () => {
        const projection = await continueFundingOperation(operationId);
        if (projection) scheduleFundingAutoProgress(projection);
      });
    }, FUNDING_AUTO_DELAY_MS);
    updateLiveOperationControls();
  }

  async function runFundingAction(initialProjection = null) {
    if (
      liveOperationsDisabled ||
      !stableFundingScopeReady ||
      fundingAutoTimer !== null
    ) return null;
    const existingOperation = savedLiveId(STORAGE_KEYS.fundingOperation);
    if (existingOperation) {
      const projection = (
        initialProjection?.operation_id === existingOperation
          ? initialProjection
          : await fetchFundingStatus()
      );
      if (!projection || readLocal(STORAGE_KEYS.fundingRecoveryStatus)) return projection;
      if (!fundingCanAdvanceAutomatically(projection)) return projection;
      const advanced = await continueFundingOperation(existingOperation);
      if (advanced) scheduleFundingAutoProgress(advanced);
      return advanced;
    }
    const created = await createFundingOperation();
    if (!created || !fundingCanAdvanceAutomatically(created)) return created;
    const advanced = await continueFundingOperation(created.operation_id);
    if (advanced) scheduleFundingAutoProgress(advanced);
    return advanced;
  }

  async function executePreparedFundingIntent(
    output,
    clientMessageId,
    expectedGeneration,
  ) {
    if (
      !stableFundingScopeReady ||
      !currentStateMatches(null, expectedGeneration)
    ) return null;
    const binding = fundingMessageAmountBinding();
    if (
      readLocal(STORAGE_KEYS.fundingPreparedMessage) !== clientMessageId ||
      binding?.client_message_id !== clientMessageId
    ) {
      clearPreparedFundingMessage(clientMessageId);
      return null;
    }
    const amount = latestAssistantFundingAmount(output);
    if (!amount || amount !== binding.amount) {
      clearPreparedFundingMessage(clientMessageId);
      return null;
    }
    const pendingLiveOperation = liveOperationPromise;
    if (pendingLiveOperation) {
      try {
        await pendingLiveOperation;
      } catch (_error) {
        // Existing live-operation errors already render their bounded recovery state.
      }
    }
    if (
      !stableFundingScopeReady ||
      !currentStateMatches(null, expectedGeneration) ||
      readLocal(STORAGE_KEYS.fundingPreparedMessage) !== clientMessageId ||
      fundingMessageAmountBinding()?.client_message_id !== clientMessageId
    ) return null;
    if (liveOperationsDisabled) {
      clearPreparedFundingMessage(clientMessageId);
      return null;
    }
    return withLiveOperationFlight(async () => {
      if (
        !stableFundingScopeReady ||
        !currentStateMatches(null, expectedGeneration) ||
        readLocal(STORAGE_KEYS.fundingPreparedMessage) !== clientMessageId ||
        fundingMessageAmountBinding()?.client_message_id !== clientMessageId
      ) return null;
      clearPreparedFundingMessage(clientMessageId);
      openOperations(true);
      const existingOperation = savedLiveId(STORAGE_KEYS.fundingOperation);
      if (existingOperation) {
        const projection = await fetchFundingStatus();
        if (!projection) return null;
        if (!fundingProjectionIsTerminal(projection)) {
          return runFundingAction(projection);
        }
        if (readLocal(STORAGE_KEYS.fundingIdempotency) === clientMessageId) {
          return projection;
        }
        cancelFundingAutoProgress();
        liveOperationGeneration += 1;
        fundingProjection = null;
        fundingTerminalVerifiedOperationId = null;
        for (const key of [
          STORAGE_KEYS.fundingAmount,
          STORAGE_KEYS.fundingIdempotency,
          STORAGE_KEYS.fundingOperation,
          STORAGE_KEYS.fundingCreateUncertain,
          STORAGE_KEYS.fundingRecoveryStatus,
        ]) removeLocal(key);
      } else if (readLocal(STORAGE_KEYS.fundingCreateUncertain) === "true") {
        return runFundingAction();
      }
      const savedIdempotency = readLocal(STORAGE_KEYS.fundingIdempotency);
      const savedAmount = canonicalFundingAmount(
        readLocal(STORAGE_KEYS.fundingAmount),
      );
      if (
        savedIdempotency &&
        LIVE_IDEMPOTENCY_KEY.test(savedIdempotency) &&
        (
          savedIdempotency !== clientMessageId ||
          savedAmount !== amount
        )
      ) {
        setCardStatus(
          elements.fundingStatus,
          "A previous funding request is still unresolved. Retry or check that same request before starting another.",
          true,
        );
        updateLiveOperationControls();
        return null;
      }
      elements.fundingAmount.value = amount;
      writeLocal(STORAGE_KEYS.fundingAmount, amount);
      writeLocal(STORAGE_KEYS.fundingIdempotency, clientMessageId);
      return runFundingAction();
    });
  }

  function validatedSigningUrl(value) {
    if (typeof value !== "string" || !value || value !== value.trim()) return null;
    try {
      const expectedOrigin = new URL(windowApi.location.origin).origin;
      const parsed = new URL(value, expectedOrigin);
      const fragment = [...new URLSearchParams(parsed.hash.slice(1)).entries()];
      if (
        parsed.origin !== expectedOrigin ||
        parsed.username ||
        parsed.password ||
        parsed.pathname !== "/execution/polymarket/order-signing-console/" ||
        parsed.search ||
        fragment.length !== 1 ||
        fragment[0][0] !== "access_token" ||
        !SIGNING_CAPABILITY.test(fragment[0][1])
      ) return null;
      return parsed.href;
    } catch (_error) {
      return null;
    }
  }

  function renderSigningProjection(result) {
    if (!result || !validLiveId(result.session_id)) {
      throw new MiniAppRequestError(503, "miniapp_unavailable");
    }
    const status = humanStage(result.status);
    if (result.status === "submitted" && validLiveId(result.execution_id)) {
      setCardStatus(
        elements.signingStatus,
        `Signing submitted · Execution ${result.execution_id}`,
      );
    } else if (result.status === "unknown") {
      setCardStatus(
        elements.signingStatus,
        "Order state is unknown. Create a new preview or reconcile it manually.",
        true,
      );
    } else {
      setCardStatus(
        elements.signingStatus,
        `Signing ${status}`,
        ["rejected", "blocked", "expired", "failed"].includes(result.status),
      );
    }
    return result;
  }

  async function fetchSigningStatus() {
    if (!conversationSessionReady()) return null;
    const sessionId = savedLiveId(STORAGE_KEYS.signingSession);
    if (!sessionId || liveOperationsDisabled) return null;
    const sessionPreview = readLocal(STORAGE_KEYS.signingSessionPreview);
    const requestContext = captureLiveOperationContext({
      previewId: validLiveId(sessionPreview) ? sessionPreview : null,
    });
    try {
      const result = await requestJson(
        `/miniapp/api/operations/polymarket/order-signing/${encodeURIComponent(sessionId)}`,
        { headers: { "Accept": "application/json" } },
      );
      if (!liveOperationContextMatches(requestContext)) return null;
      return renderSigningProjection(result);
    } catch (error) {
      if (!liveOperationContextMatches(requestContext)) return null;
      if (error instanceof MiniAppRequestError && error.status === 404) {
        disableLiveOperations();
      } else {
        setCardStatus(
          elements.signingStatus,
          "Signing status is unavailable. Nothing was submitted again.",
          true,
        );
      }
      return null;
    }
  }

  async function openOrderSigning() {
    if (!requireConversationSession() || liveOperationsDisabled) return null;
    const previewId = elements.signingPreview.value.trim();
    if (!validLiveId(previewId)) {
      setCardStatus(elements.signingStatus, "Enter a valid current preview ID.", true);
      return null;
    }
    if (preparedSigningWalletSurface?.previewId === previewId) {
      const signingUrl = preparedSigningWalletSurface.url;
      preparedSigningWalletSurface = null;
      openWalletSurfaceNow(signingUrl);
      return null;
    }
    const unknownPreview = readLocal(STORAGE_KEYS.signingUnknownPreview);
    if (unknownPreview === previewId) {
      setCardStatus(
        elements.signingStatus,
        "This preview has an unknown result. Use a new preview or reconcile it manually.",
        true,
      );
      return null;
    }
    const existingSession = savedLiveId(STORAGE_KEYS.signingSession);
    if (
      existingSession &&
      readLocal(STORAGE_KEYS.signingSessionPreview) === previewId
    ) return fetchSigningStatus();
    writeLocal(STORAGE_KEYS.signingPreview, previewId);
    const requestContext = captureLiveOperationContext({ previewId });
    setCardStatus(elements.signingStatus, "Creating one signing session…");
    try {
      const result = await requestJson(
        "/miniapp/api/operations/polymarket/order-signing",
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Agentonomy-CSRF": csrfToken(),
          },
          body: JSON.stringify({ preview_id: previewId }),
        },
      );
      if (!liveOperationContextMatches(requestContext)) return null;
      renderSigningProjection(result);
      writeLocal(STORAGE_KEYS.signingSession, result.session_id);
      writeLocal(STORAGE_KEYS.signingSessionPreview, previewId);
      updateLiveOperationControls();
      if (result.status !== "pending_browser_signature") return result;
      const signingUrl = validatedSigningUrl(result.signing_url);
      if (!signingUrl) {
        setCardStatus(
          elements.signingStatus,
          "The signing link is invalid. Check status; nothing was repeated.",
          true,
        );
        return result;
      }
      saveReturnState();
      if (telegramExternalLinkApi()) {
        preparedSigningWalletSurface = { previewId, url: signingUrl };
        setCardStatus(
          elements.signingStatus,
          "Order signing is ready. Tap again to open it in your browser.",
        );
      } else {
        windowApi.location.assign(signingUrl);
      }
      return result;
    } catch (error) {
      if (!liveOperationContextMatches(requestContext)) return null;
      if (
        error instanceof MiniAppRequestError &&
        error.reason === "miniapp_order_signing_outcome_unknown"
      ) {
        writeLocal(STORAGE_KEYS.signingUnknownPreview, previewId);
        setCardStatus(
          elements.signingStatus,
          "Signing result is unknown. Use a new preview or reconcile it manually.",
          true,
        );
      } else if (error instanceof MiniAppRequestError && error.status === 404) {
        disableLiveOperations();
      } else {
        setCardStatus(
          elements.signingStatus,
          "Signing session was not confirmed. Nothing was repeated.",
          true,
        );
      }
      updateLiveOperationControls();
      return null;
    }
  }

  function restoreLiveOperationState() {
    if (!hasLegacyLiveOperationSurface) return;
    elements.fundingAmount.value = stableFundingScopeReady
      ? readLocal(STORAGE_KEYS.fundingAmount) || ""
      : "";
    elements.signingPreview.value = readLocal(STORAGE_KEYS.signingPreview) || "";
    if (stableFundingScopeReady) {
      applyPendingFundingIntent();
      if (
        readLocal(STORAGE_KEYS.fundingRecoveryStatus) ===
        LEGACY_SCOPE_RECONCILIATION
      ) showLegacyFundingReconciliationBlock();
    }
    else {
      setCardStatus(
        elements.fundingStatus,
        "Reopen Agentonomy from Telegram to safely restore funding.",
        true,
      );
    }
    updateLiveOperationControls();
  }

  async function refreshSavedLiveOperations() {
    if (
      !hasLegacyLiveOperationSurface ||
      !conversationSessionReady() ||
      liveOperationsDisabled
    ) return null;
    return withLiveOperationFlight(async () => {
      if (
        stableFundingScopeReady &&
        savedLiveId(STORAGE_KEYS.fundingOperation)
      ) {
        await fetchFundingStatus({ scheduleAutomatic: true });
      }
      if (!liveOperationsDisabled && savedLiveId(STORAGE_KEYS.signingSession)) {
        await fetchSigningStatus();
      }
      return null;
    });
  }

  async function openSubjectBoundOperation({ endpoint, opening, unavailable }) {
    if (!requireConversationSession()) return;
    if (subjectOperationPending) return;
    const requestSessionEpoch = sessionEpoch;
    const requestScope = storageScope;
    subjectOperationPending = true;
    saveReturnState();
    setStatus(opening);
    try {
      const result = await requestJson(endpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Agentonomy-CSRF": csrfToken(),
        },
        body: JSON.stringify({}),
      });
      if (
        requestSessionEpoch !== sessionEpoch ||
        requestScope !== storageScope ||
        !conversationSessionReady()
      ) return;
      if (!result || typeof result.url !== "string" || !result.url) {
        throw new MiniAppRequestError(503, "miniapp_unavailable");
      }
      openWalletSurfaceNow(result.url);
    } catch (_error) {
      if (
        requestSessionEpoch !== sessionEpoch ||
        requestScope !== storageScope ||
        !conversationSessionReady()
      ) return;
      subjectOperationPending = false;
      setStatus(unavailable, true);
    }
  }

  async function openAccountOperation() {
    await openSubjectBoundOperation({
      endpoint: "/miniapp/api/operations/account",
      opening: "Opening Wallet & permissions…",
      unavailable: (
        "Wallet & permissions is temporarily unavailable. Your draft is safe."
      ),
    });
  }

  async function openPolymarketOperation() {
    await openSubjectBoundOperation({
      endpoint: "/miniapp/api/operations/polymarket",
      opening: "Opening Polymarket account…",
      unavailable: (
        "Polymarket account is temporarily unavailable. Your draft is safe."
      ),
    });
  }

  function closeEventStream() {
    if (eventSource && typeof eventSource.close === "function") eventSource.close();
    eventSource = null;
  }

  function cancelRunPoll(clientMessageId = null) {
    if (clientMessageId !== null) {
      const timerId = runPollTimers.get(clientMessageId);
      if (timerId !== undefined) clearTimeoutApi(timerId);
      runPollTimers.delete(clientMessageId);
      return;
    }
    for (const timerId of runPollTimers.values()) clearTimeoutApi(timerId);
    runPollTimers.clear();
  }

  function scheduleRunPoll(clientMessageId) {
    if (!clientMessageId || runPollTimers.has(clientMessageId)) return;
    const timerId = setTimeoutApi(async () => {
      runPollTimers.delete(clientMessageId);
      await recoverCurrentRun(clientMessageId);
    }, 1000);
    runPollTimers.set(clientMessageId, timerId);
  }

  function eventData(event) {
    try {
      const parsed = JSON.parse(event.data);
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch (_error) {
      return {};
    }
  }

  function eventDelta(data) {
    for (const key of ["delta", "token", "text", "content"]) {
      if (typeof data[key] === "string") return data[key];
    }
    return "";
  }

  function handleStreamEvent(type, event, clientMessageId, expectedGeneration) {
    if (
      !conversationSessionReady() ||
      !currentStateMatches(clientMessageId, expectedGeneration)
    ) return;
    const data = eventData(event);
    if (type === "token" || type === "message.delta") {
      const delta = eventDelta(data);
      if (!delta || (!streamingTurn && !delta.trim())) return;
      if (!streamingTurn) streamingTurn = renderTurn("assistant", "", { streaming: true });
      streamingTurn.body.textContent += delta;
      setStatus("Agentonomy is responding…");
      elements.transcript.scrollTop = elements.transcript.scrollHeight;
      return;
    }
    if (type === "tool" || type.startsWith("tool.")) {
      const completed = type === "tool.completed" || data.status === "completed";
      const toolLabel = safeToolLabel(data);
      if (type === "tool.completed" && FUNDING_PREPARE_TOOLS.has(toolLabel)) {
        writeLocal(STORAGE_KEYS.fundingPreparedMessage, clientMessageId);
      }
      updateToolProgress(toolLabel, completed ? "completed" : "running");
      setStatus("Agentonomy is working…");
      return;
    }
    if (type === "done" || type.startsWith("run.")) {
      handleStreamDisconnect(clientMessageId, expectedGeneration);
    }
  }

  function openEventStream(clientMessageId) {
    if (!conversationSessionReady() || !EventSourceApi || !clientMessageId) return;
    const streamGeneration = conversationGeneration;
    if (!currentStateMatches(clientMessageId, streamGeneration)) return;
    cancelRunPoll(clientMessageId);
    closeEventStream();
    eventSource = new EventSourceApi(
      `/miniapp/api/chat/messages/${encodeURIComponent(clientMessageId)}/events`,
    );
    for (const type of STREAM_EVENT_TYPES) {
      eventSource.addEventListener(type, (event) => {
        if (type === "error") {
          handleStreamDisconnect(clientMessageId, streamGeneration);
          return;
        }
        handleStreamEvent(type, event, clientMessageId, streamGeneration);
      });
    }
  }

  async function loadChat(options = {}) {
    const expectedGeneration = options.expectedGeneration ?? conversationGeneration;
    const expectedClientMessageId = options.expectedClientMessageId === undefined
      ? currentClientMessageId()
      : options.expectedClientMessageId;
    const snapshot = await requestJson("/miniapp/api/chat", {
      headers: { "Accept": "application/json" },
    });
    if (!currentStateMatches(expectedClientMessageId, expectedGeneration)) {
      return snapshot;
    }
    renderHistory(snapshot.messages);
    const latest = snapshot.latest;
    const stored = currentClientMessageId();
    const current = stored || (options.recoverLatest !== false &&
      latest && latest.status === "accepted" ? latest.client_message_id : null
    );
    if (current) {
      setCurrentClientMessage(current);
      await recoverCurrentRun(current);
    } else if (!options.preserveStatus) {
      setStatus("Connected · conversation is ready");
    }
    return snapshot;
  }

  function normalizedTerminalStatus(status) {
    if (status === "canceled") return "cancelled";
    if (status === "error") return "failed";
    return status;
  }

  function terminalStatusMessage(status) {
    const messages = {
      completed: "Response completed.",
      failed: "Response failed. Nothing was resent.",
      stopped: "Response stopped. Nothing was resent.",
      cancelled: "Response cancelled. Nothing was resent.",
    };
    return messages[normalizedTerminalStatus(status)] || "Response ended.";
  }

  async function recoverRun(clientMessageId, expectedGeneration) {
    try {
      const run = await requestJson(
        `/miniapp/api/chat/messages/${encodeURIComponent(clientMessageId)}/run`,
        { headers: { "Accept": "application/json" } },
      );
      if (!currentStateMatches(clientMessageId, expectedGeneration)) return run;
      if (TERMINAL_RUN_STATUSES.has(run.status)) {
        const terminalStatus = normalizedTerminalStatus(run.status);
        const hasSafeOutput = (
          terminalStatus === "completed" &&
          run.client_message_id === clientMessageId &&
          run.has_output === true &&
          run.has_error === false &&
          typeof run.output === "string"
        );
        if (!hasSafeOutput) {
          clearPreparedFundingMessage(clientMessageId);
        }
        explicitRetryAllowed = false;
        cancelRunPoll(clientMessageId);
        closeEventStream();
        const clearedGeneration = clearCurrentClientMessage(
          clientMessageId,
          expectedGeneration,
        );
        if (clearedGeneration === null) return run;
        streamingTurn = null;
        finishToolProgress(terminalStatus);
        if (currentStateMatches(null, clearedGeneration) && hasSafeOutput) {
          await executePreparedFundingIntent(
            run.output,
            clientMessageId,
            clearedGeneration,
          );
        }
        if (!currentStateMatches(null, clearedGeneration)) return run;
        try {
          await loadChat({
            recoverLatest: false,
            preserveStatus: true,
            expectedGeneration: clearedGeneration,
            expectedClientMessageId: null,
          });
        } catch (_error) {
          if (currentStateMatches(null, clearedGeneration)) {
            setStatus(
              "Response completed. Conversation history is temporarily unavailable.",
              true,
            );
          }
          return run;
        }
        if (currentStateMatches(null, clearedGeneration)) {
          setStatus(
            terminalStatusMessage(terminalStatus),
            terminalStatus !== "completed",
          );
        }
      } else {
        explicitRetryAllowed = false;
        closeEventStream();
        setStatus(`Agentonomy run · ${run.status}. Recovering final response…`);
        scheduleRunPoll(clientMessageId);
      }
      return run;
    } catch (error) {
      if (!currentStateMatches(clientMessageId, expectedGeneration)) return null;
      const isNotFound = error instanceof MiniAppRequestError &&
        error.status === 404 &&
        error.reason === "miniapp_not_found";
      if (isNotFound) {
        explicitRetryAllowed = false;
        cancelRunPoll(clientMessageId);
        closeEventStream();
        clearPreparedFundingMessage(clientMessageId);
        const clearedGeneration = clearCurrentClientMessage(
          clientMessageId,
          expectedGeneration,
        );
        if (clearedGeneration !== null) {
          streamingTurn = null;
          setStatus(
            "Previous response is no longer active. Your draft is safe. Tap Send to start a new request.",
            true,
          );
        }
        return null;
      }
      explicitRetryAllowed = error instanceof MiniAppRequestError &&
        error.status === 404 &&
        error.reason !== "miniapp_message_unknown";
      setStatus(
        error instanceof MiniAppRequestError && error.reason === "miniapp_message_unknown"
          ? "Message state is uncertain. No automatic resend was made."
          : "Conversation recovery is unavailable. Your draft is safe.",
        true,
      );
      if (
        currentClientMessageId() === clientMessageId &&
        error instanceof MiniAppRequestError &&
        error.status >= 500
      ) {
        scheduleRunPoll(clientMessageId);
      }
      return null;
    }
  }

  function recoverCurrentRun(clientMessageId, expectedGeneration = null) {
    if (!conversationSessionReady() || !clientMessageId) {
      return Promise.resolve(null);
    }
    const generation = expectedGeneration ?? conversationGeneration;
    if (!currentStateMatches(clientMessageId, generation)) {
      return Promise.resolve(null);
    }
    const active = recoveryFlights.get(clientMessageId);
    if (active && active.generation === generation) return active.promise;
    const promise = recoverRun(clientMessageId, generation).finally(() => {
      const latest = recoveryFlights.get(clientMessageId);
      if (latest?.promise === promise) recoveryFlights.delete(clientMessageId);
    });
    recoveryFlights.set(clientMessageId, { generation, promise });
    return promise;
  }

  async function handleStreamDisconnect(
    clientMessageId = null,
    expectedGeneration = null,
  ) {
    if (!conversationSessionReady()) return null;
    const current = clientMessageId || currentClientMessageId();
    const generation = expectedGeneration ?? conversationGeneration;
    if (!currentStateMatches(current, generation)) return null;
    closeEventStream();
    return recoverCurrentRun(current, generation);
  }

  async function submitMessage() {
    if (!requireConversationSession()) return null;
    const text = elements.input.value.trim();
    if (!text) return null;
    let clientMessageId = currentClientMessageId();
    if (clientMessageId && !explicitRetryAllowed) {
      return recoverCurrentRun(clientMessageId);
    }
    if (!clientMessageId) {
      clientMessageId = newClientMessageId(cryptoApi);
      setCurrentClientMessage(clientMessageId);
    }
    const preparedMessageId = readLocal(STORAGE_KEYS.fundingPreparedMessage);
    if (preparedMessageId && preparedMessageId !== clientMessageId) {
      clearPreparedFundingMessage();
    }
    const messageAmount = messageFundingAmount(text);
    if (messageAmount) {
      writeLocal(
        STORAGE_KEYS.fundingMessageAmount,
        JSON.stringify({
          client_message_id: clientMessageId,
          amount: messageAmount,
        }),
      );
    } else removeLocal(STORAGE_KEYS.fundingMessageAmount);
    const submissionGeneration = conversationGeneration;
    resetToolProgress();
    elements.send.disabled = true;
    setStatus("Sending once…");
    try {
      const response = await requestJson("/miniapp/api/chat/messages", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Agentonomy-CSRF": csrfToken(),
        },
        body: JSON.stringify({ client_message_id: clientMessageId, text }),
      });
      if (!currentStateMatches(clientMessageId, submissionGeneration)) {
        return response;
      }
      elements.input.value = "";
      explicitRetryAllowed = false;
      removeLocal(STORAGE_KEYS.draft);
      renderTurn("user", text);
      setStatus(`Agentonomy run · ${response.status}`);
      openEventStream(clientMessageId);
      return response;
    } catch (error) {
      if (!currentStateMatches(clientMessageId, submissionGeneration)) return null;
      const requestError = error instanceof MiniAppRequestError ? error : null;
      const isUnknown = requestError?.reason === "miniapp_message_unknown";
      const isConflict = requestError?.status === 409 &&
        requestError.reason === "miniapp_conflict";
      if (isConflict) {
        explicitRetryAllowed = false;
        clearCurrentClientMessage(clientMessageId, submissionGeneration);
        setStatus(
          "This message changed before it was accepted. Your draft is safe. Tap Send again to create a new request.",
          true,
        );
      } else if (isUnknown) {
        explicitRetryAllowed = false;
        setStatus(
          "Send result is uncertain. Checking status without resending…",
          true,
        );
      } else {
        explicitRetryAllowed = true;
        if (requestError?.reason === "miniapp_run_active") {
          setStatus(
            "Another response is still running. Wait for it to finish, then tap Send again. Nothing was resent.",
            true,
          );
        } else if (
          requestError?.reason === "miniapp_rate_limited" ||
          requestError?.status === 429
        ) {
          setStatus(
            "Too many requests. Wait a moment, then tap Send again. Nothing was resent.",
            true,
          );
        } else if (requestError?.status === 401) {
          setStatus(
            "Your session expired. Reopen Agentonomy from Telegram. Your draft is safe.",
            true,
          );
        } else if (requestError?.status === 403) {
          setStatus(
            "This request could not be verified. Reopen Agentonomy from Telegram. Your draft is safe.",
            true,
          );
        } else if (requestError?.status === 503) {
          setStatus(
            "Agentonomy is temporarily unavailable. Your draft is safe. Nothing was resent.",
            true,
          );
        } else {
          setStatus(
            "Message was not accepted. Check it, then tap Send again. Nothing was resent.",
            true,
          );
        }
      }
      if (isUnknown) {
        await recoverCurrentRun(clientMessageId, submissionGeneration);
      }
      return null;
    } finally {
      elements.send.disabled = false;
    }
  }

  function sendCurrentMessage() {
    if (!sendPromise) {
      sendPromise = submitMessage().finally(() => {
        sendPromise = null;
      });
    }
    return sendPromise;
  }

  function clearBrowserState(options = {}) {
    const preserveFundingRecovery = options.preserveFundingRecovery === true;
    sessionEpoch += 1;
    cancelFundingAutoProgress();
    conversationGeneration += 1;
    liveOperationGeneration += 1;
    liveOperationsDisabled = true;
    preparedSigningWalletSurface = null;
    fundingProjection = null;
    fundingTerminalVerifiedOperationId = null;
    stableFundingScopeReady = false;
    pendingLegacyFundingScope = "";
    pendingFundingIntent = null;
    provisionalClientMessageId = null;
    for (const key of [
      STORAGE_KEYS.csrf,
      STORAGE_KEYS.clientNonce,
      STORAGE_KEYS.scope,
    ]) {
      sessionStore.removeItem(key);
    }
    for (const key of [
      STORAGE_KEYS.draft,
      STORAGE_KEYS.currentClientMessage,
      STORAGE_KEYS.scroll,
      STORAGE_KEYS.returnMarker,
      STORAGE_KEYS.fundingAmount,
      STORAGE_KEYS.fundingIdempotency,
      STORAGE_KEYS.fundingOperation,
      STORAGE_KEYS.fundingCreateUncertain,
      STORAGE_KEYS.fundingRecoveryStatus,
      STORAGE_KEYS.fundingPreparedMessage,
      STORAGE_KEYS.fundingMessageAmount,
      STORAGE_KEYS.signingPreview,
      STORAGE_KEYS.signingSession,
      STORAGE_KEYS.signingSessionPreview,
      STORAGE_KEYS.signingUnknownPreview,
    ]) {
      if (
        preserveFundingRecovery &&
        FUNDING_RECOVERY_STORAGE_KEYS.has(key)
      ) continue;
      removeLocal(key);
    }
    storageScope = "";
  }

  function shouldPreserveFundingRecovery() {
    const operationId = savedLiveId(STORAGE_KEYS.fundingOperation);
    return liveOperationPromise !== null ||
      readLocal(STORAGE_KEYS.fundingCreateUncertain) === "true" ||
      Boolean(
        operationId &&
        fundingTerminalVerifiedOperationId !== operationId,
      );
  }

  async function logout() {
    cancelRunPoll();
    closeEventStream();
    const csrf = csrfToken();
    clearBrowserState({
      preserveFundingRecovery: shouldPreserveFundingRecovery(),
    });
    elements.input.value = "";
    if (hasLegacyLiveOperationSurface) {
      elements.fundingAmount.value = "";
      elements.signingPreview.value = "";
    }
    elements.transcript.replaceChildren();
    resetToolProgress();
    elements.identity.textContent = "Signed out";
    if (hasLegacyLiveOperationSurface) {
      setCardStatus(elements.fundingStatus, "Signed out. Funding is unavailable.");
      setCardStatus(elements.signingStatus, "Signed out. Order signing is unavailable.");
      updateLiveOperationControls();
    }
    try {
      if (csrf) {
        await requestJson("/miniapp/api/session", {
          method: "DELETE",
          headers: { "X-Agentonomy-CSRF": csrf },
        });
      }
    } catch (_error) {
      setStatus("Local session cleared. Server revocation could not be confirmed.", true);
    }
  }

  function openOperations(open) {
    if (!open) {
      cancelFundingAutoProgress();
      updateLiveOperationControls();
    }
    elements.operations.hidden = !open;
    elements.operationsToggle.setAttribute("aria-expanded", String(open));
    if (open) elements.operationsClose.focus();
    else elements.operationsToggle.focus();
  }

  function wireEvents() {
    if (wired) return;
    wired = true;
    elements.composer.addEventListener("submit", async (event) => {
      event.preventDefault();
      await sendCurrentMessage();
    });
    elements.input.addEventListener("input", () => {
      if (!conversationSessionReady()) return;
      writeLocal(STORAGE_KEYS.draft, elements.input.value);
    });
    if (hasLegacyLiveOperationSurface) {
      elements.fundingAmount.addEventListener("input", () => {
        cancelFundingAutoProgress();
        if (!stableFundingScopeReady) {
          showStableFundingScopeRequired();
          return;
        }
        const previous = readLocal(STORAGE_KEYS.fundingAmount);
        const next = elements.fundingAmount.value.trim();
        writeLocal(STORAGE_KEYS.fundingAmount, next);
        if (previous !== null && previous !== next) {
          liveOperationGeneration += 1;
          fundingProjection = null;
        }
        if (
          previous !== null &&
          previous !== next &&
          !savedLiveId(STORAGE_KEYS.fundingOperation)
        ) removeLocal(STORAGE_KEYS.fundingIdempotency);
        updateLiveOperationControls();
      });
      elements.signingPreview.addEventListener("input", () => {
        if (!conversationSessionReady()) return;
        const previous = readLocal(STORAGE_KEYS.signingPreview);
        const next = elements.signingPreview.value.trim();
        writeLocal(STORAGE_KEYS.signingPreview, next);
        if (previous !== null && previous !== next) {
          liveOperationGeneration += 1;
          preparedSigningWalletSurface = null;
          setCardStatus(
            elements.signingStatus,
            "Preview changed. Open signing to create one new session.",
          );
        }
        if (readLocal(STORAGE_KEYS.signingSessionPreview) !== next) {
          removeLocal(STORAGE_KEYS.signingSession);
          removeLocal(STORAGE_KEYS.signingSessionPreview);
        }
        if (readLocal(STORAGE_KEYS.signingUnknownPreview) !== next) {
          removeLocal(STORAGE_KEYS.signingUnknownPreview);
        }
        updateLiveOperationControls();
      });
    }
    elements.input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        sendCurrentMessage();
      }
    });
    elements.transcript.addEventListener("scroll", () => {
      if (!conversationSessionReady()) return;
      writeLocal(STORAGE_KEYS.scroll, elements.transcript.scrollTop);
    });
    elements.toolProgressToggle.addEventListener("click", () => {
      setToolProgressExpanded(elements.toolProgressList.hidden);
    });
    elements.operationsToggle.addEventListener("click", () => openOperations(true));
    elements.operationsClose.addEventListener("click", () => openOperations(false));
    if (hasLegacyLiveOperationSurface) {
      elements.fundingConfirm.addEventListener("click", async () => {
        await withLiveOperationFlight(runFundingAction);
      });
      elements.signingOpen.addEventListener("click", async () => {
        await withLiveOperationFlight(openOrderSigning);
      });
      elements.signingCheck.addEventListener("click", async () => {
        await withLiveOperationFlight(fetchSigningStatus);
      });
    }
    windowApi.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !elements.operations.hidden) {
        openOperations(false);
      }
    });
    elements.logout.addEventListener("click", logout);
    for (const control of documentApi.querySelectorAll(
      "[data-operation-url], [data-operation]",
    )) {
      control.addEventListener("click", async () => {
        if (!requireConversationSession()) return;
        if (control.dataset.operation === "account") {
          await openAccountOperation();
          return;
        }
        if (control.dataset.operation === "polymarket") {
          await openPolymarketOperation();
          return;
        }
        saveReturnState();
        windowApi.location.assign(control.dataset.operationUrl);
      });
    }
    windowApi.addEventListener("pageshow", async () => {
      cancelFundingAutoProgress();
      subjectOperationPending = false;
      if (!requireConversationSession()) return;
      elements.input.value = readLocal(STORAGE_KEYS.draft) || "";
      restoreScroll();
      restoreLiveOperationState();
      const current = currentClientMessageId();
      const conversationRecovery = current
        ? recoverCurrentRun(current)
        : Promise.resolve(null);
      await Promise.all([
        conversationRecovery,
        refreshSavedLiveOperations(),
      ]);
    });
    documentApi.addEventListener("visibilitychange", async () => {
      if (!conversationSessionReady()) return;
      if (documentApi.visibilityState === "hidden") {
        cancelFundingAutoProgress();
        updateLiveOperationControls();
        await handleStreamDisconnect();
      } else {
        const current = currentClientMessageId();
        if (current) await handleStreamDisconnect();
      }
    });
  }

  async function start() {
    wireEvents();
    const startSessionEpoch = ++sessionEpoch;
    cancelRunPoll();
    closeEventStream();
    cancelFundingAutoProgress();
    conversationGeneration += 1;
    liveOperationGeneration += 1;
    recoveryFlights.clear();
    streamingTurn = null;
    subjectOperationPending = false;
    preparedSigningWalletSurface = null;
    stableFundingScopeReady = false;
    pendingLegacyFundingScope = "";
    fundingTerminalVerifiedOperationId = null;
    elements.input.value = "";
    if (hasLegacyLiveOperationSurface) {
      elements.fundingAmount.value = "";
      elements.signingPreview.value = "";
    }
    elements.transcript.replaceChildren();
    consumeFundingFragment();
    const webApp = telegramWebApp();
    if (webApp) {
      webApp.ready();
      webApp.expand();
    }
    elements.identity.textContent = webApp?.initData
      ? "Telegram identity"
      : "Secure browser session";
    const scopeEstablished = await establishStorageScope(
      csrfToken(),
      null,
      startSessionEpoch,
    );
    if (!scopeEstablished || startSessionEpoch !== sessionEpoch) return;
    if (webApp?.initData) {
      const exchanged = await ensureStableFundingScope(
        webApp,
        startSessionEpoch,
      );
      if (startSessionEpoch !== sessionEpoch) return;
      if (!exchanged) {
        setStatus(
          "Secure sign-in is unavailable. Reopen Agentonomy from Telegram.",
          true,
        );
        return;
      }
    }
    if (startSessionEpoch !== sessionEpoch) return;
    elements.input.value = readLocal(STORAGE_KEYS.draft) || "";
    restoreScroll();
    restoreLiveOperationState();

    try {
      await loadChat();
      await refreshSavedLiveOperations();
      return;
    } catch (error) {
      if (!(error instanceof MiniAppRequestError) || error.status !== 401) {
        setStatus("Conversation is temporarily unavailable. Your draft is safe.", true);
        return;
      }
    }

    if (!webApp || !webApp.initData) {
      setStatus("Open this Mini App from Telegram to connect.", true);
      return;
    }
    setStatus("Secure sign-in is unavailable. Retry without changing this page.", true);
  }

  return {
    start,
    sendCurrentMessage,
    handleStreamDisconnect,
    logout,
  };
}


if (typeof module !== "undefined" && module.exports) {
  module.exports = { createMiniApp, STORAGE_KEYS };
}

if (typeof window !== "undefined" && typeof document !== "undefined") {
  window.addEventListener("DOMContentLoaded", () => {
    createMiniApp().start();
  }, { once: true });
}
