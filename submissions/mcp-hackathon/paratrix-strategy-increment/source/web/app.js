"use strict";

// The browser presents server results. Calculation, validation and evidence hashes
// belong to the shared backend engine; display rounding never decides a criterion.
const $ = (id) => document.getElementById(id);
const CRITERIA = [
  "min_drawdown_improvement_pp",
  "max_return_sacrifice_pp",
  "min_return_above_cash_pp",
  "max_drawdown_above_cash_pp",
];
const SOURCE_LABELS = {
  recorded_local_aimm: "录制的本地 AIMM 模拟结果",
  recorded_nexus: "录制的 Nexus 模拟结果",
  inline_simulation: "用户导入的模拟净值",
  synthetic: "构造数据 · 用于方法演示",
};
const STATUS = {
  comparison_only: { label: "事实比较", className: "info", title: "先看清变化，再决定取舍" },
  criteria_met: { label: "达到预设标准", className: "success", title: "这次增量，达到了你的研究标准" },
  criteria_not_met: { label: "未达到预设标准", className: "warning", title: "这次增量，尚未达到全部研究标准" },
};
// Localized presentation only: exception messages and API data remain English.
// Keep unrecognized server text intact so new details are never hidden.
const ERROR_MESSAGES = Object.freeze({
  "network_unavailable": "暂时无法连接服务。请检查连接；如果刚才在保存实验，请先刷新历史记录，确认结果后再重试。",
  "invalid_response": "服务没有返回可读取的数据。如果刚才在保存实验，请先查看历史记录，再决定是否重试。",
  "request_failed": "请求未完成。请检查输入或稍后重试；如果刚才在保存实验，请先查看历史记录。",
  "payload_too_large": "输入超过服务允许的 2 MiB，请缩小数据范围。",
  "file_too_large": "单份净值文件应不超过 2 MiB。请只保留所需的完整日频模拟结果。",
  "incomplete_criteria": "四项标准必须完整填写；也可以明确切换为“只比较事实”。",
  "missing_baseline": "请先选择基线 A 的模拟结果。",
  "missing_candidate": "请先选择候选 B 的模拟结果。",
  "missing_sources": "请先选择基线 A 和候选 B，或载入一个公开案例。",
  "incomplete_period": "指定区间时，需要同时填写起始和结束估值时点。",
  "not_evaluable": "当前输入不满足评估条件。请按字段提示补充数据，系统不会自动补点或截短区间。",
  "missing_template": "暂无可用格式示例，请先恢复案例服务。",
  "host_rejected": "当前访问域名未配置，请使用已发布的服务地址。",
  "origin_rejected": "仅接受来自当前站点的浏览器请求，请回到应用页面重试。",
  "json_required": "请求必须使用 application/json 格式。",
  "invalid_json": "JSON 无效，或包含重复字段、非有限数值。请检查文件格式。",
  "invalid_input": "请检查请求中的字段。",
  "not_found": "当前会话中找不到请求的记录或文件。",
  "session_quota": "当前会话已达到 100 份快照或 100 次实验的限制。",
  "storage_unavailable": "存储暂时不可用。如果刚才在保存实验，请先查看历史记录，再决定是否重试。",
  "stored_data_mismatch": "已保存数据未通过一致性检查，计算和导出已停止。",
  "internal_error": "请求处理失败。如果刚才在保存实验，请先查看历史记录，再决定是否重试。",
  "release_not_bound": "服务尚未绑定实际发布版本。"
});
const ISSUE_MESSAGES = Object.freeze({
  "invalid_field": "字段缺失、类型不正确，或不属于支持的字段。",
  "invalid_curve": "净值曲线必须是 JSON 对象。",
  "missing_field": "缺少必填字段。",
  "unknown_field": "净值曲线包含不支持的字段；仅接受文档列出的字段。",
  "unsupported_schema": "schema_version 必须为整数 1。",
  "invalid_currency": "币种必须由 2 到 20 个大写字母或数字组成，且以字母开头。",
  "unsupported_source": "只接受支持的模拟来源，不接受实盘账户净值。",
  "unknown_cost_model": "费用口径未知；请声明费用模型，或明确采用零费用模拟模型。",
  "invalid_points": "请提供 1 到 5000 个日频估值点，并单独提供初始估值点。",
  "non_increasing_timestamp": "估值时间必须严格递增，不得重复或重新排序。",
  "non_daily_interval": "相邻估值必须恰好相隔 86400 秒，不允许缺失估值点或改变估值时刻。",
  "invalid_provenance": "来源说明必须为对象。",
  "unknown_provenance_field": "来源说明包含不支持的字段；不接受凭据或账户字段。",
  "invalid_boolean": "observed_before 声明必须为布尔值。",
  "incompatible_currency": "A 和 B 必须使用相同币种。",
  "incompatible_cost_model": "A 和 B 必须使用相同费用口径。",
  "mismatched_range": "完整区间的边界不同；请明确选择两份完整曲线共有的估值边界。",
  "invalid_range": "起点必须早于终点，且至少包含一个完整日收益。",
  "boundary_not_present": "区间边界必须与已有估值点完全一致，不允许插值或按最近日期对齐。",
  "mismatched_clock": "A 和 B 必须使用相同且完整的估值时间网格。",
  "incomplete_criteria": "四项标准必须完整填写；也可以明确切换为“只比较事实”。",
  "criteria_out_of_range": "请填写 0 到 10000 之间的有限百分点数值。",
  "number_out_of_range": "数值最多包含 40 位有效数字；非零数值的调整后十进制指数必须在 -30 到 30 之间。",
  "nonpositive_equity": "净值必须为正数；不支持零或负净值。",
  "invalid_point": "估值点必须是包含 timestamp 和 equity 的对象。",
  "invalid_point_fields": "估值点必须且只能包含 timestamp 和 equity 字段。"
});
const CRITERION_LABELS = Object.freeze({
  "min_drawdown_improvement_pp": "相对A回撤改善",
  "max_return_sacrifice_pp": "相对A收益牺牲",
  "min_return_above_cash_pp": "相对现金收益增量",
  "max_drawdown_above_cash_pp": "相对现金新增回撤"
});
const RESULT_SUMMARIES = Object.freeze({
  "comparison_only": "未设置研究标准；仅比较历史模拟事实，不作是否达标的判定。",
  "criteria_met": "在所选历史模拟区间内，四项研究偏好均达到；不代表统计显著性或未来收益。",
  "criteria_not_met": "在所选历史模拟区间内，至少一项研究偏好未达到；请查看逐项收益与回撤取舍。"
});
const DISPLAY_TEXT = Object.freeze({
  "This describes the supplied simulated equity and selected interval only; source declarations do not independently authenticate market data or authorship.": "仅描述输入的模拟净值及所选区间；来源声明不等于对行情真实性或作者身份的独立认证。",
  "Initial 80/20 weights remain fixed without rebalancing; cash earns zero and shared accounts, margin, liquidation, and capital-scale effects are not modeled.": "初始资金按80/20分配，持有份额不变；实际权重随净值变化，不再平衡。现金收益为0，未模拟共享账户、保证金、强平或资本规模效应。",
  "Metrics retain costs already reflected in source equity; no additional costs are deducted, and trading within a strategy is not assumed to be free.": "指标保留来源净值已包含的费用；没有额外扣费，亦不表示策略内部交易免费。",
  "Drawdown is measured at daily valuations and does not represent intraday maximum drawdown; daily volatility is the unannualized sample standard deviation.": "回撤仅在日频估值上计算，不能代表日内最大回撤；日波动使用样本标准差，未年化。",
  "Correlation is descriptive and does not determine whether criteria are met; user-selected thresholds do not establish future performance.": "相关性仅为辅助说明，不触发达标；研究阈值是用户偏好，不能证明未来表现。",
  "The interval contains fewer than 30 daily returns; results are descriptive for a small sample and are not labeled statistically valid.": "所选区间少于30个日收益，结果只适合小样本描述，不标记统计有效性。",
  "With only one daily return, sample standard deviation and return correlation are unavailable.": "只有一个日收益，样本标准差及收益相关性不可用。",
  "B has exactly the same normalized path as A and provides no additional path variation or diversification evidence.": "B的归一化路径与A完全一致，未提供新增路径差异或分散证据。",
  "Constructed data are included to explain the method and validate behavior, not as evidence of a profitable strategy.": "包含构造数据，仅用于说明方法与验证行为，不是可盈利策略证据。",
  "The researcher declared that this interval has already been observed.": "研究者声明已观察过当前区间。",
  "The researcher selected historical exploration.": "研究者选择了历史探索。",
  "The source is marked as previously observed demonstration or historical data.": "来源标记为已观察过的演示或历史数据。",
  "Derived from an existing experiment; exploration history is retained.": "派生自已有实验，保留探索历史。",
  "This session has an experiment over an overlapping interval; it cannot be relabeled as an unseen holdout.": "当前会话曾在重叠区间进行实验，不能重新标记为未见验证。",
  "Must be a finite decimal number; booleans are not accepted.": "必须为有限十进制数，不接受布尔值。",
  "Must be a finite decimal number represented by at most 160 characters.": "必须为有限十进制数，表示长度最多 160 个字符。",
  "Must be a UTC ISO valuation timestamp ending in Z or +00:00, with at most 6 fractional-second digits.": "必须为 UTC ISO 估值时间，以 Z 或 +00:00 结尾，秒的小数位最多 6 位。",
  "Valuation timestamp is not a valid UTC calendar time.": "估值时间不是有效的 UTC 日历时间。",
  "Text must not contain control characters or invalid Unicode surrogates.": "文本不得包含控制字符或无效的 Unicode 代理码。"
});

