import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Download, Sparkles, Wand2 } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis } from "recharts";
import { api } from "../api/client";
import { HistogramTooltip } from "../components/ChartTooltip";
import DuplicateAnalysis from "../components/DuplicateAnalysis";
import { histogramBins } from "../lib/histogram";
import { useNumFmt } from "../lib/numfmt";
import { Badge, Card, DataTable, ErrorNote, Loading, PageHeader, SeverityBadge, Spinner, Tabs } from "../components/ui";
import { bytes, num, scoreColor } from "../lib/format";
import type { ColumnProfile, Dataset } from "../lib/types";

interface Preview { kind: "table" | "document"; columns?: { name: string; dtype: string }[]; rows?: Record<string, any>[]; total?: number; text?: string }
function MiniHistogram({ rows, integer, title }: { rows: NonNullable<ColumnProfile["histogram"]>; integer?: boolean; title: string }) {
  const { mode } = useNumFmt();
  const bins = useMemo(() => histogramBins(rows, { integer, mode, title }), [rows, integer, mode, title]);
  return <ResponsiveContainer width="100%" height={70}><BarChart data={bins}><XAxis dataKey="label" hide /><Tooltip content={<HistogramTooltip />} cursor={{ fill: "rgba(146,98,58,.12)" }} /><Bar dataKey="count" fill="rgb(var(--brand-600))" radius={[2, 2, 0, 0]} /></BarChart></ResponsiveContainer>;
}

const FIX_OP: Record<string, string> = { fill_missing: "fill_missing", drop_duplicates: "drop_duplicates", clip_outliers: "clip_outliers", trim_whitespace: "trim_whitespace", standardize_case: "standardize_case", drop_column: "drop_column" };

