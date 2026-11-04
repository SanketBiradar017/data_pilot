import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FileSpreadsheet, FileText, Lightbulb, ShieldCheck } from "lucide-react";
import { api } from "../api/client";
import type { Analysis, SavedReport } from "../lib/types";
import { ChartRenderer } from "./ChartRenderer";
import { ExecutiveView } from "./intelligence/ExecutiveView";
import { AutopilotView } from "./intelligence/AutopilotView";
import { InsightCard } from "./intelligence/InsightCards";
import { RootCauseView } from "./intelligence/RootCauseView";
import { ScenarioView } from "./intelligence/ScenarioView";
import { StoryBody } from "./intelligence/StoryBody";
import { Badge, Card, DataTable, ErrorNote, Spinner, Verified } from "./ui";

const KIND_TONE: Record<string, "brand" | "amber" | "green" | "slate"> = { trend: "brand", anomaly: "amber", correlation: "green", comparison: "brand", sql: "slate", document: "slate", concentration: "brand" };

export function ExportButtons({ analysisId }: { analysisId: number }) {
  const qc = useQueryClient();
  const exp = useMutation({
    mutationFn: async (format: "pdf" | "xlsx") => {
      const r = await api.post<SavedReport>("/reports", { analysis_id: analysisId, format });
      await api.download(`/reports/${r.id}/download`, `report.${format}`);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["reports"] }),
  });
  return (
    <div className="flex items-center gap-2">
      <button className="btn-ghost" disabled={exp.isPending} onClick={() => exp.mutate("pdf")}>{exp.isPending && exp.variables === "pdf" ? <Spinner /> : <FileText className="h-4 w-4" />} PDF</button>
      <button className="btn-ghost" disabled={exp.isPending} onClick={() => exp.mutate("xlsx")}>{exp.isPending && exp.variables === "xlsx" ? <Spinner /> : <FileSpreadsheet className="h-4 w-4" />} Excel</button>
      {exp.error && <ErrorNote error={exp.error} />}
    </div>
  );
}

export function AnalysisResult({ analysis }: { analysis: Analysis }) {
  const r = analysis.result?.report;
  if (analysis.status === "failed") return <ErrorNote error={new Error(analysis.error || "Analysis failed")} />;
  if (!r) return null;
  const v = r.validation;
  const validationCard = v?.total > 0 && (
    <Card title={<span className="flex items-center gap-2"><ShieldCheck className="h-4 w-4 text-emerald-500" /> Validation</span>}>
      <ul className="space-y-1 text-sm text-slate-600 dark:text-slate-300">{v.checks.map((c, i) => <li key={i}>{c.passed ? "✔" : "✘"} {c.claim.length > 110 ? c.claim.slice(0, 110) + "…" : c.claim} <span className="text-xs text-slate-400">({c.detail})</span></li>)}</ul></Card>);
  if (r.autopilot) return <><AutopilotView r={r} analysisId={analysis.id} />{validationCard && <div className="mt-5">{validationCard}</div>}</>;
  if (r.root_cause || r.executive) {  // these views carry their own narrative, evidence and actions
    return (
      <div className="space-y-5">
        <div className="flex justify-end"><ExportButtons analysisId={analysis.id} /></div>
        {r.root_cause ? <RootCauseView rc={r.root_cause} /> : <ExecutiveView ex={r.executive!} />}
        {validationCard}
      </div>
    );
  }
  const story = r.story?.statements?.length ? r.story : null;
  return (
    <div className="space-y-5">
      <Card title="Answer" action={<ExportButtons analysisId={analysis.id} />}>
        {story ? <StoryBody statements={story.statements} footnotes={story.footnotes ?? []} />
          : <div className="space-y-1.5 whitespace-pre-line text-[15px] leading-relaxed text-slate-800 dark:text-slate-100">{r.answer}</div>}
        {r.kpis.length > 0 && (
          <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            {r.kpis.map((k) => (
              <div key={k.label} className="rounded-lg bg-slate-50 px-3 py-2 dark:bg-white/5">
                <p className="text-xs text-slate-500">{k.label}</p>
                <p className="text-lg font-semibold tabular-nums">{typeof k.value === "number" ? k.value.toLocaleString() : k.value}</p>
              </div>
            ))}
          </div>
        )}
      </Card>

      {r.scenario && <ScenarioView r={r.scenario} />}
      {r.discovery && r.discovery.insights.length > 0 && <div className="grid gap-4 lg:grid-cols-2">{r.discovery.insights.map((i) => <InsightCard key={i.id} i={i} />)}</div>}

      {r.charts.length > 0 && !r.scenario && (
        <div className="grid gap-5 lg:grid-cols-2">
          {r.charts.map((c, i) => <Card key={i}><ChartRenderer spec={c} /></Card>)}
        </div>
      )}

      {r.result_rows && r.result_columns && r.sql && (
        <Card title="Query & result">
          <pre className="mb-3 overflow-x-auto rounded-lg bg-ink-950 p-3 font-mono text-xs text-slate-200">{r.sql}</pre>
          <DataTable columns={r.result_columns} rows={r.result_rows} maxHeight={280} />
        </Card>
      )}

      {r.insights.length > 0 && (
        <Card title={<span className="flex items-center gap-2"><Lightbulb className="h-4 w-4 text-amber-500" /> Findings & evidence</span>}>
          <ul className="divide-y divide-slate-100 dark:divide-white/5">
            {r.insights.map((i, k) => (
              <li key={k} className="flex gap-3 py-2.5 first:pt-0 last:pb-0">
                <Badge tone={KIND_TONE[i.kind] ?? "slate"}>{i.kind}</Badge>
                <div className="min-w-0 flex-1 text-sm"><p>{i.text}</p>{i.verification && <p className="mt-0.5 text-xs text-slate-400">Check: {i.verification}</p>}</div>
                <Verified ok={i.verified} />
              </li>
            ))}
          </ul>
        </Card>
      )}

      {r.citations.length > 0 && (
        <Card title="Document citations">
          <ul className="space-y-3">
            {r.citations.map((c, i) => (
              <li key={i} className="rounded-lg border-l-4 border-brand-500 bg-brand-50/50 p-3 text-sm dark:bg-brand-500/5">
                <p className="mb-1 text-xs font-medium text-brand-700 dark:text-brand-300">{c.source} · passage {c.chunk} · relevance {(c.score * 100).toFixed(0)}%</p>
                <p className="text-slate-700 dark:text-slate-300">{c.snippet}</p>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <div className="grid gap-5 lg:grid-cols-2">
        {r.recommendations.length > 0 && (
          <Card title="Recommendations"><ul className="list-disc space-y-1.5 pl-5 text-sm">{r.recommendations.map((x, i) => <li key={i}>{x}</li>)}</ul></Card>
        )}
        {validationCard}
      </div>
    </div>
  );
}
