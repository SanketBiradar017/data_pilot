import { useMutation } from "@tanstack/react-query";
import { ArrowDownRight, ArrowUpRight, Download, Minus, Play, Plus, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { ChartRenderer } from "../../components/ChartRenderer";
import { Card, ErrorNote, Spinner, Tabs } from "../../components/ui";
import { downloadCsv, useNumFmt } from "../../lib/numfmt";
import type { FieldMeta, VarianceResult } from "../../lib/types";
import { ColumnSelect, Field, Stat2 } from "./common";

interface M { column: string; kind: "revenue" | "cost" | "profit"; source: "column" | "value"; target_column: string; target_value: string }
const blank = (): M => ({ column: "", kind: "revenue", source: "column", target_column: "", target_value: "" });

export default function VarianceTool({ datasetId, fields }: { datasetId: number; fields: FieldMeta[] }) {
  const { fmt } = useNumFmt();
  const [mode, setMode] = useState<"target" | "period">("target");
  const [metrics, setMetrics] = useState<M[]>([blank()]);
  const [group, setGroup] = useState(""); const [tol, setTol] = useState(0); const [profit, setProfit] = useState(false);
  const [dateCol, setDateCol] = useState(""); const [period, setPeriod] = useState("month");
  useEffect(() => { setMetrics([blank()]); setGroup(""); setDateCol(""); }, [datasetId]);
  const upd = (i: number, patch: Partial<M>) => setMetrics(metrics.map((m, k) => (k === i ? { ...m, ...patch } : m)));
  const rev = metrics.find((m) => m.kind === "revenue" && m.column), cost = metrics.find((m) => m.kind === "cost" && m.column);
  const ready = metrics.every((m) => m.column && (mode === "period" || (m.source === "column" ? m.target_column : m.target_value !== ""))) && (mode === "target" || dateCol);
  const run = useMutation({
    mutationFn: () => api.post<VarianceResult>("/advanced/variance", {
      dataset_id: datasetId, mode, group_by: group || null, tolerance_pct: tol, date_column: mode === "period" ? dateCol : null, period,
      derive_profit: mode === "target" && profit && rev && cost ? { revenue: rev.column, cost: cost.column } : null,
      metrics: metrics.map((m) => ({ column: m.column, kind: m.kind, target_column: mode === "target" && m.source === "column" ? m.target_column : null, target_value: mode === "target" && m.source === "value" ? Number(m.target_value) : null })),
    }),
  });
  const r = run.data;
  const icon = (s: string) => (s === "favourable" ? <ArrowUpRight className="h-4 w-4 text-emerald-600" /> : s === "unfavourable" ? <ArrowDownRight className="h-4 w-4 text-red-600" /> : <Minus className="h-4 w-4 text-slate-400" />);
  const tone = (s: string) => (s === "favourable" ? "text-emerald-600" : s === "unfavourable" ? "text-red-600" : "text-slate-500");
  const sign = (v: number) => (v > 0 ? "+" : "") + fmt(v);

  return (
    <div className="space-y-5">
      <Tabs value={mode} onChange={setMode} tabs={[{ id: "target", label: "Actual vs target" }, { id: "period", label: "Current vs previous period" }]} />
      <Card title="Configure">
        <div className="space-y-3">
          {metrics.map((m, i) => (
            <div key={i} className="grid items-end gap-3 rounded-xl border border-slate-200 p-3 dark:border-white/10 md:grid-cols-[1.4fr_1fr_1fr_1.4fr_auto]">
              <Field label="Actual (number field)"><ColumnSelect fields={fields} value={m.column} onChange={(v) => upd(i, { column: v })} kinds={["numeric"]} measureOnly /></Field>
              <Field label="Type" hint={m.kind === "cost" ? "Lower than target = favourable" : "Higher than target = favourable"}><select className="input" value={m.kind} onChange={(e) => upd(i, { kind: e.target.value as M["kind"] })}><option value="revenue">Revenue</option><option value="cost">Cost</option><option value="profit">Profit</option></select></Field>
              {mode === "target" ? <>
                <Field label="Target from"><select className="input" value={m.source} onChange={(e) => upd(i, { source: e.target.value as M["source"] })}><option value="column">A column</option><option value="value">A fixed total</option></select></Field>
                {m.source === "column" ? <Field label="Target column"><ColumnSelect fields={fields} value={m.target_column} onChange={(v) => upd(i, { target_column: v })} kinds={["numeric"]} measureOnly exclude={[m.column]} /></Field>
                  : <Field label="Target total"><input type="number" className="input" value={m.target_value} placeholder="e.g. 1000000" onChange={(e) => upd(i, { target_value: e.target.value })} /></Field>}</>
                : <><div /><div /></>}
              <button className="mb-1 rounded p-2 text-slate-400 hover:bg-red-50 hover:text-red-600 disabled:opacity-30" disabled={metrics.length === 1} onClick={() => setMetrics(metrics.filter((_, k) => k !== i))} aria-label="Remove metric"><X className="h-4 w-4" /></button>
            </div>))}
          <button className="btn-ghost !py-1.5 text-xs" onClick={() => setMetrics([...metrics, blank()])}><Plus className="h-3.5 w-3.5" /> Add metric</button>
        </div>
        <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <Field label="Break down by (optional)"><ColumnSelect fields={fields} value={group} onChange={setGroup} kinds={["category", "text"]} placeholder="No breakdown" /></Field>
          <Field label="“On target” tolerance (±%)"><input type="number" className="input" min={0} max={100} value={tol} onChange={(e) => setTol(Number(e.target.value))} /></Field>
          {mode === "period" && <><Field label="Date column"><ColumnSelect fields={fields} value={dateCol} onChange={setDateCol} kinds={["datetime", "text"]} /></Field>
            <Field label="Compare by"><select className="input" value={period} onChange={(e) => setPeriod(e.target.value)}>{["week", "month", "quarter", "year"].map((x) => <option key={x}>{x}</option>)}</select></Field></>}
          {mode === "target" && rev && cost && <label className="flex items-center gap-2 self-end pb-2 text-sm"><input type="checkbox" className="accent-brand-600" checked={profit} onChange={(e) => setProfit(e.target.checked)} /> Add derived Profit (revenue − cost)</label>}
        </div>
        <button className="btn-primary mt-4" disabled={!ready || run.isPending} onClick={() => run.mutate()}>{run.isPending ? <Spinner /> : <Play className="h-4 w-4" />} Calculate variance</button>
      </Card>
      <ErrorNote error={run.error} />
      {r && r.mode === mode && (
        <>
          <Card>
            <p className="text-[15px] font-medium">{r.interpretation}</p>
            <div className="mt-4 grid gap-3 sm:grid-cols-3"><Stat2 label="Favourable" value={r.summary.favourable} tone="good" /><Stat2 label="Unfavourable" value={r.summary.unfavourable} tone="bad" /><Stat2 label="On target" value={r.summary.on_target} /></div>
          </Card>
          <div className="grid gap-5 xl:grid-cols-[1.3fr_1fr]">
            <Card title={r.mode === "period" ? `${r.current_period} vs ${r.previous_period}` : "Variance detail"} pad={false}
              action={<button className="btn-ghost !py-1 text-xs" onClick={() => downloadCsv("variance.csv", ["metric", "group", "kind", "actual", "comparator", "variance", "variance_pct", "status"], r.rows)}><Download className="h-3.5 w-3.5" /> CSV</button>}>
              <div className="overflow-x-auto"><table className="min-w-full"><thead><tr>{["Metric", "Group", "Actual", r.mode === "period" ? "Previous" : "Target", "Variance", "Variance %", ""].map((h, i) => <th key={h + i} className={`th ${i > 1 ? "text-right" : ""}`}>{h}</th>)}</tr></thead>
                <tbody>{r.rows.map((x, i) => (
                  <tr key={i} className="hover:bg-slate-50 dark:hover:bg-white/5"><td className="td font-medium">{x.metric}</td><td className="td text-slate-500">{x.group ?? "—"}</td>
                    <td className="td text-right tabular-nums">{fmt(x.actual)}</td><td className="td text-right tabular-nums">{fmt(x.comparator)}</td>
                    <td className={`td text-right font-semibold tabular-nums ${tone(x.status)}`}>{sign(x.variance)}</td><td className={`td text-right tabular-nums ${tone(x.status)}`}>{x.variance_pct == null ? "—" : `${x.variance_pct > 0 ? "+" : ""}${x.variance_pct.toFixed(1)}%`}</td>
                    <td className="td">{icon(x.status)}</td></tr>))}</tbody></table></div>
            </Card>
            <Card><ChartRenderer spec={r.chart} height={300} /></Card>
          </div>
        </>)}
    </div>
  );
}
