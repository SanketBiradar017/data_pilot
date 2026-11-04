import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, History as HistoryIcon, Trash2 } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { AgentTimeline } from "../components/AgentTimeline";
import { AnalysisResult } from "../components/AnalysisResult";
import { Badge, Card, Empty, ErrorNote, Loading, PageHeader } from "../components/ui";
import { ago } from "../lib/format";
import type { Analysis } from "../lib/types";
import { useAnalysis } from "./Workspace";

export function HistoryDetail() {
  const id = Number(useParams().id);
  const nav = useNavigate();
  const qc = useQueryClient();
  const { data: a, isLoading, error } = useAnalysis(id);
  const del = useMutation({ mutationFn: () => api.del(`/analyses/${id}`), onSuccess: () => { qc.invalidateQueries({ queryKey: ["analyses"] }); nav("/history"); } });
  if (isLoading) return <Loading />;
  if (!a) return <ErrorNote error={error} />;
  return (
    <>
      <Link to="/history" className="mb-3 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-brand-600"><ArrowLeft className="h-4 w-4" /> History</Link>
      <PageHeader title={a.question} subtitle={`Run ${ago(a.created_at)} · ${a.status}`} actions={<button className="btn-danger" onClick={() => confirm("Delete this analysis?") && del.mutate()}><Trash2 className="h-4 w-4" /> Delete</button>} />
      <div className="grid gap-6 xl:grid-cols-[320px_1fr]">
        <Card title="Agent workflow" className="h-fit"><AgentTimeline trace={a.trace} plan={a.plan} status={a.status} /></Card>
        <AnalysisResult analysis={a} />
      </div>
    </>
  );
}

export default function History() {
  const { data, isLoading, error } = useQuery({ queryKey: ["analyses"], staleTime: 0, queryFn: () => api.get<Analysis[]>("/analyses") });
  return (
    <>
      <PageHeader title="Analysis history" subtitle="Every analysis run, with its agent trace and verified results." />
      {isLoading ? <Loading /> : error ? <ErrorNote error={error} /> : !data?.length ? (
        <Empty icon={HistoryIcon} title="Nothing here yet" text="Analyses you run in the workspace or chat will be listed here." action={<Link to="/workspace" className="btn-primary">Start an analysis</Link>} />
      ) : (
        <Card pad={false}><ul className="divide-y divide-slate-100 dark:divide-white/5">{data.map((a) => (
          <li key={a.id}><Link to={`/history/${a.id}`} className="flex items-center gap-4 px-5 py-4 hover:bg-slate-50 dark:hover:bg-white/5">
            <div className="min-w-0 flex-1"><p className="truncate font-medium">{a.question}</p><p className="mt-0.5 truncate text-sm text-slate-500">{a.error || a.answer?.split("\n")[0]}</p></div>
            <span className="hidden text-xs text-slate-400 sm:block">{a.trace.length} agent steps</span>
            <Badge tone={a.status === "completed" ? "green" : a.status === "failed" ? "red" : "brand"}>{a.status}</Badge><span className="w-20 text-right text-xs text-slate-400">{ago(a.created_at)}</span></Link></li>))}</ul></Card>
      )}
    </>
  );
}
