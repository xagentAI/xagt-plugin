type CacheEntry<Value> = {
  value: Value;
  expiresAt: number;
};

/** Small process-local TTL cache with an injectable clock for deterministic tests. */
export class TtlCache<Key, Value> {
  private readonly entries = new Map<Key, CacheEntry<Value>>();

  constructor(
    private readonly ttlMs: number,
    private readonly now: () => number = Date.now,
  ) {
    if (!Number.isFinite(ttlMs) || ttlMs <= 0) {
      throw new RangeError("Cache TTL must be a positive finite number.");
    }
  }

  get(key: Key): Value | undefined {
    const entry = this.entries.get(key);

    if (entry === undefined) {
      return undefined;
    }

    if (entry.expiresAt <= this.now()) {
      this.entries.delete(key);
      return undefined;
    }

    return entry.value;
  }

  set(key: Key, value: Value): void {
    this.entries.set(key, {
      value,
      expiresAt: this.now() + this.ttlMs,
    });
  }

  delete(key: Key): boolean {
    return this.entries.delete(key);
  }
}
