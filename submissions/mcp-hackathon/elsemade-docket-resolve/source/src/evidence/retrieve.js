import { createHash } from "node:crypto";
import { lookup as dnsLookup } from "node:dns/promises";
import { isIP } from "node:net";

const DEFAULT_TIMEOUT_MS = 8_000;
const DEFAULT_MAX_BYTES = 512 * 1024;
const DEFAULT_CONCURRENCY = 4;

export class EvidenceRetrievalError extends Error {
  constructor(code, message, details = undefined) {
    super(message);
    this.name = "EvidenceRetrievalError";
    this.code = code;
    this.details = details;
  }
}

function isPrivateIpv4(hostname) {
  const parts = hostname.split(".").map((part) => Number.parseInt(part, 10));
  if (parts.length !== 4 || parts.some((part) => !Number.isInteger(part) || part < 0 || part > 255)) return false;
  const [first, second, third] = parts;
  return first === 0
    || first === 10
    || (first === 100 && second >= 64 && second <= 127)
    || first === 127
    || (first === 169 && second === 254)
    || (first === 172 && second >= 16 && second <= 31)
    || (first === 192 && (second === 0 || second === 2 || second === 168))
    || (first === 198 && (second === 18 || second === 19 || (second === 51 && third === 100)))
    || (first === 203 && second === 0 && third === 113)
    || first >= 224;
}

function isPrivateIpv6(hostname) {
  const normalized = hostname.toLowerCase();
  return normalized === "::"
    || normalized === "::1"
    || normalized.startsWith("fc")
    || normalized.startsWith("fd")
    || normalized.startsWith("2001:db8")
    || normalized.startsWith("2001:10")
    || normalized.startsWith("ff")
    || /^fe[89ab]/.test(normalized)
    || normalized.startsWith("::ffff:127.")
    || normalized.startsWith("::ffff:10.")
    || normalized.startsWith("::ffff:100.")
    || normalized.startsWith("::ffff:169.254.")
    || normalized.startsWith("::ffff:192.0.")
    || normalized.startsWith("::ffff:192.168.")
    || normalized.startsWith("::ffff:198.18.")
    || normalized.startsWith("::ffff:172.");
}

function isPrivateIp(hostname) {
  const normalized = hostname.toLowerCase().replace(/^\[/, "").replace(/\]$/, "");
  const numericIp = isIP(normalized);
  return numericIp === 4 ? isPrivateIpv4(normalized) : numericIp === 6 ? isPrivateIpv6(normalized) : false;
}

function assertSafeUrl(uri, allowHosts = [], requireAllowlist = false) {
  let url;
  try {
    url = new URL(uri);
  } catch {
    throw new EvidenceRetrievalError("EVIDENCE_URL_INVALID", "Evidence URI is not a valid URL.");
  }
  if (url.protocol !== "https:") {
    throw new EvidenceRetrievalError("EVIDENCE_URL_UNSAFE", "Evidence retrieval only allows HTTPS URLs.");
  }
  if (url.username || url.password || url.hash) {
    throw new EvidenceRetrievalError("EVIDENCE_URL_UNSAFE", "Evidence URI cannot contain credentials or a fragment.");
  }
  if (url.port && url.port !== "443") {
    throw new EvidenceRetrievalError("EVIDENCE_URL_UNSAFE", "Evidence retrieval only allows the HTTPS port.");
  }
  const hostname = url.hostname.toLowerCase().replace(/^\[/, "").replace(/\]$/, "");
  const numericIp = isIP(hostname);
  const privateIp = numericIp === 4 ? isPrivateIpv4(hostname) : numericIp === 6 ? isPrivateIpv6(hostname) : false;
  if (privateIp || hostname === "localhost" || hostname.endsWith(".local")) {
    throw new EvidenceRetrievalError("EVIDENCE_HOST_BLOCKED", "Evidence host is not reachable from the retrieval boundary.");
  }
  if (requireAllowlist && allowHosts.length === 0) {
    throw new EvidenceRetrievalError("EVIDENCE_ALLOWLIST_REQUIRED", "Production evidence retrieval requires an explicit host allowlist.");
  }
  if (allowHosts.length > 0 && !allowHosts.some((host) => hostname === host || hostname.endsWith(`.${host}`))) {
    throw new EvidenceRetrievalError("EVIDENCE_HOST_NOT_ALLOWED", "Evidence host is outside the configured allowlist.");
  }
  return url;
}

async function resolveHostWithTimeout(resolveHost, hostname, timeoutMs) {
  let timer;
  try {
    return await Promise.race([
      resolveHost(hostname, { all: true, verbatim: true }),
      new Promise((_, reject) => {
        timer = setTimeout(
          () => reject(new EvidenceRetrievalError("EVIDENCE_TIMEOUT", "Evidence host resolution exceeded its time limit.")),
          timeoutMs,
        );
      }),
    ]);
  } finally {
    clearTimeout(timer);
  }
}