function translatedText(value) {
  return Object.hasOwn(DISPLAY_TEXT, value) ? DISPLAY_TEXT[value] : value;
}

function errorMessage(error) {
  const message = Object.hasOwn(ERROR_MESSAGES, error?.code)
    ? ERROR_MESSAGES[error.code] : error?.message || ERROR_MESSAGES.request_failed;
  const source = { baseline: "基线 A", candidate: "候选 B" }[error?.source];
  return source ? `${source}：${message}` : message;
}

function issueMessage(issue) {
  if (Object.hasOwn(ISSUE_MESSAGES, issue.code)) return ISSUE_MESSAGES[issue.code];
  const text = translatedText(issue.message);
  if (text !== issue.message) return text;
  const textLimit = /^Must be a nonempty string of at most (\d+) characters\.$/.exec(issue.message);
  if (textLimit) return `必须为非空字符串，长度最多 ${textLimit[1]} 个字符。`;
  const semantic = /^This field must explicitly declare ([a-z0-9_]+)\.$/.exec(issue.message);
  if (semantic) return `此字段必须明确声明为 ${semantic[1]}。`;
  return issue.message || issue.code || "输入不符合要求";
}

const state = {
  baseline: null,
  candidate: null,
  currentExperiment: null,
  parentExperimentId: null,
  busy: false,
  dirty: false,
  chart: "nav",
  history: [],
  historyRequest: 0,
  demoCases: [],
};

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = String(text);
  return node;
}

