import { Bot, ShieldCheck } from "lucide-react";
import { ChartRenderer } from "../ChartRenderer";
import { Badge, Card } from "../ui";
import type { Report } from "../../lib/types";
import { StoryBody } from "./StoryBody";
import { ExportButtons } from "../AnalysisResult";

const STEP_LABEL: Record<string, string> = { quality: "Data quality", analytics: "Statistics", discovery: "Insight discovery", business: "Business questions", root_cause: "Root cause", executive: "Executive summary" };

/** The one-page result of "Analyse my data": headline, what was investigated, verified findings by topic, charts, actions. */
export function AutopilotView({ r, analysisId }: { r: Report; analysisId: number }) {
  const ap = r.autopilot!;
  const footnotes = r.story?.footnotes ?? [];
  return (
    <div className="space-y-5">
      <Card title={<span className="flex items-center gap-2"><Bot className="h-4 w-4 text-brand-500" /> Autonomous analysis</span>} action={<ExportButtons analysisId={analysisId} />}>
        <p className="text-[15px] leading-relaxed">{ap.headline}</p>
        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
          {ap.steps_run.map((s) => <Badge key={s} tone="brand">{STEP_LABEL[s] ?? s}</Badge>)}
          <Badge tone="green"><ShieldCheck className="mr-1 inline h-3 w-3" />{ap.verified} checks passed</Badge>
        </div>
        {ap.kpis.length > 0 && (
          <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            {ap.kpis.map((k) => <div key={k.label} className="rounded-lg bg-slate-50 px-3 py-2 dark:bg-white/5"><p className="text-xs text-slate-500">{k.label}</p><p className="text-lg font-semibold tabular-nums">{typeof k.value === "number" ? k.value.toLocaleString() : k.value}</p></div>)}
          </div>)}
      </Card>

      {ap.sections.map((s) => (
        <Card key={s.id} title={s.title}>
          {s.statements.length > 0 && <StoryBody statements={s.statements} footnotes={footnotes} />}
          {s.notes && <ul className="space-y-2 text-sm">{s.notes.map((n, i) => <li key={i} className="flex gap-2"><Badge tone="slate">{n.kind}</Badge><span>{n.text}</span></li>)}</ul>}
        </Card>))}

      {r.charts.length > 0 && <div className="grid gap-5 lg:grid-cols-2">{r.charts.map((c, i) => <Card key={i}><ChartRenderer spec={c} /></Card>)}</div>}

      {r.recommendations.length > 0 && <Card title="Recommended actions"><ol className="list-decimal space-y-1.5 pl-5 text-sm">{r.recommendations.map((x, i) => <li key={i}>{x}</li>)}</ol></Card>}
    </div>
  );
}
