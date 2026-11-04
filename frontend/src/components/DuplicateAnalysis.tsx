import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ChevronDown, Copy, Download, Eye, Info, Search, SlidersHorizontal, Trash2 } from "lucide-react";
import { Fragment, useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api/client";
import { displayValue, filterGroups, paginate, pctText, rateTone, recordLabel, rowList, sortGroups, type SortKey } from "../lib/duplicates";
import { formatCount } from "../lib/numfmt";
import type { ChartSpec, DupGroup, DupOptions, DupResult } from "../lib/types";
import { ChartRenderer } from "./ChartRenderer";
import { Badge, Card, ErrorNote, Spinner } from "./ui";

const DEFAULTS: DupOptions = { columns: null, blank_as_missing: true, ignore_case_space: false, exclude_id_like: false, limit: 200 };
const PAGE = 15;
const axis = { fontSize: 11, fill: "#94a3b8" };

function GroupRows({ datasetId, group, columns }: { datasetId: number; group: DupGroup; columns: string[] }) {
  const q = useQuery({ queryKey: ["dup-rows", datasetId, group.id, group.row_numbers.join(",")], queryFn: () => api.post<{ columns: string[]; rows: Record<string, any>[] }>(`/datasets/${datasetId}/duplicates/rows`, { row_numbers: group.row_numbers.slice(0, 50) }) });
  if (q.isLoading) return <p className="flex items-center gap-2 p-3 text-sm text-slate-500"><Spinner /> Loading the records…</p>;
  if (q.error || !q.data) return <div className="p-3"><ErrorNote error={q.error} /></div>;
  const cols = q.data.columns;
  const first = q.data.rows[0];
  return (
    <div className="p-3">
      <div className="overflow-auto rounded-lg border border-slate-200 dark:border-white/10" style={{ maxHeight: 280 }}>
        <table className="min-w-full"><thead className="sticky top-0"><tr><th className="th">Row #</th>{cols.map((c) => <th key={c} className={`th ${columns.includes(c) ? "" : "opacity-60"}`}>{c}</th>)}</tr></thead>
          <tbody>{q.data.rows.map((r) => (
            <tr key={r.__row__} className="hover:bg-slate-50 dark:hover:bg-white/5"><td className="td font-semibold tabular-nums text-brand-600">{r.__row__}</td>
              {cols.map((c) => { const differs = first && displayValue(r[c]) !== displayValue(first[c]); return <td key={c} title={differs ? "Differs from the first copy (treated as equal by the current rules)" : undefined} className={`td ${differs ? "bg-amber-50 dark:bg-amber-500/10" : ""} ${r[c] === null || r[c] === "" ? "text-slate-400" : ""}`}>{displayValue(r[c])}</td>; })}</tr>))}</tbody></table>
      </div>
      <p className="mt-2 text-xs text-slate-500">{group.count} copies{group.count > 50 ? " (first 50 shown)" : ""}. Cells shaded amber differ from the first copy but are counted as equal under the current rules (blank/missing, case, spacing).</p>
    </div>
  );
}

export default function DuplicateAnalysis({ datasetId, kind, allColumns = [], onChanged }: { datasetId: number; kind: "table" | "document"; allColumns?: string[]; onChanged?: () => void }) {
  const qc = useQueryClient();
  const isDoc = kind === "document";
  const [opts, setOpts] = useState<DupOptions>({ ...DEFAULTS, ignore_case_space: isDoc });
  const [showOpts, setShowOpts] = useState(false);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<{ key: SortKey; dir: "asc" | "desc" }>({ key: "count", dir: "desc" });
  const [page, setPage] = useState(0);
  const [open, setOpen] = useState<number | null>(null);
  useEffect(() => { setPage(0); setOpen(null); }, [query, sort, JSON.stringify(opts)]);

  const res = useQuery({ queryKey: ["duplicates", datasetId, JSON.stringify(opts)], queryFn: () => api.post<DupResult>(`/datasets/${datasetId}/duplicates`, opts), placeholderData: (prev) => prev });
  // what "remove duplicates" would actually delete (exact rows; blank text is a real value there)
  const exact = useQuery({ queryKey: ["duplicates-exact", datasetId], enabled: !isDoc, staleTime: 0, queryFn: () => api.post<DupResult>(`/datasets/${datasetId}/duplicates`, { ...DEFAULTS, blank_as_missing: false, limit: 1 }) });
  const remove = useMutation({
    mutationFn: () => api.post(`/datasets/${datasetId}/clean`, { op: "drop_duplicates" }),
    onSuccess: () => { ["dataset", "datasets", "duplicates", "duplicates-exact", "overview", "preview"].forEach((k) => qc.invalidateQueries({ queryKey: [k] })); onChanged?.(); },
  });
  const exportFile = useMutation({ mutationFn: (v: { format: "csv" | "xlsx"; scope: "groups" | "rows" }) => api.download(`/datasets/${datasetId}/duplicates/export`, `duplicates.${v.format}`, { ...opts, ...v }) });

  if (res.isLoading) return <Card title="Duplicate analysis"><p className="flex items-center gap-2 text-sm text-slate-500"><Spinner /> Looking for duplicates…</p></Card>;
  if (res.error && !res.data) return <Card title="Duplicate analysis"><ErrorNote error={res.error} /></Card>;
  const r = res.data!;
  const unit = r.unit === "paragraphs" ? "paragraphs" : "rows";
  const cols = r.columns_used.slice(0, 5);
  const rows = paginate(sortGroups(filterGroups(r.groups_list, query), sort.key, sort.dir), page, PAGE);
  const tone = rateTone(r.duplicate_pct);
  const toneCls = { green: "text-emerald-600", slate: "text-slate-700 dark:text-slate-200", amber: "text-amber-600", red: "text-red-600" }[tone];
  const maxCount = Math.max(1, ...r.groups_list.map((g) => g.count));
  const pct = (v: number) => (r.rows ? (v / r.rows) * 100 : 0);

  const COLORS = ["#10b981", "#fbbf24", "#ef4444"];   // same meaning as the bar above: unique / first copy / extra copies
  const kept = r.composition.map((c, i) => ({ ...c, color: COLORS[i] })).filter((c) => c.value > 0);
  const composition: ChartSpec = { type: "pie", title: `Unique vs duplicate ${unit}`, x: "label", y: ["value"], data: kept.map(({ label, value }) => ({ label, value })), colors: kept.map((c) => c.color) };
  const dist: ChartSpec = { type: "bar", title: "How often records repeat", x: "label", y: ["Duplicate records", "Extra copies"], data: r.distribution.map((d) => ({ label: d.label, "Duplicate records": d.groups, "Extra copies": d.extra_rows })) };
  const sortBy = (key: SortKey) => setSort((s) => ({ key, dir: s.key === key && s.dir === "desc" ? "asc" : "desc" }));
  const setOpt = (p: Partial<DupOptions>) => setOpts((o) => ({ ...o, ...p }));
  const customCols = opts.columns !== null;
  const nonDefault = !isDoc && (customCols || !opts.blank_as_missing || opts.ignore_case_space || opts.exclude_id_like);

  return (
    <Card title={<span className="flex items-center gap-2"><Copy className="h-4 w-4 text-brand-500" /> Duplicate analysis</span>}
      action={<div className="flex flex-wrap items-center gap-2">
        {res.isFetching && <Spinner className="text-brand-600" />}
        {!isDoc && <button className="btn-ghost !py-1 text-xs" onClick={() => setShowOpts(!showOpts)} aria-expanded={showOpts}><SlidersHorizontal className="h-3.5 w-3.5" /> Options{nonDefault && <span className="h-1.5 w-1.5 rounded-full bg-brand-500" />}</button>}
        <button className="btn-ghost !py-1 text-xs" disabled={exportFile.isPending || !r.duplicate_rows} onClick={() => exportFile.mutate({ format: "csv", scope: "groups" })}><Download className="h-3.5 w-3.5" /> Groups CSV</button>
        <button className="btn-ghost !py-1 text-xs" disabled={exportFile.isPending || !r.duplicate_rows} onClick={() => exportFile.mutate({ format: "csv", scope: "rows" })}><Download className="h-3.5 w-3.5" /> All rows CSV</button>
        <button className="btn-primary !py-1 text-xs" disabled={exportFile.isPending || !r.duplicate_rows} onClick={() => exportFile.mutate({ format: "xlsx", scope: "rows" })}>{exportFile.isPending ? <Spinner /> : <Download className="h-3.5 w-3.5" />} Excel</button>
      </div>}>
      <ErrorNote error={exportFile.error || remove.error || res.error} />

      {showOpts && !isDoc && (
        <div className="mb-5 space-y-4 rounded-xl border border-slate-200 p-4 dark:border-white/10">
          <div>
            <p className="label">Compare records using</p>
            <div className="flex gap-2 text-sm">
              <button className={!customCols ? "btn-primary !py-1" : "btn-ghost !py-1"} onClick={() => setOpt({ columns: null })}>All columns</button>
              <button className={customCols ? "btn-primary !py-1" : "btn-ghost !py-1"} onClick={() => setOpt({ columns: opts.columns ?? allColumns.slice(0, 2), exclude_id_like: false })}>Choose columns</button>
            </div>
            {customCols && <div className="mt-2 flex max-h-28 flex-wrap gap-1.5 overflow-y-auto">{allColumns.map((c) => { const on = opts.columns!.includes(c); return <button key={c} aria-pressed={on} onClick={() => { const next = on ? opts.columns!.filter((x) => x !== c) : [...opts.columns!, c]; if (next.length) setOpt({ columns: next }); }} className={`rounded-full border px-2.5 py-0.5 text-xs ${on ? "border-brand-600 bg-brand-600 text-white" : "border-slate-300 dark:border-white/15"}`}>{c}</button>; })}</div>}
          </div>
          <div className="grid gap-3 text-sm md:grid-cols-3">
            <label className="flex items-start gap-2"><input type="checkbox" className="mt-1 accent-brand-600" checked={opts.blank_as_missing} onChange={(e) => setOpt({ blank_as_missing: e.target.checked })} /><span>Treat blank text as missing<span className="block text-xs text-slate-500">Empty and spaces-only values match missing values.</span></span></label>
            <label className="flex items-start gap-2"><input type="checkbox" className="mt-1 accent-brand-600" checked={opts.ignore_case_space} onChange={(e) => setOpt({ ignore_case_space: e.target.checked })} /><span>Ignore case and extra spaces<span className="block text-xs text-slate-500">“Ann”, “ann ” and “ANN” count as the same.</span></span></label>
            <label className={`flex items-start gap-2 ${customCols ? "opacity-50" : ""}`}><input type="checkbox" className="mt-1 accent-brand-600" disabled={customCols} checked={opts.exclude_id_like} onChange={(e) => setOpt({ exclude_id_like: e.target.checked })} /><span>Ignore ID-like columns<span className="block text-xs text-slate-500">Finds rows that differ only by an auto-number.</span></span></label>
          </div>
          <button className="text-xs text-brand-600 hover:underline" onClick={() => setOpts({ ...DEFAULTS })}>Reset to defaults</button>
        </div>)}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <div className="rounded-lg bg-slate-50 px-3 py-3 dark:bg-white/5"><p className="text-xs text-slate-500">Total {unit}</p><p className="text-2xl font-semibold tabular-nums">{formatCount(r.rows)}</p></div>
        <div className="rounded-lg bg-slate-50 px-3 py-3 dark:bg-white/5"><p className="text-xs text-slate-500">Duplicate {unit} <span title="Extra copies: what removing duplicates (keeping the first) would delete">ⓘ</span></p><p className={`text-2xl font-semibold tabular-nums ${toneCls}`}>{formatCount(r.duplicate_rows)}</p></div>
        <div className="rounded-lg bg-slate-50 px-3 py-3 dark:bg-white/5"><p className="text-xs text-slate-500">Duplicate rate</p><p className={`text-2xl font-semibold tabular-nums ${toneCls}`}>{pctText(r.duplicate_pct)}</p></div>
        <div className="rounded-lg bg-slate-50 px-3 py-3 dark:bg-white/5"><p className="text-xs text-slate-500">Duplicate groups</p><p className="text-2xl font-semibold tabular-nums">{formatCount(r.groups)}</p><p className="text-xs text-slate-500">largest repeats {formatCount(r.largest_group)}×</p></div>
        <div className="rounded-lg bg-slate-50 px-3 py-3 dark:bg-white/5"><p className="text-xs text-slate-500">{unit === "rows" ? "Rows" : "Paragraphs"} involved</p><p className="text-2xl font-semibold tabular-nums">{formatCount(r.rows_involved)}</p><p className="text-xs text-slate-500">{pctText(r.rows_involved_pct)} of all {unit}</p></div>
      </div>
      <div className="mt-3" aria-label="Share of unique, kept and redundant rows">
        <div className="flex h-2.5 overflow-hidden rounded-full bg-slate-100 dark:bg-white/10" role="img" aria-label={`${pctText(r.duplicate_pct)} of ${unit} are redundant copies`}>
          <span style={{ width: `${pct(r.unique_rows)}%` }} className="bg-emerald-500" title={`Unique ${unit}: ${formatCount(r.unique_rows)}`} />
          <span style={{ width: `${pct(r.groups)}%` }} className="bg-amber-400" title={`First copies kept: ${formatCount(r.groups)}`} />
          <span style={{ width: `${pct(r.duplicate_rows)}%` }} className="bg-red-500" title={`Extra copies: ${formatCount(r.duplicate_rows)}`} />
        </div>
        <p className="mt-1 flex flex-wrap gap-x-4 text-xs text-slate-500"><span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-emerald-500" />Unique</span><span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-amber-400" />First copy of a duplicate</span><span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-red-500" />Extra copies</span></p>
      </div>
      <p className="mt-3 flex items-start gap-2 text-xs text-slate-500"><Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        {isDoc ? "Repeated paragraphs (20+ characters), compared ignoring case and spacing." : <>Compared on {r.all_columns ? "all columns" : <b>{r.columns_used.join(", ")}</b>}. Missing values match each other{r.options.blank_as_missing ? `; blank text is treated as missing${r.blank_cells_treated_as_missing ? ` (${formatCount(r.blank_cells_treated_as_missing)} blank cells)` : ""}` : "; blank text is a value"}{r.options.ignore_case_space ? "; case and extra spaces are ignored" : "; text must match exactly"}.</>}</p>

      {r.hint && (
        <div className="mt-4 flex flex-wrap items-center gap-3 rounded-lg bg-sky-50 px-3 py-2.5 text-sm text-sky-900 dark:bg-sky-500/10 dark:text-sky-200"><Info className="h-4 w-4 shrink-0" /><span className="flex-1">{r.hint.message}</span>
          <button className="btn-ghost !py-1 text-xs" onClick={() => { setShowOpts(true); setOpt({ exclude_id_like: true }); }}>Ignore ID columns</button></div>)}

      {r.duplicate_rows === 0 ? (
        <div className="mt-5 flex items-center gap-3 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-5 text-emerald-800 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-200">
          <CheckCircle2 className="h-6 w-6 shrink-0" /><div><p className="font-semibold">No duplicates found</p><p className="text-sm opacity-90">Every one of the {formatCount(r.rows)} {unit} is unique under the current rules.</p></div></div>
      ) : (
        <>
          <div className="mt-5 grid gap-5 lg:grid-cols-3">
            <div className="rounded-xl border border-slate-200 p-4 dark:border-white/10"><ChartRenderer spec={composition} height={230} /></div>
            <div className="rounded-xl border border-slate-200 p-4 dark:border-white/10"><ChartRenderer spec={dist} height={230} /></div>
            <div className="rounded-xl border border-slate-200 p-4 dark:border-white/10">
              <p className="mb-2 text-sm font-medium text-slate-700 dark:text-slate-200">Most duplicated records <span className="text-xs font-normal text-slate-400">(click a bar to inspect)</span></p>
              <ResponsiveContainer width="100%" height={230}>
                <BarChart data={r.top} layout="vertical" margin={{ left: 4, right: 12 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f033" horizontal={false} />
                  <XAxis type="number" tick={axis} allowDecimals={false} tickFormatter={(v) => formatCount(v)} />
                  <YAxis type="category" dataKey="label" width={120} tick={axis} tickFormatter={(v: string) => (v.length > 22 ? v.slice(0, 21) + "…" : v)} />
                  <Tooltip cursor={{ fill: "rgba(146,98,58,.08)" }} content={({ active, payload }) => active && payload?.length ? <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs shadow-pop dark:border-white/10 dark:bg-ink-900"><p className="font-semibold">{(payload[0].payload as any).label}</p><p>Appears <b>{formatCount((payload[0].payload as any).count)}×</b> · {formatCount((payload[0].payload as any).count - 1)} extra</p></div> : null} />
                  <Bar dataKey="count" radius={[0, 4, 4, 0]} cursor="pointer" onClick={(d: any) => { const idx = r.groups_list.findIndex((g) => g.id === d.id); if (idx >= 0) { setQuery(""); setSort({ key: "count", dir: "desc" }); setPage(Math.floor(idx / PAGE)); setOpen(d.id); } }}>
                    {r.top.map((t, i) => <Cell key={t.id} fill={open === t.id ? "#ef4444" : i === 0 ? "rgb(var(--brand-600))" : "rgb(var(--brand-400))"} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="mt-6">
            <div className="mb-3 flex flex-wrap items-center gap-3">
              <h3 className="text-sm font-semibold">Duplicate {isDoc ? "paragraphs" : "records"} <span className="font-normal text-slate-500">· {formatCount(r.groups)} group{r.groups === 1 ? "" : "s"}{r.groups > r.groups_returned ? `, top ${formatCount(r.groups_returned)} listed (exports include the same)` : ""}</span></h3>
              <div className="relative ml-auto w-full sm:w-64"><Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-slate-400" /><input className="input !pl-8" placeholder="Search values or row number…" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search duplicates" /></div>
            </div>
            <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-white/10">
              <table className="min-w-full">
                <thead><tr><th className="th w-10">#</th>{cols.map((c) => <th key={c} className="th">{c}</th>)}{r.columns_used.length > cols.length && <th className="th text-slate-400">+{r.columns_used.length - cols.length} more</th>}
                  <th className="th cursor-pointer select-none text-right" onClick={() => sortBy("count")} aria-sort={sort.key === "count" ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}>Occurrences {sort.key === "count" ? (sort.dir === "desc" ? "↓" : "↑") : ""}</th>
                  <th className="th text-right">Extra copies</th>
                  <th className="th cursor-pointer select-none" onClick={() => sortBy("first_row")}>Found at {isDoc ? "paragraph" : "row"} {sort.key === "first_row" ? (sort.dir === "desc" ? "↓" : "↑") : ""}</th><th className="th" /></tr></thead>
                <tbody>
                  {rows.items.length === 0 && <tr><td className="td py-6 text-center text-slate-500" colSpan={cols.length + 6}>No duplicate matches “{query}”.</td></tr>}
                  {rows.items.map((g) => (
                    <Fragment key={g.id}>
                      <tr className={`hover:bg-slate-50 dark:hover:bg-white/5 ${open === g.id ? "bg-brand-50/50 dark:bg-brand-500/5" : ""}`}>
                        <td className="td text-slate-400">{g.id}</td>
                        {cols.map((c) => <td key={c} className={`td max-w-[220px] truncate ${g.values[c] === null || g.values[c] === "" ? "text-slate-400" : ""}`} title={displayValue(g.values[c])}>{displayValue(g.values[c])}</td>)}
                        {r.columns_used.length > cols.length && <td className="td text-slate-400" title={recordLabel(Object.fromEntries(Object.entries(g.values).slice(cols.length)), 8, 40)}>…</td>}
                        <td className="td text-right"><span className="mr-2 inline-block h-1.5 w-14 rounded bg-slate-100 align-middle dark:bg-white/10"><span className="block h-full rounded bg-red-500" style={{ width: `${(g.count / maxCount) * 100}%` }} /></span><b className="tabular-nums">{formatCount(g.count)}×</b></td>
                        <td className="td text-right tabular-nums">{formatCount(g.extra)}</td>
                        <td className="td text-xs text-slate-500" title={`All: ${g.row_numbers.join(", ")}`}>{rowList(g.row_numbers, g.count)}</td>
                        <td className="td text-right"><button className="btn-ghost !py-1 text-xs" aria-expanded={open === g.id} onClick={() => setOpen(open === g.id ? null : g.id)}><Eye className="h-3.5 w-3.5" /> Inspect <ChevronDown className={`h-3 w-3 transition ${open === g.id ? "rotate-180" : ""}`} /></button></td>
                      </tr>
                      {open === g.id && <tr><td colSpan={cols.length + 6} className="bg-slate-50/60 p-0 dark:bg-white/[.03]"><GroupRows datasetId={datasetId} group={g} columns={r.columns_used} /></td></tr>}
                    </Fragment>))}
                </tbody>
              </table>
            </div>
            <div className="mt-2 flex items-center justify-between text-sm"><span className="text-slate-500">Page {rows.page + 1} of {rows.pages}</span>
              <span className="flex gap-2"><button className="btn-ghost !py-1" disabled={rows.page === 0} onClick={() => setPage(rows.page - 1)}>Previous</button><button className="btn-ghost !py-1" disabled={rows.page + 1 >= rows.pages} onClick={() => setPage(rows.page + 1)}>Next</button></span></div>
          </div>

          {!isDoc && (exact.data?.duplicate_rows ?? 0) > 0 && (
            <div className="mt-5 flex flex-wrap items-center gap-3 rounded-lg border border-slate-200 px-4 py-3 text-sm dark:border-white/10">
              <Trash2 className="h-4 w-4 text-slate-400" /><span className="flex-1">Remove the {formatCount(exact.data!.duplicate_rows)} exact duplicate row{exact.data!.duplicate_rows === 1 ? "" : "s"} and keep the first copy of each. <Badge tone="amber">cannot be undone</Badge></span>
              <button className="btn-danger !py-1.5" disabled={remove.isPending} onClick={() => confirm(`Delete ${formatCount(exact.data!.duplicate_rows)} duplicate row(s)? The first copy of each record is kept.`) && remove.mutate()}>{remove.isPending ? <Spinner /> : <Trash2 className="h-4 w-4" />} Remove duplicates</button>
            </div>)}
        </>)}
    </Card>
  );
}
