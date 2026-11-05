import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Tag } from "lucide-react";
import { useState } from "react";
import { api } from "../api/client";
import { Badge, Card, ErrorNote, Loading, PageHeader, Spinner } from "../components/ui";
import type { BillingMe, Plan } from "../lib/types";
import { money } from "./admin/forms";

const LIMITS: Record<string, string> = { max_datasets: "Datasets", storage_mb: "Storage (MB)", ai_analyses_per_month: "AI analyses / month", reports_per_month: "Reports / month", chat_messages_per_month: "Chat messages / month" };
const FEATURES: Record<string, string> = { ai_chat: "AI Chat", data_cleaning: "Data Cleaning", eda: "EDA", ai_agents: "AI Agents", sql_analysis: "SQL Analysis", data_visualization: "Data Visualization", pdf_reports: "PDF Reports", excel_reports: "Excel Reports", document_research: "Document Research" };
interface Quote { base_cents: number; discount_cents: number; total_cents: number; currency: string }

export default function Billing() {
  const qc = useQueryClient();
  const me = useQuery({ queryKey: ["billing", "me"], queryFn: () => api.get<BillingMe>("/billing/me") });
  const plans = useQuery({ queryKey: ["billing", "plans"], queryFn: () => api.get<Plan[]>("/billing/plans") });
  const [interval, setInterval] = useState<"monthly" | "yearly">("monthly");
  const [code, setCode] = useState(""), [target, setTarget] = useState<number | null>(null), [quote, setQuote] = useState<Quote | null>(null);
  const check = useMutation({ mutationFn: (planId: number) => api.post<Quote>("/billing/promo/validate", { code, plan_id: planId, interval }), onSuccess: setQuote, onError: () => setQuote(null) });
  const change = useMutation({ mutationFn: (planId: number) => api.post("/billing/change-plan", { plan_id: planId, interval }), onSuccess: () => { qc.invalidateQueries({ queryKey: ["billing"] }); setQuote(null); } });
  if (me.isLoading || plans.isLoading) return <Loading />;
  if (me.error || !me.data) return <ErrorNote error={me.error} />;
  const m = me.data;
  const price = (p: Plan) => (interval === "yearly" ? p.yearly_price_cents : p.monthly_price_cents);
  return (
    <>
      <PageHeader title="Plan & billing" subtitle="Your plan, usage this period, and available upgrades." />
      <div className="space-y-6">
        <Card title={<>Current plan: {m.plan.name} {m.subscription && <Badge tone={m.subscription.status === "trialing" ? "amber" : "green"}>{m.subscription.status}</Badge>}</>}>
          {m.subscription?.current_period_end && <p className="mb-3 text-sm text-slate-500">{m.subscription.status === "trialing" ? "Trial ends" : "Renews / ends"} {new Date(m.subscription.current_period_end).toLocaleDateString()}</p>}
          <ul className="grid gap-x-8 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">{Object.entries(LIMITS).map(([k, label]) => {
            const used = m.usage[k] ?? 0, lim = m.limits[k]; const pct = lim ? Math.min(100, (used / lim) * 100) : 0;
            return <li key={k}><div className="flex justify-between text-sm"><span>{label}</span><b className="tabular-nums">{used} / {lim ?? "∞"}</b></div>
              <div className="mt-1 h-1.5 rounded-full bg-slate-100 dark:bg-white/10"><div className={`h-full rounded-full ${pct > 90 ? "bg-red-500" : "bg-brand-600"}`} style={{ width: `${lim ? pct : 0}%` }} /></div></li>;
          })}</ul>
          <p className="mt-4 text-xs text-slate-500">Max upload size: {m.upload_limit_mb} MB</p>
        </Card>

        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-semibold">Available plans</h2>
          <div className="inline-flex rounded-lg border border-slate-200 p-0.5 dark:border-white/10" role="group" aria-label="Billing interval">{(["monthly", "yearly"] as const).map((i) => <button key={i} aria-pressed={interval === i} onClick={() => { setInterval(i); setQuote(null); }} className={`rounded-md px-3 py-1 text-sm capitalize ${interval === i ? "bg-brand-600 text-white" : "text-slate-600 dark:text-slate-300"}`}>{i}</button>)}</div>
        </div>

        <Card title="Promo code" pad>
          <div className="flex flex-wrap items-end gap-2">
            <label className="min-w-[200px] flex-1 sm:max-w-xs"><span className="label">Have a code?</span><input className="input font-mono uppercase" value={code} onChange={(e) => { setCode(e.target.value.toUpperCase()); setQuote(null); check.reset(); }} placeholder="LAUNCH20" /></label>
            <p className="text-xs text-slate-500">Pick a plan below and press “Apply code” to preview your price.</p>
          </div>
        </Card>

        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {plans.data?.map((p) => {
            const current = p.id === m.plan.id, base = price(p);
            const q = target === p.id ? quote : null;
            return (
              <Card key={p.id} className={current ? "ring-2 ring-brand-600" : ""}>
                <div className="flex items-start justify-between"><h3 className="text-lg font-semibold">{p.name}</h3>{current && <Badge tone="brand">Current</Badge>}{!current && p.trial_days > 0 && <Badge tone="amber">{p.trial_days}-day trial</Badge>}</div>
                {p.description && <p className="mt-1 text-sm text-slate-500">{p.description}</p>}
                <p className="mt-3 text-3xl font-semibold tabular-nums">{base ? (q ? money(q.total_cents, p.currency) : money(base, p.currency)) : "Free"}<span className="text-sm font-normal text-slate-500">{base ? ` /${interval === "yearly" ? "yr" : "mo"}` : ""}</span></p>
                {q && q.discount_cents > 0 && <p className="text-sm text-emerald-600"><s className="text-slate-400">{money(q.base_cents, p.currency)}</s> · you save {money(q.discount_cents, p.currency)}</p>}
                <ul className="mt-3 space-y-1 text-sm">{Object.entries(FEATURES).map(([k, l]) => p.features[k] !== false && <li key={k} className="flex items-center gap-2"><Check className="h-3.5 w-3.5 text-emerald-600" />{l}</li>)}</ul>
                <div className="mt-4 space-y-2">
                  {code && base > 0 && !current && <button className="btn-ghost w-full" disabled={check.isPending} onClick={() => { setTarget(p.id); check.mutate(p.id); }}>{check.isPending && target === p.id ? <Spinner /> : <Tag className="h-4 w-4" />} Apply code</button>}
                  {target === p.id && check.error && <ErrorNote error={check.error} />}
                  {!current && <button className="btn-primary w-full" disabled={change.isPending} onClick={() => { setTarget(p.id); change.mutate(p.id); }}>{change.isPending && target === p.id && <Spinner />} {base === 0 ? "Switch to this plan" : p.trial_days ? `Start ${p.trial_days}-day trial` : "Upgrade"}</button>}
                  {target === p.id && change.error && <ErrorNote error={change.error} />}
                </div>
              </Card>);
          })}
        </div>
      </div>
    </>
  );
}
