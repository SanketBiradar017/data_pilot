import { AlertTriangle, ArrowDownRight, ArrowUpRight, CheckCircle2, Lightbulb } from "lucide-react";
import { ChartRenderer } from "../ChartRenderer";
import { Card } from "../ui";
import { useNumFmt } from "../../lib/numfmt";
import type { RootCause } from "../../lib/types";
import { StoryBody, toFootnotes } from "./StoryBody";

export function RootCauseView({ rc }: { rc: RootCause }) {
  const { fmt } = useNumFmt();
  const down = rc.totals.change < 0;
  const foot = toFootnotes(rc.story.statements, rc.facts, rc.verification);
  const d: any = rc.drivers;
  const nv = Object.keys(rc.verification).length, ok = Object.values(rc.verification).filter((v) => v.verified).length;
  return (
    <div className="space-y-5">
      <Card>
        <div className="flex flex-wrap items-start gap-4">
          <span className={`rounded-xl p-3 ${down ? "bg-red-50 text-red-600 dark:bg-red-500/15" : "bg-emerald-50 text-emerald-600 dark:bg-emerald-500/15"}`}>{down ? <ArrowDownRight className="h-6 w-6" /> : <ArrowUpRight className="h-6 w-6" />}</span>
          <div className="min-w-0 flex-1">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">What happened?</p>
            <p className="mt-1 text-lg font-semibold">{(rc.story.statements.find((x) => x.kind === "what") ?? rc.story.statements[0])?.text ?? `${rc.metric} ${rc.direction}`}</p>
            <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-sm text-slate-500"><span>{rc.previous}: <b className="text-slate-800 dark:text-slate-100">{fmt(rc.totals.previous)}</b></span><span>{rc.current}: <b className="text-slate-800 dark:text-slate-100">{fmt(rc.totals.current)}</b></span>
              <span>Change: <b className={down ? "text-red-600" : "text-emerald-600"}>{rc.totals.change > 0 ? "+" : ""}{fmt(rc.totals.change)} ({rc.totals.change_pct?.toFixed(1)}%)</b></span></div>
          </div>
          <span className="flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300"><CheckCircle2 className="h-3.5 w-3.5" /> {ok}/{nv} calculations verified</span>
        </div>
        {!rc.complete_current_period && <p className="mt-3 flex items-center gap-2 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:bg-amber-500/10 dark:text-amber-300"><AlertTriangle className="h-4 w-4" /> {rc.current} has fewer days of data than a full period; the comparison may be understated.</p>}
      </Card>

      <div className="grid gap-5 xl:grid-cols-2">
        <Card title="Why did it happen?"><StoryBody statements={rc.story.statements.filter((x) => x.kind !== "what")} footnotes={foot} /></Card>
        <Card title="Contributing factors (ranked by impact)" pad={false}>
          {rc.factors.length === 0 ? <p className="p-5 text-sm text-slate-500">No single factor dominates: the change is spread across many groups.</p> : (
            <ul className="divide-y divide-slate-100 dark:divide-white/5">{rc.factors.map((f, i) => {
              const w = Math.min(100, Math.abs(f.share_pct ?? 0)); const neg = f.impact < 0;
              return (<li key={i} className="px-5 py-3"><div className="flex items-center justify-between gap-3 text-sm"><span className="font-medium">{f.title}</span><span className={`tabular-nums font-semibold ${neg ? "text-red-600" : "text-emerald-600"}`}>{f.impact > 0 ? "+" : ""}{fmt(f.impact)}</span></div>
                <div className="mt-1.5 flex items-center gap-2"><span className="h-1.5 flex-1 rounded bg-slate-100 dark:bg-white/10"><span className={`block h-full rounded ${neg ? "bg-red-500" : "bg-emerald-500"}`} style={{ width: `${w}%` }} /></span><span className="w-14 text-right text-xs text-slate-500">{f.share_pct == null ? "" : `${f.share_pct.toFixed(0)}%`}</span></div></li>);
            })}</ul>)}
        </Card>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">{rc.charts.slice(0, 2).map((c, i) => <Card key={i}><ChartRenderer spec={c} height={260} /></Card>)}</div>
      {rc.charts[2] && <Card><ChartRenderer spec={rc.charts[2]} height={240} /></Card>}

      <div className="grid gap-5 xl:grid-cols-2">
        {d.kind && (
          <Card title="Decomposition (reconciles exactly to the total change)">
            <dl className="space-y-2 text-sm">
              <div className="flex justify-between"><dt className="text-slate-500">{d.kind === "volume_price" ? `Volume (${d.quantity})` : "Number of records"}</dt><dd className="font-medium tabular-nums">{fmt(d.volume_effect)}</dd></div>
              {d.mix_effect != null ? <><div className="flex justify-between"><dt className="text-slate-500">Product mix ({d.mix_dimension})</dt><dd className="font-medium tabular-nums">{fmt(d.mix_effect)}</dd></div>
                <div className="flex justify-between"><dt className="text-slate-500">Like-for-like price</dt><dd className="font-medium tabular-nums">{fmt(d.like_for_like_price_effect)}</dd></div></>
                : <div className="flex justify-between"><dt className="text-slate-500">{d.kind === "volume_price" ? "Price / mix" : "Average value per record"}</dt><dd className="font-medium tabular-nums">{fmt(d.price_mix_effect)}</dd></div>}
              <div className="flex justify-between border-t border-slate-100 pt-2 font-semibold dark:border-white/10"><dt>Total change</dt><dd className="tabular-nums">{fmt(rc.totals.change)}</dd></div>
            </dl>
            <ul className="mt-3 space-y-1 text-xs text-slate-500">{rc.reconciliation.map((r, i) => <li key={i}>{r.passed ? "✔" : "✘"} {r.check}</li>)}</ul>
          </Card>)}
        <Card title={<span className="flex items-center gap-2"><Lightbulb className="h-4 w-4 text-amber-500" /> Recommended actions</span>}>
          {rc.story.recommendations.length ? <ul className="list-disc space-y-1.5 pl-5 text-sm">{rc.story.recommendations.map((r, i) => <li key={i}>{r}</li>)}</ul> : <p className="text-sm text-slate-500">No specific actions suggested.</p>}
        </Card>
      </div>

      <Card title="Breakdown by dimension" pad={false}>
        <div className="overflow-x-auto"><table className="min-w-full"><thead><tr>{["Dimension", "Group", `Previous (${rc.previous})`, `Current (${rc.current})`, "Change", "Share of change"].map((h, i) => <th key={h} className={`th ${i > 1 ? "text-right" : ""}`}>{h}</th>)}</tr></thead>
          <tbody>{rc.dimensions.flatMap((dm) => dm.top.slice(0, 4).map((t, i) => (
            <tr key={dm.dimension + t.group} className="hover:bg-slate-50 dark:hover:bg-white/5"><td className="td text-slate-500">{i === 0 ? dm.dimension : ""}</td><td className="td font-medium">{t.group}</td>
              <td className="td text-right tabular-nums">{fmt(t.previous)}</td><td className="td text-right tabular-nums">{fmt(t.current)}</td>
              <td className={`td text-right font-semibold tabular-nums ${t.change < 0 ? "text-red-600" : "text-emerald-600"}`}>{t.change > 0 ? "+" : ""}{fmt(t.change)}</td><td className="td text-right tabular-nums">{t.share_of_change_pct == null ? "—" : `${t.share_of_change_pct.toFixed(0)}%`}</td></tr>)))}</tbody></table></div>
      </Card>
    </div>
  );
}
