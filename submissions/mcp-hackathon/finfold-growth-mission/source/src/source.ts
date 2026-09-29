import { sha256Hex } from "./crypto";
import { AppError } from "./errors";
import { readTextBounded } from "./http";
import type { SemanticSection, SourceEvidence } from "./schemas";
import { assertPublicHttpUrl } from "./url-safety";

const MAX_SOURCE_BYTES = 1_500_000;
const MAX_REDIRECTS = 3;
const MAX_SECTIONS = 80;
const MAX_SECTION_CHARS = 1_200;

const ENTITIES: Record<string, string> = {
  amp: "&",
  apos: "'",
  gt: ">",
  hellip: "…",
  laquo: "«",
  ldquo: "“",
  lsquo: "‘",
  lt: "<",
  nbsp: " ",
  quot: '"',
  raquo: "»",
  rdquo: "”",
  rsquo: "’",
};

function decodeEntities(value: string): string {
  return value
    .replace(/&#(x?[0-9a-f]+);?/gi, (_, code: string) => {
      const numeric = code.toLowerCase().startsWith("x")
        ? Number.parseInt(code.slice(1), 16)
        : Number.parseInt(code, 10);
      return Number.isFinite(numeric) && numeric > 0 && numeric <= 0x10ffff
        ? String.fromCodePoint(numeric)
        : " ";
    })
    .replace(/&([a-z]+);/gi, (_, name: string) => ENTITIES[name.toLowerCase()] ?? " ");
}

