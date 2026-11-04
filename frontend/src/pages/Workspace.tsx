import { useMutation, useQuery } from "@tanstack/react-query";
import { Play, Sparkles, Wand2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { AgentTimeline } from "../components/AgentTimeline";
import { AnalysisResult } from "../components/AnalysisResult";
import { useDatasets } from "../components/DatasetPicker";
import { SuggestionChips, useSuggestions } from "../components/SuggestionChips";
import { Card, ErrorNote, PageHeader, Spinner } from "../components/ui";
import type { Analysis } from "../lib/types";

const AUTO_QUESTION = "Analyse my data";

export function useAnalysis(id: number | null) {
  return useQuery({
    queryKey: ["analysis", id], enabled: id != null, queryFn: () => api.get<Analysis>(`/analyses/${id}`),
    refetchInterval: (q) => (q.state.data && ["queued", "running"].includes(q.state.data.status) ? 600 : false),
  });
}

export default function Workspace() {
  const [params] = useSearchParams();
  const { data: datasets = [] } = useDatasets();
  const [selected, setSelected] = useState<number[]>(params.get("dataset") ? [Number(params.get("dataset"))] : []);
  const [question, setQuestion] = useState("");
  const [aid, setAid] = useState<number | null>(null);
  useEffect(() => { if (!selected.length && datasets.length) setSelected([datasets[0].id]); }, [datasets, selected.length]);
  const sugg = useSuggestions(selected);
  const run = useMutation({ mutationFn: (q?: string) => api.post<Analysis>("/analyses", { question: q ?? question, dataset_ids: selected }), onSuccess: (a) => setAid(a.id) });
  const auto = useRef(false);
  useEffect(() => {  // arriving from "Analyse my data" starts the autonomous run once
    if (params.get("auto") && selected.length && !auto.current) { auto.current = true; run.mutate(AUTO_QUESTION); }
  }, [params, selected.length]); // eslint-disable-line react-hooks/exhaustive-deps
  const { data: a } = useAnalysis(aid);
  const busy = run.isPending || (!!a && ["queued", "running"].includes(a.status));
  const toggle = (id: number) => setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));

  return (
    <>
      <PageHeader title="Analysis workspace" subtitle="Ask a question — the planner routes it to specialised agents, and every number is verified before you see it." />
      <Card className="mb-6">
        <div className="mb-3 flex flex-wrap gap-2">
          {datasets.length === 0 && <p className="text-sm text-slate-500">Add a data source first.</p>}
          {datasets.map((d) => (
            <button key={d.id} onClick={() => toggle(d.id)} aria-pressed={selected.includes(d.id)}
              className={`rounded-full border px-3 py-1 text-xs font-medium transition ${selected.includes(d.id) ? "border-brand-600 bg-brand-600 text-white" : "border-slate-300 text-slate-600 hover:border-brand-400 dark:border-white/15 dark:text-slate-300"}`}>{d.name}</button>))}
        </div>
        <div className="mb-4 flex flex-wrap items-center gap-3 rounded-lg border border-brand-500/30 bg-brand-50/50 px-4 py-3 dark:bg-brand-500/5">
          <div className="min-w-0 flex-1"><p className="text-sm font-semibold">Autonomous Data Analyst</p><p className="text-xs text-slate-500">Upload your data, let AI investigate, discover what matters. No questions needed.</p></div>
          <button type="button" className="btn-primary" disabled={busy || !selected.length} onClick={() => { setQuestion(AUTO_QUESTION); run.mutate(AUTO_QUESTION); }}>{busy ? <Spinner /> : <Wand2 className="h-4 w-4" />} Analyse my data</button>
        </div>
        <form onSubmit={(e) => { e.preventDefault(); run.mutate(undefined); }} className="flex flex-col gap-3 sm:flex-row">
          <input className="input flex-1" value={question} onChange={(e) => setQuestion(e.target.value)} placeholder={`e.g. ${sugg.data?.[0]?.question ?? "Ask a question about your data"}`} aria-label="Question" />
          <button className="btn-primary sm:w-40" disabled={busy || question.trim().length < 2 || !selected.length}>{busy ? <Spinner /> : <Play className="h-4 w-4" />} Run analysis</button>
        </form>
        <SuggestionChips ids={selected} onPick={setQuestion} className="mt-3" />
        <div className="mt-3"><ErrorNote error={run.error} /></div>
      </Card>

      {!a ? (
        <div className="flex flex-col items-center py-16 text-center text-slate-500"><Sparkles className="mb-3 h-8 w-8 text-brand-400" /><p>Results, charts and the live agent workflow appear here.</p></div>
      ) : (
        <div className="grid gap-6 xl:grid-cols-[320px_1fr]">
          <Card title="Agent workflow" className="h-fit xl:sticky xl:top-0">
            <AgentTimeline trace={a.trace} plan={a.plan} status={a.status} />
            {a.plan?.rationale && <p className="mt-3 border-t border-slate-100 pt-3 text-xs text-slate-500 dark:border-white/5">{a.plan.rationale}</p>}
          </Card>
          <div>{busy && !a.result?.report ? <Card><p className="flex items-center gap-2 text-sm text-slate-500"><Spinner /> Agents are working on “{a.question}”…</p></Card> : <AnalysisResult analysis={a} />}</div>
        </div>
      )}
    </>
  );
}
