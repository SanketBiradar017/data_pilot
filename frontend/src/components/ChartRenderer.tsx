import { Download } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, ComposedChart, Legend, Line, LineChart, Pie, PieChart, ReferenceLine, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis } from "recharts";
import { histogramBins } from "../lib/histogram";
import { axisWidth, formatCount, formatNumber, useNumFmt } from "../lib/numfmt";
import type { ChartSpec } from "../lib/types";
import { ChartTooltip, HistogramTooltip } from "./ChartTooltip";

const DARK_PALETTE = ["#6366f1", "#0ea5e9", "#10b981", "#f59e0b", "#ec4899", "#8b5cf6", "#14b8a6", "#f97316", "#64748b", "#84cc16", "#06b6d4", "#e11d48"];
const WOOD_PALETTE = ["#92623a", "#3f8f8a", "#d09a45", "#6b8e4e", "#b5524a", "#7a6aa8", "#4a7a9b", "#c47a3a", "#8a7a68", "#9aa84a", "#5aa0a8", "#a8453f"];
const isDarkNow = () => document.documentElement.classList.contains("dark");
const axis = { fontSize: 11, fill: "#94a3b8" };
/** Every numeric value found under the given keys (used to size the Y axis so big numbers are never clipped). */
const extent = (rows: Record<string, any>[], keys: string[]): number[] => {
  const out: number[] = [0];
  for (const r of rows) for (const k of keys) if (typeof r[k] === "number" && Number.isFinite(r[k])) out.push(r[k]);
  return [Math.min(...out), Math.max(...out)];
};

function Heatmap({ spec }: { spec: ChartSpec }) {
  const cols = spec.columns ?? [];
  const val = (x: string, y: string) => spec.data.find((d) => d.x === x && d.y === y)?.value ?? 0;
  const color = (v: number) => (v >= 0 ? `rgb(var(--brand-600) / ${Math.abs(v)})` : `rgba(181,82,74,${Math.abs(v)})`);
  return (
    <div className="overflow-auto">
      <div className="inline-grid gap-px text-[10px]" style={{ gridTemplateColumns: `90px repeat(${cols.length}, minmax(44px, 1fr))` }}>
        <div />
        {cols.map((c) => <div key={c} className="truncate px-1 pb-1 text-center text-slate-500" title={c}>{c}</div>)}
        {cols.map((r) => (
          <div key={r} className="contents">
            <div className="truncate pr-2 text-right leading-8 text-slate-500" title={r}>{r}</div>
            {cols.map((c) => { const v = val(r, c); return <div key={c} title={`${r} × ${c}: ${formatNumber(v, "standard", 2, true)}`} className="flex h-8 items-center justify-center rounded-sm font-medium" style={{ background: color(v), color: Math.abs(v) > 0.5 ? "#fff" : "#64748b" }}>{formatNumber(v, "standard", 2, true)}</div>; })}
          </div>
        ))}
      </div>
    </div>
  );
}

