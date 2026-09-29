export const OLAXBT_NEXUS_URL = "https://nexus.olaxbt.xyz/api/mcp/tools/call";

export class OlaXbtNexusError extends Error {
  constructor(code, message, { status = null, tool = null, detail = null } = {}) {
    super(message);
    this.name = "OlaXbtNexusError";
    this.code = code;
    this.status = status;
    this.tool = tool;
    this.detail = detail;
  }
}

export function resolveOlaXbtApiKey(env = process.env) {
  const key = String(env.OLAXBT_NEXUS_API_KEY || env.OLAXBT_API_KEY || "").trim();
  if (!key) {
    throw new OlaXbtNexusError(
      "OLAXBT_NEXUS_API_KEY_MISSING",
      "Server-side OlaXBT Nexus API key is not configured."
    );
  }
  return key;
}

function compactDetail(payload) {
  if (payload == null) return null;
  if (typeof payload === "string") return payload.slice(0, 500);
  if (typeof payload === "object") {
    const candidate = payload.error ?? payload.message ?? payload.detail ?? payload.reason ?? null;
    if (candidate == null) return null;
    return typeof candidate === "string" ? candidate.slice(0, 500) : JSON.stringify(candidate).slice(0, 500);
  }
  return String(payload).slice(0, 500);
}

function parseTextContent(value) {
  if (typeof value !== "string") return value;
  const text = value.trim();
  if (!text) return value;
  try { return JSON.parse(text); } catch { return value; }
}

export function unwrapNexusPayload(payload) {
  let current = payload;
  for (let depth = 0; depth < 6; depth += 1) {
    if (Array.isArray(current)) return current;
    if (current == null || typeof current !== "object") return parseTextContent(current);

    if (Array.isArray(current.content) && current.content.length > 0) {
      const textItem = current.content.find((item) => item && typeof item === "object" && typeof item.text === "string");
      if (textItem) {
        current = parseTextContent(textItem.text);
        continue;
      }
    }

    const wrapperKeys = ["result", "data", "output", "payload"];
    const key = wrapperKeys.find((candidate) => Object.prototype.hasOwnProperty.call(current, candidate));
    if (key) {
      current = current[key];
      continue;
    }
    return current;
  }
  return current;
}

export async function callOlaXbtTool(name, args = {}, {
  fetchImpl = fetch,
  apiKey = null,
  timeoutMs = 15000
} = {}) {
  const key = apiKey || resolveOlaXbtApiKey();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  let response;
  try {
    response = await fetchImpl(OLAXBT_NEXUS_URL, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-api-key": key
      },
      body: JSON.stringify({ name, arguments: args }),
      signal: controller.signal
    });
  } catch (error) {
    const code = error?.name === "AbortError" ? "OLAXBT_UPSTREAM_TIMEOUT" : "OLAXBT_UPSTREAM_UNAVAILABLE";
    throw new OlaXbtNexusError(code, `OlaXBT Nexus call failed for ${name}.`, {
      tool: name,
      detail: String(error?.message || error)
    });
  } finally {
    clearTimeout(timer);
  }

  const raw = await response.text();
  let parsed;
  try {
    parsed = raw ? JSON.parse(raw) : null;
  } catch {
    throw new OlaXbtNexusError("OLAXBT_UPSTREAM_MALFORMED_RESPONSE", `OlaXBT Nexus returned non-JSON for ${name}.`, {
      status: response.status,
      tool: name
    });
  }

  if (!response.ok) {
    const code = response.status === 401 || response.status === 403
      ? "OLAXBT_UPSTREAM_AUTH_FAILED"
      : "OLAXBT_UPSTREAM_HTTP_ERROR";
    throw new OlaXbtNexusError(code, `OlaXBT Nexus returned HTTP ${response.status} for ${name}.`, {
      status: response.status,
      tool: name,
      detail: compactDetail(parsed)
    });
  }

  return {
    tool: name,
    status: response.status,
    payload: unwrapNexusPayload(parsed)
  };
}