function formatNumber(value, digits = 2, signed = false) {
  if (value === null || value === undefined || value === "") return "不可用";
  const number = Number(value);
  if (!Number.isFinite(number)) return "不可用";
  return new Intl.NumberFormat("zh-CN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
    signDisplay: signed ? "exceptZero" : "auto",
  }).format(number);
}

function percentage(value, digits = 2) {
  const formatted = formatNumber(value, digits);
  return formatted === "不可用" ? formatted : `${formatted}%`;
}

function dateOnly(value) {
  return typeof value === "string" ? value.slice(0, 10) : "未提供";
}

function dateTime(value) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "未提供";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
    timeZone: "Asia/Shanghai", hour12: false,
  }).format(parsed);
}

class RequestError extends Error {
  constructor(message, issues = [], code = "request_failed") {
    super(message);
    this.issues = Array.isArray(issues) ? issues : [];
    this.code = code;
  }
}

async function request(path, body, rawBody) {
  let response;
  const isPost = body !== undefined || rawBody !== undefined;
  try {
    response = await fetch(path, {
      method: isPost ? "POST" : "GET",
      credentials: "same-origin",
      headers: !isPost ? { Accept: "application/json" } : {
        Accept: "application/json", "Content-Type": "application/json",
      },
      ...(isPost ? { body: rawBody === undefined ? JSON.stringify(body) : rawBody } : {}),
    });
  } catch {
    throw new RequestError("Unable to connect to the service; check experiment history before retrying a save.", [], "network_unavailable");
  }
  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new RequestError("The service returned an unreadable response; check experiment history before retrying a save.", [], "invalid_response");
  }
  if (!response.ok) {
    const error = payload?.error;
    const message = error?.message || (response.status === 413
      ? "Input exceeds the service size limit."
      : "The request failed; check experiment history before retrying a save.");
    throw new RequestError(message, error?.issues, error?.code || (response.status === 413 ? "payload_too_large" : "request_failed"));
  }
  return payload;
}

function showError(error) {
  const box = $("form-error");
  box.replaceChildren(element("strong", null,
    error instanceof RequestError && error.code === "not_evaluable" ? "当前数据无法评估" : "操作需要处理"));
  box.append(element("div", null, errorMessage(error)));
  if (error.issues?.length) {
    const list = element("ul");
    for (const issue of error.issues.slice(0, 20)) {
      list.append(element("li", null, `${issue.path ? `${issue.path}：` : ""}${issueMessage(issue)}`));
    }
    box.append(list);
    if (error.issues.length > 20) box.append(element("p", "help", `另有 ${error.issues.length - 20} 项问题，修正后可再次检查。`));
  }
  box.hidden = false;
}

function clearError() {
  $("form-error").hidden = true;
  $("form-error").replaceChildren();
}

function observedSource(source) {
  if (!source) return false;
  const curve = source.curve || source.metadata || {};
  return curve.provenance?.observed_before === true || curve.observed_before === true
    || ["recorded_local_aimm", "recorded_nexus", "synthetic"].includes(curve.source_kind);
}

function updateSeenState() {
  const observed = observedSource(state.baseline) || observedSource(state.candidate);
  if (observed) $("data-seen").checked = true;
  $("data-seen").disabled = state.busy || observed;
  $("mode-note").textContent = observed
    ? "当前结果已被观察，记录为历史探索。更改阈值或声明固定检验不会消除这项记录。"
    : "普通导入默认历史探索。固定检验仅记录你的声明，不证明数据未曾被观察。";
}

function setBusy(busy, progress = "") {
  state.busy = busy;
  document.body.classList.toggle("busy", busy);
  $("experiment-form").setAttribute("aria-busy", String(busy));
  for (const control of $("experiment-form").querySelectorAll("button, input, select")) control.disabled = busy;
  $("refresh-history").disabled = busy;
  for (const control of $("experiment-history").querySelectorAll("button")) control.disabled = busy;
  $("run-label").textContent = busy ? "正在处理…" : "保存并运行实验";
  $("run-progress").hidden = !busy;
  $("run-progress").textContent = progress;
  updateSeenState();
}

