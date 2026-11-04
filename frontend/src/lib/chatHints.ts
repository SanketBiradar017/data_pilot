import type { Message } from "./types";

type Payload = Message["payload"];

/** Suggested next questions shown under an answer. They only fill the input box; the backend resolves
 *  "it" / "that" against the previous question. */
export function followUpChips(p: Payload): string[] {
  if (p.clarification) return [];
  const steps = p.intents ?? [];
  if (steps.includes("forecast")) return ["Why did it change recently?", "What if prices rise 10%?", "Forecast the next 12 months"];
  if (steps.includes("root_cause")) return ["Forecast it for the next 3 months", "Show the monthly trend", "Give me an executive summary"];
  if (steps.includes("sql") || steps.includes("analytics")) return ["Why did it change?", "Forecast the next 3 months", "Show the monthly trend"];
  return [];
}

export function hasNotes(p: Payload): boolean {
  return Boolean(p.interpretation || p.followup_note || (p.notes && p.notes.length));
}
