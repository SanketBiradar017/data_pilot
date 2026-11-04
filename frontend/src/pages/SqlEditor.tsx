import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bookmark, ChevronRight, Play, Table2, Trash2, Wand2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { ChartRenderer } from "../components/ChartRenderer";
import { Card, DataTable, ErrorNote, PageHeader, Spinner } from "../components/ui";
import type { QueryResult, SchemaTable } from "../lib/types";

interface Saved { id: number; name: string; sql: string }

export default function SqlEditor() {
  const qc = useQueryClient();
  const schema = useQuery({ queryKey: ["sql-schema"], staleTime: 0, queryFn: () => api.get<SchemaTable[]>("/sql/schema") });
  const saved = useQuery({ queryKey: ["saved-queries"], queryFn: () => api.get<Saved[]>("/sql/saved") });
  const [sql, setSql] = useState("");
  const [nl, setNl] = useState("");
  const area = useRef<HTMLTextAreaElement>(null);
  const [view, setView] = useState<"table" | "chart">("table");
  useEffect(() => { if (!sql && schema.data?.[0]) setSql(`SELECT *\nFROM ${schema.data[0].table}\nLIMIT 100`); }, [schema.data, sql]);

  /** Insert text at the caret (replacing any selection) instead of appending. */
  const insert = (text: string) => {
    const el = area.current;
    const a = el?.selectionStart ?? sql.length, b = el?.selectionEnd ?? sql.length;
    setSql(sql.slice(0, a) + text + sql.slice(b));
    requestAnimationFrame(() => { el?.focus(); el?.setSelectionRange(a + text.length, a + text.length); });
  };
  const run = useMutation({ mutationFn: () => api.post<QueryResult>("/sql/query", { sql, max_rows: 1000 }), onSuccess: (r) => setView(r.chart ? "chart" : "table") });
  const gen = useMutation({
    mutationFn: () => api.post<{ sql: string; rationale: string }>("/sql/generate", { question: nl, dataset_id: schema.data![0].dataset_id }),
    onSuccess: (r) => setSql(r.sql),
  });
  const save = useMutation({ mutationFn: (name: string) => api.post("/sql/saved", { name, sql }), onSuccess: () => qc.invalidateQueries({ queryKey: ["saved-queries"] }) });
  const del = useMutation({ mutationFn: (id: number) => api.del(`/sql/saved/${id}`), onSuccess: () => qc.invalidateQueries({ queryKey: ["saved-queries"] }) });
  const r = run.data;
  const empty = schema.data && schema.data.length === 0;

  return (
    <>
      <PageHeader title="SQL editor" subtitle="Read-only DuckDB SQL across all your tabular data sources. Joins between sources work." />
      {empty && <ErrorNote error={new Error("No tabular data sources yet — upload a dataset first.")} />}
      <div className="grid gap-6 lg:grid-cols-[260px_1fr]">
        <div className="space-y-4">
          <Card title="Tables" pad={false}>
            <ul className="max-h-80 divide-y divide-slate-100 overflow-y-auto dark:divide-white/5">{(schema.data ?? []).map((t) => (
              <li key={t.table}><details className="group"><summary className="flex cursor-pointer items-center gap-2 px-4 py-2 text-sm font-medium"><ChevronRight className="h-3.5 w-3.5 transition group-open:rotate-90" /><Table2 className="h-3.5 w-3.5 text-brand-500" />{t.table}<span role="button" tabIndex={0} title="Insert table name" className="ml-auto rounded px-1 text-xs text-brand-600 hover:bg-brand-50" onClick={(e) => { e.preventDefault(); insert(t.table); }}>insert</span></summary>
                <ul className="pb-2 pl-11 pr-3 text-xs">{t.columns.map((c) => <li key={c.name}><button className="flex w-full justify-between py-0.5 text-slate-600 hover:text-brand-600 dark:text-slate-300" onClick={() => insert(`"${c.name}"`)}><span>{c.name}</span><span className="text-slate-400">{c.dtype}</span></button></li>)}</ul></details></li>))}</ul>
          </Card>
          <Card title="Saved queries" pad={false}>
            {(saved.data ?? []).length === 0 ? <p className="p-4 text-xs text-slate-500">None yet.</p> : <ul className="divide-y divide-slate-100 dark:divide-white/5">{saved.data!.map((s) => (
              <li key={s.id} className="group flex items-center"><button className="min-w-0 flex-1 truncate px-4 py-2 text-left text-sm hover:text-brand-600" onClick={() => setSql(s.sql)}>{s.name}</button><button className="p-2 text-slate-400 opacity-0 hover:text-red-600 group-hover:opacity-100" aria-label="Delete saved query" onClick={() => del.mutate(s.id)}><Trash2 className="h-3.5 w-3.5" /></button></li>))}</ul>}
          </Card>
        </div>
        <div className="min-w-0 space-y-4">
          <Card>
            <div className="mb-3 flex gap-2"><input className="input" placeholder="Describe a query in plain English… e.g. average revenue by category" value={nl} onChange={(e) => setNl(e.target.value)} onKeyDown={(e) => e.key === "Enter" && nl && schema.data?.length && gen.mutate()} />
              <button className="btn-ghost shrink-0" disabled={!nl || !schema.data?.length || gen.isPending} onClick={() => gen.mutate()}>{gen.isPending ? <Spinner /> : <Wand2 className="h-4 w-4" />} Generate SQL</button></div>
            {gen.data && <p className="mb-2 text-xs text-slate-500">{gen.data.rationale}</p>}
            <textarea ref={area} className="input h-44 font-mono text-[13px] leading-relaxed" spellCheck={false} value={sql} onChange={(e) => setSql(e.target.value)} onKeyDown={(e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") run.mutate(); }} aria-label="SQL" />
            <div className="mt-3 flex items-center gap-2">
              <button className="btn-primary" disabled={run.isPending || !sql.trim() || empty} onClick={() => run.mutate()}>{run.isPending ? <Spinner /> : <Play className="h-4 w-4" />} Run <kbd className="ml-1 rounded bg-white/20 px-1 text-[10px]">Ctrl ↵</kbd></button>
              <button className="btn-ghost" disabled={!sql.trim()} onClick={() => { const n = prompt("Name this query"); if (n) save.mutate(n); }}><Bookmark className="h-4 w-4" /> Save</button>
              {r && <span className="ml-auto text-xs text-slate-500">{r.row_count.toLocaleString()} rows{r.truncated ? " (truncated)" : ""} · {r.elapsed_ms} ms</span>}
            </div>
          </Card>
          <ErrorNote error={run.error || save.error || gen.error} />
          {r && (
            <Card title="Result" action={r.chart && <div className="flex gap-1 text-xs">{(["table", "chart"] as const).map((v) => <button key={v} onClick={() => setView(v)} className={`rounded px-2 py-1 capitalize ${view === v ? "bg-brand-600 text-white" : "text-slate-500 hover:bg-slate-100 dark:hover:bg-white/10"}`}>{v}</button>)}</div>}>
              {view === "chart" && r.chart ? <ChartRenderer spec={r.chart} height={300} /> : <DataTable columns={r.columns} rows={r.rows} />}
            </Card>
          )}
        </div>
      </div>
    </>
  );
}
