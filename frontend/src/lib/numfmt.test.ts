import { describe, expect, it } from "vitest";
import { axisWidth, formatCount, formatNumber, formatPercent, formatSig, sanitizeSci } from "./numfmt";
import { num } from "./format";

const NASTY = [1.26e4, 6.34e3, 3.13e4, 1e15, 1e21, 123456789012345680000, 1e-7, 1.5e-10, -1.26e4, -1e-9, 4.56, 123.456, 0.5, 0];

describe("formatNumber", () => {
  it("never produces scientific notation, in any mode", () => {
    for (const mode of ["standard", "indian", "inr"] as const)
      for (const v of NASTY) {
        expect(formatNumber(v, mode)).not.toMatch(/e[+-]?\d/i);
        expect(formatSig(v, 4, mode)).not.toMatch(/e[+-]?\d/i);
        expect(formatCount(v, mode)).not.toMatch(/e[+-]?\d/i);
      }
  });
  it("turns the reported examples into plain numbers", () => {
    expect(formatNumber(1.26e4, "standard")).toBe("12,600");
    expect(formatNumber(6.34e3, "standard")).toBe("6,340");
    expect(formatNumber(3.13e4, "standard")).toBe("31,300");
    expect(formatNumber(1000000, "standard")).toBe("1,000,000");
  });
  it("adds thousands separators on axes", () => {
    expect(formatNumber(1000, "standard")).toBe("1,000");
    expect(formatNumber(10000, "standard")).toBe("10,000");
  });
  it("keeps small and decimal values readable", () => {
    expect(formatNumber(4.56, "standard")).toBe("4.56");
    expect(formatNumber(123.456, "standard")).toBe("123.46");
    expect(formatNumber(13.4, "standard")).toBe("13.4");
    expect(formatNumber(0.5, "standard")).toBe("0.5");
    expect(formatNumber(0.0123, "standard")).toBe("0.0123");
    expect(formatNumber(1e-7, "standard")).toBe("0.0000001");
  });
  it("supports Indian grouping and the rupee format", () => {
    expect(formatNumber(1234567, "indian")).toBe("12,34,567");
    expect(formatNumber(12600, "indian")).toBe("12,600");
    expect(formatNumber(100000, "indian")).toBe("1,00,000");
    expect(formatNumber(1234567, "inr")).toBe("₹12,34,567");
    expect(formatNumber(1.26e4, "inr")).toBe("₹12,600");
  });
  it("puts the minus sign before the currency symbol and never prints -0", () => {
    expect(formatNumber(-1234.5, "standard")).toBe("-1,235");
    expect(formatNumber(-1234, "inr")).toBe("-₹1,234");
    expect(formatNumber(-0.004, "standard", 2)).toBe("0");
    expect(formatNumber(-2.5, "standard")).toBe("-2.5");
  });
  it("handles missing and non-finite values", () => {
    for (const v of [null, undefined, "", NaN, Infinity, -Infinity]) expect(formatNumber(v as any)).toBe("—");
    expect(formatNumber("text" as any)).toBe("text");
  });
  it("handles very large numbers without losing digits", () => {
    expect(formatNumber(1e15, "standard")).toBe("1,000,000,000,000,000");
    expect(formatNumber(1e12, "indian")).toBe("10,00,00,00,00,000");
  });
  it("does not round before calculating: formatting leaves the input untouched", () => {
    const v = 123.456789;
    formatNumber(v);
    expect(v).toBe(123.456789);
  });
  it("fixed digits pad, capped digits trim", () => {
    expect(formatNumber(13, "standard", 2, true)).toBe("13.00");
    expect(formatNumber(13.456, "standard", 1)).toBe("13.5");
  });
});

describe("counts, percentages, significant digits", () => {
  it("counts follow the grouping style but never get a currency symbol", () => {
    expect(formatCount(1234567, "inr")).toBe("12,34,567");
    expect(formatCount(15, "standard")).toBe("15");
    expect(formatCount(14.6, "standard")).toBe("15");
  });
  it("percentages", () => {
    expect(formatPercent(18.75, 2, true)).toBe("18.75%");
    expect(formatPercent(20, 2)).toBe("20%");
    expect(formatPercent(null)).toBe("—");
  });
  it("significant digits for statistics", () => {
    expect(formatSig(0.000123456, 4)).toBe("0.0001235");
    expect(formatSig(12345.6, 4)).toBe("12,346");
    expect(formatSig(-3.14159, 3)).toBe("-3.14");
  });
});

describe("sanitizeSci / axisWidth / table alias", () => {
  it("rewrites legacy scientific labels", () => {
    expect(sanitizeSci("1.26e+04–3.13e+04")).toBe("12,600–31,300");
    expect(sanitizeSci("plain 12 text")).toBe("plain 12 text");
  });
  it("sizes the axis from the longest label", () => {
    const f = (v: number) => formatNumber(v, "standard");
    expect(axisWidth([0, 1000000], f)).toBeGreaterThan(axisWidth([0, 10], f));
    expect(axisWidth([0, 1e30], f)).toBeLessThanOrEqual(120);
  });
  it("table numbers never get a currency symbol", () => {
    expect(num(287)).toBe("287");
    expect(num(null)).toBe("—");
  });
});
