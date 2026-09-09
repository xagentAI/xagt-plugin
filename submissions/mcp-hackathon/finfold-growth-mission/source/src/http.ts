import { AppError, asAppError } from "./errors";

const JSON_HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "no-store",
  "x-content-type-options": "nosniff",
} as const;

export function jsonResponse(body: unknown, status = 200, headers?: HeadersInit): Response {
  const responseHeaders = new Headers(JSON_HEADERS);
  if (headers) {
    for (const [key, value] of new Headers(headers)) responseHeaders.set(key, value);
  }
  return new Response(JSON.stringify(body), { status, headers: responseHeaders });
}

export function errorResponse(error: unknown, requestId: string): Response {
  const appError = asAppError(error);
  const body: Record<string, unknown> = {
    error: {
      code: appError.code,
      message: appError.message,
      retryable: appError.retryable,
      requestId,
    },
  };
  if (appError.details) body.error = { ...(body.error as object), details: appError.details };
  return jsonResponse(body, appError.status);
}

export function requestIdFrom(request: Request): string {
  const provided = request.headers.get("x-request-id");
  if (provided && /^[A-Za-z0-9._-]{8,96}$/.test(provided)) return provided;
  return crypto.randomUUID();
}

export async function readJsonBody(request: Request, maxBytes = 32_768): Promise<unknown> {
  const contentType = request.headers.get("content-type")?.split(";", 1)[0]?.trim();
  if (contentType !== "application/json") {
    throw new AppError("INVALID_REQUEST", "Content-Type must be application/json.", 415);
  }

  const declared = Number(request.headers.get("content-length") ?? 0);
  if (Number.isFinite(declared) && declared > maxBytes) {
    throw new AppError("INVALID_REQUEST", `Request body exceeds ${maxBytes} bytes.`, 413);
  }
  if (!request.body) throw new AppError("INVALID_REQUEST", "A JSON request body is required.", 400);

  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  while (true) {
    const result = await reader.read();
    if (result.done) break;
    total += result.value.byteLength;
    if (total > maxBytes) {
      await reader.cancel("body too large");
      throw new AppError("INVALID_REQUEST", `Request body exceeds ${maxBytes} bytes.`, 413);
    }
    chunks.push(result.value);
  }

  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  try {
    return JSON.parse(new TextDecoder().decode(bytes));
  } catch {
    throw new AppError("INVALID_REQUEST", "Request body is not valid JSON.", 400);
  }
}

export async function readTextBounded(response: Response, maxBytes: number): Promise<string> {
  const declared = Number(response.headers.get("content-length") ?? 0);
  if (Number.isFinite(declared) && declared > maxBytes) {
    throw new AppError("SOURCE_TOO_LARGE", `Response exceeds ${maxBytes} bytes.`, 422);
  }
  if (!response.body) return "";

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let total = 0;
  let text = "";
  while (true) {
    const result = await reader.read();
    if (result.done) break;
    total += result.value.byteLength;
    if (total > maxBytes) {
      await reader.cancel("response too large");
      throw new AppError("SOURCE_TOO_LARGE", `Response exceeds ${maxBytes} bytes.`, 422);
    }
    text += decoder.decode(result.value, { stream: true });
  }
  return text + decoder.decode();
}
