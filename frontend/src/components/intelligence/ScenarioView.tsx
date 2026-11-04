import { FlaskConical, Info } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card } from "../ui";
import { axisWidth, useNumFmt } from "../../lib/numfmt";
import type { ScenarioResult } from "../../lib/types";

const axis = { fontSize: 11, fill: "#94a3b8" };
const OBS = "rgb(var(--brand-600))";
const EST = ["#f59e0b", "#0ea5e9", "#a855f7", "#ec4899"];

export function ScenarioView({ r }: { r: ScenarioResult }) {
  const { fmt } = useNumFmt();
  const f = new Map(r.facts.map((x) => [x.id, x.value]));
  const v = (id?: string) => (id ? f.get(id) ?? null : null);
  const metrics: [string, string, "money" | "pct"][] = [["revenue", "Revenue", "money"], ["cost", "Cost", "money"], ["profit", "Profit", "money"], ["margin", "Profit margin", "pct"], ["quantity", "Quantity", "money"]];
  const rows = metrics.filter(([k]) => r.observed[k] || r.scenarios[0].facts[k]);
  const show = (x: number | null, kind: "money" | "pct") => (x == null ? "—" : kind === "pct" ? `${x.toFixed(1)}%` : fmt(x));
  const chartData = rows.filter(([k]) => ["revenue", "cost", "profit"].includes(k)).map(([k, label]) => ({ label, "Observed baseline": v(r.observed[k]), ...Object.fromEntries(r.scenarios.map((s) => [`${s.name} (estimate)`, v(s.facts[k])])) }));
  const sens = r.sensitivity;
  return (
    <div className="space-y-5">
      <div className="flex items-start gap-3 rounded-xl border-2 border-dashed border-amber-400 bg-amber-50 p-4 text-amber-900 dark:border-amber-500/50 dark:bg-amber-500/10 dark:text-amber-200">
        <FlaskConical className="mt-0.5 h-5 w-5 shrink-0" /><div><p className="font-semibold">These are estimates, not observed data</p><p className="text-sm">{r.disclaimer}</p></div>
      </div>
      {(r.data_notes ?? []).map((n, i) => <p key={i} className="flex items-start gap-2 rounded-lg bg-sky-50 px-3 py-2 text-sm text-sky-800 dark:bg-sky-500/10 dark:text-sky-200"><Info className="mt-0.5 h-4 w-4 shrink-0" /> {n}</p>)}
      <Card title="Baseline vs scenario" pad={false}>
        <div className="overflow-x-auto">
          <table className="min-w-full">
            <thead><tr><th className="th">Metric</th>
              <th className="th text-right"><span className="mr-1 rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-bold text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-300">OBSERVED</span>{r.baseline_scope}</th>
              {r.scenarios.map((s, i) => <th key={i} className="th text-right" style={{ borderBottom: `2px solid ${EST[i % 4]}` }}><span className="mr-1 rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-bold text-amber-800 dark:bg-amber-500/20 dark:text-amber-300">ESTIMATE</span>{s.name}</th>)}</tr></thead>
            <tbody>{rows.map(([k, label, kind]) => (
              <tr key={k} className="hover:bg-slate-50 dark:hover:bg-white/5"><td className="td font-medium">{label}</td>
                <td className="td text-right tabular-nums">{show(v(r.observed[k]), kind)}</td>
                {r.scenarios.map((s, i) => {
                  const est = v(s.facts[k]); const base = v(r.observed[k]);
                  const d = est != null && base != null ? est - base : null; const pct = d != null && base ? (d / Math.abs(base)) * 100 : null;
                  return <td key={i} className="td text-right tabular-nums" style={{ background: "repeating-linear-gradient(135deg, transparent 0 6px, rgba(245,158,11,.06) 6px 12px)" }}>
                    <span className="font-semibold">{show(est, kind)}</span>
                    {d != null && kind === "money" && <span className={`ml-2 text-xs ${d < 0 ? "text-red-600" : "text-emerald-600"}`}>{d > 0 ? "+" : ""}{fmt(d)} ({pct == null ? "—" : `${pct > 0 ? "+" : ""}${pct.toFixed(1)}%`})</span>}
                    {d != null && kind === "pct" && <span className={`ml-2 text-xs ${d < 0 ? "text-red-600" : "text-emerald-600"}`}>{d > 0 ? "+" : ""}{d.toFixed(1)} pts</span>}</td>;
                })}</tr>))}</tbody>
          </table>
        </div>
        <div className="grid gap-2 border-t border-slate-100 p-4 text-xs text-slate-500 dark:border-white/5 md:grid-cols-2">
          {r.scenarios.map((s, i) => (
            <div key={i}><b style={{ color: EST[i % 4] }}>{s.name}</b> — assumes: price {s.assumptions.price_change_pct > 0 ? "+" : ""}{s.assumptions.price_change_pct}%, volume {s.assumptions.volume_change_pct > 0 ? "+" : ""}{s.assumptions.volume_change_pct}%, elasticity {s.assumptions.elasticity}, cost {s.assumptions.cost_change_pct > 0 ? "+" : ""}{s.assumptions.cost_change_pct}%, fixed-cost share {s.assumptions.fixed_cost_pct}%; applies to <b>{s.segment}</b>.
              {s.notes.map((n, k) => <p key={k} className="mt-1 flex gap-1 text-amber-700 dark:text-amber-300"><Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />{n}</p>)}</div>))}
        </div>
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Observed baseline vs estimated scenarios">
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={chartData}><CartesianGrid strokeDasharray="3 3" stroke="#e2e8f033" vertical={false} /><XAxis dataKey="label" tick={axis} /><YAxis tick={axis} tickFormatter={(x) => fmt(x)} width={axisWidth(chartData.flatMap((d) => Object.values(d).filter((x): x is number => typeof x === "number")), (x) => fmt(x))} /><Tooltip formatter={(x: any) => fmt(x)} /><Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="Observed baseline" fill={OBS} radius={[4, 4, 0, 0]} />
              {r.scenarios.map((s, i) => <Bar key={i} dataKey={`${s.name} (estimate)`} fill={EST[i % 4]} fillOpacity={0.55} stroke={EST[i % 4]} strokeDasharray="4 3" radius={[4, 4, 0, 0]} />)}</BarChart>
          </ResponsiveContainer>
        </Card>
        {sens.length > 0 && sens[0].profit != null && (
          <Card title="Sensitivity: estimated profit vs price change (first scenario's other assumptions)">
            <ResponsiveContainer width="100%" height={280}>
              <LineChart data={sens}><CartesianGrid strokeDasharray="3 3" stroke="#e2e8f033" vertical={false} /><XAxis dataKey="price_change_pct" tick={axis} tickFormatter={(x) => `${x}%`} /><YAxis tick={axis} tickFormatter={(x) => fmt(x)} width={axisWidth(sens.flatMap((d) => [d.revenue, d.profit ?? 0]), (x) => fmt(x))} /><Tooltip formatter={(x: any) => fmt(x)} labelFormatter={(l) => `Price ${l}%`} />
                <ReferenceLine x={0} stroke="#94a3b8" strokeDasharray="3 3" label={{ value: "today", fontSize: 10, fill: "#94a3b8" }} /><Legend wrapperStyle={{ fontSize: 12 }} />
                <Line type="monotone" dataKey="profit" name="Estimated profit" stroke="#f59e0b" strokeWidth={2} strokeDasharray="5 4" dot /><Line type="monotone" dataKey="revenue" name="Estimated revenue" stroke="#0ea5e9" strokeWidth={2} strokeDasharray="5 4" dot={false} /></LineChart>
            </ResponsiveContainer>
          </Card>)}
      </div>

      {r.scenarios.some((s) => s.breakdown.length > 0) && (
        <Card title="Breakdown (estimate)" pad={false}>
          <div className="overflow-x-auto"><table className="min-w-full"><thead><tr>{["Scenario", "Group", "Baseline revenue", "Scenario revenue", "Baseline profit", "Scenario profit"].map((h, i) => <th key={h} className={`th ${i > 1 ? "text-right" : ""}`}>{h}</th>)}</tr></thead>
            <tbody>{r.scenarios.flatMap((s) => s.breakdown.map((b, i) => <tr key={s.name + b.group}><td className="td text-slate-500">{i === 0 ? s.name : ""}</td><td className="td font-medium">{b.group}</td>
              <td className="td text-right tabular-nums">{fmt(b.baseline_revenue)}</td><td className="td text-right tabular-nums text-amber-700 dark:text-amber-300">{fmt(b.scenario_revenue)}</td>
              <td className="td text-right tabular-nums">{b.baseline_profit == null ? "—" : fmt(b.baseline_profit)}</td><td className="td text-right tabular-nums text-amber-700 dark:text-amber-300">{b.scenario_profit == null ? "—" : fmt(b.scenario_profit)}</td></tr>))}</tbody></table></div>
        </Card>)}
      {r.elasticity_hint && <p className="flex gap-2 rounded-lg bg-slate-100 px-3 py-2 text-sm text-slate-600 dark:bg-white/5 dark:text-slate-300"><Info className="mt-0.5 h-4 w-4 shrink-0" /><span><b>What the data says about price sensitivity:</b> {r.elasticity_hint.message}</span></p>}
    </div>
  );
}
