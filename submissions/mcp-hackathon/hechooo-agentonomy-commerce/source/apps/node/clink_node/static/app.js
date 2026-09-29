const CATEGORY_ORDER = [
  "data",
  "search",
  "infrastructure",
  "inference",
  "media",
  "other",
];

const CATEGORY_LABELS = {
  data: "Data & Analytics",
  search: "Search & Research",
  infrastructure: "Infrastructure",
  inference: "AI & Inference",
  media: "Media & Content",
  other: "More Services",
};

const SUBCATEGORY_LABELS = {
  onchain_data: "Onchain data",
  market_data: "Market data",
  risk_identity: "Risk & identity",
  analytics: "Analytics",
  general_data: "Data service",
  web_search: "Web search",
  research: "Research",
  semantic_search: "Semantic search",
  content_extraction: "Content extraction",
  general_search: "Search service",
  rpc: "RPC",
  storage: "Storage",
  developer_tools: "Developer tools",
  automation: "Automation",
  general_infrastructure: "Infrastructure",
  language_models: "Language models",
  voice_audio: "Voice & audio",
  vision: "Vision",
  general_inference: "AI service",
  audio_video: "Audio & video",
  content_processing: "Content processing",
  general_media: "Media service",
  other: "Other",
};

function setupViews() {
  for (const button of document.querySelectorAll(".view-tab")) {
    button.addEventListener("click", () => {
      document.querySelectorAll(".view-tab, .view").forEach((node) => {
        node.classList.remove("active");
      });
      button.classList.add("active");
      document.querySelector(
        `[data-view="${button.dataset.target}"]`
      )?.classList.add("active");
    });
  }
}

function selectedUserId() {
  const query = new URLSearchParams(location.search).get("user_id");
  return query || localStorage.getItem("clink.account_user_id") || "";
}

async function fetchJson(path) {
  const response = await fetch(path, {
    headers: {"Accept": "application/json"},
  });
  const body = await response.json();
  if (!response.ok) {
    throw new Error(
      body.detail || `Request failed with HTTP ${response.status}`
    );
  }
  return body;
}

function serviceMeta(label, value) {
  const item = document.createElement("span");
  const key = document.createElement("small");
  const content = document.createElement("strong");
  key.textContent = label;
  content.textContent = value;
  item.append(key, content);
  return item;
}

function trustLabel(value) {
  const text = (value || "verified").replaceAll("_", " ");
  return `${text.charAt(0).toUpperCase()}${text.slice(1)}`;
}

function formatPrice(value) {
  if (value == null || value === "") return "Quote required";
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) return "Quote required";
  return `$${new Intl.NumberFormat("en-US", {
    maximumSignificantDigits: 6,
    useGrouping: false,
  }).format(number)}`;
}

function iconTone(value) {
  let hash = 0;
  for (const character of value || "") {
    hash = ((hash << 5) - hash + character.charCodeAt(0)) | 0;
  }
  return `tone-${Math.abs(hash) % 6}`;
}

function serviceIcon(service) {
  const icon = document.createElement("span");
  icon.className = "service-icon";
  icon.classList.add(iconTone(service.icon_key));
  icon.dataset.iconKey = service.icon_key || "service-fallback";
  icon.setAttribute("aria-hidden", "true");
  icon.textContent = (service.icon_text || "?").slice(0, 2);
  return icon;
}

function serviceCard(service) {
  const card = document.createElement("article");
  card.className = "service-card";
  const header = document.createElement("div");
  header.className = "service-card-header";
  const identity = document.createElement("div");
  identity.className = "service-identity";
  const title = document.createElement("h3");
  title.textContent = service.name || "Unnamed service";
  const subtype = document.createElement("span");
  subtype.className = "service-subcategory";
  subtype.textContent =
    SUBCATEGORY_LABELS[service.subcategory] || "Other";
  identity.append(title, subtype);
  header.append(serviceIcon(service), identity);
  const description = document.createElement("p");
  description.textContent =
    service.description || "No service description provided.";
  const facts = document.createElement("div");
  facts.className = "service-facts";
  const price = formatPrice(service.starting_price_usd);
  facts.append(
    serviceMeta("FROM", price),
    serviceMeta(
      "NETWORK",
      service.networks?.join(" · ") || "Not specified",
    ),
    serviceMeta("TRUST", trustLabel(service.trust_tier)),
  );
  card.append(header, description, facts);
  return card;
}

