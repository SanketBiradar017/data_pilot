import { createContext, useContext, useState, type ReactNode } from "react";

export type NumMode = "standard" | "indian" | "inr";
const KEY = "datapilot.numfmt";
const Ctx = createContext<{ mode: NumMode; setMode: (m: NumMode) => void; fmt: (v: unknown, digits?: number) => string }>(null!);
export const useNumFmt = () => useContext(Ctx);

/** Module-level copy of the selected format so non-React callers (table cells, tick formatters) honour it too. */
let currentMode: NumMode = "standard";
export const getNumMode = () => currentMode;

const cache = new Map<string, Intl.NumberFormat>();
function nf(locale: string, o: Intl.NumberFormatOptions): Intl.NumberFormat {
  const k = locale + JSON.stringify(o);
  let f = cache.get(k);
  if (!f) { f = new Intl.NumberFormat(locale, { ...o, useGrouping: true, notation: "standard" }); cache.set(k, f); }
  return f;
}
const localeOf = (m: NumMode) => (m === "standard" ? "en-US" : "en-IN");
/** Digit grouping for the mode WITHOUT a currency symbol (counts, percentages, coefficients are not money). */
export const groupingOf = (m: NumMode): NumMode => (m === "inr" ? "indian" : m);
const sign = (neg: boolean, out: string) => (neg && !/^[0.,]*$/.test(out) ? "-" : "");

/**
 * The one number formatter. Never scientific notation, handles null / NaN / ±Infinity / negatives / huge and tiny values.
 * Presentation only: callers always pass the unrounded value. `digits` caps decimals (`fixed` also pads them).
 */
export function formatNumber(v: unknown, mode: NumMode = currentMode, digits?: number, fixed = false): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v !== "number") return String(v);
  if (!Number.isFinite(v)) return "—";
  const abs = Math.abs(v);
  let o: Intl.NumberFormatOptions;
  if (digits !== undefined) o = { minimumFractionDigits: fixed ? digits : 0, maximumFractionDigits: digits };
  else if (Number.isInteger(v) || abs >= 1000) o = { maximumFractionDigits: 0 };
  else if (abs >= 1) o = { maximumFractionDigits: 2 };
  else o = { maximumSignificantDigits: 3 };           // 0.0123 stays 0.0123, 0.000000123 stays 0.000000123
  const out = nf(localeOf(mode), o).format(abs);
  return `${sign(v < 0, out)}${mode === "inr" ? "₹" : ""}${out}`;
}

/** Whole-number counts: grouped per the selected style, never with a currency symbol. */
export const formatCount = (v: unknown, mode: NumMode = currentMode) => formatNumber(typeof v === "number" ? Math.round(v) : v, groupingOf(mode), 0);

export function formatPercent(v: unknown, digits = 1, fixed = false): string {
  if (typeof v !== "number" || !Number.isFinite(v)) return "—";
  const out = nf("en-US", { minimumFractionDigits: fixed ? digits : 0, maximumFractionDigits: digits }).format(Math.abs(v));
  return `${sign(v < 0, out)}${out}%`;
}

/** Significant-digit formatting for statistics (coefficients, effects). Values >= 1000 keep every integer digit. */
export function formatSig(v: unknown, sig = 4, mode: NumMode = currentMode): string {
  if (typeof v !== "number") return formatNumber(v, mode);
  if (!Number.isFinite(v)) return "—";
  if (Math.abs(v) >= 1000) return formatNumber(v, groupingOf(mode), 0);
  const out = nf(localeOf(mode), { maximumSignificantDigits: sig }).format(Math.abs(v));
  return `${sign(v < 0, out)}${out}`;
}

/** Rewrites any scientific-notation token inside a string (e.g. legacy chart labels such as "1.26e+04"). */
export function sanitizeSci(text: string, mode: NumMode = currentMode): string {
  return text.replace(/[-+]?\d+(?:\.\d+)?e[-+]?\d+/gi, (m) => formatNumber(Number(m), groupingOf(mode)));
}

/** Y-axis width (px) that fits the longest formatted value, so large numbers are never clipped. */
export function axisWidth(values: number[], format: (v: number) => string, min = 44, max = 120): number {
  const longest = values.reduce((n, v) => Math.max(n, format(v).length), 0);
  return Math.min(max, Math.max(min, longest * 7 + 14));
}

export function NumFmtProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<NumMode>(() => { try { return (localStorage.getItem(KEY) as NumMode) || "standard"; } catch { return "standard"; } });
  currentMode = mode;   // set during render so every descendant (including plain functions) sees the new mode immediately
  const setMode = (m: NumMode) => { setModeState(m); try { localStorage.setItem(KEY, m); } catch { /* ignore */ } };
  return <Ctx.Provider value={{ mode, setMode, fmt: (v, d) => formatNumber(v, mode, d) }}>{children}</Ctx.Provider>;
}

export function downloadCsv(name: string, columns: string[], rows: Record<string, any>[]) {
  const esc = (v: unknown) => { const s = v == null ? "" : String(v); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  const csv = [columns.join(","), ...rows.map((r) => columns.map((c) => esc(r[c])).join(","))].join("\n");
  const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(new Blob([csv], { type: "text/csv" })), download: name });
  a.click(); URL.revokeObjectURL(a.href);
}
