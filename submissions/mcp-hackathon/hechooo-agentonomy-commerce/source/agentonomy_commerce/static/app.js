"use strict";

const el = (id) => document.getElementById(id);
const STORAGE_KEYS = Object.freeze({
  sessionId: "agentonomy_demo_session_id",
  previewId: "agentonomy_demo_preview_id",
  previewKey: "agentonomy_demo_preview_key",
  purchaseId: "agentonomy_demo_purchase_id",
});
const sample = "transaction_id,date,description,amount,currency,category\n" +
  "demo-001,2026-09-01,Synthetic hosting,-12.50,USD,software\n" +
  "demo-002,2026-09-02,Synthetic invoice,40.00,USD,revenue\n" +
  "demo-001,2026-09-01,Synthetic hosting,-12.50,USD,software\n";
const emptyResult = "交付后将在这里显示报告、输入摘要和订单状态。";
let demoEnabled = false;
let sessionId = null;
let sessionExpiresAt = null;
let activePreview = null;
let previewKey = null;
let lockedInput = null;
let purchaseId = null;
let busy = false;

function storageRead(key) {
  try { return window.sessionStorage.getItem(key); }
  catch (_) { return null; }
}
function storageWrite(key, value) {
  try { window.sessionStorage.setItem(key, value); }
  catch (_) { /* The demo remains usable when storage is unavailable. */ }
}
function storageRemove(key) {
  try { window.sessionStorage.removeItem(key); }
  catch (_) { /* The demo remains usable when storage is unavailable. */ }
}
function clearSavedIdentifiers() {
  for (const key of Object.values(STORAGE_KEYS)) storageRemove(key);
}
function saveState() {
  if (!sessionId) return;
  storageWrite(STORAGE_KEYS.sessionId, sessionId);
  for (const [key, value] of [[STORAGE_KEYS.previewId, activePreview],
    [STORAGE_KEYS.previewKey, previewKey], [STORAGE_KEYS.purchaseId, purchaseId]]) {
    if (value) storageWrite(key, value); else storageRemove(key);
  }
}
function status(message, error = false) { el("status").textContent = message; el("status").classList.toggle("error", error); }
function sessionNotice(message) { el("session-note").textContent = message; }
function resetOrderView() {
  el("purchase-id").value = "";
  el("order-state").textContent = "尚未购买";
  el("result").textContent = emptyResult;
}
function clearActiveSession(message) {
  sessionId = null; sessionExpiresAt = null; activePreview = null;
  previewKey = null; lockedInput = null; purchaseId = null;
  clearSavedIdentifiers(); resetOrderView();
  for (const id of ["remaining", "used", "settlements", "deliveries"]) el(id).textContent = "—";
  if (message) sessionNotice(message);
  el("preview-note").textContent = demoEnabled ? "开始演示后即可锁定报价。报价有效期为 5 分钟。" : "公开演示暂未开启。";
  controls();
}
function controls() {
  const hasSession = Boolean(sessionId);
  el("start-demo").disabled = busy || !demoEnabled || hasSession;
  el("start-demo").textContent = hasSession ? "演示已开始" : "开始演示";
  for (const id of ["sample", "csv"]) el(id).disabled = busy;
  for (const id of ["preview", "refresh", "lookup"]) el(id).disabled = busy || !hasSession;
  for (const id of ["purchase", "replay"]) el(id).disabled = busy || !hasSession || !activePreview;
}
function expiryText(value) {
  if (value === undefined || value === null || value === "") return "访客会话已开始。刷新页面会恢复状态，不会自动购买。";
  const numeric = typeof value === "number" ? value * (value < 100000000000 ? 1000 : 1) : Date.parse(value);
  if (!Number.isFinite(numeric)) return "访客会话已开始。刷新页面会恢复状态，不会自动购买。";
  return `访客会话有效至 ${new Date(numeric).toLocaleString("zh-CN")}。刷新页面会恢复状态，不会自动购买。`;
}
function activateSession(data) {
  const nextSessionId = typeof data.session_id === "string" ? data.session_id : "";
  if (!nextSessionId) throw new Error("演示会话未创建，请稍后重试。");
  const savedSessionId = storageRead(STORAGE_KEYS.sessionId);
  const sameSession = savedSessionId === nextSessionId;
  demoEnabled = data.enabled !== false; sessionId = nextSessionId; sessionExpiresAt = data.expires_at;
  if (sameSession) {
    activePreview = storageRead(STORAGE_KEYS.previewId); previewKey = storageRead(STORAGE_KEYS.previewKey);
    purchaseId = storageRead(STORAGE_KEYS.purchaseId); if (!activePreview) previewKey = null; lockedInput = null;
  } else {
    activePreview = null; previewKey = null; lockedInput = null; purchaseId = null;
    clearSavedIdentifiers(); resetOrderView();
  }
  storageWrite(STORAGE_KEYS.sessionId, sessionId); sessionNotice(expiryText(sessionExpiresAt));
  el("preview-note").textContent = activePreview
    ? `已恢复报价 ${activePreview}。确认购买会使用当前报价，不会自动扣款。`
    : "开始演示后即可锁定报价。报价有效期为 5 分钟。";
  controls();
}
function errorCode(data) {
  const value = data && (data.error || data.detail);
  if (Array.isArray(value)) return "invalid_request";
  return String(value || "").split(/[;·]/, 1)[0].trim().toLowerCase();
}
function friendlyError(statusCode, code) {
  if (statusCode === 401 || code === "unauthorized" || code === "invalid_session" || code.includes("session_expired")) return "演示会话已过期或失效，请点击“开始演示”重新进入。";
  if (statusCode === 429 || code === "session_capacity" || code === "session_rate_limited" || code === "operation_in_progress" || code.includes("rate") || code.includes("capacity") || code.includes("limit")) return "当前演示请求较多或容量已满，请稍后再试。已有报价和订单仍会保留。";
  if (statusCode === 503 || code === "worker_unavailable" || code.includes("unavailable") || code.includes("disabled")) return "公开演示暂时不可用，请稍后再试。已有报价和订单仍会保留。";
  if (statusCode === 413 || code.includes("too_large")) return "请求内容过大，请缩短 CSV 后重试。";
  if (statusCode === 404 || code === "not_found") return "没有找到这笔订单，请检查订单 ID。";
  if (statusCode === 409 || code.includes("conflict")) return "当前请求与已保存的报价冲突，请载入示例或修改 CSV 后重新锁定报价。";
  if (statusCode === 422 || code === "invalid_request" || code === "invalid_input") return "请求内容无法处理，请检查 CSV 后重试。";
  return `请求未完成（HTTP ${statusCode}）。请保留当前报价和订单后稍后查询。`;
}
function timeoutSignal(milliseconds) {
  if (typeof AbortSignal !== "undefined" && typeof AbortSignal.timeout === "function") return AbortSignal.timeout(milliseconds);
  const controller = new AbortController(); window.setTimeout(() => controller.abort(), milliseconds); return controller.signal;
}
async function request(path, body, key) {
  const headers = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (key) headers["Idempotency-Key"] = key;
  let response;
  try {
    response = await fetch(path, {method: body === undefined ? "GET" : "POST", headers,
      body: body === undefined ? undefined : JSON.stringify(body), credentials: "same-origin",
      signal: timeoutSignal(55000)});
  } catch (error) {
    const network = new Error(error && error.name === "TimeoutError"
      ? "请求超时。请保留当前报价和订单后查询，不要重复创建购买。"
      : "暂时无法连接演示服务。请保留当前报价和订单后稍后重试。");
    network.cause = error; throw network;
  }
  const data = await response.json().catch(() => ({}));
  if (response.status === 401) clearActiveSession("演示会话已过期或失效，请点击“开始演示”重新进入。");
  if (!response.ok) {
    const code = errorCode(data); const requestError = new Error(friendlyError(response.status, code));
    requestError.status = response.status; requestError.code = code; throw requestError;
  }
  return data;
}
async function action(fn) {
  busy = true; controls(); status("正在处理…");
  try { await fn(); } catch (error) { status(error.message || "请求未完成，请稍后重试。", true); }
  finally { busy = false; controls(); }
}
function requireSession() {
  if (!sessionId) throw new Error("请先点击“开始演示”创建访客会话。");
}
async function budget() {
  requireSession();
  const data = await request("/demo/v1/budget");
  el("remaining").textContent = data.remaining_amount_usdc ?? "—";
  el("used").textContent = data.used_amount_usdc ?? "—";
  el("settlements").textContent = data.settlement_submissions ?? "—";
  el("deliveries").textContent = data.merchant_deliveries ?? "—";
}
function showOrder(data, {preservePreview = false} = {}) {
  const order = data && typeof data === "object" ? data : {};
  el("result").textContent = JSON.stringify(order, null, 2);
  if (order.purchase_id) {
    purchaseId = order.purchase_id;
    el("purchase-id").value = order.purchase_id;
  }
  if (order.preview_id && !preservePreview) activePreview = order.preview_id;
  saveState();
  const state = order.state || order.status || "unknown";
  el("order-state").textContent = state;
  const delivered = state === "delivered";
  status(delivered
    ? "服务已交付。可查询订单，或重放同一笔购买核对预算是否保持不变。"
    : `订单状态：${state}。${order.reason_code || "请保留当前订单并检查结果。"}`,
  !delivered);
}
el("start-demo").addEventListener("click", () => action(async () => {
  if (!demoEnabled) throw new Error("公开演示暂未开启，请稍后再试。");
  status("正在开始访客演示…");
  const data = await request("/demo/session", {});
  if (data.enabled === false) {
    demoEnabled = false;
    controls();
    throw new Error("公开演示暂未开启，请稍后再试。");
  }
  activateSession(data);
  await budget();
  status("演示已开始。示例 CSV 已准备好，锁定报价后再确认购买。");
}));
function inputChanged() {
  activePreview = null;
  previewKey = null;
  lockedInput = null;
  storageRemove(STORAGE_KEYS.previewId);
  storageRemove(STORAGE_KEYS.previewKey);
  el("preview-note").textContent = sessionId
    ? "输入已更新，请重新锁定报价。"
    : "开始演示后即可锁定报价。报价有效期为 5 分钟。";
  controls();
}
el("csv").addEventListener("input", inputChanged);
el("sample").addEventListener("click", () => { el("csv").value = sample; inputChanged(); });
el("preview").addEventListener("click", () => action(async () => {
  requireSession();
  const csv = el("csv").value;
  if (!csv.trim()) throw new Error("请先填写 CSV 或载入合成示例。");
  if (activePreview && previewKey && !lockedInput) {
    status(`已恢复报价 ${activePreview}。确认购买会使用当前报价，不会自动扣款。`);
    return;
  }
  if (csv !== lockedInput || !previewKey) {
    previewKey = crypto.randomUUID();
    lockedInput = csv;
  }
  saveState();
  status("正在锁定报价…");
  const data = await request("/demo/v1/previews",
    {offering_id: "csv-reconciliation-v1", csv_text: csv}, previewKey);
  activePreview = data.preview_id;
  saveState();
  el("preview-note").textContent = `报价已锁定 · ${data.preview_id} · 有效至 ${data.expires_at}`;
  status("报价已锁定，尚未扣款。确认后使用 0.30 模拟 USDC 获取报告。");
}));
async function purchase() {
  requireSession();
  if (!activePreview) throw new Error("请先锁定报价。");
  status("正在核验预算并请求商家交付…");
  showOrder(await request("/demo/v1/purchases", {preview_id: activePreview}));
  await budget();
}
el("purchase").addEventListener("click", () => action(purchase));
el("replay").addEventListener("click", () => action(purchase));
el("refresh").addEventListener("click", () => action(async () => {
  await budget();
  status("预算已刷新。");
}));
el("lookup").addEventListener("click", () => action(async () => {
  requireSession();
  const id = el("purchase-id").value.trim();
  if (!id) throw new Error("请填写订单 ID。");
  purchaseId = id;
  saveState();
  showOrder(await request(`/demo/v1/purchases/${encodeURIComponent(id)}`));
  await budget();
}));
async function restoreSession() {
  const savedSessionId = storageRead(STORAGE_KEYS.sessionId);
  busy = true;
  controls();
  try {
    const data = await request("/demo/session");
    demoEnabled = data.enabled === true;
    if (!demoEnabled) {
      clearActiveSession("公开演示暂未开启，请稍后再试。");
      status("公开演示暂未开启，请稍后再试。", true);
      return;
    }
    if (!data.authenticated || !data.session_id) {
      clearActiveSession(savedSessionId
        ? "访客会话已过期，请点击“开始演示”重新进入。"
        : "准备就绪。点击“开始演示”即可获得独立的 1.00 模拟 USDC 预算。");
      status(savedSessionId ? "访客会话已过期，请点击“开始演示”重新进入。" : "准备开始访客演示。");
      return;
    }
    activateSession(data);
    await budget();
    if (purchaseId) {
      try {
        showOrder(await request(`/demo/v1/purchases/${encodeURIComponent(purchaseId)}`), {preservePreview: true});
      } catch (error) {
        if (error.status === 404 || error.code === "not_found") {
          purchaseId = null;
          storageRemove(STORAGE_KEYS.purchaseId);
          el("purchase-id").value = "";
          status("已恢复预算；保存的订单已过期，请保留当前报价或重新锁定报价。", true);
        } else {
          throw error;
        }
      }
    } else {
      status(activePreview ? "演示会话和报价已恢复。确认购买仍需点击按钮。" : "演示会话已恢复。示例 CSV 已准备好，可锁定报价。");
    }
  } catch (error) {
    status(error.message || "暂时无法读取演示会话，请稍后重试。", true);
    if (!sessionId) sessionNotice("暂时无法读取演示服务，请稍后刷新页面重试。");
  } finally {
    busy = false;
    controls();
  }
}
fetch("/health", {credentials: "same-origin"}).then((response) => response.json()).then((data) => {
  el("build").textContent = `服务 ${data.status} · commit ${data.commit.slice(0, 12)}`;
  el("build").title = data.commit;
}).catch(() => { el("build").textContent = "服务暂不可用"; });
controls();
restoreSession();
