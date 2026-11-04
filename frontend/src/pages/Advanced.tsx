import { Calculator, FlaskConical, GitCompareArrows, LineChart, Table2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { DatasetPicker, useDatasets } from "../components/DatasetPicker";
import { Empty, ErrorNote, Loading, PageHeader } from "../components/ui";
import { useNumFmt, type NumMode } from "../lib/numfmt";
import HypothesisTool from "./advanced/HypothesisTool";
import ParetoTool from "./advanced/ParetoTool";
import PivotTool from "./advanced/PivotTool";
import RegressionTool from "./advanced/RegressionTool";
import VarianceTool from "./advanced/VarianceTool";
import { useFields } from "./advanced/common";

const TOOLS = [
  { id: "pivot", label: "Pivot table", icon: Table2, text: "Summarise data by rows and columns without SQL." },
  { id: "regression", label: "Regression", icon: LineChart, text: "Find which variables drive an outcome and predict it." },
  { id: "hypothesis", label: "Hypothesis tests", icon: FlaskConical, text: "Check whether differences are statistically significant." },
  { id: "pareto", label: "Pareto & ABC", icon: Calculator, text: "Find the vital few that drive most of the result." },
  { id: "variance", label: "Variance", icon: GitCompareArrows, text: "Compare actual performance with targets or last period." },
] as const;
type ToolId = (typeof TOOLS)[number]["id"];

export default function Advanced() {
  const [params, setParams] = useSearchParams();
  const tool = (TOOLS.find((t) => t.id === params.get("tool"))?.id ?? "pivot") as ToolId;
  const { data: datasets = [], isLoading } = useDatasets();
  const tables = datasets.filter((d) => d.kind === "table");
  const [datasetId, setDatasetId] = useState<number | null>(params.get("dataset") ? Number(params.get("dataset")) : null);
  const { mode, setMode } = useNumFmt();
  useEffect(() => { if (datasetId == null && tables.length) setDatasetId(tables[0].id); }, [tables, datasetId]);
  const fieldsQ = useFields(datasetId);
  const fields = fieldsQ.data?.columns ?? [];
  const current = TOOLS.find((t) => t.id === tool)!;

  if (isLoading) return <Loading />;
  return (
    <>
      <PageHeader title="Advanced analytics" subtitle="Professional analyst tools: pivot tables, regression, hypothesis tests, Pareto/ABC and variance analysis."
        actions={<><DatasetPicker value={datasetId} onChange={setDatasetId} kind="table" />
          <select className="input !w-auto" value={mode} onChange={(e) => setMode(e.target.value as NumMode)} aria-label="Number format" title="Number format">
            <option value="standard">1,234,567</option><option value="indian">12,34,567</option><option value="inr">₹ 12,34,567</option></select></>} />
      <div className="mb-6 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
        {TOOLS.map((t) => (
          <button key={t.id} onClick={() => setParams({ tool: t.id, ...(datasetId ? { dataset: String(datasetId) } : {}) })} aria-pressed={tool === t.id}
            className={`group flex items-start gap-3 rounded-xl border p-3 text-left transition ${tool === t.id ? "border-brand-600 bg-brand-50 shadow-card dark:bg-brand-500/10" : "border-slate-200 bg-white hover:-translate-y-0.5 hover:border-brand-400 dark:border-white/10 dark:bg-ink-900"}`}>
            <span className={`rounded-lg p-2 transition ${tool === t.id ? "bg-brand-600 text-white" : "bg-slate-100 text-slate-500 group-hover:bg-brand-100 group-hover:text-brand-600 dark:bg-white/10"}`}><t.icon className="h-4 w-4" /></span>
            <span><span className="block text-sm font-semibold">{t.label}</span><span className="block text-xs text-slate-500">{t.text}</span></span>
          </button>))}
      </div>
      {tables.length === 0 ? <Empty icon={current.icon} title="No tabular data yet" text="Upload a CSV, Excel, JSON, Parquet or SQLite file on the Data sources page to use these tools." />
        : !datasetId ? <p className="text-sm text-slate-500">Select a data source above.</p>
          : fieldsQ.isLoading ? <Loading /> : fieldsQ.error ? <ErrorNote error={fieldsQ.error} /> : (
            <div key={`${tool}-${datasetId}`} className="page-enter">
              {tool === "pivot" && <PivotTool datasetId={datasetId} fields={fields} />}
              {tool === "regression" && <RegressionTool datasetId={datasetId} fields={fields} />}
              {tool === "hypothesis" && <HypothesisTool datasetId={datasetId} fields={fields} />}
              {tool === "pareto" && <ParetoTool datasetId={datasetId} fields={fields} />}
              {tool === "variance" && <VarianceTool datasetId={datasetId} fields={fields} />}
            </div>)}
    </>
  );
}
