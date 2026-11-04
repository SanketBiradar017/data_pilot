import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, FileSpreadsheet, FileText, Trash2 } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Card, Empty, ErrorNote, Loading, PageHeader } from "../components/ui";
import { ago, bytes } from "../lib/format";
import type { SavedReport } from "../lib/types";

export default function Reports() {
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery({ queryKey: ["reports"], staleTime: 0, queryFn: () => api.get<SavedReport[]>("/reports") });
  const del = useMutation({ mutationFn: (id: number) => api.del(`/reports/${id}`), onSuccess: () => qc.invalidateQueries({ queryKey: ["reports"] }) });
  const dl = useMutation({ mutationFn: (r: SavedReport) => api.download(`/reports/${r.id}/download`, `report.${r.format}`) });
  return (
    <>
      <PageHeader title="Reports" subtitle="Exported PDF and Excel reports generated from completed analyses." />
      {isLoading ? <Loading /> : error ? <ErrorNote error={error} /> : !data?.length ? (
        <Empty icon={FileText} title="No reports yet" text="Run an analysis, then export it as PDF or Excel from the results page." action={<Link to="/workspace" className="btn-primary">Run an analysis</Link>} />
      ) : (
        <Card pad={false}>
          <ul className="divide-y divide-slate-100 dark:divide-white/5">{data.map((r) => (
            <li key={r.id} className="flex items-center gap-4 px-5 py-4">
              <span className={`rounded-lg p-2.5 ${r.format === "pdf" ? "bg-red-50 text-red-600 dark:bg-red-500/15" : "bg-emerald-50 text-emerald-600 dark:bg-emerald-500/15"}`}>{r.format === "pdf" ? <FileText className="h-5 w-5" /> : <FileSpreadsheet className="h-5 w-5" />}</span>
              <div className="min-w-0 flex-1"><p className="truncate font-medium">{r.title}</p><p className="text-xs text-slate-500">{r.format.toUpperCase()} · {bytes(r.size_bytes)} · {ago(r.created_at)}{r.analysis_id && <> · <Link className="text-brand-600 hover:underline" to={`/history/${r.analysis_id}`}>source analysis</Link></>}</p></div>
              <button className="btn-ghost" onClick={() => dl.mutate(r)}><Download className="h-4 w-4" /> Download</button>
              <button className="rounded p-2 text-slate-400 hover:bg-red-50 hover:text-red-600" aria-label="Delete report" onClick={() => confirm("Delete this report?") && del.mutate(r.id)}><Trash2 className="h-4 w-4" /></button>
            </li>))}</ul>
          <div className="px-5 pb-3"><ErrorNote error={dl.error || del.error} /></div>
        </Card>
      )}
    </>
  );
}