export default function DatasetDetail() {
  const id = Number(useParams().id);
  const qc = useQueryClient();
  const [tab, setTab] = useState<"preview" | "profile" | "quality">("preview");
  const [page, setPage] = useState(0);
  const ds = useQuery({ queryKey: ["dataset", id], queryFn: () => api.get<Dataset>(`/datasets/${id}`) });
  const pv = useQuery({ queryKey: ["preview", id, page, ds.data?.updated_at], queryFn: () => api.get<Preview>(`/datasets/${id}/preview?limit=50&offset=${page * 50}`), enabled: !!ds.data });
  const clean = useMutation({
    mutationFn: (b: { op: string; column?: string | null; strategy?: string }) => api.post<{ message: string; quality_before: number; quality_after: number; dataset: Dataset }>(`/datasets/${id}/clean`, b),
    onSuccess: (r) => { qc.setQueryData(["dataset", id], r.dataset); qc.invalidateQueries({ queryKey: ["datasets"] }); qc.invalidateQueries({ queryKey: ["overview"] }); },
  });
  if (ds.isLoading) return <Loading />;
  if (!ds.data) return <ErrorNote error={ds.error} />;
  const d = ds.data, p = d.profile, q = d.quality;

  return (
    <>
      <Link to="/datasets" className="mb-3 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-brand-600"><ArrowLeft className="h-4 w-4" /> Data sources</Link>
      <PageHeader title={d.name} subtitle={d.kind === "table" ? `${d.row_count.toLocaleString()} rows × ${d.column_count} columns · ${bytes(d.size_bytes)} · SQL table “${d.table_name}”` : `Document · ${p?.words?.toLocaleString()} words`}
        actions={<>
          {d.kind === "table" && <button className="btn-ghost" onClick={() => api.download(`/datasets/${id}/download`, `${d.table_name}.csv`)}><Download className="h-4 w-4" /> CSV</button>}
          {d.kind === "table" && <Link to={`/workspace?dataset=${id}&auto=1`} className="btn-primary"><Wand2 className="h-4 w-4" /> Analyse my data</Link>}
          <Link to={`/workspace?dataset=${id}`} className="btn-ghost"><Sparkles className="h-4 w-4" /> Ask a question</Link></>} />
      {d.kind === "document" ? (
        <div className="space-y-5"><Card title="Extracted text"><pre className="max-h-[60vh] overflow-auto whitespace-pre-wrap text-sm leading-relaxed">{pv.data?.text ?? p?.preview}</pre></Card><DuplicateAnalysis datasetId={id} kind="document" /></div>
      ) : (
        <>
          <Tabs value={tab} onChange={setTab} tabs={[{ id: "preview", label: "Preview" }, { id: "profile", label: "Profile" }, { id: "quality", label: `Data quality${q ? ` · ${q.score}` : ""}` }]} />
          {tab === "preview" && (
            <Card pad={false}>
              {pv.isLoading ? <Loading /> : <div className="p-3"><DataTable columns={pv.data?.columns?.map((c) => c.name) ?? []} rows={pv.data?.rows ?? []} maxHeight={520} /></div>}
              <div className="flex items-center justify-between border-t border-slate-100 px-4 py-2 text-sm dark:border-white/5">
                <span className="text-slate-500">Rows {(page * 50 + 1).toLocaleString()}–{Math.min((page + 1) * 50, d.row_count).toLocaleString()} of {d.row_count.toLocaleString()}</span>
                <span className="flex gap-2"><button className="btn-ghost py-1" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button><button className="btn-ghost py-1" disabled={(page + 1) * 50 >= d.row_count} onClick={() => setPage(page + 1)}>Next</button></span>
              </div>
            </Card>
          )}
          {tab === "profile" && p && (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {p.column_profiles.map((c) => (
                <Card key={c.name} className="!p-0">
                  <div className="space-y-2 p-4">
                    <div className="flex items-center justify-between"><span className="truncate font-medium" title={c.name}>{c.name}</span><Badge tone="brand">{c.type}</Badge></div>
                    <dl className="grid grid-cols-3 gap-2 text-xs"><div><dt className="text-slate-500">Missing</dt><dd className="font-medium">{c.missing_pct}%</dd></div><div><dt className="text-slate-500">Unique</dt><dd className="font-medium">{c.unique.toLocaleString()}</dd></div><div><dt className="text-slate-500">dtype</dt><dd className="font-medium">{c.dtype}</dd></div></dl>
                    {c.type === "numeric" && <dl className="grid grid-cols-3 gap-2 text-xs"><div><dt className="text-slate-500">Mean</dt><dd className="font-medium">{num(c.mean)}</dd></div><div><dt className="text-slate-500">Median</dt><dd className="font-medium">{num(c.median)}</dd></div><div><dt className="text-slate-500">Std</dt><dd className="font-medium">{num(c.std)}</dd></div><div><dt className="text-slate-500">Min</dt><dd className="font-medium">{num(c.min)}</dd></div><div><dt className="text-slate-500">Max</dt><dd className="font-medium">{num(c.max)}</dd></div><div><dt className="text-slate-500">Skew</dt><dd className="font-medium">{num(c.skew)}</dd></div></dl>}
                    {c.type === "datetime" && <p className="text-xs text-slate-500">{String(c.min).slice(0, 10)} → {String(c.max).slice(0, 10)}</p>}
                    {c.histogram && c.histogram.length > 0 && <MiniHistogram rows={c.histogram} integer={c.integer} title={`Distribution of ${c.name}`} />}
                    {c.top_values && <ul className="space-y-1 text-xs">{c.top_values.slice(0, 5).map((t) => <li key={t.value} className="flex items-center gap-2"><span className="w-24 truncate" title={t.value}>{t.value}</span><span className="h-1.5 flex-1 rounded bg-slate-100 dark:bg-white/10"><span className="block h-full rounded bg-brand-500" style={{ width: `${t.pct}%` }} /></span><span className="w-10 text-right tabular-nums text-slate-500">{t.pct}%</span></li>)}</ul>}
                  </div>
                </Card>))}
            </div>
          )}
          {tab === "quality" && q && (
            <div className="space-y-5">
              <div className="grid gap-4 sm:grid-cols-5">
                <Card className="sm:col-span-1"><p className="text-sm text-slate-500">Quality score</p><p className={`text-4xl font-semibold tabular-nums ${scoreColor(q.score)}`}>{q.score}</p><p className="text-xs text-slate-500">Grade {q.grade}</p></Card>
                {Object.entries(q.dimensions).map(([k, v]) => <Card key={k}><p className="text-sm capitalize text-slate-500">{k}</p><p className="text-2xl font-semibold tabular-nums">{v}%</p><span className="mt-2 block h-1.5 rounded bg-slate-100 dark:bg-white/10"><span className="block h-full rounded bg-brand-500" style={{ width: `${v}%` }} /></span></Card>)}
              </div>
              <Card title="Issues" action={<button className="btn-primary py-1.5" disabled={clean.isPending} onClick={() => clean.mutate({ op: "auto_clean" })}>{clean.isPending ? <Spinner /> : <Wand2 className="h-4 w-4" />} Auto-clean all</button>}>
                {clean.data && <p className="mb-3 rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300">{clean.data.message} · quality {clean.data.quality_before} → {clean.data.quality_after}</p>}
                <ErrorNote error={clean.error} />
                {q.issues.length === 0 ? <p className="text-sm text-emerald-600">No issues detected 🎉</p> : (
                  <ul className="divide-y divide-slate-100 dark:divide-white/5">{q.issues.map((i, n) => (
                    <li key={n} className="flex items-center gap-3 py-2.5"><SeverityBadge s={i.severity} /><span className="min-w-0 flex-1 text-sm"><b>{i.column ?? "Dataset"}</b> — {i.message}</span>
                      {FIX_OP[i.fix] && <button className="btn-ghost py-1 text-xs" disabled={clean.isPending} onClick={() => clean.mutate({ op: FIX_OP[i.fix], column: i.column })}>{i.fix.replace(/_/g, " ")}</button>}</li>))}</ul>)}
              </Card>
              <DuplicateAnalysis datasetId={id} kind="table" allColumns={p?.column_profiles.map((c) => c.name) ?? []} onChanged={() => setPage(0)} />
              {d.cleaning_log && d.cleaning_log.length > 0 && <Card title="Change log"><ol className="space-y-1 text-sm text-slate-600 dark:text-slate-300">{d.cleaning_log.map((l, i) => <li key={i}>{i + 1}. {l.message}</li>)}</ol></Card>}
            </div>
          )}
        </>
      )}
    </>
  );
}