function progress(text) {
  $("run-progress").textContent = text;
}

function markDirty() {
  state.dirty = true;
  $("draft-status").textContent = state.currentExperiment ? "派生草稿" : "编辑中";
  $("stale-notice").hidden = !state.currentExperiment;
  if (state.currentExperiment) {
    state.parentExperimentId = state.currentExperiment.experiment_id;
    renderParentNote();
  }
}

function renderParentNote() {
  $("parent-note").hidden = !state.parentExperimentId;
  $("parent-note").textContent = state.parentExperimentId
    ? `本次将创建新实验，保留来源实验 ${state.parentExperimentId.slice(0, 12)}… 的探索记录。` : "";
}

function renderCurve(slot) {
  const source = state[slot];
  const name = $(`${slot}-name`);
  const meta = $(`${slot}-meta`);
  meta.replaceChildren();
  if (!source) {
    name.textContent = "尚未选择";
    return;
  }
  const curve = source.curve || source.metadata || {};
  name.textContent = curve.name || "已保存的模拟净值";
  const first = curve.initial?.timestamp;
  const points = Array.isArray(curve.points) ? curve.points : [];
  if (first && points.length) {
    meta.append(element("div", null, `${dateOnly(first)} → ${dateOnly(points[points.length - 1]?.timestamp)} · ${points.length} 个日间隔`));
    meta.append(element("div", null, `${curve.currency || "币种未提供"} · 初始 ${formatNumber(curve.initial?.equity)} · UTC`));
  } else {
    meta.append(element("div", null, "沿用当前会话中的不可变数据快照"));
  }
  const sourceLabel = SOURCE_LABELS[curve.source_kind] || "来源待服务端校验";
  meta.append(element("span", "source-label", sourceLabel));
  if (curve.cost_model) meta.append(element("div", null, `费用口径：${curve.cost_model}`));
  if (curve.provenance?.description) {
    const description = element("details", "curve-provenance");
    description.append(element("summary", null, "数据来源说明"), element("div", null, curve.provenance.description));
    meta.append(description);
  }
  if (curve.run_id) meta.append(element("div", null, `回测：${curve.run_id}`));
}

function selectSource(slot, curve, snapshotId = null) {
  state[slot] = { curve, snapshotId, metadata: null };
  renderCurve(slot);
  updateSeenState();
}

function applyDemo(demo) {
  selectSource("baseline", demo.baseline);
  selectSource("candidate", demo.candidate);
  $("demo-description").textContent = demo.description || "公开演示数据，已被观察，按历史探索记录。";
  $("custom-period").checked = false;
  $("period-fields").hidden = true;
  $("period-start").value = demo.baseline.initial?.timestamp || "";
  $("period-end").value = demo.baseline.points?.at(-1)?.timestamp || "";
  $("research-mode").value = "historical_exploration";
  $("data-seen").checked = true;
  markDirty();
}

async function loadDemo() {
  const id = $("demo-select").value;
  if (!id || state.busy) return;
  clearError();
  setBusy(true, "正在载入公开演示案例…");
  try {
    const demo = await request(`/v1/demo-cases/${encodeURIComponent(id)}`);
    applyDemo(demo);
  } catch (error) {
    showError(error);
  } finally {
    setBusy(false);
  }
}

async function importFile(slot, input) {
  const file = input.files?.[0];
  if (!file || state.busy) return;
  clearError();
  setBusy(true, "正在读取模拟净值文件…");
  try {
    if (file.size > 2 * 1024 * 1024) throw new RequestError("A simulation file must not exceed 2 MiB.", [], "file_too_large");
    // Send the original numeric tokens and duplicate fields to the server's
    // strict JSON parser. A browser parse/stringify round trip would lose
    // decimal precision before the canonical validation can inspect it.
    const raw = await file.text();
    progress("正在校验模拟净值并保存原始精度…");
    const saved = await request("/v1/data-snapshots", undefined, `{"curve":${raw}}`);
    selectSource(slot, saved.curve, saved.snapshot_id);
    $("demo-select").value = "";
    $("demo-description").textContent = "已校验并导入模拟净值。运行时继续检查两份结果的区间和费用口径是否可比。";
    markDirty();
  } catch (error) {
    showError(error);
  } finally {
    input.value = "";
    setBusy(false);
  }
}

function updateCriteriaMode() {
  const enabled = document.querySelector('input[name="criteria-mode"]:checked').value === "criteria";
  $("criteria-fields").hidden = !enabled;
  $("criteria-help").textContent = enabled
    ? "固定四项阈值，检查候选的改善是否值得相应取舍。"
    : "展示三组对照及取舍，不给出达标结论。";
}

function readCriteria() {
  if (document.querySelector('input[name="criteria-mode"]:checked').value === "facts") return null;
  const criteria = {};
  const issues = [];
  for (const key of CRITERIA) {
    const value = $(key).value.trim();
    if (value === "" || !Number.isFinite(Number(value)) || Number(value) < 0 || Number(value) > 10000) {
      issues.push({ path: key, code: "criteria_out_of_range", message: "Criteria must be finite percentage-point values between 0 and 10000." });
    } else criteria[key] = value;
  }
  if (issues.length) throw new RequestError("Complete all four criteria or select comparison-only mode.", issues, "incomplete_criteria");
  return criteria;
}