function serviceGroup(category, services) {
  const section = document.createElement("section");
  section.className = "service-category";
  section.dataset.category = category;

  const header = document.createElement("div");
  header.className = "service-category-header";
  const title = document.createElement("h3");
  title.textContent = CATEGORY_LABELS[category] || CATEGORY_LABELS.other;
  const count = document.createElement("span");
  count.textContent = `${services.length} ${
    services.length === 1 ? "service" : "services"
  }`;
  header.append(title, count);

  const grid = document.createElement("div");
  grid.className = "service-grid";
  grid.append(...services.map(serviceCard));
  section.append(header, grid);
  return section;
}

function marketplaceState(message, kind) {
  const state = document.createElement("div");
  state.className = `marketplace-state ${kind}`;
  state.textContent = message;
  return state;
}

function renderMarketplace(catalog) {
  const grid = document.querySelector("#marketplace-services");
  if (!grid) return;
  grid.replaceChildren();
  grid.setAttribute("aria-busy", "false");
  const services = catalog.services || [];
  document.querySelector("#marketplace-count").textContent =
    `${services.length} verified services`;
  if (!services.length) {
    grid.append(marketplaceState(
      "No usable services are available right now.",
      "empty",
    ));
    return;
  }
  const grouped = new Map(CATEGORY_ORDER.map((category) => [category, []]));
  for (const service of services) {
    const category = CATEGORY_ORDER.includes(service.category)
      ? service.category
      : "other";
    grouped.get(category).push(service);
  }
  grid.append(
    ...CATEGORY_ORDER
      .filter((category) => grouped.get(category).length)
      .map((category) => serviceGroup(category, grouped.get(category))),
  );
}

async function loadMarketplace() {
  const grid = document.querySelector("#marketplace-services");
  if (!grid) return;
  try {
    renderMarketplace(
      await fetchJson("/v1/marketplace/services?limit=20"),
    );
  } catch (error) {
    grid.replaceChildren(marketplaceState(
      "Marketplace service catalog temporarily unavailable.",
      "error",
    ));
    grid.setAttribute("aria-busy", "false");
    document.querySelector("#marketplace-count").textContent =
      "Catalog unavailable";
  }
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

function activityCell(value) {
  const cell = document.createElement("span");
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
      activityCell(time),
      activityCell(item.event),
      activityCell(item.module),
      activityCell(item.amount),
      activityCell(item.status),
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

async function unlockInteraction() {
  const shell = document.querySelector("[data-interaction-id]");
  if (!shell) return;
  const token = new URLSearchParams(location.hash.slice(1)).get("token");
  if (!token) {
    document.querySelector("#interaction-state p").textContent =
      "This link does not contain an access token.";
    return;
  }
  const response = await fetch(
    `/v1/interactions/${shell.dataset.interactionId}/consume`,
    {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({token}),
    },
  );
  const body = await response.json();
  if (!response.ok) {
    document.querySelector("#interaction-state p").textContent =
      body.detail || "This request is unavailable.";
    return;
  }
  history.replaceState(null, "", location.pathname);
  const output = document.querySelector("#interaction-payload");
  output.textContent = JSON.stringify(body.payload, null, 2);
  output.hidden = false;
  document.querySelector("#interaction-state p").textContent =
    "Request unlocked. Verify every field before signing.";
}

document.addEventListener("DOMContentLoaded", () => {
  loadMarketplace();
  setupViews();
  setupAccountProjection();
  document.querySelector("#unlock-interaction")
    ?.addEventListener("click", unlockInteraction);
});
