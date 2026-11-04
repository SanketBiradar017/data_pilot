import { describe, expect, it } from "vitest";
import { binRange, histogramBins, pickDigits } from "./histogram";

const edges = (xs: number[], counts: number[]) => counts.map((count, i) => ({ start: xs[i], end: xs[i + 1], count }));
const labels = (bins: { label: string }[]) => bins.map((b) => b.label);

describe("integer data", () => {
  it("turns the reported bin boundaries into readable, non-overlapping ranges", () => {
    // 1, 13.4, 25.8, 38.1, 50.5, 62.9  ->  1–13, 14–25, 26–38, 39–50, 51–62
    const rows = edges([1, 13.4, 25.8, 38.1, 50.5, 62.9], [10, 12, 20, 22, 16]);
    expect(labels(histogramBins(rows, { integer: true, mode: "standard" }))).toEqual(["1–13", "14–25", "26–38", "39–50", "51–62"]);
  });
  it("consecutive ranges never overlap and never leave a gap", () => {
    const xs = [0, 7.3, 14.6, 21.9, 29.2, 36.5, 43.8];
    const bins = histogramBins(edges(xs, [1, 2, 3, 4, 5, 6]), { integer: true, mode: "standard" });
    const parse = (l: string) => l.split("–").map((x) => Number(x.replace(/,/g, "")));
    for (let i = 1; i < bins.length; i++) expect(parse(bins[i].label)[0]).toBe(parse(bins[i - 1].label).slice(-1)[0] + 1);
  });
  it("every integer value falls into exactly the bin whose range label contains it", () => {
    const xs = [1, 13.4, 25.8, 38.1, 50.5, 62.9];
    const bins = histogramBins(edges(xs, [1, 1, 1, 1, 1]), { integer: true, mode: "standard" });
    const parse = (l: string) => { const [a, b] = l.split("–").map((x) => Number(x.replace(/,/g, ""))); return [a, b ?? a]; };
    for (let v = 1; v <= 62; v++) {
      const k = xs.findIndex((e, i) => i < xs.length - 1 && v >= e && (v < xs[i + 1] || (i === xs.length - 2 && v <= xs[i + 1])));
      const hits = bins.map((b, i) => (v >= parse(b.label)[0] && v <= parse(b.label)[1] ? i : -1)).filter((i) => i >= 0);
      expect(hits).toEqual([k]);
    }
  });
  it("a bin narrower than one integer falls back to its real edges", () => {
    expect(binRange(1.2, 1.5, { integer: true, last: false, digits: 1, mode: "standard", symbol: "both" })).toBe("1.2–1.5");
  });
  it("single-integer bins show one number", () => {
    expect(binRange(3, 4, { integer: true, last: false, digits: 0, mode: "standard", symbol: "first" })).toBe("3");
  });
});

describe("decimal / money data", () => {
  it("shows the real edges for large numbers", () => {
    const bins = histogramBins(edges([6340, 12600, 18900, 25200], [15, 30, 35]), { integer: false, mode: "standard" });
    expect(labels(bins)).toEqual(["6,340–12,600", "12,600–18,900", "18,900–25,200"]);
    expect(bins[0].range).toBe("6,340–12,600");
  });
  it("uses one shared precision, exact where possible", () => {
    expect(pickDigits([0.5, 1.25, 2, 2.75])).toBe(2);
    expect(pickDigits([1, 13.4, 25.8])).toBe(1);
    expect(pickDigits([0, 10, 20])).toBe(0);
    const bins = histogramBins(edges([0.5, 1.25, 2], [3, 4]), { integer: false, mode: "standard" });
    expect(labels(bins)).toEqual(["0.50–1.25", "1.25–2.00"]);
  });
  it("round-off edges from numpy use only as many decimals as the bin width warrants", () => {
    expect(pickDigits([10.6, 35.761, 60.922, 86.083])).toBe(1);               // not 10.600–35.761
    const bins = histogramBins(edges([10.6, 35.761, 60.922], [5, 7]), { integer: false, mode: "standard" });
    expect(labels(bins)).toEqual(["10.6–35.8", "35.8–60.9"]);
    expect(pickDigits([0.00011, 0.00022, 0.00033])).toBe(4);
  });
  it("tiny and huge edges stay plain", () => {
    const bins = histogramBins(edges([0.0001, 0.0002, 0.0003], [1, 1]), { integer: false, mode: "standard" });
    expect(labels(bins).join()).not.toMatch(/e[+-]?\d/);
    const big = histogramBins(edges([1e12, 2e12, 3e12], [1, 1]), { integer: false, mode: "indian" });
    expect(big[0].label).toBe("10,00,00,00,00,000–20,00,00,00,00,000");
  });
  it("handles negative edges", () => {
    const bins = histogramBins(edges([-1500, -500, 500], [4, 6]), { integer: false, mode: "standard" });
    expect(labels(bins)).toEqual(["-1,500–-500", "-500–500"]);
  });
});

describe("tooltip data and number formats", () => {
  it("gives range, records and percentage of all records (15 of 80 = 18.75%)", () => {
    const bins = histogramBins(edges([6340, 12600, 18900, 25200], [15, 30, 35]), { integer: false, mode: "standard" });
    expect(bins[0].count).toBe(15);
    expect(bins[0].pct).toBeCloseTo(18.75, 10);
    expect(bins.reduce((n, b) => n + b.pct, 0)).toBeCloseTo(100, 10);
  });
  it("respects the currency format: compact axis label, full tooltip range", () => {
    const bins = histogramBins(edges([6340, 12600, 18900], [15, 65]), { integer: false, mode: "inr" });
    expect(bins[0].label).toBe("₹6,340–12,600");
    expect(bins[0].range).toBe("₹6,340–₹12,600");
  });
  it("respects Indian grouping", () => {
    const bins = histogramBins(edges([100000, 250000, 400000], [5, 5]), { integer: false, mode: "indian" });
    expect(bins[0].label).toBe("1,00,000–2,50,000");
  });
  it("percentages are 0 when there are no records, never NaN", () => {
    const bins = histogramBins(edges([0, 1, 2], [0, 0]), { integer: false, mode: "standard" });
    expect(bins.map((b) => b.pct)).toEqual([0, 0]);
  });
  it("empty input", () => expect(histogramBins([], { mode: "standard" })).toEqual([]));
});

describe("legacy stored charts", () => {
  it("rebuilds ranges from old left-edge labels and removes scientific notation", () => {
    const rows = [{ bin: "6.34e+03", count: 15 }, { bin: "1.26e+04", count: 30 }, { bin: "1.89e+04", count: 35 }];
    const bins = histogramBins(rows, { mode: "standard", title: "Distribution of revenue" });
    expect(labels(bins).join()).not.toMatch(/e[+-]?\d/);
    expect(bins[0].label).toBe("6,340–12,600");
    expect(bins[2].label).toBe("18,900–25,200");
  });
  it("labels that cannot be turned into ranges are at least made readable", () => {
    const bins = histogramBins([{ bin: "1.26e+04", count: 1 }, { bin: "3.13e+04", count: 2 }], { mode: "standard", title: "Residual distribution" });
    expect(labels(bins)).toEqual(["12,600", "31,300"]);
  });
});
