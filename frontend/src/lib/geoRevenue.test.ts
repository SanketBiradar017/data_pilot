import { describe, expect, it } from "vitest";
import { compact, crumbs, fillFor, maxMetric, metric, net, radiusFor, type GeoRegion } from "./geoRevenue";

const r = (o: Partial<GeoRegion>): GeoRegion => ({ key: "x", name: "X", revenue: 0, loss: 0, profit: null, transactions: 1, ...o });

describe("net / metric", () => {
  it("prefers reported profit, else revenue minus loss", () => {
    expect(net(r({ revenue: 100, loss: 30, profit: 50 }))).toBe(50);
    expect(net(r({ revenue: 100, loss: 30 }))).toBe(70);
    expect(net(r({ revenue: null, loss: 30 }))).toBe(-30);
  });
  it("metric per mode", () => {
    const x = r({ revenue: 100, loss: 30 });
    expect([metric(x, "revenue"), metric(x, "loss"), metric(x, "both")]).toEqual([100, 30, 70]);
  });
});

describe("fillFor", () => {
  const regs = [r({ revenue: 1000, loss: 100 }), r({ revenue: 10, loss: 400 })];
  it("is neutral without data or magnitude", () => {
    expect(fillFor(undefined, "revenue", 10)).toBeNull();
    expect(fillFor(r({ revenue: 5 }), "revenue", 0)).toBeNull();
    expect(fillFor(r({ revenue: 5, loss: 0 }), "loss", 10)).toBeNull();
  });
  it("green for revenue/positive net, red for loss/negative net", () => {
    expect(fillFor(regs[0], "revenue", 1000)).toContain("16, 185, 129");
    expect(fillFor(regs[1], "loss", 400)).toContain("239, 68, 68");
    expect(fillFor(regs[1], "both", maxMetric(regs, "both"))).toContain("239, 68, 68");
    expect(fillFor(regs[0], "both", maxMetric(regs, "both"))).toContain("16, 185, 129");
  });
  it("bigger value is more opaque", () => {
    const a = (s: string | null) => Number(/, ([\d.]+)\)$/.exec(s ?? "")?.[1]);
    expect(a(fillFor(regs[0], "revenue", 1000))).toBeGreaterThan(a(fillFor(regs[1], "revenue", 1000)));
  });
});

describe("radiusFor / crumbs / compact", () => {
  it("radius stays within bounds", () => {
    expect(radiusFor(r({ revenue: 100 }), "revenue", 100)).toBe(18);
    expect(radiusFor(r({ revenue: 0 }), "revenue", 100)).toBe(4);
    expect(radiusFor(r({ revenue: 1 }), "revenue", 0)).toBe(4);
  });
  it("builds hierarchy breadcrumbs", () => {
    expect(crumbs({}).map((c) => c.level)).toEqual(["world"]);
    expect(crumbs({ country: { iso3: "IND", name: "India" }, state: "Goa", city: "Panaji" }).map((c) => c.label)).toEqual(["World", "India", "Goa", "Panaji"]);
    expect(crumbs({ state: "Goa" }).length).toBe(1);
  });
  it("compacts numbers", () => {
    expect(compact(1_250_000)).toBe("1.3M");
    expect(compact(-2500)).toBe("-2.5K");
    expect(compact(null)).toBe("—");
    expect(compact(42)).toBe("42");
    expect(compact(5000, "inr")).toBe("₹5K");
  });
});