async function snapshot(slot) {
  const source = state[slot];
  if (source?.snapshotId) return source.snapshotId;
  if (!source?.curve) throw new RequestError(`Select the ${slot} simulation first.`, [], `missing_${slot}`);
  const saved = await request("/v1/data-snapshots", { curve: source.curve });
  source.snapshotId = saved.snapshot_id;
  source.curve = saved.curve;
  renderCurve(slot);
  return saved.snapshot_id;
}

async function runExperiment(event) {
  event.preventDefault();
  if (state.busy) return;
  clearError();
  try {
    if (!state.baseline || !state.candidate) throw new RequestError("Select both baseline and candidate simulations, or load a public example.", [], "missing_sources");
    const criteria = readCriteria();
    const customPeriod = $("custom-period").checked;
    const start = customPeriod ? $("period-start").value.trim() : null;
    const end = customPeriod ? $("period-end").value.trim() : null;
    if (customPeriod && (!start || !end)) throw new RequestError("Provide both start and end valuation timestamps for a custom interval.", [], "incomplete_period");
    setBusy(true, "1 / 3 · 校验并保存不可变数据快照…");
    const saved = await Promise.allSettled([snapshot("baseline"), snapshot("candidate")]);
    const failed = saved.findIndex((item) => item.status === "rejected");
    if (failed !== -1) {
      const error = saved[failed].reason;
      const failure = new RequestError(`${failed === 0 ? "Baseline" : "Candidate"}: ${error.message}`, error.issues, error.code);
      failure.source = failed === 0 ? "baseline" : "candidate";
      throw failure;
    }
    const [baselineId, candidateId] = saved.map((item) => item.value);
    progress("2 / 3 · 检查币种、日历、费用与估值区间…");
    const input = { baseline_snapshot_id: baselineId, candidate_snapshot_id: candidateId, start, end };
    const validation = await request("/v1/comparison-inputs/validate", input);
    if (!validation.comparable) throw new RequestError("The inputs do not meet comparison requirements; review the field issues.", validation.issues, "not_evaluable");
    progress("3 / 3 · 运行三组对照并保存实验记录…");
    const experiment = await request("/v1/experiments", {
      ...input,
      criteria,
      mode: $("research-mode").value,
      data_seen: $("data-seen").checked || observedSource(state.baseline) || observedSource(state.candidate),
      parent_experiment_id: state.parentExperimentId,
    });
    state.currentExperiment = experiment;
    state.parentExperimentId = experiment.experiment_id;
    state.dirty = false;
    $("draft-status").textContent = "已保存";
    $("stale-notice").hidden = true;
    renderParentNote();
    renderReport(experiment);
    await refreshHistory(false);
    $("result-title").focus({ preventScroll: true });
    if (window.matchMedia("(max-width: 680px)").matches) $("report").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    showError(error);
  } finally {
    setBusy(false);
  }
}

function renderMetrics(result) {
  const container = $("metric-cards");
  container.replaceChildren();
  const titles = { baseline: "100% A · 原基线", candidate: "80% A + 20% B", cash: "80% A + 20% 现金" };
  for (const key of ["baseline", "candidate", "cash"]) {
    const metric = result.scenarios?.[key] || {};
    const card = element("div", `metric-card ${key}`);
    card.append(element("div", "metric-title", titles[key]));
    card.append(element("div", "metric-primary-label", "区间收益"));
    const direction = Number(metric.total_return_pct) < 0 ? "negative" : "positive";
    card.append(element("div", `metric-value ${direction}`, percentage(metric.total_return_pct)));
    for (const [label, value] of [["最大回撤", metric.max_drawdown_pct], ["日收益波动", metric.daily_volatility_pct]]) {
      const row = element("div", "metric-row");
      row.append(element("span", null, label), element("strong", null, percentage(value)));
      card.append(row);
    }
    container.append(card);
  }
}

function renderCriteria(result) {
  const hasCriteria = Boolean(result.criteria_results?.length);
  const rows = hasCriteria ? result.criteria_results : result.comparison_facts || [];
  $("criteria-results-panel").hidden = rows.length === 0;
  $("criteria-results-title").textContent = hasCriteria ? "是否达到预设标准" : "相对基线与现金的变化";
  $("criteria-results-panel").querySelector(".section-heading > span").textContent = hasCriteria ? "依据未舍入数值判定" : "仅展示变化，不判定达标";
  const body = $("criteria-results");
  body.replaceChildren();
  for (const item of rows) {
    const row = element("tr");
    row.append(element("td", null, Object.hasOwn(CRITERION_LABELS, item.key) ? CRITERION_LABELS[item.key] : item.label));
    const actual = element("td", null, `${formatNumber(item.actual_pp, 4)} pp`);
    actual.title = `未舍入值：${item.actual_pp}`;
    row.append(actual, element("td", null, hasCriteria ? `${item.operator === ">=" ? "≥" : "≤"} ${formatNumber(item.threshold_pp, 4)} pp` : "未设置"));
    const statusCell = element("td");
    statusCell.append(element("span", `condition-status${!hasCriteria ? " facts" : item.met ? "" : " unmet"}`,
      hasCriteria ? item.met ? "达到" : "未达到" : "仅比较事实"));
    row.append(statusCell);
    body.append(row);
  }
}

