import { formatCount, formatNumber, formatPercent } from "../lib/numfmt";
import type { Bin } from "../lib/histogram";

const box = "rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs shadow-pop dark:border-white/10 dark:bg-ink-900 dark:text-slate-100";

/** Value text by series meaning: percentages and counts are never shown with a currency symbol. */
export function seriesValue(key: string, v: unknown): string {
  if (typeof v !== "number") return v == null ? "—" : String(v);
  if (/pct|percent|share/i.test(key)) return formatPercent(v, 1);
  if (/^(count|records|n)$/i.test(key)) return formatCount(v);
  return formatNumber(v);
}

/** Tooltip for histogram bars: value range, number of records, and share of all records. */
export function HistogramTooltip({ active, payload }: { active?: boolean; payload?: { payload: Bin }[] }) {
  if (!active || !payload?.length) return null;
  const b = payload[0].payload;
  return (
    <div className={box}>
      <p className="mb-1 font-semibold">Range: {b.range}</p>
      <p>Records: <b className="tabular-nums">{formatCount(b.count)}</b></p>
      <p>Percentage: <b className="tabular-nums">{formatPercent(b.pct, 2, true)}</b></p>
    </div>
  );
}

interface Item { name?: string | number; value?: unknown; dataKey?: string | number; color?: string; payload?: any }

/** One tooltip for bar / line / scatter / pareto / pie charts, honouring the selected number format. */
export function ChartTooltip({ active, payload, label, xKey, pieTotal }: { active?: boolean; payload?: Item[]; label?: unknown; xKey?: string; pieTotal?: number }) {
  if (!active || !payload?.length) return null;
  const first = payload[0];
  if (pieTotal !== undefined) {
    const v = first.value as number;
    return <div className={box}><p className="font-semibold">{String(first.name)}</p><p>{formatNumber(v)} <span className="text-slate-500">({formatPercent(pieTotal ? (v / pieTotal) * 100 : 0, 1)})</span></p></div>;
  }
  const row = first.payload ?? {};
  const head = xKey && row[xKey] !== undefined && typeof row[xKey] !== "object" ? (typeof row[xKey] === "number" ? formatNumber(row[xKey]) : String(row[xKey])) : label !== undefined && label !== "" ? String(label) : null;
  return (
    <div className={box}>
      {head !== null && <p className="mb-1 font-semibold">{head}</p>}
      {payload.map((p, i) => <p key={i} className="flex items-center gap-2">{p.color && <span className="h-2 w-2 rounded-full" style={{ background: p.color }} />}<span className="text-slate-500">{String(p.name ?? p.dataKey)}:</span><b className="tabular-nums">{seriesValue(String(p.dataKey ?? p.name), p.value)}</b></p>)}
    </div>
  );
}
