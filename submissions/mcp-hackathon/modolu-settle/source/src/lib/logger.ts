/**
 * Structured logger: one JSON object per line on stdout (debug/info) or
 * stderr (warn/error). See ARCHITECTURE.md §11 "Logging" for what may and may
 * not be logged; this module enforces the format, call sites enforce the
 * content.
 *
 * This module must not import `config.ts`: configuration failures are logged
 * through it, so it resolves its own level from `LOG_LEVEL` defensively.
 */

export const LOG_LEVELS = ["debug", "info", "warn", "error", "silent"] as const;

export type LogLevel = (typeof LOG_LEVELS)[number];

export type LogFields = Readonly<Record<string, unknown>>;

export interface Logger {
  readonly level: LogLevel;
  debug(message: string, fields?: LogFields): void;
  info(message: string, fields?: LogFields): void;
  warn(message: string, fields?: LogFields): void;
  error(message: string, fields?: LogFields): void;
  /** Returns a logger that includes `bindings` on every line it emits. */
  child(bindings: LogFields): Logger;
}

export interface LoggerOptions {
  readonly level?: LogLevel;
  readonly bindings?: LogFields;
  /** Sink for finished lines; defaults to stdout/stderr. Injectable for tests. */
  readonly write?: (line: string, level: LogLevel) => void;
}

const LEVEL_PRIORITY: Readonly<Record<LogLevel, number>> = {
  debug: 10,
  info: 20,
  warn: 30,
  error: 40,
  silent: 100,
};

export function isLogLevel(value: unknown): value is LogLevel {
  return typeof value === "string" && (LOG_LEVELS as readonly string[]).includes(value);
}

/** Lenient parse used only by the default logger; `config.ts` validates strictly. */
export function parseLogLevel(value: string | undefined, fallback: LogLevel = "info"): LogLevel {
  return isLogLevel(value) ? value : fallback;
}

function writeToProcessStreams(line: string, level: LogLevel): void {
  const stream = LEVEL_PRIORITY[level] >= LEVEL_PRIORITY.warn ? process.stderr : process.stdout;
  stream.write(`${line}\n`);
}

function serializeError(error: Error): Record<string, unknown> {
  const out: Record<string, unknown> = {
    name: error.name,
    message: error.message,
  };
  if (error.stack !== undefined) {
    out["stack"] = error.stack;
  }
  if ("code" in error && typeof error.code === "string") {
    out["code"] = error.code;
  }
  if (error.cause !== undefined) {
    out["cause"] = error.cause instanceof Error ? serializeError(error.cause) : error.cause;
  }
  return out;
}

const MAX_STRING_LENGTH = 2_000;

/**
 * Redaction applied to every string that reaches a log line, whatever path it
 * took to get there (error messages, causes, stacks, ad-hoc fields):
 * credentials embedded in URLs, provider keys in URL paths, environment-style
 * secret assignments, and query parameters echoed by database driver errors.
 */
const REDACTIONS: ReadonlyArray<readonly [RegExp, string]> = [
  // scheme://user:password@host → scheme://[redacted]@host
  [/([a-z][a-z0-9+.-]*:\/\/)[^\s/@:]+:[^\s/@]+@/gi, "$1[redacted]@"],
  // https://…alchemy.com/v2/<key> and similar provider key paths
  [/(\/v2\/)[A-Za-z0-9_-]{8,}/g, "$1[redacted]"],
  // DATABASE_URL=…, ALCHEMY_BASE_RPC_URL=… (any *_URL / *_KEY / *_SECRET assignment)
  [/\b([A-Z0-9_]*(?:URL|KEY|SECRET|TOKEN|PASSWORD)[A-Z0-9_]*)=\S+/g, "$1=[redacted]"],
  // Drizzle/pg "Failed query: … params: …" — parameters carry addresses and references
  [/(params:\s*).*$/s, "$1[redacted]"],
];

export function redactSecrets(text: string): string {
  let out = text.length > MAX_STRING_LENGTH ? `${text.slice(0, MAX_STRING_LENGTH)}…[truncated]` : text;
  for (const [pattern, replacement] of REDACTIONS) {
    out = out.replace(pattern, replacement);
  }
  return out;
}

/**
 * JSON replacer: money is `bigint` throughout the codebase, Errors are opaque
 * to JSON, and every string is redacted before it leaves the process.
 */
function jsonReplacer(_key: string, value: unknown): unknown {
  if (typeof value === "bigint") {
    return value.toString();
  }
  if (value instanceof Error) {
    return serializeError(value);
  }
  if (typeof value === "string") {
    return redactSecrets(value);
  }
  return value;
}

export function createLogger(options: LoggerOptions = {}): Logger {
  const level = options.level ?? "info";
  const bindings = options.bindings ?? {};
  const write = options.write ?? writeToProcessStreams;
  const threshold = LEVEL_PRIORITY[level];

  const emit = (entryLevel: Exclude<LogLevel, "silent">, message: string, fields?: LogFields): void => {
    if (LEVEL_PRIORITY[entryLevel] < threshold) {
      return;
    }
    const entry = {
      level: entryLevel,
      time: new Date().toISOString(),
      msg: message,
      ...bindings,
      ...fields,
    };
    write(JSON.stringify(entry, jsonReplacer), entryLevel);
  };

  return {
    level,
    debug: (message, fields) => emit("debug", message, fields),
    info: (message, fields) => emit("info", message, fields),
    warn: (message, fields) => emit("warn", message, fields),
    error: (message, fields) => emit("error", message, fields),
    child: (childBindings) =>
      createLogger({ level, bindings: { ...bindings, ...childBindings }, write }),
  };
}

/** Process-wide default logger. Request-scoped loggers are derived via `child()`. */
export const logger: Logger = createLogger({ level: parseLogLevel(process.env["LOG_LEVEL"]) });
