import { describe, expect, it } from "vitest";
import { displayValue, filterGroups, paginate, pctText, rateTone, recordLabel, rowList, sortGroups } from "./duplicates";
import type { DupGroup } from "./types";

const g = (id: number, count: number, first: number, values: Record<string, any>, rows = [first]): DupGroup => ({ id, count, extra: count - 1, first_row: first, row_numbers: rows, values, share_of_duplicates_pct: 0 });
const groups = [g(1, 3, 20, { name: "Bob", city: "Delhi" }, [20, 25, 30]), g(2, 2, 5, { name: "Ann", city: null }), g(3, 2, 9, { name: "", city: "Pune" }), g(4, 5, 1, { name: "Cy", city: "  " })];

describe("displayValue", () => {
  it("keeps missing, blank and spaces visibly different", () => {
    expect(displayValue(null)).toBe("∅ missing");
    expect(displayValue(undefined)).toBe("∅ missing");
    expect(displayValue("")).toBe("(blank)");
    expect(displayValue("   ")).toBe("(spaces)");
    expect(displayValue(0)).toBe("0");
    expect(displayValue(false)).toBe("false");
    expect(displayValue("Ann")).toBe("Ann");
  });
});

describe("recordLabel", () => {
  it("joins the first columns, marks blanks and truncates", () => {
    expect(recordLabel({ a: "Ann", b: null, c: "" })).toBe("Ann · ∅ · (blank)");
    expect(recordLabel({ a: "x", b: "y", c: "z", d: "w" })).toBe("x · y · z …");
    expect(recordLabel({ a: "a-very-long-value-that-keeps-going" }, 3, 10)).toBe("a-very-lo…");
  });
});

describe("pctText / rateTone", () => {
  it("never shows a real rate as 0%", () => {
    expect(pctText(0)).toBe("0%");
    expect(pctText(0.004)).toBe("<0.01%");
    expect(pctText(18.75)).toBe("18.75%");
    expect(pctText(50)).toBe("50%");
    expect(pctText(null)).toBe("—");
    expect(pctText(NaN)).toBe("—");
  });
  it("tones", () => {
    expect([0, 0.5, 3, 12].map(rateTone)).toEqual(["green", "slate", "amber", "red"]);
  });
});

describe("filter / sort / paginate", () => {
  it("searches values (incl. blank markers) and row numbers", () => {
    expect(filterGroups(groups, "bob").map((x) => x.id)).toEqual([1]);
    expect(filterGroups(groups, "missing").map((x) => x.id)).toEqual([2]);
    expect(filterGroups(groups, "(blank)").map((x) => x.id)).toEqual([3]);
    expect(filterGroups(groups, "25").map((x) => x.id)).toEqual([1]);
    expect(filterGroups(groups, "  ")).toBe(groups);
    expect(filterGroups(groups, "zzz")).toEqual([]);
  });
  it("sorts by occurrences or first row, ties broken by first row, without mutating", () => {
    const copy = [...groups];
    expect(sortGroups(groups, "count", "desc").map((x) => x.id)).toEqual([4, 1, 2, 3]);
    expect(sortGroups(groups, "count", "asc").map((x) => x.id)).toEqual([2, 3, 1, 4]);
    expect(sortGroups(groups, "first_row", "asc").map((x) => x.id)).toEqual([4, 2, 3, 1]);
    expect(groups).toEqual(copy);
  });
  it("paginates and clamps the page", () => {
    const items = Array.from({ length: 23 }, (_, i) => i);
    expect(paginate(items, 0, 10)).toMatchObject({ pages: 3, page: 0, items: items.slice(0, 10) });
    expect(paginate(items, 2, 10).items).toEqual([20, 21, 22]);
    expect(paginate(items, 99, 10).page).toBe(2);
    expect(paginate(items, -5, 10).page).toBe(0);
    expect(paginate([], 0, 10)).toEqual({ items: [], pages: 1, page: 0 });
  });
});

describe("rowList", () => {
  it("shows the first rows and how many more", () => {
    expect(rowList([2, 6, 7], 3)).toBe("2, 6, 7");
    expect(rowList([1, 2, 3, 4, 5, 6, 7, 8], 40)).toBe("1, 2, 3, 4, 5, 6 … (+34)");
  });
});
