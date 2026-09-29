import { describe, expect, it } from "vitest";

import { TtlCache } from "../src/lib/cache.js";

describe("TtlCache", () => {
  it("returns a value before its TTL and removes it at expiry", () => {
    let now = 1_000;
    const cache = new TtlCache<string, string>(300_000, () => now);

    cache.set("issue", "context");
    now += 299_999;
    expect(cache.get("issue")).toBe("context");

    now += 1;
    expect(cache.get("issue")).toBeUndefined();
    expect(cache.get("issue")).toBeUndefined();
  });

  it("rejects a non-positive or non-finite TTL", () => {
    expect(() => new TtlCache(0)).toThrow(RangeError);
    expect(() => new TtlCache(Number.POSITIVE_INFINITY)).toThrow(RangeError);
  });
});
