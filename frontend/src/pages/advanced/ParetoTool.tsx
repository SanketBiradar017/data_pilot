import { useMutation } from "@tanstack/react-query";
import { Download, Play } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { ChartRenderer } from "../../components/ChartRenderer";
import { Badge, Card, ErrorNote, Spinner } from "../../components/ui";
import { downloadCsv, useNumFmt } from "../../lib/numfmt";
import type { FieldMeta, ParetoResult } from "../../lib/types";
import { ColumnSelect, Field, Stat2 } from "./common";

const TONE = { A: "green", B: "amber", C: "slate" } as const;

export default function ParetoTool({ datasetId, fields }: { datasetId: number; fields: FieldMeta[] }) {
  const { fmt } = useNumFmt();
  const [category, setCategory] = useState(""); const [value, setValue] = useState("");
  const [a, setA] = useState(80); const [b, setB] = useState(95);
  useEffect(() => { setCategory(""); setValue(""); }, [datasetId]);
  const run = useMutation({ mutationFn: () => api.post<ParetoResult>("/advanced/pareto", { dataset_id: datasetId, category, value: value || null, a_cut: a, b_cut: b }) });
  const r = run.data;
  return (
    <div className="space-y-5">
      <Card title="Configure">
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
          <Field label="Rank which items?" hint="e.g. product, customer, category"><ColumnSelect fields={fields} value={category} onChange={setCategory} kinds={["category", "text"]} /></Field>
          <Field label="By contribution of" hint="Leave empty to count rows"><ColumnSelect fields={fields} value={value} onChange={setValue} kinds={["numeric"]} measureOnly placeholder="Count of rows" /></Field>
          <Field label="Class A up to (cum. %)"><input type="number" className="input" min={1} max={99} value={a} onChange={(e) => setA(Number(e.target.value))} /></Field>
          <Field label="Class B up to (cum. %)"><input type="number" className="input" min={2} max={100} value={b} onChange={(e) => setB(Number(e.target.value))} /></Field>
          <div className="flex items-end"><button className="btn-primary w-full" disabled={!category || run.isPending} onClick={() => run.mutate()}>{run.isPending ? <Spinner /> : <Play className="h-4 w-4" />} Analyse</button></div>
        </div>
      </Card>
      <ErrorNote error={run.error} />
      {r && (
        <>
          <Card><p className="text-[15px] font-medium">{r.interpretation}</p>
            {r.notes.map((n, i) => <p key={i} className="mt-1 text-sm text-amber-700 dark:text-amber-300">⚠ {n}</p>)}
            <div className="mt-4 grid gap-3 sm:grid-cols-3">
              {r.summary.map((s) => (
                <div key={s.class} className="rounded-xl border border-slate-200 p-4 dark:border-white/10"><div className="flex items-center justify-between"><Badge tone={TONE[s.class as "A"]}>Class {s.class}</Badge><span className="text-xs text-slate-500">{s.class === "A" ? `top ${a}%` : s.class === "B" ? `next ${b - a}%` : `last ${(100 - b).toFixed(0)}%`}</span></div>
                  <p className="mt-2 text-2xl font-semibold tabular-nums">{s.items.toLocaleString()} <span className="text-sm font-normal text-slate-500">items ({s.items_pct.toFixed(1)}%)</span></p>
                  <p className="text-sm text-slate-500">{fmt(s.value)} · {s.value_pct.toFixed(1)}% of total</p></div>))}
            </div>
            <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3"><Stat2 label="Total items" value={r.n_items.toLocaleString()} /><Stat2 label="Total" value={fmt(r.total)} sub={r.measure} /><Stat2 label="Items for 80%" value={`${r.items_for_80pct} (${r.items_for_80pct_pct.toFixed(1)}%)`} /></div>
          </Card>
          <Card><ChartRenderer spec={r.chart} height={340} /></Card>
          <Card title="Ranking" action={<button className="btn-ghost !py-1 text-xs" onClick={() => downloadCsv("pareto_abc.csv", ["rank", "category", "value", "share_pct", "cum_pct", "class"], r.rows)}><Download className="h-3.5 w-3.5" /> CSV</button>} pad={false}>
            <div className="max-h-[420px] overflow-auto"><table className="min-w-full"><thead className="sticky top-0"><tr>{["#", r.category, "Value", "Share %", "Cumulative %", "Class"].map((h, i) => <th key={h} className={`th ${i > 1 ? "text-right" : ""}`}>{h}</th>)}</tr></thead>
              <tbody>{r.rows.map((x) => <tr key={x.rank} className="hover:bg-slate-50 dark:hover:bg-white/5"><td className="td text-slate-400">{x.rank}</td><td className="td font-medium">{x.category}</td><td className="td text-right tabular-nums">{fmt(x.value)}</td><td className="td text-right tabular-nums">{x.share_pct.toFixed(2)}</td>
                <td className="td text-right tabular-nums"><span className="mr-2 inline-block h-1.5 w-16 rounded bg-slate-100 align-middle dark:bg-white/10"><span className="block h-full rounded bg-brand-500" style={{ width: `${x.cum_pct}%` }} /></span>{x.cum_pct.toFixed(2)}</td><td className="td text-right"><Badge tone={TONE[x.class]}>{x.class}</Badge></td></tr>)}</tbody></table></div>
          </Card>
        </>)}
    </div>
  );
}
