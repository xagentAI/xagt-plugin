const API = window.location.origin;
let projectId = null;
let project = null;
let tests = [];
let tools = [];
let proof = null;
let outcomeReceipt = null;
let findingFilter = "all";

const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char]));

async function request(path, options = {}) {
  const response = await fetch(API + path, options);
  const text = await response.text();
  let body = null;
  try { body = text ? JSON.parse(text) : null; } catch { body = text; }
  if (!response.ok) {
    const detail = body && body.detail ? body.detail : body || `HTTP ${response.status}`;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return body;
}

function jsonPost(path, body = {}) {
  return request(path, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
}

function busy(button, state, label = "Working…") {
  if (!button) return;
  if (state) { if (!button.disabled) button.dataset.label = button.textContent; button.textContent = label; button.disabled = true; }
  else { button.textContent = button.dataset.label || button.textContent; button.disabled = false; }
}

function message(target, value, ok = false) {
  target.textContent = value || "";
  if (target.id === "outcomeMessage") target.style.color = ok ? "#74e1ae" : "#ff9b95";
  else target.style.color = ok ? "var(--green)" : "var(--red)";
}

async function copyTarget(button) {
  const target = $(button.dataset.copyTarget);
  if (!target) return;
  const value = target.textContent.trim();
  const original = button.textContent;
  let helper = null;
  try {
    if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(value);
    else {
      helper = document.createElement("textarea");
      helper.value = value;
      helper.setAttribute("readonly", "");
      helper.style.position = "fixed";
      helper.style.opacity = "0";
      document.body.appendChild(helper);
      helper.select();
      if (!document.execCommand("copy")) throw new Error("Clipboard unavailable");
    }
    button.textContent = "Copied ✓";
  } catch {
    button.textContent = "Copy failed";
  } finally {
    if (helper) helper.remove();
  }
  window.setTimeout(() => { button.textContent = original; }, 1600);
}

async function checkHealth() {
  try {
    const health = await request("/health");
    $("healthDot").classList.add("ok");
    $("healthText").textContent = `online · v${health.version}`;
  } catch {
    $("healthText").textContent = "backend unavailable";
  }
}

async function parseInput() {
  const name = $("projectName").value.trim() || "Imported API";
  let raw = $("specText").value.trim();
  if (raw) {
    let spec;
    try { spec = JSON.parse(raw); }
    catch { throw new Error("Pasted specifications must be JSON. Select the file input to upload YAML."); }
    return {name, openapi_json: spec};
  }
  const url = $("specUrl").value.trim();
  if (!url) throw new Error("Provide an OpenAPI URL, paste JSON, or select a file.");
  return {name, openapi_url: url};
}

async function createFromInput(button) {
  busy(button, true, "Inspecting…");
  message($("launchMessage"), "");
  try {
    const file = $("specFile").files[0];
    let created;
    if (file) {
      const form = new FormData();
      form.append("name", $("projectName").value.trim() || "Imported API");
      form.append("file", file);
      created = await request("/api/projects/upload", {method: "POST", body: form});
    } else {
      const body = await parseInput();
      created = await jsonPost("/api/projects", body);
    }
    await openProject(created.id);
  } catch (error) { message($("launchMessage"), error.message); }
  finally { busy(button, false); }
}

async function runDemo() {
  const button = $("demoBtn");
  busy(button, true, "Creating evidence workspace…");
  message($("launchMessage"), "");
  try {
    const spec = await request("/demo/openapi.json");
    const created = await jsonPost("/api/projects", {name: "Inconsistent Shop API · Live Demo", openapi_json: spec});
    projectId = created.id;
    proof = null;
    await refresh();
    busy(button, true, "Collecting 3× live samples…");
    await jsonPost(`/api/projects/${projectId}/test`, {samples_per_endpoint: 3});
    busy(button, true, "Generating agent contract…");
    await jsonPost(`/api/projects/${projectId}/contract`, {});
    await refresh();
    busy(button, true, "Proving complete catalog…");
    proof = await jsonPost(`/api/projects/${projectId}/prove`, {operation_id: "listItems", claim_type: "EXACT_COUNT", expected_count: 7, arguments: {limit: 3}});
    renderProof();
    message($("workspaceMessage"), "Live demo complete. Scores come from stored observations, and the 7-item catalog proof comes from three server-collected pages.", true);
  } catch (error) { message($("launchMessage"), error.message); }
  finally { busy(button, false); }
}

async function openProject(id) {
  projectId = id;
  proof = null;
  await refresh();
  $("workspace").scrollIntoView({behavior: "smooth", block: "start"});
}

async function refresh() {
  [project, tests, tools] = await Promise.all([
    request(`/api/projects/${projectId}`),
    request(`/api/projects/${projectId}/tests`).catch(() => []),
    request(`/api/projects/${projectId}/tools`).catch(() => []),
  ]);
  proof = project.proof && Object.keys(project.proof).length ? project.proof : proof;
  $("workspace").style.display = "block";
  $("projectTitle").textContent = project.name;
  $("projectMeta").textContent = `${project.endpoints.length} operations · project ${project.id}`;
  const comparison = project.comparison || {};
  $("sourceScore").textContent = comparison.before_score ?? project.score?.overall ?? "—";
  $("contractScore").textContent = comparison.after_score ?? "—";
  $("delta").textContent = comparison.improvement > 0 ? `↑ +${comparison.improvement} points` : "";
  const evidenced = tests.filter((test) => ["passed", "warning", "failed"].includes(test.status)).length;
  $("coverage").textContent = `${evidenced}/${project.endpoints.length}`;
  $("step2").classList.toggle("done", tests.length > 0);
  $("step3").classList.toggle("done", project.has_agent_contract);
  $("step4").classList.toggle("done", project.has_agent_contract && tools.length > 0);
  renderEndpoints(); renderFindings(); renderScores(); renderProof(); renderTools(); renderConnect();
}

function renderEndpoints() {
  const byOperation = Object.fromEntries(tests.map((test) => [test.operation_id, test]));
  $("endpointRows").innerHTML = project.endpoints.map((endpoint) => {
    const test = byOperation[endpoint.operation_id];
    const status = test?.status || "not tested";
    const autoSafe = ["GET", "HEAD", "OPTIONS"].includes(endpoint.method);
    return `<tr><td><strong>${esc(endpoint.operation_id)}</strong><br><span class="tag">${autoSafe ? "auto-safe" : "manual"}</span></td><td><span class="tag">${esc(endpoint.method)}</span> ${esc(endpoint.path)}</td><td><span class="tag ${esc(status)}">${esc(status)}</span></td><td>${test?.latency_ms != null ? `${esc(test.latency_ms)} ms` : "—"}</td><td>${test?.shape_drift ? '<span class="tag high">detected</span>' : "—"}</td></tr>`;
  }).join("");
}

function renderFindings() {
  const severityOrder = {critical: 0, high: 1, medium: 2, low: 3, info: 4};
  const findings = [...(project.issues || [])].sort((a,b) => (severityOrder[a.severity] ?? 9) - (severityOrder[b.severity] ?? 9));
  const counts = findings.reduce((result, finding) => ({...result, [finding.severity]: (result[finding.severity] || 0) + 1}), {});
  if (findingFilter !== "all" && !counts[findingFilter]) findingFilter = "all";
  const filters = ["all", "critical", "high", "medium", "low", "info"].filter((severity) => severity === "all" || counts[severity]);
  $("findingSummary").innerHTML = filters.map((severity) => {
    const count = severity === "all" ? findings.length : counts[severity];
    return `<button type="button" class="severity-filter ${findingFilter === severity ? "active" : ""}" data-finding-filter="${severity}">${severity === "all" ? "All" : esc(severity)} · ${count}</button>`;
  }).join("");
  const visible = findingFilter === "all" ? findings : findings.filter((finding) => finding.severity === findingFilter);
  $("findingList").innerHTML = visible.length ? visible.map((finding) => `<div class="finding"><div><span class="tag ${esc(finding.severity)}">${esc(finding.severity)}</span></div><div><b>${esc(finding.code)}</b><p>${esc(finding.message)}</p><p><strong>Recommended:</strong> ${esc(finding.suggested_repair)}</p><span class="tag">${esc(finding.endpoint)}</span></div></div>`).join("") : '<div class="empty">No findings in this severity.</div>';
}

function renderScores() {
  const breakdown = project.score?.breakdown || {};
  const max = {schema_quality:25, documentation:15, consistency:15, error_handling:15, reliability:15, agent_usability:15};
  $("scoreCards").innerHTML = Object.entries(breakdown).map(([key, value]) => `<div class="tool"><h4>${esc(key.replaceAll("_", " "))}</h4><div style="font-size:28px;font-weight:850">${esc(value)} <span style="font-size:13px;color:var(--muted)">/ ${max[key] || 15}</span></div></div>`).join("");
}

function renderOutcome(integrityValid) {
  const receipt = outcomeReceipt;
  $("outcomeResult").style.display = "block";
  $("outcomeVerdict").textContent = receipt.verdict;
  $("outcomeProvider").textContent = receipt.selected_provider || "none";
  $("outcomeAgreement").textContent = `${receipt.agreement.providers}/${receipt.agreement.required}`;
  $("outcomePrice").textContent = `$${Number(receipt.selected_price_usd || 0).toFixed(3)}`;
  $("outcomeAttempts").innerHTML = receipt.attempts.map((attempt) => {
    const selected = attempt.status === "SELECTED";
    const observed = attempt.value_preview !== undefined && attempt.value_preview !== null ? `value ${attempt.value_preview} · ` : "";
    const detail = observed + (selected ? `trust ${attempt.trust_score} · ${attempt.latency_ms} ms` : attempt.reason || `${attempt.latency_ms} ms`);
    return `<div class="attempt"><div class="attempt-top"><b>${esc(attempt.name)}</b><span class="tag ${selected ? "passed" : "failed"}">${esc(attempt.status)}</span></div><p>${esc(detail)} · $${Number(attempt.price_usd).toFixed(3)}</p></div>`;
  }).join("");
  const proof = {receipt_id: receipt.receipt_id, result: receipt.result, selected_provider: receipt.selected_provider, deployment_commit: receipt.deployment_commit, fingerprint: receipt.integrity.fingerprint, integrity_verified_after_storage: integrityValid};
  $("outcomeIntegrity").className = integrityValid ? "integrity-ok" : "integrity-bad";
  $("outcomeIntegrity").textContent = integrityValid ? "✓ Receipt integrity verified" : "✕ Integrity check failed";
  $("outcomeReceipt").textContent = JSON.stringify(proof, null, 2);
  const proofLink = $("outcomeProofLink");
  if (proofLink) {
    proofLink.href = `/receipts/${receipt.receipt_id}`;
    proofLink.style.display = "inline-flex";
    proofLink.textContent = "View public proof →";
  }
}

async function runOutcomeDemo(live = false) {
  const button = live ? $("liveOutcomeBtn") : $("outcomeBtn");
  busy(button, true, live ? "Calling 3 live origins…" : "Calling 4 fixtures…");
  message($("outcomeMessage"), "");
  try {
    outcomeReceipt = await jsonPost(live ? "/api/outcomes/live-demo" : "/api/outcomes/demo", {});
    busy(button, true, "Verifying stored receipt…");
    const stored = await request(`/api/outcomes/receipts/${outcomeReceipt.receipt_id}`);
    renderOutcome(stored.integrity_valid);
    const rejected = outcomeReceipt.attempts.filter((attempt) => attempt.status === "REJECTED").length;
    const scope = live ? "distinct public origins" : "deterministic in-process fixtures";
    message($("outcomeMessage"), `${outcomeReceipt.verdict}: ${outcomeReceipt.agreement.providers}/${outcomeReceipt.agreement.required} providers agreed across ${scope}; ${rejected} rejected. Price is quoted transparently and no payment was moved.`, outcomeReceipt.verdict === "VERIFIED");
  } catch (error) { message($("outcomeMessage"), error.message); }
  finally { busy(button, false); }
}

function renderProof() {
  const select = $("proofOperation");
  const previous = select.value;
  const operations = project.endpoints.filter((endpoint) => endpoint.method === "GET");
  select.innerHTML = operations.map((endpoint) => `<option value="${esc(endpoint.operation_id)}">${esc(endpoint.operation_id)} · ${esc(endpoint.path)}</option>`).join("");
  if (operations.some((endpoint) => endpoint.operation_id === previous)) select.value = previous;
  else if (operations.some((endpoint) => endpoint.operation_id === "listItems")) select.value = "listItems";
  if (!proof) return;
  const problems = [...(proof.blocking_reasons || []), ...(proof.warnings || [])];
  const explanation = problems.length ? problems.map((item) => `<div class="finding"><div><span class="tag ${proof.verdict === "UNPROVEN" ? "high" : "medium"}">${esc(item.code)}</span></div><div><b>${esc(item.message)}</b><p>${esc(item.next_action)}</p></div></div>`).join("") : '<p class="sub">Every required obligation passed.</p>';
  $("proofResult").className = "proof-result";
  $("proofResult").innerHTML = `<div><div class="verdict ${esc(proof.verdict.toLowerCase())}">${esc(proof.verdict)}</div><p class="sub" style="margin-top:10px;text-align:center">${esc(proof.certificate?.certificate_id || "No certificate issued")}</p></div><div>${explanation}<div class="code">${esc(JSON.stringify({certified_value: proof.certified_value, evidence: proof.evidence, certificate: proof.certificate}, null, 2))}</div></div>`;
}

async function runProof() {
  const button = $("proofBtn"); busy(button, true, "Collecting every page…"); message($("proofMessage"), "");
  try {
    const rawArgs = $("proofArgs").value.trim();
    const argumentsValue = rawArgs ? JSON.parse(rawArgs) : {};
    if (!argumentsValue || Array.isArray(argumentsValue) || typeof argumentsValue !== "object") throw new Error("Arguments must be a JSON object.");
    const claimType = $("proofClaim").value;
    const payload = {operation_id: $("proofOperation").value, claim_type: claimType, arguments: argumentsValue};
    if (claimType === "EXACT_COUNT") payload.expected_count = Number($("proofExpected").value);
    if (["MIN", "MAX"].includes(claimType)) {
      payload.field = $("proofField").value.trim();
      if ($("proofCandidate").value.trim()) payload.candidate_id = $("proofCandidate").value.trim();
    }
    proof = await jsonPost(`/api/projects/${projectId}/prove`, payload);
    renderProof();
    message($("proofMessage"), `${proof.verdict}: ${proof.evidence.records_examined || 0} records across ${proof.evidence.pages_examined || 0} page(s), collected by APIVouch.`, proof.verdict !== "UNPROVEN");
  } catch (error) { message($("proofMessage"), error.message); }
  finally { busy(button, false); }
}

function renderTools() {
  $("toolList").innerHTML = tools.length ? tools.map((tool) => `<div class="tool"><h4>${esc(tool.name)}</h4><p>${esc(tool.description)}</p><span class="tag ${tool.annotations?.readOnlyHint ? "passed" : "warning"}">${tool.annotations?.readOnlyHint ? "read only" : "confirmation required"}</span><details><summary style="margin-top:12px;cursor:pointer">Input schema</summary><div class="code">${esc(JSON.stringify(tool.inputSchema, null, 2))}</div></details></div>`).join("") : '<div class="empty">Generate the agent contract to create MCP tools.</div>';
}

function renderConnect() {
  const endpoint = `${API}/mcp/${projectId}`;
  $("mcpUrl").textContent = endpoint;
  $("mcpExample").textContent = `curl -X POST ${endpoint} \\\n+  -H "Content-Type: application/json" \\\n+  -d '${JSON.stringify({jsonrpc:"2.0",id:1,method:"initialize",params:{protocolVersion:"2025-06-18",capabilities:{},clientInfo:{name:"reviewer",version:"1"}}})}'`;
}

async function collectEvidence() {
  const button = $("testBtn"); busy(button, true, "Collecting…"); message($("workspaceMessage"), "");
  try { await jsonPost(`/api/projects/${projectId}/test`, {samples_per_endpoint: 3}); await refresh(); message($("workspaceMessage"), "Live observations stored. Required parameters and state-changing methods remain safely skipped.", true); }
  catch (error) { message($("workspaceMessage"), error.message); }
  finally { busy(button, false); }
}

async function generateContract() {
  const button = $("contractBtn"); busy(button, true, "Generating…"); message($("workspaceMessage"), "");
  try { const result = await jsonPost(`/api/projects/${projectId}/contract`, {}); await refresh(); message($("workspaceMessage"), `Agent contract generated from ${result.comparison.changes_applied} evidence-labelled changes.`, true); }
  catch (error) { message($("workspaceMessage"), error.message); }
  finally { busy(button, false); }
}

async function exportPack() {
  const button = $("exportBtn"); busy(button, true, "Preparing…");
  try {
    const data = await request(`/api/projects/${projectId}/export`);
    const blob = new Blob([JSON.stringify(data, null, 2)], {type: "application/json"});
    const link = document.createElement("a"); link.href = URL.createObjectURL(blob); link.download = `apivouch-${projectId}-agent-pack.json`; link.click(); URL.revokeObjectURL(link.href);
  } catch (error) { message($("workspaceMessage"), error.message); }
  finally { busy(button, false); }
}

let explorerReceipt = null;
let explorerReceiptId = null;
let labScenarios = [];

function receiptIdFromPath() {
  const match = window.location.pathname.match(/^\/receipts\/([A-Za-z0-9_-]{1,64})\/?$/);
  if (!match) return null;
  return match[1];
}

function isReceiptRoute() {
  return window.location.pathname.startsWith("/receipts/");
}

function enterReceiptMode(receiptId) {
  const explorer = $("receiptExplorer");
  if (explorer) explorer.classList.add("active");
  document.querySelectorAll(".hero,#outcome,#chaos-lab,#quick-connect,#launch,#workspace").forEach((section) => {
    if (section) section.style.display = "none";
  });
  if (!/^[0-9a-f]{24}$/.test(receiptId || "")) {
    renderReceiptError("Receipt not found", "This public proof link is malformed. Receipt IDs are 24 lowercase hexadecimal characters.");
    return;
  }
  explorerReceiptId = receiptId;
  loadReceiptExplorer(receiptId);
}

function receiptStatusBadge(verdict) {
  const verified = verdict === "VERIFIED";
  return `<span class="receipt-verdict ${verified ? "verified" : "unverified"}">${esc(verdict || "UNVERIFIED")}</span>`;
}

function renderReceiptError(title, detail) {
  const body = $("receiptBody");
  if (!body) return;
  body.innerHTML = `<div class="receipt-error">${esc(title)}</div><p class="sub">${esc(detail)}</p>`;
  $("receiptJson").textContent = "—";
  $("receiptTitle").textContent = "Receipt Explorer";
}

function renderReceiptExplorer(envelope) {
  const receipt = envelope.receipt;
  const integrityValid = envelope.integrity_valid === true;
  const authenticity = envelope.authenticity || {state: "unavailable", valid: false};
  explorerReceipt = receipt;
  const body = $("receiptBody");
  const hasSelection = receipt.selected_provider && receipt.result !== null && receipt.result !== undefined;
  const agreement = receipt.agreement || {};
  const integrity = receipt.integrity || {};
  const authenticityState = authenticity.state || "unavailable";
  const keyId = receipt.authenticity && receipt.authenticity.key_id ? receipt.authenticity.key_id : null;
  const attempts = Array.isArray(receipt.attempts) ? receipt.attempts : [];
  const integrityLine = integrityValid
    ? '<div class="receipt-error" style="background:var(--mint);color:var(--green)">✓ Integrity verified — fingerprint recomputed from canonical receipt JSON.</div>'
    : '<div class="receipt-error">✕ Integrity check failed — this receipt does not match its fingerprint.</div>';
  const authenticityLine = authenticityState === "signed" && authenticity.valid
    ? `<div class="receipt-note">Authenticity: signed and valid. Same-origin signature discovery proves consistency with this deployment, not independent truth of upstream data.</div>`
    : authenticityState === "unsigned"
    ? `<div class="receipt-note">Authenticity: unsigned. Hash integrity is verified separately; no issuer signature is present. Same-origin signature discovery proves consistency with this deployment, not independent truth of upstream data.</div>`
    : `<div class="receipt-note">Authenticity: ${esc(authenticityState)} (valid: ${authenticity.valid ? "true" : "false"}). Shown separately from hash integrity; an unavailable signature is never a success. Same-origin signature discovery proves consistency with this deployment, not independent truth of upstream data.</div>`;
  body.innerHTML = `
    <div style="margin:10px 0">${receiptStatusBadge(receipt.verdict)}</div>
    ${integrityLine}
    <div class="receipt-grid">
      <div class="receipt-field"><span>Receipt ID</span><b>${esc(receipt.receipt_id)}</b></div>
      <div class="receipt-field"><span>Created</span><b>${esc(receipt.created_at)}</b></div>
      <div class="receipt-field"><span>Goal</span><b>${esc(receipt.goal)}</b></div>
      <div class="receipt-field"><span>Selected result / provider</span><b>${hasSelection ? `${esc(JSON.stringify(receipt.result))} · ${esc(receipt.selected_provider)}` : "no result selected"}</b></div>
      <div class="receipt-field"><span>Agreement</span><b>${esc(agreement.providers ?? "—")} achieved vs ${esc(agreement.required ?? "—")} required</b></div>
      <div class="receipt-field"><span>Quoted price</span><b>$${esc(Number(receipt.selected_price_usd || 0).toFixed(3))} · not charged / no settlement</b></div>
      <div class="receipt-field"><span>Deployment commit</span><b>${esc(receipt.deployment_commit)}</b></div>
      <div class="receipt-field"><span>Receipt format</span><b>${esc(receipt.format)}</b></div>
      <div class="receipt-field"><span>Fingerprint</span><b>${esc(integrity.fingerprint || "—")}</b></div>
      <div class="receipt-field"><span>Fingerprint algorithm</span><b>${esc(integrity.algorithm || "—")}</b></div>
      <div class="receipt-field"><span>Integrity valid</span><b>${esc(integrityValid ? "true" : "false")}</b></div>
      <div class="receipt-field"><span>Authenticity</span><b>${esc(authenticityState)} · valid: ${esc(authenticity.valid ? "true" : "false")}${keyId ? ` · key ${esc(keyId)}` : ""}</b></div>
    </div>
    <h3 style="margin:18px 0 8px">Provider attempts</h3>
    <div class="receipt-attempts">${attempts.map((attempt) => `
      <div class="receipt-attempt"><div class="attempt-top"><b>${esc(attempt.name)}</b><span class="tag ${attempt.status === "SELECTED" ? "passed" : "failed"}">${esc(attempt.status)}</span></div>
      <p>URL: ${esc(attempt.url || "—")}</p>
      <p>Latency: ${esc(attempt.latency_ms ?? "—")} ms · Price: $${esc(Number(attempt.price_usd || 0).toFixed(3))}${attempt.trust_score !== undefined && attempt.trust_score !== null ? ` · Trust: ${esc(attempt.trust_score)}` : ""}</p>
      <p>${esc(attempt.reason || (attempt.status === "SELECTED" ? "Selected from the agreeing group" : "No reason recorded"))}</p></div>`).join("") || '<div class="empty">No provider attempts recorded.</div>'}
    </div>
    ${authenticityLine}`;
  $("receiptTitle").textContent = `Receipt ${receipt.receipt_id}`;
  $("receiptJson").textContent = JSON.stringify(receipt, null, 2);
}

async function loadReceiptExplorer(receiptId) {
  const body = $("receiptBody");
  if (body) body.innerHTML = '<p class="receipt-loading">Loading receipt…</p>';
  $("receiptJson").textContent = "—";
  try {
    const envelope = await request(`/api/outcomes/receipts/${receiptId}`);
    renderReceiptExplorer(envelope);
  } catch (error) {
    const safe = String(error.message || "");
    if (/not found/i.test(safe)) renderReceiptError("Receipt not found", "No stored receipt matches this ID on this deployment.");
    else renderReceiptError("Receipt could not be loaded", "Please try again. No diagnostic details are exposed on this page.");
  }
}

async function verifyReceiptAgain() {
  if (!explorerReceiptId) return;
  const button = $("receiptVerifyBtn");
  busy(button, true, "Verifying…");
  try { await loadReceiptExplorer(explorerReceiptId); }
  finally { busy(button, false); }
}

async function copyTextValue(button, value) {
  const original = button.textContent;
  try {
    if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(value);
    else {
      const helper = document.createElement("textarea");
      helper.value = value;
      helper.setAttribute("readonly", "");
      helper.style.position = "fixed";
      helper.style.opacity = "0";
      document.body.appendChild(helper);
      helper.select();
      if (!document.execCommand("copy")) throw new Error("Clipboard unavailable");
      helper.remove();
    }
    button.textContent = "Copied ✓";
  } catch { button.textContent = "Copy failed"; }
  window.setTimeout(() => { button.textContent = original; }, 1600);
}

function downloadReceiptJson() {
  if (!explorerReceipt) return;
  const blob = new Blob([JSON.stringify(explorerReceipt, null, 2)], {type: "application/json"});
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `apivouch-receipt-${explorerReceipt.receipt_id}.json`;
  link.click();
  URL.revokeObjectURL(link.href);
}

function labCardHtml(entry) {
  const state = entry.status || "idle";
  const badge = state === "idle" ? '<span class="lab-badge idle">Not run</span>'
    : entry.passed ? '<span class="lab-badge pass">PASS</span>' : '<span class="lab-badge fail">FAIL</span>';
  const observed = entry.observed || "—";
  const evidence = entry.evidence || entry.description || "";
  const receiptId = entry.receiptId || "—";
  const proofLink = entry.receiptId ? `<p><a href="/receipts/${esc(entry.receiptId)}">View proof →</a></p>` : "";
  return `<div class="lab-card"><h3>${esc(entry.title || entry.id)}</h3>${badge}
    <p>Expected verdict: ${esc(entry.expected || "—")} · Observed: ${esc(observed)}</p>
    <p class="lab-meta">${esc(evidence)}</p>
    <p class="lab-meta">Receipt: ${esc(receiptId)}</p>${proofLink}</div>`;
}

function renderLabCards(resultsById) {
  const container = $("labCards");
  if (!container) return;
  container.innerHTML = labScenarios.map((scenario) => {
    const entry = (resultsById && resultsById[scenario.id]) || {id: scenario.id, title: scenario.title, description: scenario.description, expected: scenario.expected_verdict, status: "idle"};
    return labCardHtml(entry);
  }).join("");
}

async function loadLabCatalog() {
  try {
    const catalog = await request("/api/outcomes/lab");
    labScenarios = Array.isArray(catalog.scenarios) ? catalog.scenarios : [];
    renderLabCards(null);
  } catch { labScenarios = []; }
}

function decisiveEvidence(result) {
  const failed = (result.checks || []).find((check) => !check.passed);
  if (failed) return failed.summary || failed.id;
  const key = (result.checks || []).find((check) => ["agreement-met", "disagreement-rejection", "schema-rejection", "upstream-rejection", "zero-provider-calls", "final-origin-rejection", "budget-rejection", "refusal-selects-nothing", "selected-provider-eligible"].includes(check.id));
  return (key && key.summary) || `Observed ${result.observed_verdict}`;
}

async function runAllLabScenarios() {
  const button = $("labRunAll");
  const summary = $("labSummary");
  busy(button, true, "Running safety scenarios…");
  message($("labMessage"), "");
  try {
    if (!labScenarios.length) await loadLabCatalog();
    if (!labScenarios.length) throw new Error("Safety catalog unavailable");
    const resultsById = {};
    renderLabCards(resultsById);
    let passedCount = 0;
    for (const scenario of labScenarios) {
      const card = resultsById[scenario.id] || {id: scenario.id, title: scenario.title, description: scenario.description, expected: scenario.expected_verdict, status: "running"};
      try {
        const result = await request(`/api/outcomes/lab/${scenario.id}`, {method: "POST"});
        const passed = result.passed === true;
        if (passed) passedCount += 1;
        resultsById[scenario.id] = {id: scenario.id, title: scenario.title, description: scenario.description, expected: scenario.expected_verdict, observed: result.observed_verdict, passed, status: passed ? "pass" : "fail", evidence: decisiveEvidence(result), receiptId: result.receipt && result.receipt.receipt_id};
      } catch (error) {
        resultsById[scenario.id] = {id: scenario.id, title: scenario.title, description: scenario.description, expected: scenario.expected_verdict, observed: "ERROR", passed: false, status: "fail", evidence: "Scenario request failed safely without exposing diagnostics.", receiptId: null};
      }
      renderLabCards(resultsById);
    }
    summary.textContent = `${passedCount}/${labScenarios.length} safety scenarios behaved as expected`;
    message($("labMessage"), passedCount === labScenarios.length ? "All safety refusals behaved as expected. UNVERIFIED is a passing safety result." : "One or more scenarios did not behave as expected.", passedCount === labScenarios.length);
  } catch (error) { message($("labMessage"), "Safety scenarios could not run. Please try again."); }
  finally { busy(button, false); }
}

document.querySelectorAll(".tab").forEach((button) => button.addEventListener("click", () => {
  document.querySelectorAll(".tab").forEach((item) => item.classList.toggle("active", item === button));
  document.querySelectorAll(".tabview").forEach((view) => view.classList.toggle("active", view.id === `tab-${button.dataset.tab}`));
}));
document.querySelectorAll("[data-copy-target]").forEach((button) => button.addEventListener("click", () => copyTarget(button)));
if ($("findingSummary")) $("findingSummary").addEventListener("click", (event) => {
  const button = event.target.closest("[data-finding-filter]");
  if (!button) return;
  findingFilter = button.dataset.findingFilter;
  renderFindings();
});
if ($("analyzeBtn")) $("analyzeBtn").addEventListener("click", () => createFromInput($("analyzeBtn")));
if ($("pasteBtn")) $("pasteBtn").addEventListener("click", () => createFromInput($("pasteBtn")));
if ($("demoBtn")) $("demoBtn").addEventListener("click", runDemo);
if ($("testBtn")) $("testBtn").addEventListener("click", collectEvidence);
if ($("contractBtn")) $("contractBtn").addEventListener("click", generateContract);
if ($("proofBtn")) $("proofBtn").addEventListener("click", runProof);
if ($("exportBtn")) $("exportBtn").addEventListener("click", exportPack);
if ($("liveOutcomeBtn")) $("liveOutcomeBtn").addEventListener("click", () => runOutcomeDemo(true));
if ($("outcomeBtn")) $("outcomeBtn").addEventListener("click", () => runOutcomeDemo(false));
if ($("receiptVerifyBtn")) $("receiptVerifyBtn").addEventListener("click", verifyReceiptAgain);
if ($("receiptCopyLinkBtn")) $("receiptCopyLinkBtn").addEventListener("click", (event) => copyTextValue(event.currentTarget, `${window.location.origin}/receipts/${explorerReceiptId || ""}`));
if ($("receiptCopyJsonBtn")) $("receiptCopyJsonBtn").addEventListener("click", (event) => copyTextValue(event.currentTarget, explorerReceipt ? JSON.stringify(explorerReceipt, null, 2) : "—"));
if ($("receiptDownloadBtn")) $("receiptDownloadBtn").addEventListener("click", downloadReceiptJson);
if ($("labRunAll")) $("labRunAll").addEventListener("click", runAllLabScenarios);
checkHealth();
if ($("productMcpUrl")) $("productMcpUrl").textContent = `${API}/mcp`;
if (isReceiptRoute()) {
  enterReceiptMode(receiptIdFromPath());
} else {
  loadLabCatalog();
  const query = new URLSearchParams(window.location.search);
  const linkedProject = query.get("project");
  if (linkedProject && /^[a-f0-9]{12}$/.test(linkedProject)) {
    openProject(linkedProject).catch((error) => message($("launchMessage"), `Linked project could not be loaded: ${error.message}`));
  }
  if (query.get("demo") === "fixture") {
    runOutcomeDemo(false);
  }
}
