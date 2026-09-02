import { AppError } from "./errors";

const BLOCKED_HOSTS = new Set([
  "localhost",
  "localhost.localdomain",
  "metadata.google.internal",
  "metadata.google.internal.",
  "169.254.169.254",
  "100.100.100.200",
]);

function isPrivateIpv4(hostname: string): boolean {
  const parts = hostname.split(".");
  if (parts.length !== 4 || parts.some((part) => !/^\d{1,3}$/.test(part))) return false;
  const numbers = parts.map(Number);
  if (numbers.some((part) => part < 0 || part > 255)) return true;
  const [a = 0, b = 0] = numbers;
  return (
    a === 0 ||
    a === 10 ||
    a === 127 ||
    (a === 169 && b === 254) ||
    (a === 172 && b >= 16 && b <= 31) ||
    (a === 192 && b === 168) ||
    (a === 100 && b >= 64 && b <= 127) ||
    a >= 224
  );
}

function isPrivateIpv6(hostname: string): boolean {
  const host = hostname.toLowerCase().replace(/^\[|\]$/g, "");
  if (!host.includes(":")) return false;
  return host === "::" || host === "::1" || host.startsWith("fc") || host.startsWith("fd") || host.startsWith("fe8") || host.startsWith("fe9") || host.startsWith("fea") || host.startsWith("feb") || host.startsWith("::ffff:127.") || host.startsWith("::ffff:10.") || host.startsWith("::ffff:192.168.");
}

export function assertPublicHttpUrl(rawUrl: string): URL {
  let url: URL;
  try {
    url = new URL(rawUrl);
  } catch {
    throw new AppError("SOURCE_URL_BLOCKED", "The URL is invalid.", 422);
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new AppError("SOURCE_URL_BLOCKED", "Only public HTTP and HTTPS URLs are allowed.", 422);
  }
  if (url.username || url.password) {
    throw new AppError("SOURCE_URL_BLOCKED", "URLs containing credentials are not allowed.", 422);
  }
  const hostname = url.hostname.toLowerCase().replace(/\.$/, "");
  if (
    BLOCKED_HOSTS.has(hostname) ||
    hostname.endsWith(".localhost") ||
    hostname.endsWith(".local") ||
    hostname.endsWith(".internal") ||
    hostname.endsWith(".home.arpa") ||
    isPrivateIpv4(hostname) ||
    isPrivateIpv6(hostname)
  ) {
    throw new AppError("SOURCE_URL_BLOCKED", "Private, local, and metadata network targets are blocked.", 422);
  }
  if (url.port && !["80", "443"].includes(url.port)) {
    throw new AppError("SOURCE_URL_BLOCKED", "Only standard HTTP and HTTPS ports are allowed.", 422);
  }
  url.hash = "";
  return url;
}

export function trackedDestination(rawUrl: string, platform: string, missionId: string): string {
  const url = assertPublicHttpUrl(rawUrl);
  url.searchParams.set("utm_source", "finfold_growth_mission");
  url.searchParams.set("utm_medium", platform);
  url.searchParams.set("utm_campaign", missionId);
  return url.toString();
}
