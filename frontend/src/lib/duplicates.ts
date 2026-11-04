import type { DupGroup } from "./types";
import { formatPercent } from "./numfmt";

/** How a cell value is shown: real missing (∅) and blank text are different things and must look different. */
export function displayValue(v: unknown): string {
  if (v === null || v === undefined) return "∅ missing";
  if (typeof v === "string" && v.trim() === "") return v === "" ? "(blank)" : "(spaces)";
  return String(v);
}

/** Short one-line label of a duplicate record (mirrors `_label` on the server). */
export function recordLabel(values: Record<string, unknown>, maxCols = 3, width = 22): string {
  const entries = Object.entries(values);
  const parts = entries.slice(0, maxCols).map(([, v]) => {
    const t = v === null || v === undefined ? "∅" : v === "" ? "(blank)" : String(v);
    return t.length <= width ? t : t.slice(0, width - 1) + "…";
  });
  return parts.join(" · ") + (entries.length > maxCols ? " …" : "");
}

/** Percentage text that never rounds a real duplicate rate down to "0%". */
export function pctText(p: number | null | undefined): string {
  if (p === null || p === undefined || !Number.isFinite(p)) return "—";
  if (p === 0) return "0%";
  return p < 0.01 ? "<0.01%" : formatPercent(p, 2);
}

/** Colour tone for the duplicate rate. */
export function rateTone(p: number): "green" | "slate" | "amber" | "red" {
  return p === 0 ? "green" : p < 1 ? "slate" : p < 5 ? "amber" : "red";
}

export type SortKey = "count" | "first_row";

export function filterGroups(groups: DupGroup[], query: string): DupGroup[] {
  const q = query.trim().toLowerCase();
  if (!q) return groups;
  return groups.filter((g) => String(g.first_row) === q || g.row_numbers.some((r) => String(r) === q) ||
    Object.values(g.values).some((v) => displayValue(v).toLowerCase().includes(q)));
}

export function sortGroups(groups: DupGroup[], key: SortKey, dir: "asc" | "desc"): DupGroup[] {
  const sign = dir === "asc" ? 1 : -1;
  return [...groups].sort((a, b) => sign * (key === "count" ? a.count - b.count : a.first_row - b.first_row) || a.first_row - b.first_row);
}

export function paginate<T>(items: T[], page: number, size: number): { items: T[]; pages: number; page: number } {
  const pages = Math.max(1, Math.ceil(items.length / size));
  const p = Math.min(Math.max(0, page), pages - 1);
  return { items: items.slice(p * size, p * size + size), pages, page: p };
}

/** Ranges like "3, 7, 8 …" for display of which rows a record appears on. */
export function rowList(numbers: number[], total: number, max = 6): string {
  const shown = numbers.slice(0, max).join(", ");
  return total > max ? `${shown} … (+${total - max})` : shown;
}
