import { describe, expect, it } from "vitest";

import { formatUsdcAmount, parseUsdcAmount } from "@/domain/money";

describe("parseUsdcAmount", () => {
  it.each([
    ["0.000001", 1n],
    ["1", 1_000_000n],
    ["1.0", 1_000_000n],
    ["1.000000", 1_000_000n],
    ["850.00", 850_000_000n],
    ["999999999.999999", 999_999_999_999_999n],
    ["0.5", 500_000n],
    ["123456789012345678901234567890", 123456789012345678901234567890_000000n],
  ])("parses %s → %s units", (input, units) => {
    expect(parseUsdcAmount(input)).toEqual({ ok: true, units });
  });

  it.each([
    "0",
    "0.0",
    "0.000000",
    "-1",
    "+1",
    "1e3",
    "1E3",
    "1.0000001",
    "NaN",
    "Infinity",
    "",
    " 1",
    "1 ",
    "1.",
    ".5",
    "01",
    "1,000",
    "0x10",
    "850.00 USDC",
    "1234567890123456789012345678901",
  ])("rejects %j", (input) => {
    const result = parseUsdcAmount(input);
    expect(result.ok).toBe(false);
  });

  it("rejects non-string input without throwing", () => {
    expect(parseUsdcAmount(850).ok).toBe(false);
    expect(parseUsdcAmount(850n).ok).toBe(false);
    expect(parseUsdcAmount(null).ok).toBe(false);
    expect(parseUsdcAmount(undefined).ok).toBe(false);
  });

  it("explains zero separately from malformed input", () => {
    const zero = parseUsdcAmount("0.00");
    expect(zero.ok === false && zero.reason).toBe("must be greater than zero");
  });
});

describe("formatUsdcAmount", () => {
  it.each([
    [0n, "0.00"],
    [1n, "0.000001"],
    [1_000_000n, "1.00"],
    [850_000_000n, "850.00"],
    [1_500_000n, "1.50"],
    [1_234_567n, "1.234567"],
    [999_999_999_999_999n, "999999999.999999"],
    [350_000_000n, "350.00"],
  ])("formats %s units → %s", (units, expected) => {
    expect(formatUsdcAmount(units)).toBe(expected);
  });

  it("round-trips every parsed value", () => {
    for (const input of ["0.000001", "1", "850.00", "999999999.999999", "12.345678", "1.5"]) {
      const parsed = parseUsdcAmount(input);
      expect(parsed.ok).toBe(true);
      if (parsed.ok) {
        expect(parseUsdcAmount(formatUsdcAmount(parsed.units))).toEqual(parsed);
      }
    }
  });

  it("refuses negative units", () => {
    expect(() => formatUsdcAmount(-1n)).toThrow(RangeError);
  });
});
