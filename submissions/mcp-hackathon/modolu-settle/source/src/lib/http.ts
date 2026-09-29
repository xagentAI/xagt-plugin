/**
 * HTTP boundary helpers for Next.js route handlers (Node runtime).
 *
 * `apiRoute` gives every handler a request ID, a request-scoped logger, an
 * access log line, and uniform error mapping. Route handlers validate input,
 * call one service, and map the result to a response — nothing else
 * (ARCHITECTURE.md §6, §11).
 */
import { toAppError, toErrorEnvelope, type AppError } from "./errors";
import { newRequestId } from "./ids";
import { logger as rootLogger, type Logger } from "./logger";

export const REQUEST_ID_HEADER = "X-Request-Id";

/** Client-supplied request IDs are honoured only when they are plainly safe to log and echo. */
const SAFE_REQUEST_ID = /^[A-Za-z0-9_-]{8,64}$/;

export interface RequestContext {
  readonly request: Request;
  readonly requestId: string;
  readonly log: Logger;
}

export type RouteHandler<TArgs extends unknown[]> = (
  context: RequestContext,
  ...args: TArgs
) => Promise<Response> | Response;

export function resolveRequestId(headers: Headers): string {
  const supplied = headers.get(REQUEST_ID_HEADER);
  return supplied !== null && SAFE_REQUEST_ID.test(supplied) ? supplied : newRequestId();
}

export interface JsonResponseInit {
  readonly requestId: string;
  readonly status?: number;
}

/** JSON response with the request ID header; API responses are never cacheable. */
export function jsonResponse(body: unknown, init: JsonResponseInit): Response {
  return Response.json(body, {
    status: init.status ?? 200,
    headers: {
      [REQUEST_ID_HEADER]: init.requestId,
      "Cache-Control": "no-store",
    },
  });
}

export function errorResponse(error: AppError, requestId: string): Response {
  return jsonResponse(toErrorEnvelope(error), { requestId, status: error.httpStatus });
}

/**
 * Wraps a route handler with request context, error mapping and access
 * logging. Extra Next.js handler arguments (e.g. `{ params }`) are passed
 * through untouched.
 */
export function apiRoute<TArgs extends unknown[]>(
  route: string,
  handler: RouteHandler<TArgs>,
): (request: Request, ...args: TArgs) => Promise<Response> {
  return async (request, ...args) => {
    const startedAt = performance.now();
    const requestId = resolveRequestId(request.headers);
    const log = rootLogger.child({ requestId, route, method: request.method });

    let response: Response;
    let errorCode: string | undefined;
    try {
      response = await handler({ request, requestId, log }, ...args);
    } catch (thrown) {
      const error = toAppError(thrown);
      errorCode = error.code;
      if (error.httpStatus >= 500) {
        log.error("request failed", { err: error, errorCode: error.code, ...error.context });
      }
      response = errorResponse(error, requestId);
    }

    response.headers.set(REQUEST_ID_HEADER, requestId);
    log.info("request completed", {
      status: response.status,
      durationMs: Math.round(performance.now() - startedAt),
      ...(errorCode === undefined ? {} : { errorCode }),
    });
    return response;
  };
}
