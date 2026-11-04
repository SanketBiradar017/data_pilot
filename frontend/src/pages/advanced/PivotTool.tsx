import { useMutation } from "@tanstack/react-query";
import { BarChart3, Columns3, Download, Filter, GripVertical, Plus, Rows3, Sigma, Table2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../../api/client";
import { ChartRenderer } from "../../components/ChartRenderer";
import { Card, ErrorNote, Spinner } from "../../components/ui";
import { useNumFmt } from "../../lib/numfmt";
import type { FieldMeta, PivotResult } from "../../lib/types";
import { KindIcon } from "./common";

type Zone = "rows" | "columns" | "values" | "filters";
interface Val { column: string; agg: string }
interface Flt { column: string; op: string; value: any }
const AGGS = [["sum", "Sum"], ["count", "Count"], ["avg", "Average"], ["min", "Min"], ["max", "Max"]];
const OPS: Record<string, [string, string][]> = {
  numeric: [["gt", ">"], ["gte", "≥"], ["lt", "<"], ["lte", "≤"], ["eq", "="], ["ne", "≠"], ["between", "between"]],
  datetime: [["gte", "on/after"], ["lte", "on/before"], ["between", "between"]],
  category: [["in", "is any of"], ["not_in", "is none of"], ["eq", "equals"], ["ne", "not equal"], ["contains", "contains"]],
  text: [["contains", "contains"], ["eq", "equals"], ["ne", "not equal"]],
};

function FilterEditor({ f, meta, onChange, onRemove }: { f: Flt; meta?: FieldMeta; onChange: (f: Flt) => void; onRemove: () => void }) {
  const kind = meta?.kind ?? "text";
  const set = (v: any) => onChange({ ...f, value: v });
  const multi = f.op === "in" || f.op === "not_in";
  const input = (v: any, cb: (x: string) => void, ph?: string) => <input className="input !py-1 text-xs" type={kind === "datetime" ? "date" : kind === "numeric" ? "number" : "text"} value={v ?? ""} placeholder={ph} onChange={(e) => cb(e.target.value)} />;
  return (
    <div className="space-y-1.5 rounded-lg border border-slate-200 p-2 dark:border-white/10">
      <div className="flex items-center gap-2 text-xs"><KindIcon kind={kind} /><b className="truncate">{f.column}</b>
        <select className="input !w-auto !py-1 text-xs" value={f.op} onChange={(e) => onChange({ ...f, op: e.target.value, value: e.target.value === "between" ? ["", ""] : e.target.value === "in" || e.target.value === "not_in" ? [] : "" })}>
          {(OPS[kind] ?? OPS.text).map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
        <button className="ml-auto text-slate-400 hover:text-red-600" onClick={onRemove} aria-label={`Remove filter ${f.column}`}><X className="h-3.5 w-3.5" /></button></div>
      {f.op === "between" ? <div className="flex gap-2">{input(f.value?.[0], (x) => set([x, f.value?.[1] ?? ""]), "from")}{input(f.value?.[1], (x) => set([f.value?.[0] ?? "", x]), "to")}</div>
        : multi && meta?.values ? <div className="flex max-h-24 flex-wrap gap-1 overflow-y-auto">{meta.values.map((v) => { const on = (f.value ?? []).includes(v); return <button key={v} onClick={() => set(on ? f.value.filter((x: string) => x !== v) : [...(f.value ?? []), v])} className={`rounded-full border px-2 py-0.5 text-[11px] transition ${on ? "border-brand-600 bg-brand-600 text-white" : "border-slate-300 text-slate-600 dark:border-white/15 dark:text-slate-300"}`}>{v}</button>; })}</div>
          : multi ? input((f.value ?? []).join(","), (x) => set(x.split(",").map((s) => s.trim()).filter(Boolean)), "comma separated")
            : input(f.value, set, "value")}
    </div>
  );
}

export default function PivotTool({ datasetId, fields }: { datasetId: number; fields: FieldMeta[] }) {
  const { fmt } = useNumFmt();
  const [rows, setRows] = useState<string[]>([]);
  const [columns, setColumns] = useState<string[]>([]);
  const [values, setValues] = useState<Val[]>([]);
  const [filters, setFilters] = useState<Flt[]>([]);
  const [totals, setTotals] = useState(true);
  const [view, setView] = useState<"table" | "chart">("table");
  const [over, setOver] = useState<Zone | null>(null);
  const [menu, setMenu] = useState<string | null>(null);
  const meta = (n: string) => fields.find((f) => f.name === n);

  useEffect(() => { setRows([]); setColumns([]); setValues([]); setFilters([]); }, [datasetId]);

  const place = (name: string, zone: Zone) => {
    if (name === "*") { if (zone === "values") setValues((v) => [...v, { column: "*", agg: "count" }]); return; }
    const m = meta(name); if (!m) return;
    if (zone === "rows" || zone === "columns") {
      setRows((r) => r.filter((x) => x !== name)); setColumns((c) => c.filter((x) => x !== name));
      (zone === "rows" ? setRows : setColumns)((l) => [...l, name]);
    } else if (zone === "values") setValues((v) => [...v, { column: name, agg: m.measure ? "sum" : "count" }]);
    else setFilters((f) => [...f, { column: name, op: (OPS[m.kind] ?? OPS.text)[0][0], value: (OPS[m.kind] ?? OPS.text)[0][0] === "in" ? [] : "" }]);
  };

  const body = useMemo(() => ({
    dataset_id: datasetId, rows, columns, values, totals,
    filters: filters.filter((f) => f.value !== "" && !(Array.isArray(f.value) && (f.value.length === 0 || (f.op === "between" && f.value.some((x: string) => x === ""))))),
  }), [datasetId, rows, columns, values, filters, totals]);
  const ready = values.length > 0 && rows.length + columns.length > 0;
  const run = useMutation({ mutationFn: () => api.post<PivotResult>("/advanced/pivot", body) });
  const key = JSON.stringify(body);
  useEffect(() => { if (!ready) return; const t = setTimeout(() => run.mutate(), 450); return () => clearTimeout(t); /* eslint-disable-next-line */ }, [key, ready]);
  const res = ready ? run.data : undefined;

  const exportAs = (format: "csv" | "xlsx") => api.download("/advanced/pivot/export", `pivot.${format}`, { ...body, format }).catch((e) => alert(e.message));
  const zoneCls = (z: Zone) => `min-h-[72px] rounded-xl border-2 border-dashed p-2 transition ${over === z ? "border-brand-500 bg-brand-50 dark:bg-brand-500/10" : "border-slate-300 dark:border-white/15"}`;
  const Drop = ({ zone, title, icon: Icon, children, hint }: { zone: Zone; title: string; icon: typeof Rows3; children: React.ReactNode; hint: string }) => (
    <div onDragOver={(e) => { e.preventDefault(); setOver(zone); }} onDragLeave={() => setOver(null)} onDrop={(e) => { e.preventDefault(); setOver(null); place(e.dataTransfer.getData("text/plain"), zone); }}>
      <p className="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500"><Icon className="h-3.5 w-3.5" /> {title}</p>
      <div className={zoneCls(zone)}>{children}<p className="px-1 text-[11px] text-slate-400 empty:hidden">{hint}</p></div>
    </div>
  );
  const chip = (n: string, onRemove: () => void) => (
    <span key={n} className="mb-1 mr-1 inline-flex items-center gap-1 rounded-full bg-brand-100 px-2.5 py-1 text-xs font-medium text-brand-700 dark:bg-brand-500/20 dark:text-brand-200"><KindIcon kind={meta(n)?.kind ?? "text"} />{n}
      <button onClick={onRemove} aria-label={`Remove ${n}`} className="hover:text-red-600"><X className="h-3 w-3" /></button></span>
  );
  const isTotalCol = (c: string) => c === "Total" || c.startsWith("Total ·");

  return (
    <div className="grid gap-5 xl:grid-cols-[250px_1fr]">
      <Card title="Fields" pad={false}>
        <p className="px-4 pt-3 text-xs text-slate-500">Drag fields into the areas on the right, or click a field to choose where it goes.</p>
        <ul className="max-h-[520px] space-y-1 overflow-y-auto p-3">
          {[{ name: "*", kind: "numeric" as const, unique: 0, measure: true }, ...fields].map((f) => (
            <li key={f.name} className="relative">
              <div draggable onDragStart={(e) => { e.dataTransfer.setData("text/plain", f.name); e.dataTransfer.effectAllowed = "move"; }} onClick={() => setMenu(menu === f.name ? null : f.name)}
                className="flex cursor-grab items-center gap-2 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-sm transition hover:border-brand-400 hover:shadow-card active:cursor-grabbing dark:border-white/10 dark:bg-ink-900">
                <GripVertical className="h-3.5 w-3.5 text-slate-300" />{f.name === "*" ? <Sigma className="h-3.5 w-3.5 text-amber-500" /> : <KindIcon kind={f.kind} />}
                <span className="truncate">{f.name === "*" ? "Count of records" : f.name}</span>
                {f.name !== "*" && <span className="ml-auto text-[11px] text-slate-400">{f.unique}</span>}
              </div>
              {menu === f.name && (
                <div className="absolute left-0 right-0 z-10 mt-1 flex flex-wrap gap-1 rounded-lg border border-slate-200 bg-white p-1.5 shadow-pop dark:border-white/10 dark:bg-ink-800">
                  {(f.name === "*" ? (["values"] as Zone[]) : (["rows", "columns", "values", "filters"] as Zone[])).map((z) => <button key={z} className="btn-ghost !px-2 !py-1 text-xs capitalize" onClick={() => { place(f.name, z); setMenu(null); }}>+ {z}</button>)}
                </div>)}
            </li>))}
        </ul>
      </Card>

      <div className="min-w-0 space-y-5">
        <Card>
          <div className="grid gap-4 md:grid-cols-2">
            <Drop zone="rows" title="Rows" icon={Rows3} hint={rows.length ? "" : "Drop fields to group by (e.g. region)"}>{rows.map((r) => chip(r, () => setRows(rows.filter((x) => x !== r))))}</Drop>
            <Drop zone="columns" title="Columns" icon={Columns3} hint={columns.length ? "" : "Optional: spread a field across columns"}>{columns.map((c) => chip(c, () => setColumns(columns.filter((x) => x !== c))))}</Drop>
            <Drop zone="values" title="Values" icon={Sigma} hint={values.length ? "" : "Drop a number field (or Count of records)"}>
              {values.map((v, i) => (
                <div key={i} className="mb-1 flex items-center gap-1.5 rounded-lg bg-emerald-50 px-2 py-1 text-xs dark:bg-emerald-500/10">
                  <select className="rounded border-0 bg-transparent py-0 pr-5 text-xs font-semibold" value={v.agg} onChange={(e) => setValues(values.map((x, k) => (k === i ? { ...x, agg: e.target.value } : x)))} aria-label="Aggregation">
                    {AGGS.filter(([a]) => v.column !== "*" || a === "count").filter(([a]) => meta(v.column)?.measure || v.column === "*" ? true : a === "count" || a === "min" || a === "max").map(([a, l]) => <option key={a} value={a}>{l}</option>)}</select>
                  <span className="truncate">of {v.column === "*" ? "records" : v.column}</span>
                  <button className="ml-auto text-slate-400 hover:text-red-600" onClick={() => setValues(values.filter((_, k) => k !== i))} aria-label="Remove value"><X className="h-3.5 w-3.5" /></button></div>))}
            </Drop>
            <Drop zone="filters" title="Filters" icon={Filter} hint={filters.length ? "" : "Drop a field to filter rows"}>
              <div className="space-y-1.5">{filters.map((f, i) => <FilterEditor key={i} f={f} meta={meta(f.column)} onChange={(nf) => setFilters(filters.map((x, k) => (k === i ? nf : x)))} onRemove={() => setFilters(filters.filter((_, k) => k !== i))} />)}</div>
            </Drop>
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-slate-100 pt-3 dark:border-white/5">
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={totals} onChange={(e) => setTotals(e.target.checked)} className="accent-brand-600" /> Show totals</label>
            <button className="btn-ghost !py-1.5 text-xs" onClick={() => { setRows([]); setColumns([]); setValues([]); setFilters([]); }}><X className="h-3.5 w-3.5" /> Clear</button>
            <span className="ml-auto flex items-center gap-2">{run.isPending && <Spinner className="text-brand-600" />}
              <button className="btn-ghost !py-1.5" disabled={!res} onClick={() => exportAs("csv")}><Download className="h-4 w-4" /> CSV</button>
              <button className="btn-primary !py-1.5" disabled={!res} onClick={() => exportAs("xlsx")}><Download className="h-4 w-4" /> Excel</button></span>
          </div>
        </Card>

        <ErrorNote error={ready ? run.error : null} />
        {!ready && <div className="rounded-xl border border-dashed border-slate-300 p-10 text-center text-sm text-slate-500 dark:border-white/15"><Plus className="mx-auto mb-2 h-6 w-6 text-brand-400" />Add at least one <b>row or column</b> field and one <b>value</b> to build your pivot table.</div>}
        {res && (
          <Card title={<span>{res.row_count.toLocaleString()} rows · {res.source_rows.toLocaleString()} source records</span>}
            action={<div className="flex gap-1 text-xs">{([["table", Table2], ["chart", BarChart3]] as const).map(([v, I]) => <button key={v} onClick={() => setView(v)} className={`flex items-center gap-1 rounded px-2 py-1 capitalize ${view === v ? "bg-brand-600 text-white" : "text-slate-500 hover:bg-slate-100 dark:hover:bg-white/10"}`}><I className="h-3.5 w-3.5" />{v}</button>)}</div>} pad={false}>
            {view === "chart" ? <div className="p-5">{res.chart ? <ChartRenderer spec={res.chart} height={340} /> : <p className="text-sm text-slate-500">Nothing to chart.</p>}</div> : (
              <div className="max-h-[520px] overflow-auto">
                <table className="min-w-full">
                  <thead className="sticky top-0 z-[1]"><tr>{res.columns.map((c, i) => <th key={c} className={`th ${i >= res.row_fields.length ? "text-right" : ""} ${isTotalCol(c) ? "!bg-brand-100 dark:!bg-brand-500/20" : ""}`}>{c}</th>)}</tr></thead>
                  <tbody>{res.rows.map((r, i) => (
                    <tr key={i} className={r.__total__ ? "font-semibold" : "hover:bg-slate-50 dark:hover:bg-white/5"}>
                      {res.columns.map((c, k) => <td key={c} className={`td ${k >= res.row_fields.length ? "text-right tabular-nums" : ""} ${r.__total__ ? "border-t-2 border-t-slate-300 bg-slate-100 dark:bg-white/10" : isTotalCol(c) ? "bg-brand-50 font-semibold dark:bg-brand-500/10" : ""}`}>{k < res.row_fields.length ? (r[c] ?? "") : fmt(r[c])}</td>)}
                    </tr>))}</tbody>
                </table>
              </div>)}
          </Card>)}
      </div>
    </div>
  );
}