function svgNode(tag, attributes = {}, text) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
  if (text !== undefined) node.textContent = String(text);
  return node;
}

function renderChart() {
  const series = state.currentExperiment?.result?.series || [];
  const box = $("path-chart");
  box.replaceChildren();
  const drawdown = state.chart === "dd";
  $("chart-title").textContent = drawdown ? "历史回撤路径" : "历史净值路径";
  $("chart-subtitle").textContent = drawdown ? "回撤以正的损失幅度显示" : "各组初始净值归一化为 1";
  $("chart-nav").classList.toggle("active", !drawdown);
  $("chart-dd").classList.toggle("active", drawdown);
  $("chart-nav").setAttribute("aria-pressed", String(!drawdown));
  $("chart-dd").setAttribute("aria-pressed", String(drawdown));
  if (!series.length) return;
  const keys = ["baseline", "candidate", "cash"];
  const value = (row, key) => Number(row[drawdown ? `${key}_drawdown_pct` : key]);
  let min = Infinity;
  let max = -Infinity;
  for (const row of series) {
    for (const key of keys) {
      const number = value(row, key);
      if (!Number.isFinite(number)) continue;
      min = Math.min(min, number);
      max = Math.max(max, number);
    }
  }
  if (!Number.isFinite(min) || !Number.isFinite(max)) {
    box.append(element("p", "help", "当前路径无法绘制，请查看复算包。"));
    return;
  }
  if (drawdown) min = 0;
  const span = max - min || Math.max(Math.abs(max) * 0.03, 0.01);
  if (!drawdown) min -= span * 0.1;
  max += span * 0.1;
  if (max === min) max = min + 0.01;
  const width = 730, height = 262;
  const left = 55, right = 17, top = 12, bottom = 33;
  const plotWidth = width - left - right, plotHeight = height - top - bottom;
  const x = (index) => left + index / Math.max(series.length - 1, 1) * plotWidth;
  const y = (number) => drawdown
    ? top + (number - min) / (max - min) * plotHeight
    : top + (max - number) / (max - min) * plotHeight;
  const svg = svgNode("svg", { viewBox: `0 0 ${width} ${height}`, "aria-hidden": "true" });
  for (let i = 0; i <= 4; i += 1) {
    const number = min + (max - min) * i / 4;
    const position = y(number);
    svg.append(svgNode("line", { x1: left, x2: width - right, y1: position, y2: position, class: "chart-grid-line" }));
    svg.append(svgNode("text", { x: left - 10, y: position + 3, "text-anchor": "end", class: "chart-axis-label" }, `${formatNumber(number, drawdown ? 1 : 3)}${drawdown ? "%" : ""}`));
  }
  const dateIndices = [...new Set([0, Math.floor((series.length - 1) / 2), series.length - 1])];
  for (const index of dateIndices) {
    svg.append(svgNode("text", {
      x: x(index), y: height - 6,
      "text-anchor": index === 0 ? "start" : index === series.length - 1 ? "end" : "middle",
      class: "chart-axis-label",
    }, dateOnly(series[index].timestamp)));
  }
  // Scaling and drawing are presentation only: all NAV and drawdown values
  // arrive from the server, including the initial valuation boundary.
  for (const key of ["cash", "baseline", "candidate"]) {
    let path = "";
    let drawing = false;
    for (let index = 0; index < series.length; index += 1) {
      const number = value(series[index], key);
      if (!Number.isFinite(number)) { drawing = false; continue; }
      path += `${drawing ? "L" : "M"}${x(index).toFixed(2)},${y(number).toFixed(2)} `;
      drawing = true;
    }
    svg.append(svgNode("path", { d: path, class: `chart-path ${key}` }));
  }
  box.append(svg);
}

function renderObservations(result) {
  const body = $("observation-rows");
  const fragment = document.createDocumentFragment();
  for (const point of result.series || []) {
    const row = element("tr");
    const date = element("th", null, point.timestamp);
    date.scope = "row";
    row.append(date);
    for (const key of ["baseline", "candidate", "cash"]) row.append(element("td", null, formatNumber(point[key], 6)));
    for (const key of ["baseline", "candidate", "cash"]) row.append(element("td", null, percentage(point[`${key}_drawdown_pct`], 4)));
    fragment.append(row);
  }
  body.replaceChildren(fragment);
}

function renderDiagnostics(result) {
  const diagnostics = result.diagnostics || {};
  const box = $("diagnostics");
  box.replaceChildren();
  for (const [label, value] of [
    ["A / B 日收益相关性", formatNumber(diagnostics.return_correlation, 4)],
    ["共同亏损日 / 日间隔", `${diagnostics.joint_loss_count ?? "—"} / ${diagnostics.return_observations ?? "—"}`],
    ["A / B 路径是否相同", diagnostics.duplicate_curves ? "相同" : "不同"],
  ]) {
    const item = element("div");
    item.append(element("div", "diagnostic-value", value), element("div", "diagnostic-label", label));
    box.append(item);
  }
}

