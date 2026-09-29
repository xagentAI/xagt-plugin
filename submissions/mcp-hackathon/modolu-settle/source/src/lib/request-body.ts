/**
 * Bounded JSON request-body reader. The limit is enforced while streaming so
 * that a client cannot bypass it by lying about `Content-Length`
 * (ARCHITECTURE.md §2, §12).
 */
import { AppError } from "./errors";

/** Maximum accepted JSON request body: 16 KiB (code constant). */
export const MAX_JSON_BODY_BYTES = 16 * 1024;

function isJsonContentType(value: string | null): boolean {
  if (value === null) {
    return false;
  }
  const mediaType = value.split(";", 1)[0]?.trim().toLowerCase();
  return mediaType === "application/json";
}

/**
 * Reads and parses a JSON body of at most `maxBytes`. Throws
 * `VALIDATION_ERROR` for a wrong content type, an oversized body, an empty
 * body, or malformed JSON. Returns the parsed value untyped; callers validate
 * its shape with Zod.
 */
export async function readJsonBody(request: Request, maxBytes = MAX_JSON_BODY_BYTES): Promise<unknown> {
  if (!isJsonContentType(request.headers.get("content-type"))) {
    throw new AppError("VALIDATION_ERROR", "Content-Type must be application/json");
  }

  const declaredLength = Number(request.headers.get("content-length") ?? "0");
  if (Number.isFinite(declaredLength) && declaredLength > maxBytes) {
    throw new AppError("VALIDATION_ERROR", `Request body must not exceed ${maxBytes} bytes`);
  }

  const chunks: Uint8Array[] = [];
  let received = 0;
  if (request.body !== null) {
    const reader = request.body.getReader();
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) {
          break;
        }
        received += value.byteLength;
        if (received > maxBytes) {
          throw new AppError("VALIDATION_ERROR", `Request body must not exceed ${maxBytes} bytes`);
        }
        chunks.push(value);
      }
    } finally {
      await reader.cancel().catch(() => undefined);
    }
  }

  if (received === 0) {
    throw new AppError("VALIDATION_ERROR", "Request body must be a JSON object");
  }

  try {
    const text = new TextDecoder("utf-8", { fatal: true }).decode(Buffer.concat(chunks));
    return JSON.parse(text) as unknown;
  } catch {
    throw new AppError("VALIDATION_ERROR", "Request body is not valid JSON");
  }
}

/**
 * For endpoints that take no body (e.g. `POST …/reconcile`): rejects any
 * request that carries one, without buffering it. A declared length is
 * checked first; otherwise the first chunk of the stream decides, and the
 * stream is cancelled either way so nothing is read beyond it.
 */
export async function assertNoRequestBody(request: Request): Promise<void> {
  const declaredLength = Number(request.headers.get("content-length") ?? "0");
  if (Number.isFinite(declaredLength) && declaredLength > 0) {
    throw new AppError("VALIDATION_ERROR", "This endpoint does not accept a request body");
  }
  if (request.body === null) {
    return;
  }
  const reader = request.body.getReader();
  try {
    const { done, value } = await reader.read();
    if (!done && value.byteLength > 0) {
      throw new AppError("VALIDATION_ERROR", "This endpoint does not accept a request body");
    }
  } finally {
    await reader.cancel().catch(() => undefined);
  }
}
