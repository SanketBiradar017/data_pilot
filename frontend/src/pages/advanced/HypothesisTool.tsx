import { useMutation } from "@tanstack/react-query";
import { CheckCircle2, MinusCircle, Play } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { ChartRenderer } from "../../components/ChartRenderer";
import { Badge, Card, ErrorNote, Spinner } from "../../components/ui";
import type { FieldMeta, HypothesisResult } from "../../lib/types";
import { ColumnSelect, Field, Stat2, n4, p } from "./common";

const TESTS = [
  { id: "t_independent", name: "Independent t-test", text: "Compare the average of one number between two groups (equal variances)." },
  { id: "t_welch", name: "Welch t-test", text: "Like the t-test but safe when group variances or sizes differ. Usually the best default." },
  { id: "t_paired", name: "Paired t-test", text: "Compare two measurements on the same rows (before vs after)." },
  { id: "anova", name: "ANOVA", text: "Compare the average of one number across three or more groups." },
  { id: "chi_square", name: "Chi-square", text: "Test whether two categorical fields are related." },
] as const;

export default function HypothesisTool({ datasetId, fields }: { datasetId: number; fields: FieldMeta[] }) {
  const [test, setTest] = useState<(typeof TESTS)[number]["id"]>("t_welch");
  const [value, setValue] = useState(""); const [value2, setValue2] = useState(""); const [group, setGroup] = useState("");
  const [picked, setPicked] = useState<string[]>([]); const [alpha, setAlpha] = useState(0.05);
  useEffect(() => { setValue(""); setValue2(""); setGroup(""); setPicked([]); }, [datasetId, test]);
  const levels = fields.find((f) => f.name === group)?.values ?? [];
  const twoGroups = test === "t_independent" || test === "t_welch";
  const ready = test === "t_paired" ? value && value2 : test === "chi_square" ? value && value2 : value && group && (!twoGroups || levels.length === 2 || picked.length === 2);
  const run = useMutation({ mutationFn: () => api.post<HypothesisResult>("/advanced/hypothesis", { dataset_id: datasetId, test, value: value || null, value2: value2 || null, group: group || null, groups: twoGroups && levels.length !== 2 ? picked : null, alpha }) });
  const r = run.data;
  const cats: FieldMeta["kind"][] = ["category", "text"];
  const df = r ? (Array.isArray(r.df) ? r.df.join(", ") : r.df.toFixed(1)) : "";

  return (
    <div className="space-y-5">
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
        {TESTS.map((t) => <button key={t.id} onClick={() => setTest(t.id)} aria-pressed={test === t.id} className={`rounded-xl border p-3 text-left transition ${test === t.id ? "border-brand-600 bg-brand-50 shadow-card dark:bg-brand-500/10" : "border-slate-200 hover:border-brand-400 dark:border-white/10"}`}><p className="text-sm font-semibold">{t.name}</p><p className="mt-1 text-xs text-slate-500">{t.text}</p></button>)}
      </div>
      <Card title="Configure">
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {test === "t_paired" ? <>
            <Field label="Measurement 1 (before)"><ColumnSelect fields={fields} value={value} onChange={setValue} kinds={["numeric"]} measureOnly exclude={[value2]} /></Field>
            <Field label="Measurement 2 (after)"><ColumnSelect fields={fields} value={value2} onChange={setValue2} kinds={["numeric"]} measureOnly exclude={[value]} /></Field></>
            : test === "chi_square" ? <>
              <Field label="Categorical field A"><ColumnSelect fields={fields} value={value} onChange={setValue} kinds={cats} exclude={[value2]} /></Field>
              <Field label="Categorical field B"><ColumnSelect fields={fields} value={value2} onChange={setValue2} kinds={cats} exclude={[value]} /></Field></>
              : <>
                <Field label="Number to compare"><ColumnSelect fields={fields} value={value} onChange={setValue} kinds={["numeric"]} measureOnly /></Field>
                <Field label="Grouped by"><ColumnSelect fields={fields} value={group} onChange={(v) => { setGroup(v); setPicked([]); }} kinds={cats} /></Field>
                {twoGroups && levels.length > 2 && <Field label="Pick exactly two groups" hint={`${picked.length}/2 selected`}>
                  <div className="flex max-h-24 flex-wrap gap-1 overflow-y-auto">{levels.map((l) => { const on = picked.includes(l); return <button key={l} onClick={() => setPicked(on ? picked.filter((x) => x !== l) : picked.length < 2 ? [...picked, l] : picked)} className={`rounded-full border px-2.5 py-0.5 text-xs ${on ? "border-brand-600 bg-brand-600 text-white" : "border-slate-300 dark:border-white/15"}`}>{l}</button>; })}</div></Field>}</>}
          <Field label="Significance level α"><select className="input" value={alpha} onChange={(e) => setAlpha(Number(e.target.value))}>{[0.1, 0.05, 0.01].map((a) => <option key={a} value={a}>{a} ({(1 - a) * 100}% confidence)</option>)}</select></Field>
        </div>
        <button className="btn-primary mt-4" disabled={!ready || run.isPending} onClick={() => run.mutate()}>{run.isPending ? <Spinner /> : <Play className="h-4 w-4" />} Run test</button>
      </Card>
      <ErrorNote error={run.error} />
      {r && (
        <>
          <Card>
            <div className={`mb-4 flex items-start gap-3 rounded-xl p-4 ${r.significant ? "bg-emerald-50 dark:bg-emerald-500/10" : "bg-slate-100 dark:bg-white/5"}`}>
              {r.significant ? <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-600" /> : <MinusCircle className="mt-0.5 h-5 w-5 shrink-0 text-slate-500" />}
              <div><p className="font-semibold">{r.significant ? `Statistically significant at α = ${r.alpha}` : `Not statistically significant at α = ${r.alpha}`}</p><p className="mt-1 text-sm">{r.interpretation}</p></div>
            </div>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
              <Stat2 label="Test" value={<span className="text-sm">{r.name}</span>} />
              <Stat2 label="Statistic" value={n4(r.statistic)} sub={`df = ${df}`} />
              <Stat2 label="p-value" value={p(r.p_value)} tone={r.significant ? "good" : undefined} />
              {r.mean_difference != null && <Stat2 label="Mean difference" value={n4(r.mean_difference)} sub={`${(r.confidence! * 100).toFixed(0)}% CI ${n4(r.ci_low)} to ${n4(r.ci_high)}`} />}
              <Stat2 label={r.effect_size.name} value={n4(r.effect_size.value)} sub={r.effect_size.label + " effect"} />
            </div>
            {r.notes.length > 0 && <ul className="mt-4 space-y-1 text-sm text-slate-600 dark:text-slate-300">{r.notes.map((n, i) => <li key={i}>ℹ️ {n}</li>)}</ul>}
          </Card>
          <div className="grid gap-5 lg:grid-cols-2">
            <Card><ChartRenderer spec={r.chart} height={280} /></Card>
            {r.groups.length > 0 ? (
              <Card title="Group statistics" pad={false}><div className="overflow-x-auto"><table className="min-w-full"><thead><tr>{["Group", "n", "Mean", "Std", "Median", "CI low", "CI high"].map((h, i) => <th key={h} className={`th ${i ? "text-right" : ""}`}>{h}</th>)}</tr></thead>
                <tbody>{r.groups.map((g) => <tr key={g.group}><td className="td font-medium">{g.group}</td>{[g.n, n4(g.mean), n4(g.std), n4(g.median), n4(g.ci_low), n4(g.ci_high)].map((v, i) => <td key={i} className="td text-right tabular-nums">{v}</td>)}</tr>)}</tbody></table></div></Card>
            ) : r.contingency && (
              <Card title="Observed counts" pad={false}><div className="overflow-x-auto"><table className="min-w-full"><thead><tr><th className="th" />{r.contingency.columns.map((c) => <th key={c} className="th text-right">{c}</th>)}</tr></thead>
                <tbody>{r.contingency.rows.map((row, i) => <tr key={row}><td className="td font-medium">{row}</td>{r.contingency!.counts[i].map((v, k) => <td key={k} className="td text-right tabular-nums">{v}</td>)}</tr>)}</tbody></table></div>
                <div className="px-4 py-2"><Badge tone="brand">{r.effect_size.name} = {r.effect_size.value.toFixed(2)}</Badge></div></Card>)}
          </div>
        </>)}
    </div>
  );
}
