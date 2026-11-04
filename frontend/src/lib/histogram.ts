import { formatNumber, groupingOf, sanitizeSci, type NumMode } from "./numfmt";

export interface BinRow { start?: number; end?: number; count: number; pct?: number; bin?: string }
export interface Bin { label: string; range: string; count: number; pct: number }

/**
 * One decimal precision for all labels of a chart: the fewest decimals (0-4) whose rounding error stays under 1% of the bin
 * width and keeps consecutive edges distinct (0.5, 1.25 -> 2; 10.6, 35.761 -> 1; 6340, 12600 -> 0).
 */
export function pickDigits(edges: number[]): number {
  const width = Math.min(...edges.slice(1).map((e, i) => e - edges[i]).filter((w) => w > 0), Infinity);
  const distinct = (r: number[]) => r.every((x, i) => i === 0 || x > r[i - 1]);
  for (let d = 0; d <= 4; d++) {
    const r = edges.map((e) => Number(e.toFixed(d)));
    if (distinct(r) && (!Number.isFinite(width) || edges.every((e, i) => Math.abs(e - r[i]) <= 0.01 * width + 1e-12))) return d;
  }
  for (let d = 0; d <= 4; d++) if (distinct(edges.map((e) => Number(e.toFixed(d))))) return d;
  return 4;
}

const EPS = 1e-9;

/**
 * Readable bin range. Bins are [start, end) and the last one is closed, exactly as numpy builds them.
 * Integer data: the integers inside the bin ("1–13", "14–25"); otherwise the real edges with one shared precision.
 * `symbol`: "first" -> "₹1–13" (compact axis), "both" -> "₹6,340–₹12,600" (tooltip), in the currency format.
 * Mirrors `range_label` in backend/app/analytics/utils.py so PDF / Excel output matches the web charts.
 */
export function binRange(start: number, end: number, o: { integer: boolean; last: boolean; digits: number; mode: NumMode; symbol: "first" | "both" }): string {
  const f = (x: number, withSymbol: boolean, digits: number) => formatNumber(x, withSymbol ? o.mode : groupingOf(o.mode), digits, true);
  if (o.integer) {
    const lo = Math.ceil(start - EPS);
    const hi = o.last ? Math.floor(end + EPS) : Math.ceil(end - EPS) - 1;
    if (hi >= lo) return lo === hi ? f(lo, true, 0) : `${f(lo, true, 0)}–${f(hi, o.symbol === "both", 0)}`;
  }
  return `${f(start, true, o.digits)}–${f(end, o.symbol === "both", o.digits)}`;
}

/** Legacy results stored only left edges ("1.26e+04"); rebuild ranges when the labels are a clean sequence of numbers. */
function inferLegacy(rows: BinRow[], title?: string): BinRow[] | null {
  if (!title?.startsWith("Distribution of") || rows.length < 2) return null;
  const starts = rows.map((r) => Number(r.bin));
  if (starts.some((x) => !Number.isFinite(x)) || starts.some((x, i) => i > 0 && x <= starts[i - 1])) return null;
  const step = starts[starts.length - 1] - starts[starts.length - 2];
  return rows.map((r, i) => ({ ...r, start: starts[i], end: i < rows.length - 1 ? starts[i + 1] : starts[i] + step }));
}

/** Presentation bins for a histogram spec. Counts are untouched; labels and percentages are derived. */
export function histogramBins(rows: BinRow[], o: { integer?: boolean; mode: NumMode; title?: string; total?: number }): Bin[] {
  if (!rows.length) return [];
  const total = o.total ?? rows.reduce((n, r) => n + (r.count || 0), 0);
  const withEdges = rows.every((r) => Number.isFinite(r.start) && Number.isFinite(r.end)) ? rows : inferLegacy(rows, o.title);
  if (!withEdges) {   // no edges available: keep the stored label but never show scientific notation
    return rows.map((r) => { const l = sanitizeSci(String(r.bin ?? ""), o.mode); return { label: l, range: l, count: r.count, pct: total ? (r.count / total) * 100 : 0 }; });
  }
  const digits = pickDigits([...withEdges.map((r) => r.start as number), withEdges[withEdges.length - 1].end as number]);
  const integer = !!o.integer;
  return withEdges.map((r, i) => {
    const last = i === withEdges.length - 1;
    const base = { integer, last, digits, mode: o.mode };
    return {
      label: binRange(r.start as number, r.end as number, { ...base, symbol: "first" }),
      range: binRange(r.start as number, r.end as number, { ...base, symbol: "both" }),
      count: r.count,
      pct: total ? (r.count / total) * 100 : 0,
    };
  });
}
