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
  subtype.textContent = SUBCATEGORY_LABELS[service.subcategory] || "Other";
  identity.append(title, subtype);
  header.append(serviceIcon(service), identity);
  const description = document.createElement("p");
  description.textContent = service.description || "No service description provided.";
  const facts = document.createElement("div");
  facts.className = "service-facts";
  facts.append(
    serviceMeta("FROM", formatPrice(service.starting_price_usd)),
    serviceMeta("NETWORK", service.networks?.join(" · ") || "Not specified"),
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
  count.textContent = `${services.length} ${services.length === 1 ? "service" : "services"}`;
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
  const container = document.querySelector("#marketplace-services");
  if (!container) return;
  container.replaceChildren();
  container.setAttribute("aria-busy", "false");
  const services = catalog.services || [];
  document.querySelector("#marketplace-count").textContent =
    `${services.length} current services`;
  if (!services.length) {
    container.append(marketplaceState(
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
  container.append(
    ...CATEGORY_ORDER
      .filter((category) => grouped.get(category).length)
      .map((category) => serviceGroup(category, grouped.get(category))),
  );
}

async function loadMarketplace() {
  const container = document.querySelector("#marketplace-services");
  if (!container) return;
  try {
    renderMarketplace(await fetchJson("/v1/marketplace/services?limit=20"));
  } catch (_error) {
    container.replaceChildren(marketplaceState(
      "Marketplace service catalog temporarily unavailable.",
      "error",
    ));
    container.setAttribute("aria-busy", "false");
    document.querySelector("#marketplace-count").textContent = "Catalog unavailable";
  }
}

function setupAuthorizationField() {
  const field = document.querySelector("#authorization-field");
  const detail = document.querySelector("#gate-detail");
  if (!field || !detail) return;
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!reducedMotion) {
    window.requestAnimationFrame(() => field.classList.add("is-running"));
  }
  const gates = [...field.querySelectorAll(".control-gate")];
  const activate = (gate) => {
    for (const item of gates) item.classList.toggle("is-active", item === gate);
    detail.textContent = gate.dataset.gateDetail;
  };
  for (const gate of gates) {
    gate.addEventListener("focus", () => activate(gate));
    gate.addEventListener("pointerenter", () => activate(gate));
    gate.addEventListener("click", () => activate(gate));
  }
}

document.addEventListener("DOMContentLoaded", () => {
  setupAuthorizationField();
  loadMarketplace();
});