async function boundedBody(response, maxBytes) {
  const declaredLength = Number(response.headers?.get?.("content-length") ?? 0);
  if (declaredLength > maxBytes) {
    throw new EvidenceRetrievalError("EVIDENCE_TOO_LARGE", "Evidence exceeds the retrieval size limit.");
  }
  if (!response.body?.getReader) {
    const buffer = Buffer.from(await response.arrayBuffer());
    if (buffer.length > maxBytes) throw new EvidenceRetrievalError("EVIDENCE_TOO_LARGE", "Evidence exceeds the retrieval size limit.");
    return buffer;
  }
  const reader = response.body.getReader();
  const chunks = [];
  let size = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > maxBytes) {
      await reader.cancel();
      throw new EvidenceRetrievalError("EVIDENCE_TOO_LARGE", "Evidence exceeds the retrieval size limit.");
    }
    chunks.push(Buffer.from(value));
  }
  return Buffer.concat(chunks);
}

export async function retrieveEvidenceItem(item, {
  fetchImpl = globalThis.fetch,
  timeoutMs = DEFAULT_TIMEOUT_MS,
  maxBytes = DEFAULT_MAX_BYTES,
  allowHosts = [],
  requireAllowlist = false,
  resolveHost = dnsLookup,
} = {}) {
  const url = assertSafeUrl(item.uri, allowHosts, requireAllowlist);
  const resolvedHostname = url.hostname.toLowerCase().replace(/^\[/, "").replace(/\]$/, "");
  const controller = new AbortController();
  const boundedTimeoutMs = Number.isFinite(timeoutMs)
    ? Math.min(Math.max(timeoutMs, 250), 30_000)
    : DEFAULT_TIMEOUT_MS;
  const timer = setTimeout(() => controller.abort(), boundedTimeoutMs);
  try {
    if (isIP(resolvedHostname) === 0) {
      let resolved;
      try {
        resolved = await resolveHostWithTimeout(resolveHost, resolvedHostname, boundedTimeoutMs);
      } catch (error) {
        if (error instanceof EvidenceRetrievalError) throw error;
        throw new EvidenceRetrievalError("EVIDENCE_HOST_RESOLUTION_FAILED", "Evidence host could not be resolved safely.");
      }
      const addresses = Array.isArray(resolved)
        ? resolved.map((entry) => typeof entry === "string" ? entry : entry.address)
        : [resolved?.address ?? resolved];
      if (addresses.some((address) => typeof address !== "string" || isPrivateIp(address))) {
        throw new EvidenceRetrievalError("EVIDENCE_HOST_BLOCKED", "Evidence host resolves to a private or local network address.");
      }
    }
    const response = await fetchImpl(url, {
      method: "GET",
      redirect: "error",
      signal: controller.signal,
      headers: { accept: "application/json, text/plain, text/html;q=0.9" },
    });
    if (!response.ok) {
      throw new EvidenceRetrievalError("EVIDENCE_FETCH_FAILED", "Evidence endpoint returned an unsuccessful status.", { status: response.status });
    }
    const bytes = await boundedBody(response, maxBytes);
    const digest = `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
    if (digest.toLowerCase() !== item.digest.toLowerCase()) {
      throw new EvidenceRetrievalError("EVIDENCE_DIGEST_MISMATCH", "Fetched evidence does not match its declared digest.");
    }
    return {
      id: item.id,
      content: new TextDecoder().decode(bytes),
      contentType: response.headers?.get?.("content-type") ?? "application/octet-stream",
      bytes: bytes.length,
      digest,
      verified: true,
      retrievedAt: new Date().toISOString(),
    };
  } catch (error) {
    if (error instanceof EvidenceRetrievalError) throw error;
    if (error?.name === "AbortError") {
      throw new EvidenceRetrievalError("EVIDENCE_TIMEOUT", "Evidence retrieval exceeded its time limit.");
    }
    throw new EvidenceRetrievalError("EVIDENCE_FETCH_FAILED", "Evidence could not be retrieved safely.");
  } finally {
    clearTimeout(timer);
  }
}

export async function retrieveAgreementEvidence(agreement, options = {}) {
  const evidence = Array.isArray(agreement?.evidence) ? agreement.evidence : [];
  const concurrency = Number.isInteger(options.concurrency)
    ? Math.min(Math.max(options.concurrency, 1), DEFAULT_CONCURRENCY)
    : DEFAULT_CONCURRENCY;
  const results = new Array(evidence.length);
  let cursor = 0;

  async function worker() {
    while (true) {
      const index = cursor++;
      if (index >= evidence.length) return;
      const item = evidence[index];
      try {
        results[index] = { item: await retrieveEvidenceItem(item, options) };
      } catch (error) {
        results[index] = { error: { evidenceId: item.id, code: error.code, message: error.message } };
      }
    }
  }

  await Promise.all(Array.from({ length: Math.min(concurrency, evidence.length) }, worker));
  return {
    items: results.filter((result) => result?.item).map((result) => result.item),
    errors: results.filter((result) => result?.error).map((result) => result.error),
  };
}
