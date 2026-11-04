import { useQuery } from "@tanstack/react-query";
import { Activity, CheckCircle2, Database, FileText, Rows3, ShieldCheck, Wand2 } from "lucide-react";
import { Link } from "react-router-dom";
import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api/client";
import { Badge, Card, Empty, ErrorNote, Loading, PageHeader, SeverityBadge, Stat } from "../components/ui";
import { ago, scoreColor } from "../lib/format";
import { formatNumber } from "../lib/numfmt";
import type { Overview } from "../lib/types";

export default function OverviewPage() {
  const { data, error, isLoading } = useQuery({ queryKey: ["overview"], staleTime: 0, queryFn: () => api.get<Overview>("/dashboard/overview") });
  if (isLoading) return <Loading />;
  if (error || !data) return <ErrorNote error={error} />;
  const k = data.kpis;
  return (
    <>
      <PageHeader title="Overview" subtitle="Your data estate and analysis activity at a glance." actions={<><Link to={data.recent_datasets[0] ? `/workspace?dataset=${data.recent_datasets[0].id}&auto=1` : "/workspace"} className="btn-primary"><Wand2 className="h-4 w-4" /> Analyse my data</Link><Link to="/workspace" className="btn-ghost">New analysis</Link></>} />
      {k.datasets === 0 ? (
        <Empty icon={Database} title="Connect your first data source" text="Upload a CSV, Excel, JSON, or document — or connect a SQL database — and the agents will profile it automatically." action={<Link to="/datasets" className="btn-primary">Add data</Link>} />
      ) : (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
            <Stat label="Data sources" value={k.datasets} icon={Database} />
            <Stat label="Rows available" value={k.total_rows} icon={Rows3} tone="green" />
            <Stat label="Analyses run" value={k.analyses} hint={`${k.completed_analyses} completed`} icon={Activity} />
            <Stat label="Avg. data quality" value={k.avg_quality ?? "—"} icon={ShieldCheck} tone={k.avg_quality && k.avg_quality >= 85 ? "green" : "amber"} hint="out of 100" />
            <Stat label="Reports" value={k.reports} icon={FileText} tone="amber" />
          </div>
          <div className="grid gap-6 lg:grid-cols-3">
            <Card title="Data quality by source" className="lg:col-span-2">
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={data.quality_by_dataset} layout="vertical" margin={{ left: 20 }}>
                  <XAxis type="number" domain={[0, 100]} tick={{ fontSize: 11, fill: "#94a3b8" }} />
                  <YAxis type="category" dataKey="name" width={110} tick={{ fontSize: 11, fill: "#94a3b8" }} />
                  <Tooltip cursor={{ fill: "rgba(99,102,241,.08)" }} formatter={(v: any) => [formatNumber(v, "standard", 1), "Quality score"]} />
                  <Bar dataKey="score" radius={[0, 4, 4, 0]} barSize={16}>{data.quality_by_dataset.map((d, i) => <Cell key={i} fill={d.score >= 90 ? "#10b981" : d.score >= 75 ? "#f59e0b" : "#ef4444"} />)}</Bar>
                </BarChart>
              </ResponsiveContainer>
            </Card>
            <Card title="Top data issues" action={<Link to="/datasets" className="text-xs text-brand-600">Fix →</Link>}>
              {data.top_issues.length === 0 ? <p className="flex items-center gap-2 text-sm text-emerald-600"><CheckCircle2 className="h-4 w-4" /> No issues detected.</p> : (
                <ul className="space-y-3">{data.top_issues.map((i, n) => <li key={n} className="text-sm"><div className="flex items-center gap-2"><SeverityBadge s={i.severity} /><span className="font-medium">{i.dataset}</span></div><p className="mt-0.5 text-slate-500">{i.column ? `${i.column}: ` : ""}{i.message}</p></li>)}</ul>
              )}
            </Card>
          </div>
          <div className="grid gap-6 lg:grid-cols-2">
            <Card title="Recent analyses" action={<Link to="/history" className="text-xs text-brand-600">All →</Link>} pad={false}>
              {data.recent_analyses.length === 0 ? <p className="p-5 text-sm text-slate-500">No analyses yet.</p> : (
                <ul className="divide-y divide-slate-100 dark:divide-white/5">{data.recent_analyses.map((a) => (
                  <li key={a.id}><Link to={`/history/${a.id}`} className="flex items-center justify-between gap-3 px-5 py-3 hover:bg-slate-50 dark:hover:bg-white/5">
                    <span className="min-w-0 truncate text-sm">{a.question}</span><span className="flex shrink-0 items-center gap-2"><Badge tone={a.status === "completed" ? "green" : a.status === "failed" ? "red" : "brand"}>{a.status}</Badge><span className="text-xs text-slate-400">{ago(a.created_at)}</span></span></Link></li>))}</ul>
              )}
            </Card>
            <Card title="Recent data sources" action={<Link to="/datasets" className="text-xs text-brand-600">All →</Link>} pad={false}>
              <ul className="divide-y divide-slate-100 dark:divide-white/5">{data.recent_datasets.map((d) => (
                <li key={d.id}><Link to={`/datasets/${d.id}`} className="flex items-center justify-between gap-3 px-5 py-3 hover:bg-slate-50 dark:hover:bg-white/5">
                  <span className="min-w-0"><span className="block truncate text-sm font-medium">{d.name}</span><span className="text-xs text-slate-500">{d.kind === "table" ? `${d.row_count.toLocaleString()} rows × ${d.column_count} cols` : "document"} · {d.source_type}</span></span>
                  {d.quality_score != null && <span className={`text-sm font-semibold tabular-nums ${scoreColor(d.quality_score)}`}>{d.quality_score}</span>}</Link></li>))}</ul>
            </Card>
          </div>
        </div>
      )}
    </>
  );
}