function renderProvenance(experiment) {
  const p = experiment.provenance || {};
  const config = experiment.config || {};
  const dl = $("provenance");
  dl.replaceChildren();
  const add = (label, value) => dl.append(element("dt", null, label), element("dd", null, value || "未提供"));
  for (const [key, label] of [["baseline", "基线 A"], ["candidate", "候选 B"]]) {
    const source = p[key] || state[key]?.curve || state[key]?.metadata || {};
    add(label, `${source.name || "已保存快照"} · ${SOURCE_LABELS[source.source_kind] || "模拟结果"}`);
    add(`${label} 回测`, source.run_id);
  }
  add("实际研究类型", p.effective_mode === "declared_holdout" ? "声明固定检验（未经独立证明）" : "历史探索");
  add("已见数据声明", (p.data_seen ?? config.data_seen) ? "已观察过数据或相关结果" : "用户声明未观察；系统不能独立验证");
  if (Array.isArray(p.exploration_reasons) && p.exploration_reasons.length) add("探索记录", p.exploration_reasons.map(translatedText).join("；"));
  add("方法", experiment.result.method_version);
  add("固定规则", "初始资金按 80/20 分配，持有份额不变；实际权重随净值变化；不再平衡；现金收益 0");
  add("保存时间", `${dateTime(experiment.created_at)}（北京时间）`);
  if (config.parent_experiment_id) add("来源实验", config.parent_experiment_id);
  for (const [key, label] of [["baseline", "A 数据摘要"], ["candidate", "B 数据摘要"]]) {
    if (p[key]?.content_hash) add(label, p[key].content_hash);
  }
  $("experiment-id").textContent = `实验 ${experiment.experiment_id} · 摘要证明文件一致性，不认证市场真实性。`;
  const limitations = $("limitations");
  limitations.replaceChildren();
  for (const line of experiment.result.limitations || []) limitations.append(element("li", null, translatedText(line)));
  const evidence = $("download-evidence");
  // Only this same-origin API endpoint can be used for downloads; never trust
  // a server-provided arbitrary URL as a navigation target.
  evidence.href = `/v1/experiments/${encodeURIComponent(experiment.experiment_id)}/evidence`;
  evidence.setAttribute("download", `experiment-${experiment.experiment_id}.json`);
}

function renderReport(experiment) {
  const result = experiment.result;
  const status = STATUS[result.status] || STATUS.comparison_only;
  $("empty-state").hidden = true;
  $("report").hidden = false;
  $("result-title").textContent = status.title;
  $("result-status").className = `pill ${status.className}`;
  $("result-status").textContent = status.label;
  $("result-summary-text").textContent = Object.hasOwn(RESULT_SUMMARIES, result.status) ? RESULT_SUMMARIES[result.status] : result.summary;
  const coverage = result.coverage || {};
  const count = Number(coverage.observations);
  const coverageLabel = Number.isInteger(count) && count > 0 ? `${count} 个估值点（${count - 1} 个日间隔）` : "估值数量未提供";
  $("result-period").textContent = `${dateOnly(coverage.start)} → ${dateOnly(coverage.end)} · ${coverageLabel} · ${coverage.currency || ""}`;
  $("result-mode").textContent = experiment.provenance?.effective_mode === "declared_holdout"
    ? "声明固定检验 · 未经独立证明" : "历史探索 · 可追溯记录";
  renderMetrics(result);
  renderCriteria(result);
  renderChart();
  renderObservations(result);
  renderDiagnostics(result);
  renderProvenance(experiment);
}

function renderHistory() {
  const box = $("experiment-history");
  box.replaceChildren();
  if (!state.history.length) {
    box.append(element("p", "history-empty", "尚无实验记录。运行第一个案例后，会在这里留下记录。"));
    return;
  }
  for (const entry of state.history) {
    const status = STATUS[entry.status] || STATUS.comparison_only;
    const current = entry.experiment_id === state.currentExperiment?.experiment_id;
    const button = element("button", `history-item${current ? " current" : ""}`);
    button.type = "button";
    button.disabled = state.busy;
    const title = element("div");
    title.append(element("strong", null, `${entry.baseline_name || "基线 A"} + ${entry.candidate_name || "候选 B"}`));
    title.append(element("small", null, `${dateTime(entry.created_at)} · ${entry.experiment_id.slice(0, 10)} · ${entry.mode === "declared_holdout" ? "声明固定检验" : "历史探索"}`));
    button.append(title, element("span", `pill ${status.className}`, status.label));
    button.addEventListener("click", () => loadExperiment(entry.experiment_id));
    box.append(button);
  }
}