export function normalizeExtractedText(value: string): string {
  return decodeEntities(value.replace(/<[^>]*>/g, " "))
    .replace(/\p{Cc}+/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function metaContent(html: string, key: "description" | "og:title" | "og:description"): string | undefined {
  const escaped = key.replace(":", "\\:");
  const patterns = [
    new RegExp(`<meta[^>]+(?:name|property)=["']${escaped}["'][^>]+content=["']([^"']+)["'][^>]*>`, "i"),
    new RegExp(`<meta[^>]+content=["']([^"']+)["'][^>]+(?:name|property)=["']${escaped}["'][^>]*>`, "i"),
  ];
  for (const pattern of patterns) {
    const match = html.match(pattern)?.[1];
    if (match) return normalizeExtractedText(match);
  }
  return undefined;
}

function jsonLdTexts(html: string): string[] {
  const values: string[] = [];
  const pattern = /<script[^>]+type=["']application\/ld\+json["'][^>]*>([\s\S]*?)<\/script>/gi;
  for (const match of html.matchAll(pattern)) {
    if (values.length >= 8) break;
    const raw = match[1]?.trim();
    if (!raw || raw.length > 100_000) continue;
    try {
      const parsed: unknown = JSON.parse(raw);
      const queue: unknown[] = [parsed];
      const text: string[] = [];
      let visited = 0;
      while (queue.length && visited < 200) {
        visited += 1;
        const item = queue.shift();
        if (Array.isArray(item)) {
          queue.push(...item.slice(0, 30));
        } else if (item && typeof item === "object") {
          for (const [key, value] of Object.entries(item)) {
            if (["name", "description", "headline", "slogan", "category"].includes(key) && typeof value === "string") {
              const normalized = normalizeExtractedText(value);
              if (normalized.length >= 3) text.push(normalized);
            } else if (["@graph", "mainEntity", "itemListElement", "offers", "about"].includes(key)) {
              queue.push(value);
            }
          }
        }
      }
      if (text.length) values.push(text.join(" · ").slice(0, MAX_SECTION_CHARS));
    } catch {
      continue;
    }
  }
  return values;
}

export function extractSemanticSections(html: string): { title: string; sections: SemanticSection[] } {
  const safeHtml = html
    .replace(/<!--([\s\S]*?)-->/g, " ")
    .replace(/<(script|style|noscript|svg|template|iframe)\b[^>]*>[\s\S]*?<\/\1>/gi, " ");
  const candidates: Array<Omit<SemanticSection, "id">> = [];
  const title = normalizeExtractedText(html.match(/<title\b[^>]*>([\s\S]*?)<\/title>/i)?.[1] ?? metaContent(html, "og:title") ?? "");
  if (title) candidates.push({ kind: "title", text: title });
  for (const description of [metaContent(html, "description"), metaContent(html, "og:description")]) {
    if (description) candidates.push({ kind: "description", text: description });
  }

  const tagPattern = /<(h1|h2|h3|p|li|a)\b[^>]*>([\s\S]*?)<\/\1>/gi;
  for (const match of safeHtml.matchAll(tagPattern)) {
    if (candidates.length >= MAX_SECTIONS) break;
    const tag = match[1]?.toLowerCase();
    const text = normalizeExtractedText(match[2] ?? "").slice(0, MAX_SECTION_CHARS);
    if (text.length < 3) continue;
    const kind: SemanticSection["kind"] = tag?.startsWith("h")
      ? "heading"
      : tag === "li"
        ? "list"
        : tag === "a"
          ? "link"
          : "paragraph";
    if (!candidates.some((candidate) => candidate.text === text)) candidates.push({ kind, text });
  }
  for (const text of jsonLdTexts(html)) {
    if (!candidates.some((candidate) => candidate.text === text)) candidates.push({ kind: "structured-data", text });
  }

  const sections = candidates.slice(0, MAX_SECTIONS).map((section, index) => ({
    id: `s${index + 1}`,
    ...section,
  }));
  return { title, sections };
}

export async function fetchSourceEvidence(
  rawUrl: string,
  fetcher: typeof fetch = fetch,
): Promise<SourceEvidence> {
  let current = assertPublicHttpUrl(rawUrl);
  let response: Response | undefined;

  for (let redirect = 0; redirect <= MAX_REDIRECTS; redirect += 1) {
    try {
      response = await fetcher(current, {
        method: "GET",
        redirect: "manual",
        headers: {
          accept: "text/html,application/xhtml+xml;q=0.9",
          "user-agent": "FinfoldGrowthMission/1.0 (+https://api.finfold.app)",
        },
        signal: AbortSignal.timeout(10_000),
      });
    } catch {
      throw new AppError("SOURCE_FETCH_FAILED", "The source page could not be fetched.", 422, { retryable: true });
    }
    if ([301, 302, 303, 307, 308].includes(response.status)) {
      if (redirect === MAX_REDIRECTS) {
        throw new AppError("SOURCE_FETCH_FAILED", "The source exceeded the redirect limit.", 422);
      }
      const location = response.headers.get("location");
      if (!location) throw new AppError("SOURCE_FETCH_FAILED", "The source returned an invalid redirect.", 422);
      const next = assertPublicHttpUrl(new URL(location, current).toString());
      if (current.protocol === "https:" && next.protocol === "http:") {
        throw new AppError("SOURCE_URL_BLOCKED", "HTTPS-to-HTTP redirects are blocked.", 422);
      }
      current = next;
      continue;
    }
    break;
  }

  if (!response || !response.ok) {
    throw new AppError("SOURCE_FETCH_FAILED", `The source returned HTTP ${response?.status ?? "unknown"}.`, 422, {
      retryable: (response?.status ?? 500) >= 500,
    });
  }
  const mime = response.headers.get("content-type")?.split(";", 1)[0]?.trim().toLowerCase();
  if (mime !== "text/html" && mime !== "application/xhtml+xml") {
    throw new AppError("SOURCE_INVALID_MIME", "The source must return public HTML.", 422, {
      details: { received: mime ?? "missing" },
    });
  }

  const html = await readTextBounded(response, MAX_SOURCE_BYTES);
  const { title, sections } = extractSemanticSections(html);
  const totalText = sections.reduce((sum, section) => sum + section.text.length, 0);
  const scripts = (html.match(/<script\b/gi) ?? []).length;
  if (totalText < 180 && scripts >= 3) {
    throw new AppError("SOURCE_NEEDS_RENDERING", "The page appears to require JavaScript rendering.", 422);
  }
  if (sections.length < 3 || totalText < 240) {
    throw new AppError("INSUFFICIENT_EVIDENCE", "The page does not contain enough public evidence.", 422);
  }
  const digest = await sha256Hex(sections.map((section) => `${section.id}:${section.text}`).join("\n"));
  return { finalUrl: current.toString(), digest, title, sections };
}
