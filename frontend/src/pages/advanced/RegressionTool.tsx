import { useMutation } from "@tanstack/react-query";
import { AlertTriangle, LineChart as LineIcon, Play } from "lucide-react";
import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../../api/client";
import { ChartRenderer } from "../../components/ChartRenderer";
import { ChartTooltip } from "../../components/ChartTooltip";
import { formatSig } from "../../lib/numfmt";
import { Badge, Card, ErrorNote, Spinner } from "../../components/ui";
import type { ChartSpec, FieldMeta, RegressionResult } from "../../lib/types";
import { ColumnSelect, Field, Stat2, n4, p } from "./common";

export default function RegressionTool({ datasetId, fields }: { datasetId: number; fields: FieldMeta[] }) {
  const [target, setTarget] = useState("");
  const [features, setFeatures] = useState<string[]>([]);
  const [auto, setAuto] = useState(false);
  useEffect(() => { setTarget(""); setFeatures([]); }, [datasetId]);
  const candidates = fields.filter((f) => f.name !== target && ((f.kind === "numeric" && f.measure) || (f.kind === "category" && f.unique >= 2 && f.unique <= 12)));
  const run = useMutation({ mutationFn: () => api.post<RegressionResult>("/advanced/regression", { dataset_id: datasetId, target, features, auto_select: auto }) });
  const r = run.data;
  const toggle = (n: string) => setFeatures((f) => (f.includes(n) ? f.filter((x) => x !== n) : [...f, n]));

  const avp: ChartSpec | undefined = r && { type: "scatter", title: "Actual vs predicted", x: "predicted", y: ["actual"], data: r.charts.actual_vs_predicted, line: r.charts.perfect_line.map((d) => ({ predicted: d.predicted, actual: d.actual })), note: "Dashed line = perfect prediction" };
  const rvf: ChartSpec | undefined = r && { type: "scatter", title: "Residuals vs fitted", x: "fitted", y: ["residual"], data: r.charts.residuals_vs_fitted, note: "A random cloud around 0 means a good fit; a funnel or curve signals problems" };
  const hist: ChartSpec | undefined = r && { type: "histogram", title: "Residual distribution", x: "bin", y: ["count"], data: r.charts.residual_histogram };

  return (
    <div className="space-y-5">
      <Card title="Model setup">
        <div className="grid gap-5 lg:grid-cols-[260px_1fr]">
          <div className="space-y-4">
            <Field label="Outcome to predict (Y)"><ColumnSelect fields={fields} value={target} onChange={(v) => { setTarget(v); setFeatures((f) => f.filter((x) => x !== v)); }} kinds={["numeric"]} measureOnly placeholder="e.g. revenue" /></Field>
            <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1 accent-brand-600" checked={auto} onChange={(e) => setAuto(e.target.checked)} />
              <span>Auto-select features<span className="block text-xs text-slate-500">Backward elimination: repeatedly drops the least significant predictor (p &gt; 0.05).</span></span></label>
            <button className="btn-primary w-full" disabled={!target || !features.length || run.isPending} onClick={() => run.mutate()}>{run.isPending ? <Spinner /> : <Play className="h-4 w-4" />} Fit model</button>
          </div>
          <div>
            <p className="label">Predictors (X) — pick one for simple, several for multiple regression</p>
            <div className="flex flex-wrap gap-2">
              {candidates.length === 0 && <p className="text-sm text-slate-500">Pick the outcome first.</p>}
              {candidates.map((f) => <button key={f.name} aria-pressed={features.includes(f.name)} onClick={() => toggle(f.name)} className={`rounded-full border px-3 py-1 text-sm transition ${features.includes(f.name) ? "border-brand-600 bg-brand-600 text-white" : "border-slate-300 hover:border-brand-400 dark:border-white/15"}`}>{f.name}{f.kind === "category" && <span className="ml-1 text-[10px] opacity-70">categorical</span>}</button>)}
            </div>
          </div>
        </div>
      </Card>
      <ErrorNote error={run.error} />
      {r && (
        <>
          <Card title={<span className="flex items-center gap-2"><LineIcon className="h-4 w-4 text-brand-500" /> {r.kind === "simple" ? "Simple" : "Multiple"} linear regression: {r.target} ~ {r.features.join(" + ")}</span>}>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 xl:grid-cols-6">
              <Stat2 label="R²" value={r.metrics.r2.toFixed(4)} sub="variance explained" tone={r.metrics.r2 > 0.7 ? "good" : r.metrics.r2 < 0.3 ? "warn" : undefined} />
              <Stat2 label="Adjusted R²" value={r.metrics.adj_r2.toFixed(4)} />
              <Stat2 label="F-test p-value" value={p(r.metrics.f_p_value)} tone={r.metrics.f_p_value < 0.05 ? "good" : "bad"} sub={`F = ${n4(r.metrics.f_stat)}`} />
              <Stat2 label="RMSE" value={n4(r.metrics.rmse)} sub={`MAE ${n4(r.metrics.mae)}`} />
              <Stat2 label="Observations" value={r.n.toLocaleString()} sub={r.dropped_rows ? `${r.dropped_rows} dropped (missing)` : undefined} />
              {r.holdout && <Stat2 label="Holdout R² (20%)" value={r.holdout.r2.toFixed(4)} sub={`RMSE ${n4(r.holdout.rmse)}`} />}
            </div>
            <ul className="mt-4 space-y-1.5 text-sm">{r.interpretation.map((t, i) => <li key={i} className="flex gap-2"><span className="text-brand-500">▸</span>{t}</li>)}</ul>
            {r.removed_by_selection.length > 0 && <p className="mt-3 text-sm text-slate-500">Auto-select removed: {r.removed_by_selection.join(", ")}.</p>}
            {r.warnings.length > 0 && <div className="mt-3 space-y-1.5">{r.warnings.map((w, i) => <p key={i} className="flex gap-2 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:bg-amber-500/10 dark:text-amber-300"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />{w}</p>)}</div>}
          </Card>
          <Card title="Coefficients" pad={false}>
            <div className="overflow-x-auto"><table className="min-w-full"><thead><tr>{["Term", "Coefficient", "Std. error", "t", "p-value", "95% CI low", "95% CI high", ""].map((h, i) => <th key={h + i} className={`th ${i ? "text-right" : ""}`}>{h}</th>)}</tr></thead>
              <tbody>{r.coefficients.map((c) => (
                <tr key={c.name} className="hover:bg-slate-50 dark:hover:bg-white/5"><td className="td font-medium">{c.name === "const" ? "Intercept" : c.name}</td>
                  {[n4(c.coef), n4(c.std_err), c.t.toFixed(2), p(c.p_value), n4(c.ci_low), n4(c.ci_high)].map((v, i) => <td key={i} className="td text-right tabular-nums">{v}</td>)}
                  <td className="td text-right">{c.name !== "const" && <Badge tone={c.significant ? "green" : "slate"}>{c.significant ? "significant" : "n.s."}</Badge>}</td></tr>))}</tbody></table></div>
          </Card>
          <div className="grid gap-5 lg:grid-cols-2">
            {avp && <Card><ChartRenderer spec={avp} height={300} /></Card>}
            {rvf && <Card><ChartRenderer spec={rvf} height={300} /></Card>}
            {hist && <Card><ChartRenderer spec={hist} height={260} /></Card>}
            {r.coefficients.length > 2 && (
              <Card title="Effect size per predictor (raw coefficient)"><ResponsiveContainer width="100%" height={240}><BarChart data={r.charts.coefficient_bars} layout="vertical" margin={{ left: 20 }}><CartesianGrid strokeDasharray="3 3" stroke="#e2e8f033" horizontal={false} /><XAxis type="number" tick={{ fontSize: 11, fill: "#94a3b8" }} tickFormatter={(v) => formatSig(v, 4)} /><YAxis type="category" dataKey="name" width={100} tick={{ fontSize: 11, fill: "#94a3b8" }} /><Tooltip content={<ChartTooltip />} /><Bar dataKey="coef" name="Coefficient" fill="rgb(var(--brand-600))" radius={[0, 4, 4, 0]} /></BarChart></ResponsiveContainer>
                <p className="mt-1 text-xs text-slate-500">Coefficients are in the units of each predictor, so compare them with care.</p></Card>)}
            <Card title="Residual diagnostics">
              <dl className="space-y-2 text-sm">
                {r.diagnostics.durbin_watson != null && <div className="flex justify-between"><dt className="text-slate-500">Durbin–Watson (independence, ≈2 is good)</dt><dd className="font-medium tabular-nums">{r.diagnostics.durbin_watson.toFixed(2)}</dd></div>}
                {r.diagnostics.normality_p != null && <div className="flex justify-between"><dt className="text-slate-500">Jarque–Bera normality p</dt><dd className="font-medium tabular-nums">{p(r.diagnostics.normality_p)}</dd></div>}
                {r.diagnostics.heteroscedasticity_p != null && <div className="flex justify-between"><dt className="text-slate-500">Breusch–Pagan constant-variance p</dt><dd className="font-medium tabular-nums">{p(r.diagnostics.heteroscedasticity_p)}</dd></div>}
                {r.vif.map((v) => <div key={v.name} className="flex justify-between"><dt className="text-slate-500">VIF · {v.name}</dt><dd className={`font-medium tabular-nums ${v.vif > 10 ? "text-red-600" : ""}`}>{v.vif.toFixed(2)}</dd></div>)}
              </dl>
              {r.influential_points.length > 0 && <div className="mt-3 border-t border-slate-100 pt-3 text-sm dark:border-white/5"><p className="mb-1 font-medium">Most influential rows (Cook's distance)</p>
                {r.influential_points.map((o) => <p key={o.row} className="flex justify-between text-slate-600 dark:text-slate-300"><span>row {o.row}</span><span className="tabular-nums">D = {o.cooks_d.toFixed(2)} · residual {n4(o.residual)}</span></p>)}</div>}
            </Card>
          </div>
        </>)}
    </div>
  );
}
