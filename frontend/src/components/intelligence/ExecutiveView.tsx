import { ArrowDownRight, ArrowUpRight, CheckCircle2, Info, Rocket, ShieldAlert } from "lucide-react";
import { ChartRenderer } from "../ChartRenderer";
import { Badge, Card } from "../ui";
import { useNumFmt } from "../../lib/numfmt";
import type { Executive } from "../../lib/types";
import { InsightCard } from "./InsightCards";
import { StoryBody, toFootnotes } from "./StoryBody";

export function ExecutiveView({ ex, onInvestigate }: { ex: Executive; onInvestigate?: (i: any) => void }) {
  const { fmt } = useNumFmt();
  const foot = toFootnotes(ex.performance, ex.facts, ex.verification);
  const pri = { high: "red", medium: "amber", low: "slate" } as const;
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        {ex.kpis.map((k) => (
          <div key={k.label} className="card lift p-4">
            <p className="flex items-center justify-between text-xs capitalize text-slate-500">{k.label}{k.verified && <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />}</p>
            <p className="mt-1 text-2xl font-semibold tabular-nums">{k.value == null ? "—" : fmt(k.value)}</p>
            {k.change_pct != null && <p className={`mt-0.5 flex items-center gap-1 text-xs font-medium ${k.change_pct >= 0 ? (k.label === "cost" ? "text-red-600" : "text-emerald-600") : (k.label === "cost" ? "text-emerald-600" : "text-red-600")}`}>{k.change_pct >= 0 ? <ArrowUpRight className="h-3.5 w-3.5" /> : <ArrowDownRight className="h-3.5 w-3.5" />}{Math.abs(k.change_pct).toFixed(1)}% in {ex.period}</p>}
          </div>))}
      </div>
      {(ex.data_notes ?? []).map((n, i) => <p key={i} className="flex items-start gap-2 rounded-lg bg-sky-50 px-3 py-2 text-sm text-sky-800 dark:bg-sky-500/10 dark:text-sky-200"><Info className="mt-0.5 h-4 w-4 shrink-0" /> {n}</p>)}
      <Card title="Overall business performance"><StoryBody statements={ex.performance} footnotes={foot} /></Card>
      <div className="grid gap-5 xl:grid-cols-2">
        <Card title={<span className="flex items-center gap-2"><ShieldAlert className="h-4 w-4 text-red-500" /> Risks</span>}>{ex.risks.length ? <div className="space-y-3">{ex.risks.map((i) => <InsightCard key={i.id} i={i} onInvestigate={onInvestigate} />)}</div> : <p className="text-sm text-slate-500">No significant risks detected.</p>}</Card>
        <Card title={<span className="flex items-center gap-2"><Rocket className="h-4 w-4 text-emerald-500" /> Opportunities</span>}>{ex.opportunities.length ? <div className="space-y-3">{ex.opportunities.map((i) => <InsightCard key={i.id} i={i} onInvestigate={onInvestigate} />)}</div> : <p className="text-sm text-slate-500">No standout opportunities detected.</p>}</Card>
      </div>
      <Card title="Business recommendations"><ol className="space-y-2.5">{ex.recommendations.map((r, i) => <li key={i} className="flex gap-3 text-sm"><Badge tone={pri[r.priority]}>{r.priority}</Badge><span>{r.text}</span></li>)}{ex.recommendations.length === 0 && <li className="text-sm text-slate-500">No actions suggested.</li>}</ol></Card>
      {ex.charts.length > 0 && <div className="grid gap-5 lg:grid-cols-2">{ex.charts.map((c, i) => <Card key={i}><ChartRenderer spec={c} height={260} /></Card>)}</div>}
      <details className="card p-4"><summary className="cursor-pointer text-sm font-semibold">Supporting evidence ({ex.evidence.length} calculations, {ex.evidence.filter((e) => e.verified).length} verified)</summary>
        <div className="mt-3 max-h-80 overflow-auto"><table className="min-w-full text-xs"><thead><tr><th className="th">Fact</th><th className="th text-right">Value</th><th className="th">How it was checked</th></tr></thead>
          <tbody>{ex.evidence.map((e) => <tr key={e.id}><td className="td">{e.label}</td><td className="td text-right tabular-nums">{e.value == null ? "—" : e.unit === "pct" ? `${e.value.toFixed(2)}%` : fmt(e.value)}</td><td className="td whitespace-normal break-all text-slate-500">{e.verified ? "✔ " : "✘ "}{e.sql ?? `${e.op}(${(e.inputs ?? []).join(", ")})`}</td></tr>)}</tbody></table></div></details>
    </div>
  );
}
