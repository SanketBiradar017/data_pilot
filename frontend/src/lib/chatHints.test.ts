import { describe, expect, it } from "vitest";
import { followUpChips, hasNotes } from "./chatHints";

describe("followUpChips", () => {
  it("offers nothing after a clarification (the question must be fixed first)", () => {
    expect(followUpChips({ clarification: { message: "x", missing: ["profit"], suggestions: {}, columns: [] }, intents: ["sql"] })).toEqual([]);
  });
  it("suggests why / forecast / trend after a data answer", () => {
    expect(followUpChips({ intents: ["sql", "visualization"] })).toContain("Forecast the next 3 months");
  });
  it("does not suggest forecasting again after a forecast", () => {
    expect(followUpChips({ intents: ["forecast"] }).some((c) => c === "Forecast the next 3 months")).toBe(false);
  });
  it("is empty when nothing is known", () => { expect(followUpChips({})).toEqual([]); });
});

describe("hasNotes", () => {
  it("is true when the question was interpreted or repaired", () => {
    expect(hasNotes({ interpretation: "Total revenue by region" })).toBe(true);
    expect(hasNotes({ notes: ["Reading “regon” as column “region”."] })).toBe(true);
    expect(hasNotes({})).toBe(false);
  });
});