export function ChartRenderer({ spec, height = 260 }: { spec: ChartSpec; height?: number }) {
  const [, force] = useState(0);
  useEffect(() => { const f = () => force((n) => n + 1); window.addEventListener("datapilot:theme", f); return () => window.removeEventListener("datapilot:theme", f); }, []);
  const { mode } = useNumFmt();                 // re-render when the number format changes
  const PALETTE = isDarkNow() ? DARK_PALETTE : WOOD_PALETTE;
  const [hidden, setHidden] = useState<string[]>([]);
  const ref = useRef<HTMLDivElement>(null);
  const ys = spec.y.filter((y) => spec.data.some((d) => d[y] != null));
  const money = (v: unknown) => formatNumber(v, mode);
  const yWidth = (keys: string[]) => axisWidth(extent(spec.data, keys), money);
  const bins = useMemo(() => (spec.type === "histogram" ? histogramBins(spec.data as any, { integer: spec.integer, mode, title: spec.title, total: spec.total }) : []), [spec, mode]);

  const exportCsv = () => {
    const keys = Object.keys(spec.data[0] ?? {});
    const csv = [keys.join(","), ...spec.data.map((r) => keys.map((k) => JSON.stringify(r[k] ?? "")).join(","))].join("\n");
    const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(new Blob([csv], { type: "text/csv" })), download: `${spec.title.replace(/\W+/g, "_")}.csv` });
    a.click(); URL.revokeObjectURL(a.href);
  };

  const legend = ys.length > 1 && (
    <Legend onClick={(e) => setHidden((h) => (h.includes(String(e.dataKey)) ? h.filter((k) => k !== e.dataKey) : [...h, String(e.dataKey)]))} wrapperStyle={{ fontSize: 12, cursor: "pointer" }} />
  );

  let body;
  if (spec.type === "heatmap") body = <Heatmap spec={spec} />;
  else {
    const common = { margin: { top: 8, right: 12, left: 0, bottom: 0 } };
    body = (
      <ResponsiveContainer width="100%" height={height}>
        {spec.type === "pie" ? (
          <PieChart>
            <Pie isAnimationActive animationDuration={700} animationEasing="ease-out" data={spec.data} dataKey={ys[0]} nameKey={spec.x} innerRadius="55%" outerRadius="85%" paddingAngle={2}>
              {spec.data.map((_, i) => <Cell key={i} fill={spec.colors?.[i] ?? PALETTE[i % PALETTE.length]} />)}
            </Pie>
            <Tooltip content={<ChartTooltip pieTotal={spec.data.reduce((n, d) => n + (Number(d[ys[0]]) || 0), 0)} />} /><Legend wrapperStyle={{ fontSize: 12 }} />
          </PieChart>
        ) : spec.type === "pareto" ? (
          <ComposedChart data={spec.data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f033" vertical={false} />
            <XAxis dataKey={spec.x} tick={axis} interval={0} angle={-30} textAnchor="end" height={64} />
            <YAxis yAxisId="l" tick={axis} tickFormatter={(v) => money(v)} width={yWidth(["value"])} />
            <YAxis yAxisId="r" orientation="right" domain={[0, 100]} tick={axis} tickFormatter={(v) => `${formatCount(v, "standard")}%`} width={48} />
            <Tooltip content={<ChartTooltip xKey={spec.x} />} /><Legend wrapperStyle={{ fontSize: 12 }} />
            <ReferenceLine yAxisId="r" y={80} stroke="#ef4444" strokeDasharray="4 4" label={{ value: "80%", fill: "#ef4444", fontSize: 11, position: "right" }} />
            <Bar yAxisId="l" dataKey="value" name="Value" fill={PALETTE[0]} radius={[4, 4, 0, 0]} isAnimationActive animationDuration={700} />
            <Line yAxisId="r" type="monotone" dataKey="cum_pct" name="Cumulative %" stroke={PALETTE[2]} strokeWidth={2} dot={{ r: 2 }} isAnimationActive animationDuration={700} />
          </ComposedChart>
        ) : spec.type === "scatter" ? (
          <ComposedChart margin={common.margin}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f033" />
            <XAxis dataKey={spec.x} type="number" name={spec.x} tick={axis} domain={["auto", "auto"]} tickFormatter={(v) => money(v)} />
            <YAxis dataKey={ys[0]} type="number" name={ys[0]} tick={axis} tickFormatter={(v) => money(v)} width={yWidth([ys[0]])} domain={["auto", "auto"]} />
            <Tooltip content={<ChartTooltip />} cursor={{ strokeDasharray: "3 3" }} />
            <Scatter data={spec.data} fill={PALETTE[0]} fillOpacity={0.55} isAnimationActive={false} />
            {spec.line && <Line data={spec.line} dataKey={ys[0]} stroke={PALETTE[4]} strokeWidth={2} dot={false} strokeDasharray="5 4" isAnimationActive={false} legendType="none" />}
            {spec.line && spec.line.length === 2 && spec.line[0][spec.x] === 0 ? <ReferenceLine y={0} stroke="#94a3b8" /> : null}
          </ComposedChart>
        ) : spec.type === "line" ? (
          <LineChart data={spec.data} {...common}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f033" vertical={false} />
            <XAxis dataKey={spec.x} tick={axis} minTickGap={28} />
            <YAxis tick={axis} tickFormatter={(v) => money(v)} width={yWidth(ys)} />
            <Tooltip content={<ChartTooltip xKey={spec.x} />} />{legend}
            {ys.map((y, i) => {
              const bound = /^(low|high)\b/i.test(y), est = bound || /^forecast$/i.test(y);  // model estimates are dashed; the range is thinner
              const colour = est ? PALETTE[Math.max(1, ys.findIndex((k) => /^forecast$/i.test(k))) % PALETTE.length] : PALETTE[i % PALETTE.length];
              return <Line isAnimationActive animationDuration={700} animationEasing="ease-out" key={y} hide={hidden.includes(y)} type="monotone" dataKey={y} stroke={colour} strokeWidth={bound ? 1 : 2} strokeOpacity={bound ? 0.55 : 1} dot={false} connectNulls strokeDasharray={est ? "5 4" : undefined} />;
            })}
          </LineChart>
        ) : (
          spec.type === "histogram" ? (
          <BarChart data={bins} {...common} barCategoryGap={1}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f033" vertical={false} />
            <XAxis dataKey="label" tick={axis} interval={bins.length > 12 ? Math.ceil(bins.length / 10) - 1 : 0} angle={-30} textAnchor="end" height={60} />
            <YAxis tick={axis} tickFormatter={(v) => formatCount(v)} width={axisWidth([0, ...bins.map((b) => b.count)], (v) => formatCount(v))} allowDecimals={false} />
            <Tooltip content={<HistogramTooltip />} cursor={{ fill: "rgba(146,98,58,.08)" }} />
            <Bar isAnimationActive animationDuration={700} animationEasing="ease-out" dataKey="count" name="Records" fill={PALETTE[0]} radius={[4, 4, 0, 0]} maxBarSize={60} />
          </BarChart>
        ) : (
          <BarChart data={spec.data} {...common} barCategoryGap="20%">
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f033" vertical={false} />
            <XAxis dataKey={spec.x} tick={axis} interval={0} angle={spec.data.length > 6 ? -30 : 0} textAnchor={spec.data.length > 6 ? "end" : "middle"} height={spec.data.length > 6 ? 56 : 28} />
            <YAxis tick={axis} tickFormatter={(v) => money(v)} width={yWidth(ys)} />
            <Tooltip content={<ChartTooltip xKey={spec.x} />} cursor={{ fill: "rgba(146,98,58,.08)" }} />{legend}
            {ys.map((y, i) => (
              <Bar isAnimationActive animationDuration={700} animationEasing="ease-out" key={y} hide={hidden.includes(y)} dataKey={y} fill={PALETTE[i % PALETTE.length]} radius={[4, 4, 0, 0]} maxBarSize={48}>
                {spec.signed && spec.data.map((d, k) => <Cell key={k} fill={(d[y] ?? 0) >= 0 ? "#10b981" : "#ef4444"} />)}
              </Bar>))}
            {spec.signed && <ReferenceLine y={0} stroke="#94a3b8" />}
          </BarChart>
        )
        )}
      </ResponsiveContainer>
    );
  }
  return (
    <figure ref={ref} className="group">
      <figcaption className="mb-2 flex items-center justify-between">
        <span className="text-sm font-medium text-slate-700 dark:text-slate-200">{spec.title}</span>
        <button onClick={exportCsv} className="rounded p-1 text-slate-400 opacity-0 transition hover:text-brand-600 group-hover:opacity-100 focus:opacity-100" title="Download chart data (CSV)" aria-label="Download chart data"><Download className="h-4 w-4" /></button>
      </figcaption>
      {body}
      {spec.note && <p className="mt-1 text-xs text-slate-400">{spec.note}</p>}
    </figure>
  );
}
