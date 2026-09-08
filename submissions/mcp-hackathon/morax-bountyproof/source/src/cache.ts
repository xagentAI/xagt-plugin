interface CacheEntry<T> {
  expiresAt: number;
  value: T;
}

export class TtlCache<T> {
  readonly #entries = new Map<string, CacheEntry<T>>();

  constructor(
    readonly ttlMs = 5 * 60 * 1_000,
    readonly maxEntries = 128,
  ) {}

  get(key: string, now = Date.now()): T | null {
    const entry = this.#entries.get(key);
    if (!entry) return null;
    if (entry.expiresAt <= now) {
      this.#entries.delete(key);
      return null;
    }
    this.#entries.delete(key);
    this.#entries.set(key, entry);
    return entry.value;
  }

  set(key: string, value: T, now = Date.now()): void {
    this.#entries.delete(key);
    while (this.#entries.size >= this.maxEntries) {
      const oldest = this.#entries.keys().next().value as string | undefined;
      if (!oldest) break;
      this.#entries.delete(oldest);
    }
    this.#entries.set(key, { expiresAt: now + this.ttlMs, value });
  }

  get size(): number {
    return this.#entries.size;
  }
}
