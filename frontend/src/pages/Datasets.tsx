import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Database, FileText, Link2, Table2, Trash2, UploadCloud, Wand2 } from "lucide-react";
import { useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useDatasets } from "../components/DatasetPicker";
import { Badge, Card, Empty, ErrorNote, Loading, PageHeader, Spinner } from "../components/ui";
import { ago, bytes, scoreColor } from "../lib/format";
import type { Dataset } from "../lib/types";

const ACCEPT = ".csv,.tsv,.xlsx,.xls,.json,.jsonl,.parquet,.sqlite,.db,.pdf,.docx,.txt,.md";

function UploadZone() {
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);
  const up = useMutation({
    mutationFn: async (files: File[]) => { for (const f of files) await api.upload<Dataset>("/datasets", f); },
    onSettled: () => { qc.invalidateQueries({ queryKey: ["datasets"] }); qc.invalidateQueries({ queryKey: ["overview"] }); },
  });
  const pick = (fl: FileList | null) => fl?.length && up.mutate(Array.from(fl));
  return (
    <div>
      <div onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)} onDrop={(e) => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files); }}
        onClick={() => input.current?.click()} role="button" tabIndex={0} onKeyDown={(e) => e.key === "Enter" && input.current?.click()}
        className={`flex cursor-pointer flex-col items-center rounded-xl border-2 border-dashed px-6 py-10 text-center transition ${drag ? "border-brand-500 bg-brand-50 dark:bg-brand-500/10" : "border-slate-300 hover:border-brand-400 dark:border-white/15"}`}>
        {up.isPending ? <Spinner className="h-7 w-7 text-brand-600" /> : <UploadCloud className="h-7 w-7 text-brand-600" />}
        <p className="mt-3 font-medium">{up.isPending ? "Ingesting, profiling and checking quality…" : "Drop files here or click to browse"}</p>
        <p className="mt-1 text-xs text-slate-500">CSV · TSV · Excel · JSON · Parquet · SQLite · PDF · DOCX · TXT · Markdown</p>
        <input ref={input} type="file" multiple accept={ACCEPT} hidden onChange={(e) => { pick(e.target.files); e.target.value = ""; }} />
      </div>
      <div className="mt-3"><ErrorNote error={up.error} /></div>
    </div>
  );
}

function SqlConnect() {
  const qc = useQueryClient();
  const [f, setF] = useState({ name: "", url: "", table: "", query: "" });
  const m = useMutation({
    mutationFn: () => api.post<Dataset>("/datasets/from-sql", { name: f.name, url: f.url, table: f.table || null, query: f.query || null }),
    onSuccess: () => { setF({ name: "", url: "", table: "", query: "" }); qc.invalidateQueries({ queryKey: ["datasets"] }); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); m.mutate(); };
  return (
    <form onSubmit={submit} className="space-y-3">
      <p className="text-sm text-slate-500">Import a table or the result of a read-only SELECT from an external SQL database. Data is copied into the analytics store.</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <div><label className="label">Name</label><input required className="input" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="warehouse_orders" /></div>
        <div><label className="label">Table</label><input className="input" value={f.table} onChange={(e) => setF({ ...f, table: e.target.value })} placeholder="public.orders" /></div>
      </div>
      <div><label className="label">Connection URL</label><input required className="input font-mono text-xs" value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} placeholder="postgresql+psycopg://user:password@host:5432/db" /></div>
      <div><label className="label">…or SELECT query</label><textarea className="input font-mono text-xs" rows={2} value={f.query} onChange={(e) => setF({ ...f, query: e.target.value })} placeholder="SELECT * FROM orders WHERE created_at > '2024-01-01'" /></div>
      <ErrorNote error={m.error} />
      <button className="btn-primary" disabled={m.isPending || (!f.table && !f.query)}>{m.isPending ? <Spinner /> : <Link2 className="h-4 w-4" />} Import</button>
    </form>
  );
}

export default function DatasetsPage() {
  const qc = useQueryClient();
  const { data = [], isLoading, error } = useDatasets();
  const [tab, setTab] = useState<"upload" | "sql">("upload");
  const del = useMutation({ mutationFn: (id: number) => api.del(`/datasets/${id}`), onSuccess: () => { qc.invalidateQueries({ queryKey: ["datasets"] }); qc.invalidateQueries({ queryKey: ["overview"] }); } });
  const sample = useMutation({ mutationFn: () => api.post<Dataset>("/datasets/load-sample"), onSuccess: () => qc.invalidateQueries({ queryKey: ["datasets"] }) });

  return (
    <>
      <PageHeader title="Data sources" subtitle="Upload files, connect databases, and manage everything the agents can analyze." />
      <Card className="mb-6">
        <div className="mb-4 flex gap-2">
          {([["upload", "Upload files", UploadCloud], ["sql", "SQL database", Database]] as const).map(([id, label, I]) => (
            <button key={id} onClick={() => setTab(id)} className={tab === id ? "btn-primary" : "btn-ghost"}><I className="h-4 w-4" /> {label}</button>))}
        </div>
        {tab === "upload" ? <UploadZone /> : <SqlConnect />}
      </Card>
      {isLoading ? <Loading /> : error ? <ErrorNote error={error} /> : data.length === 0 ? (
        <Empty icon={Table2} title="No data yet" text="Upload a file above, or try the bundled demo sales dataset (1,200 orders with realistic quality issues)." action={<><button className="btn-primary" onClick={() => sample.mutate()} disabled={sample.isPending}>{sample.isPending && <Spinner />} Load demo dataset</button><div className="mt-3"><ErrorNote error={sample.error} /></div></>} />
      ) : (
        <Card pad={false}>
          <div className="overflow-x-auto">
            <table className="min-w-full">
              <thead><tr>{["Name", "Type", "Size", "Quality", "Added", ""].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
              <tbody>{data.map((d) => (
                <tr key={d.id} className="hover:bg-slate-50 dark:hover:bg-white/5">
                  <td className="td"><Link to={`/datasets/${d.id}`} className="flex items-center gap-2 font-medium text-slate-900 hover:text-brand-600 dark:text-white">{d.kind === "table" ? <Table2 className="h-4 w-4 text-brand-500" /> : <FileText className="h-4 w-4 text-amber-500" />}{d.name}</Link>
                    <span className="ml-6 text-xs text-slate-500">{d.kind === "table" ? `${d.row_count.toLocaleString()} rows × ${d.column_count} cols · SQL: ${d.table_name}` : `${d.row_count} paragraphs`}</span></td>
                  <td className="td"><Badge>{d.source_type}</Badge></td>
                  <td className="td tabular-nums">{bytes(d.size_bytes)}</td>
                  <td className={`td font-semibold tabular-nums ${scoreColor(d.quality_score)}`}>{d.quality_score ?? "—"}</td>
                  <td className="td text-slate-500">{ago(d.created_at)}</td>
                  <td className="td whitespace-nowrap text-right">{d.kind === "table" && <Link to={`/workspace?dataset=${d.id}&auto=1`} className="mr-2 inline-flex items-center gap-1 rounded-lg bg-brand-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-brand-700"><Wand2 className="h-3.5 w-3.5" /> Analyse my data</Link>}<button className="rounded p-1.5 text-slate-400 hover:bg-red-50 hover:text-red-600" aria-label={`Delete ${d.name}`} onClick={() => confirm(`Delete "${d.name}"? This cannot be undone.`) && del.mutate(d.id)}><Trash2 className="h-4 w-4" /></button></td>
                </tr>))}</tbody>
            </table>
          </div>
        </Card>
      )}
    </>
  );
}
