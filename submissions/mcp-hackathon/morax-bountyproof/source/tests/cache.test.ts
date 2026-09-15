import { describe, expect, it } from "vitest";
import { TtlCache } from "../src/cache.js";

describe("TtlCache", () => {
  it("expires values and applies a bounded least-recently-used eviction order", () => {
    const cache = new TtlCache<number>(100, 2);
    cache.set("a", 1, 0);
    cache.set("b", 2, 0);
    expect(cache.get("a", 50)).toBe(1); // a becomes most recent
    cache.set("c", 3, 50); // b is evicted
    expect(cache.get("b", 50)).toBeNull();
    expect(cache.get("a", 99)).toBe(1);
    expect(cache.get("a", 101)).toBeNull();
    expect(cache.size).toBe(1);
  });
});
