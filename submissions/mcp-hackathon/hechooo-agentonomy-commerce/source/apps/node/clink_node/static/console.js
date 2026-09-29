function setupViews() {
  const buttons = [...document.querySelectorAll(".view-tab")];
  const activate = (button) => {
    document.querySelectorAll(".view").forEach((view) => {
      view.classList.toggle("active", view.dataset.view === button.dataset.target);
    });
    for (const item of buttons) {
      const active = item === button;
      item.classList.toggle("active", active);
      item.setAttribute("aria-selected", String(active));
      item.tabIndex = active ? 0 : -1;
    }
  };
  for (const button of buttons) {
    button.addEventListener("click", () => {
      activate(button);
    });
    button.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
      event.preventDefault();
      const offset = event.key === "ArrowRight" ? 1 : -1;
      const next = buttons[(buttons.indexOf(button) + offset + buttons.length) % buttons.length];
      activate(next);
      next.focus();
    });
  }
}

function selectedUserId() {
  const query = new URLSearchParams(location.search).get("user_id");
  return query || localStorage.getItem("clink.account_user_id") || "";
}

async function fetchJson(path) {
  const response = await fetch(path, {
    headers: {Accept: "application/json"},
  });
  const body = await response.json();
  if (!response.ok) {
    throw new Error(body.detail || `Request failed with HTTP ${response.status}`);
  }
  return body;
}

function shortAddress(value) {
  if (!value || value.length < 12) return value || "Not bound";
  return `${value.slice(0, 8)}...${value.slice(-6)}`;
}

function renderAccount(summary) {
  const core = summary.core || {};
  const mandate = core.active_spending_mandate;
  document.querySelector("#wallet-state").textContent =
    core.wallet_bound ? shortAddress(core.wallet_address) : "Not bound";
  const mandateState = document.querySelector("#mandate-state");
  if (!mandate) {
    mandateState.textContent = "Not authorized";
  } else {
    const limits = mandate.limits_usdc || {};
    mandateState.textContent =
      `${limits.per_transaction || "0"} tx / ` +
      `${limits.rolling_hour || "0"} hour / ${limits.daily || "0"} day`;
  }
  const marketplace = summary.products?.marketplace;
  const prediction = summary.products?.prediction_markets;
  document.querySelector("#business-state").textContent = [
    `Marketplace ${marketplace?.ready ? "ready" : "blocked"}`,
    `Polymarket ${prediction?.ready ? "ready" : "blocked"}`,
  ].join(" / ");
}

function activityCell(value, label) {
  const cell = document.createElement("span");
  cell.setAttribute("role", "cell");
  cell.dataset.label = label;
  cell.textContent = value || "—";
  return cell;
}

function renderActivity(activity) {
  const container = document.querySelector("#activity-rows");
  container.replaceChildren();
  if (!activity.items?.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    const title = document.createElement("p");
    title.textContent = "No recorded activity yet.";
    const detail = document.createElement("span");
    detail.textContent = "Core will add decisions and account changes here.";
    empty.append(title, detail);
    container.append(empty);
    return;
  }
  for (const item of activity.items) {
    const row = document.createElement("div");
    row.className = "activity-row";
    row.setAttribute("role", "row");
    const time = item.at ? new Date(item.at).toLocaleString() : "—";
    row.append(
      activityCell(time, "Time"),
      activityCell(item.event, "Action"),
      activityCell(item.module, "Module"),
      activityCell(item.amount, "Amount"),
      activityCell(item.status, "Status"),
    );
    container.append(row);
  }
}

async function loadAccount(userId) {
  if (!userId) return;
  localStorage.setItem("clink.account_user_id", userId);
  const query = new URLSearchParams(location.search);
  query.set("user_id", userId);
  history.replaceState(null, "", `${location.pathname}?${query}`);
  const encoded = encodeURIComponent(userId);
  try {
    const [account, activity] = await Promise.all([
      fetchJson(`/v1/account/summary?user_id=${encoded}`),
      fetchJson(`/v1/activity?user_id=${encoded}&limit=20`),
    ]);
    renderAccount(account);
    renderActivity(activity);
  } catch (error) {
    document.querySelector("#business-state").textContent =
      `Node unavailable: ${error.message}`;
  }
}

function setupAccountProjection() {
  const input = document.querySelector("#account-user-id");
  const initial = selectedUserId();
  input.value = initial;
  document.querySelector("#account-selector").addEventListener(
    "submit",
    (event) => {
      event.preventDefault();
      loadAccount(input.value.trim());
    },
  );
  if (initial) loadAccount(initial);
}

document.addEventListener("DOMContentLoaded", () => {
  setupViews();
  setupAccountProjection();
});
