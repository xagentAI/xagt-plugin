const API = window.location.origin;
let projectId = null;
let project = null;
let tests = [];
let tools = [];
let proof = null;
let outcomeReceipt = null;

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
  $("delta").textContent = comparison.improvement > 0 ? `+${comparison.improvement}` : "";
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
  $("findingList").innerHTML = findings.length ? findings.map((finding) => `<div class="finding"><div><span class="tag ${esc(finding.severity)}">${esc(finding.severity)}</span></div><div><b>${esc(finding.code)}</b><p>${esc(finding.message)}</p><p><strong>Recommended:</strong> ${esc(finding.suggested_repair)}</p><span class="tag">${esc(finding.endpoint)}</span></div></div>`).join("") : '<div class="empty">No findings.</div>';
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
  $("outcomeReceipt").innerHTML = `<span class="${integrityValid ? "integrity-ok" : "integrity-bad"}">${integrityValid ? "✓ RECEIPT INTEGRITY VERIFIED" : "✕ INTEGRITY CHECK FAILED"}</span>\n${esc(JSON.stringify(proof, null, 2))}`;
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

document.querySelectorAll(".tab").forEach((button) => button.addEventListener("click", () => {
  document.querySelectorAll(".tab").forEach((item) => item.classList.toggle("active", item === button));
  document.querySelectorAll(".tabview").forEach((view) => view.classList.toggle("active", view.id === `tab-${button.dataset.tab}`));
}));
$("analyzeBtn").addEventListener("click", () => createFromInput($("analyzeBtn")));
$("pasteBtn").addEventListener("click", () => createFromInput($("pasteBtn")));
$("demoBtn").addEventListener("click", runDemo);
$("testBtn").addEventListener("click", collectEvidence);
$("contractBtn").addEventListener("click", generateContract);
$("proofBtn").addEventListener("click", runProof);
$("exportBtn").addEventListener("click", exportPack);
$("liveOutcomeBtn").addEventListener("click", () => runOutcomeDemo(true));
$("outcomeBtn").addEventListener("click", () => runOutcomeDemo(false));
checkHealth();
const query = new URLSearchParams(window.location.search);
const linkedProject = query.get("project");
if (linkedProject && /^[a-f0-9]{12}$/.test(linkedProject)) {
  openProject(linkedProject).catch((error) => message($("launchMessage"), `Linked project could not be loaded: ${error.message}`));
}
if (query.get("demo") === "fixture") {
  runOutcomeDemo(false);
}
