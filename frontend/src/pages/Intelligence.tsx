import { useMutation, useQuery } from "@tanstack/react-query";
import { FileSpreadsheet, FileText, FlaskConical, Play, Plus, RefreshCw, Rocket, Search, Sparkles, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { DatasetPicker, useDatasets } from "../components/DatasetPicker";
import { SuggestionChips } from "../components/SuggestionChips";
import { ExecutiveView } from "../components/intelligence/ExecutiveView";
import { InsightCard } from "../components/intelligence/InsightCards";
import { RootCauseView } from "../components/intelligence/RootCauseView";
import { ScenarioView } from "../components/intelligence/ScenarioView";
import { Card, Empty, ErrorNote, Loading, PageHeader, Spinner } from "../components/ui";
import { useNumFmt } from "../lib/numfmt";
import type { DataRoles, Discovery, Executive, Insight, RootCause, SavedReport, ScenarioResult } from "../lib/types";
import { ColumnSelect, Field } from "./advanced/common";
import { useFields } from "./advanced/common";

const TABS = [
  { id: "insights", label: "Insight discovery", icon: Sparkles, text: "What the data is telling you, found automatically." },
  { id: "root", label: "Root cause", icon: Search, text: "Why a metric changed, with the evidence." },
  { id: "executive", label: "Executive summary", icon: Rocket, text: "Management view: KPIs, risks, actions." },
  { id: "scenario", label: "Scenarios", icon: FlaskConical, text: "What-if: simulate prices, costs and volume." },
] as const;
type Tab = (typeof TABS)[number]["id"];

function InsightsTab({ datasetId, onInvestigate }: { datasetId: number; onInvestigate: (i: Insight) => void }) {
  const { mode } = useNumFmt();
  const q = useQuery({ queryKey: ["discover", datasetId, mode], staleTime: 0, queryFn: () => api.get<Discovery>(`/intelligence/discover/${datasetId}?number_mode=${mode}`) });
  const refresh = useMutation({ mutationFn: () => api.get<Discovery>(`/intelligence/discover/${datasetId}?number_mode=${mode}&refresh=true`), onSuccess: () => q.refetch() });
  const [filter, setFilter] = useState("all");
  if (q.isLoading) return <Loading label="Scanning your data for patterns…" />;
  if (q.error || !q.data) return <ErrorNote error={q.error} />;
  const d = q.data;
  const types = ["all", ...Object.keys(d.summary)];
  const list = d.insights.filter((i) => filter === "all" || i.type === filter);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {types.map((t) => <button key={t} onClick={() => setFilter(t)} className={`rounded-full border px-3 py-1 text-xs font-medium capitalize ${filter === t ? "border-brand-600 bg-brand-600 text-white" : "border-slate-300 hover:border-brand-400 dark:border-white/15"}`}>{t}{t !== "all" && ` · ${d.summary[t]}`}</button>)}
        <span className="ml-auto text-xs text-slate-500">{d.insights.length} insights · all numbers re-checked{d.dropped_unverified ? ` · ${d.dropped_unverified} unverified removed` : ""}{d.period.current ? ` · compared ${d.period.previous} → ${d.period.current}` : ""}</span>
        <button className="btn-ghost !py-1 text-xs" onClick={() => refresh.mutate()} disabled={refresh.isPending}>{refresh.isPending ? <Spinner /> : <RefreshCw className="h-3.5 w-3.5" />} Rescan</button>
      </div>
      {d.skipped.map((s, i) => <p key={i} className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:bg-amber-500/10 dark:text-amber-300">{s}</p>)}
      {list.length === 0 ? <Empty icon={Sparkles} title="Nothing notable found" text="The scan found no significant patterns. Try a dataset with dates and a numeric measure like revenue." />
        : <div className="grid gap-4 lg:grid-cols-2">{list.map((i) => <InsightCard key={i.id} i={i} onInvestigate={onInvestigate} />)}</div>}
    </div>
  );
}

function RootCauseTab({ datasetId, seed }: { datasetId: number; seed: { current?: string; metric?: string; grain?: string } | null }) {
  const { mode } = useNumFmt();
  const roles = useQuery({ queryKey: ["roles", datasetId], queryFn: () => api.get<DataRoles>(`/intelligence/roles/${datasetId}`) });
  const [question, setQuestion] = useState("");
  const [metric, setMetric] = useState(""); const [grain, setGrain] = useState("month"); const [current, setCurrent] = useState("");
  useEffect(() => { if (seed) { setCurrent(seed.current ?? ""); setMetric(seed.metric ?? ""); setGrain(seed.grain ?? "month"); setQuestion(""); } }, [seed]);
  const run = useMutation({ mutationFn: (auto: boolean) => api.post<RootCause>("/intelligence/root-cause", { dataset_id: datasetId, question: question || null, metric: metric || null, grain, current: current || null, number_mode: mode, ...(auto ? {} : {}) }) });
  useEffect(() => { if (seed?.current) run.mutate(true); /* eslint-disable-next-line */ }, [seed]);
  const measures = roles.data?.measures ?? [];
  return (
    <div className="space-y-5">
      <Card>
        <form onSubmit={(e) => { e.preventDefault(); run.mutate(false); }} className="space-y-4">
          <Field label="Ask why" hint="Name the metric and the period, e.g. “Why did revenue decrease in July?”. Leave blank to explain the latest period instead.">
            <input className="input" value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="e.g. Why did revenue change last month?" /></Field>
          <SuggestionChips ids={[datasetId]} only={["Why"]} onPick={setQuestion} />
          <details className="text-sm"><summary className="cursor-pointer text-slate-500">Options</summary>
            <div className="mt-3 grid gap-4 md:grid-cols-3">
              <Field label="Metric"><select className="input" value={metric} onChange={(e) => setMetric(e.target.value)}><option value="">Auto-detect</option>{measures.map((m) => <option key={m}>{m}</option>)}</select></Field>
              <Field label="Compare by"><select className="input" value={grain} onChange={(e) => setGrain(e.target.value)}>{["day", "week", "month", "quarter", "year"].map((g) => <option key={g}>{g}</option>)}</select></Field>
              <Field label="Current period (e.g. 2025-07)"><input className="input" value={current} onChange={(e) => setCurrent(e.target.value)} placeholder="latest" /></Field></div></details>
          <button className="btn-primary" disabled={run.isPending}>{run.isPending ? <Spinner /> : <Play className="h-4 w-4" />} Find root cause</button>
        </form>
      </Card>
      <ErrorNote error={run.error} />
      {run.data && <RootCauseView rc={run.data} />}
    </div>
  );
}

function ExecutiveTab({ datasetId, onInvestigate }: { datasetId: number; onInvestigate: (i: Insight) => void }) {
  const { mode } = useNumFmt();
  const q = useQuery({ queryKey: ["executive", datasetId, mode], staleTime: 0, queryFn: () => api.post<Executive>("/intelligence/executive-summary", { dataset_id: datasetId, number_mode: mode }) });
  const exp = useMutation({ mutationFn: async (format: "pdf" | "xlsx") => { const r = await api.post<SavedReport>("/intelligence/executive-summary/export", { dataset_id: datasetId, format, number_mode: mode }); await api.download(`/reports/${r.id}/download`, `executive.${format}`); } });
  if (q.isLoading) return <Loading label="Preparing the executive summary…" />;
  if (q.error || !q.data) return <ErrorNote error={q.error} />;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3"><h2 className="text-lg font-semibold">{q.data.title}</h2><span className="text-sm text-slate-500">latest period: {q.data.period}</span>
        <span className="ml-auto flex gap-2"><button className="btn-ghost" disabled={exp.isPending} onClick={() => exp.mutate("pdf")}>{exp.isPending && exp.variables === "pdf" ? <Spinner /> : <FileText className="h-4 w-4" />} PDF</button>
          <button className="btn-ghost" disabled={exp.isPending} onClick={() => exp.mutate("xlsx")}>{exp.isPending && exp.variables === "xlsx" ? <Spinner /> : <FileSpreadsheet className="h-4 w-4" />} Excel</button></span></div>
      <ErrorNote error={exp.error} />
      <ExecutiveView ex={q.data} onInvestigate={onInvestigate} />
    </div>
  );
}

interface Sc { name: string; price: string; volume: string; cost: string; elasticity: string; fixed: string; segCol: string; segVals: string[] }
const newSc = (i: number, p = ""): Sc => ({ name: `Scenario ${i}`, price: p, volume: "", cost: "", elasticity: "", fixed: "", segCol: "", segVals: [] });

function ScenarioTab({ datasetId }: { datasetId: number }) {
  const { mode } = useNumFmt();
  const roles = useQuery({ queryKey: ["roles", datasetId], queryFn: () => api.get<DataRoles>(`/intelligence/roles/${datasetId}`) });
  const fields = useFields(datasetId).data?.columns ?? [];
  const [cols, setCols] = useState({ revenue: "", cost: "", quantity: "" });
  const [scope, setScope] = useState("all"); const [groupBy, setGroupBy] = useState("");
  const [scs, setScs] = useState<Sc[]>([{ ...newSc(1, "10"), name: "Prices +10%" }]);
  useEffect(() => { if (roles.data) setCols({ revenue: roles.data.revenue ?? "", cost: roles.data.cost ?? "", quantity: roles.data.quantity ?? "" }); }, [roles.data]);
  const num = (s: string) => (s === "" ? 0 : Number(s));
  const run = useMutation({
    mutationFn: () => api.post<ScenarioResult>("/intelligence/scenario", {
      dataset_id: datasetId, revenue: cols.revenue || null, cost: cols.cost || null, quantity: cols.quantity || null, baseline_scope: scope, group_by: groupBy || null, number_mode: mode,
      scenarios: scs.map((s) => ({ name: s.name, price_change_pct: num(s.price), volume_change_pct: num(s.volume), cost_change_pct: num(s.cost), elasticity: num(s.elasticity), fixed_cost_pct: num(s.fixed), segment: s.segCol && s.segVals.length ? { column: s.segCol, values: s.segVals } : null })),
    }),
  });
  const upd = (i: number, p: Partial<Sc>) => setScs(scs.map((s, k) => (k === i ? { ...s, ...p } : s)));
  const dims = fields.filter((f) => f.kind === "category");
  const inp = (i: number, key: keyof Sc, label: string, ph = "0", hint?: string) => <Field label={label} hint={hint}><input type="number" className="input" value={scs[i][key] as string} placeholder={ph} onChange={(e) => upd(i, { [key]: e.target.value } as any)} /></Field>;
  return (
    <div className="space-y-5">
      <Card title="1 · Observed data used as the baseline">
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
          <Field label="Revenue column"><ColumnSelect fields={fields} value={cols.revenue} onChange={(v) => setCols({ ...cols, revenue: v })} kinds={["numeric"]} measureOnly /></Field>
          <Field label="Cost column" hint="Needed for profit"><ColumnSelect fields={fields} value={cols.cost} onChange={(v) => setCols({ ...cols, cost: v })} kinds={["numeric"]} measureOnly placeholder="None" /></Field>
          <Field label="Quantity column"><ColumnSelect fields={fields} value={cols.quantity} onChange={(v) => setCols({ ...cols, quantity: v })} kinds={["numeric"]} measureOnly placeholder="None" /></Field>
          <Field label="Baseline period"><select className="input" value={scope} onChange={(e) => setScope(e.target.value)}><option value="all">All data</option><option value="latest">Latest full month</option></select></Field>
          <Field label="Break down by" hint="Optional"><ColumnSelect fields={fields} value={groupBy} onChange={setGroupBy} kinds={["category"]} placeholder="No breakdown" /></Field>
        </div>
      </Card>
      <Card title="2 · Assumptions to test (these produce ESTIMATES)" action={scs.length < 4 && <button className="btn-ghost !py-1 text-xs" onClick={() => setScs([...scs, newSc(scs.length + 1)])}><Plus className="h-3.5 w-3.5" /> Add scenario</button>}>
        <div className="space-y-4">
          {scs.map((s, i) => {
            const levels = fields.find((f) => f.name === s.segCol)?.values ?? [];
            return (
              <div key={i} className="rounded-xl border border-amber-300/60 bg-amber-50/40 p-4 dark:border-amber-500/30 dark:bg-amber-500/5">
                <div className="mb-3 flex items-center gap-3"><input className="input !w-64 font-medium" value={s.name} onChange={(e) => upd(i, { name: e.target.value })} aria-label="Scenario name" />
                  <button disabled={scs.length === 1} onClick={() => setScs(scs.filter((_, k) => k !== i))} className="ml-auto rounded p-2 text-slate-400 hover:bg-red-50 hover:text-red-600 disabled:opacity-30" aria-label="Remove scenario"><Trash2 className="h-4 w-4" /></button></div>
                <div className="grid gap-4 md:grid-cols-3 xl:grid-cols-5">
                  {inp(i, "price", "Price change (%)", "e.g. 10")}{inp(i, "volume", "Volume change (%)", "e.g. -5", "Direct demand change")}
                  {inp(i, "elasticity", "Price elasticity", "e.g. -1.2", "% volume change per 1% price change")}{inp(i, "cost", "Unit cost change (%)", "e.g. 5")}{inp(i, "fixed", "Fixed share of cost (%)", "0", "Doesn't scale with volume")}
                </div>
                <div className="mt-3 grid gap-4 md:grid-cols-2"><Field label="Apply only to (optional)"><select className="input" value={s.segCol} onChange={(e) => upd(i, { segCol: e.target.value, segVals: [] })}><option value="">Everything</option>{dims.map((d) => <option key={d.name}>{d.name}</option>)}</select></Field>
                  {s.segCol && <Field label="Values"><div className="flex max-h-20 flex-wrap gap-1 overflow-y-auto">{levels.map((l) => { const on = s.segVals.includes(l); return <button key={l} onClick={() => upd(i, { segVals: on ? s.segVals.filter((x) => x !== l) : [...s.segVals, l] })} className={`rounded-full border px-2.5 py-0.5 text-xs ${on ? "border-amber-600 bg-amber-500 text-white" : "border-slate-300 dark:border-white/15"}`}>{l}</button>; })}</div></Field>}</div>
              </div>);
          })}
        </div>
        <button className="btn-primary mt-4" disabled={!cols.revenue || run.isPending} onClick={() => run.mutate()}>{run.isPending ? <Spinner /> : <Play className="h-4 w-4" />} Simulate</button>
      </Card>
      <ErrorNote error={run.error} />
      {run.data && <ScenarioView r={run.data} />}
    </div>
  );
}

export default function Intelligence() {
  const [params, setParams] = useSearchParams();
  const nav = useNavigate();
  const tab = (TABS.find((t) => t.id === params.get("tab"))?.id ?? "insights") as Tab;
  const { data: datasets = [], isLoading } = useDatasets();
  const tables = datasets.filter((d) => d.kind === "table");
  const [datasetId, setDatasetId] = useState<number | null>(params.get("dataset") ? Number(params.get("dataset")) : null);
  const [seed, setSeed] = useState<{ current?: string; metric?: string; grain?: string } | null>(null);
  const { mode, setMode } = useNumFmt();
  useEffect(() => { if (datasetId == null && tables.length) setDatasetId(tables[0].id); }, [tables, datasetId]);
  const go = (t: Tab) => setParams({ tab: t, ...(datasetId ? { dataset: String(datasetId) } : {}) });
  const investigate = (i: Insight) => {
    const inv = i.investigate;
    if (!inv) return;
    if (inv.tool === "root_cause") { setSeed({ current: inv.current, metric: inv.metric, grain: inv.grain }); go("root"); }
    else if (inv.tool === "clean") nav(`/datasets/${datasetId}`);
    else nav(`/advanced?tool=pareto&dataset=${datasetId}`);
  };
  if (isLoading) return <Loading />;
  const current = TABS.find((t) => t.id === tab)!;
  return (
    <>
      <PageHeader title="AI intelligence" subtitle="Automated discovery, root-cause analysis, executive summaries and what-if scenarios. Every number is re-checked against your data."
        actions={<><DatasetPicker value={datasetId} onChange={setDatasetId} kind="table" />
          <select className="input !w-auto" value={mode} onChange={(e) => setMode(e.target.value as any)} aria-label="Number format"><option value="standard">1,234,567</option><option value="indian">12,34,567</option><option value="inr">₹ 12,34,567</option></select></>} />
      <div className="mb-6 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {TABS.map((t) => (
          <button key={t.id} onClick={() => go(t.id)} aria-pressed={tab === t.id} className={`group flex items-start gap-3 rounded-xl border p-3 text-left transition ${tab === t.id ? "border-brand-600 bg-brand-50 shadow-card dark:bg-brand-500/10" : "border-slate-200 bg-white hover:-translate-y-0.5 hover:border-brand-400 dark:border-white/10 dark:bg-ink-900"}`}>
            <span className={`rounded-lg p-2 ${tab === t.id ? "bg-brand-600 text-white" : "bg-slate-100 text-slate-500 group-hover:bg-brand-100 group-hover:text-brand-600 dark:bg-white/10"}`}><t.icon className="h-4 w-4" /></span>
            <span><span className="block text-sm font-semibold">{t.label}</span><span className="block text-xs text-slate-500">{t.text}</span></span></button>))}
      </div>
      {tables.length === 0 ? <Empty icon={current.icon} title="No tabular data yet" text="Upload a dataset with a date column and numeric measures (e.g. revenue) on the Data sources page." />
        : !datasetId ? <p className="text-sm text-slate-500">Select a data source above.</p> : (
          <div key={`${tab}-${datasetId}`} className="page-enter">
            {tab === "insights" && <InsightsTab datasetId={datasetId} onInvestigate={investigate} />}
            {tab === "root" && <RootCauseTab datasetId={datasetId} seed={seed} />}
            {tab === "executive" && <ExecutiveTab datasetId={datasetId} onInvestigate={investigate} />}
            {tab === "scenario" && <ScenarioTab datasetId={datasetId} />}
          </div>)}
    </>
  );
}