async function refreshHistory(showFailure = true) {
  const generation = ++state.historyRequest;
  try {
    const response = await request("/v1/experiments");
    if (generation !== state.historyRequest) return;
    state.history = response.experiments || [];
    renderHistory();
  } catch (error) {
    if (showFailure && generation === state.historyRequest) {
      $("experiment-history").replaceChildren(element("p", "history-empty", errorMessage(error)));
    }
  }
}

async function loadExperiment(id) {
  if (state.busy) return;
  clearError();
  setBusy(true, "正在读取已保存的实验…");
  try {
    const experiment = await request(`/v1/experiments/${encodeURIComponent(id)}`);
    const config = experiment.config || {};
    state.currentExperiment = experiment;
    state.parentExperimentId = experiment.experiment_id;
    for (const slot of ["baseline", "candidate"]) {
      state[slot] = { snapshotId: config[`${slot}_snapshot_id`], curve: null, metadata: experiment.provenance?.[slot] || {} };
      renderCurve(slot);
    }
    $("demo-select").value = "";
    $("demo-description").textContent = "已载入保存的实验。修改后再次运行会创建新记录，原实验保持不变。";
    $("custom-period").checked = Boolean(config.start || config.end);
    $("period-fields").hidden = !$("custom-period").checked;
    $("period-start").value = config.start || experiment.result.coverage?.start || "";
    $("period-end").value = config.end || experiment.result.coverage?.end || "";
    $("research-mode").value = config.mode || "historical_exploration";
    $("data-seen").checked = config.data_seen !== false;
    document.querySelector(`input[name="criteria-mode"][value="${config.criteria ? "criteria" : "facts"}"]`).checked = true;
    for (const key of CRITERIA) $(key).value = config.criteria?.[key] ?? "";
    updateCriteriaMode();
    updateSeenState();
    state.dirty = false;
    $("draft-status").textContent = "已保存";
    $("stale-notice").hidden = true;
    renderParentNote();
    renderReport(experiment);
    renderHistory();
  } catch (error) {
    showError(error);
  } finally {
    setBusy(false);
  }
}

async function downloadTemplate() {
  if (state.busy) return;
  clearError();
  setBusy(true, "正在准备格式示例…");
  try {
    const id = state.demoCases[0]?.id;
    if (!id) throw new RequestError("No format example is available; restore the example service first.", [], "missing_template");
    const demo = await request(`/v1/demo-cases/${encodeURIComponent(id)}`);
    const blob = new Blob([JSON.stringify(demo.baseline, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = element("a");
    link.href = url;
    link.download = "simulation-curve-example.json";
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) {
    showError(error);
  } finally {
    setBusy(false);
  }
}

async function initialize() {
  $("experiment-form").addEventListener("submit", runExperiment);
  $("load-demo").addEventListener("click", loadDemo);
  $("baseline-file").addEventListener("change", (event) => importFile("baseline", event.target));
  $("candidate-file").addEventListener("change", (event) => importFile("candidate", event.target));
  $("download-template").addEventListener("click", downloadTemplate);
  $("custom-period").addEventListener("change", () => { $("period-fields").hidden = !$("custom-period").checked; markDirty(); });
  for (const input of document.querySelectorAll('input[name="criteria-mode"]')) input.addEventListener("change", () => { updateCriteriaMode(); markDirty(); });
  for (const id of [...CRITERIA, "period-start", "period-end", "research-mode", "data-seen"]) $(id).addEventListener("input", markDirty);
  $("criteria-preset").addEventListener("click", () => { CRITERIA.forEach((key, index) => { $(key).value = [0, 2, 0, 2][index]; }); markDirty(); });
  $("chart-nav").addEventListener("click", () => { state.chart = "nav"; renderChart(); });
  $("chart-dd").addEventListener("click", () => { state.chart = "dd"; renderChart(); });
  $("refresh-history").addEventListener("click", () => refreshHistory());
  $("demo-select").addEventListener("change", () => {
    const selected = state.demoCases.find((item) => item.id === $("demo-select").value);
    if (selected) $("demo-description").textContent = `待载入：${selected.description || selected.name}`;
  });
  setBusy(true, "正在建立研究会话并载入案例…");
  try {
    // Keep the draft stable during bootstrap. The HTML normally sets the cookie;
    // this also prevents concurrent writes if the API must establish it again.
    const response = await request("/v1/demo-cases");
    state.demoCases = response.cases || [];
    const select = $("demo-select");
    select.replaceChildren(element("option", null, "选择案例"));
    select.firstChild.value = "";
    for (const demo of state.demoCases) {
      const option = element("option", null, demo.name);
      option.value = demo.id;
      select.append(option);
    }
    if (state.demoCases.length) {
      select.value = state.demoCases[0].id;
      const demo = await request(`/v1/demo-cases/${encodeURIComponent(select.value)}`);
      applyDemo(demo);
      $("draft-status").textContent = "待运行";
    }
    await refreshHistory();
  } catch (error) {
    $("demo-select").replaceChildren(element("option", null, "案例暂不可用"));
    $("service-message").textContent = `${errorMessage(error)} 可刷新页面重新载入案例，或导入自己的模拟净值 JSON。`;
    $("service-message").hidden = false;
  } finally {
    setBusy(false);
  }
}

initialize();
