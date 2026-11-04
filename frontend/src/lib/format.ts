import { formatNumber, getNumMode, groupingOf } from "./numfmt";

/** Table / stat numbers: honours the digit-grouping style (1,234,567 vs 12,34,567) but never adds a currency symbol (IDs, quantities). */
export const num = (v: unknown, digits?: number): string => formatNumber(v, groupingOf(getNumMode()), typeof digits === "number" ? digits : undefined);
export const bytes = (n: number) => (n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(1)} MB`);
/** API timestamps are UTC; SQLite returns them without an offset, so add one before parsing. */
const utc = (iso: string) => new Date(/([zZ]|[+-]\d\d:?\d\d)$/.test(iso) ? iso : `${iso}Z`);
export const ago = (iso: string) => {
  const s = Math.max(0, (Date.now() - utc(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return utc(iso).toLocaleDateString();
};
export const cellText = (v: unknown) => (v === null || v === undefined ? "∅" : typeof v === "number" ? num(v) : String(v));
export const scoreColor = (s: number | null | undefined) => (s == null ? "text-slate-400" : s >= 90 ? "text-emerald-600 dark:text-emerald-400" : s >= 75 ? "text-amber-600 dark:text-amber-400" : "text-red-600 dark:text-red-400");
