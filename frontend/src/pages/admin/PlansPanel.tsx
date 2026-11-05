import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CreditCard, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { api } from "../../api/client";
import { Badge, Card, ErrorNote, Loading, Spinner } from "../../components/ui";
import type { Plan } from "../../lib/types";
import { Modal } from "./common";
import { Field, NumInput, Toggle, money } from "./forms";

interface PlansResp { items: Plan[]; features: Record<string, string>; limits: Record<string, string> }
const blank = (): Plan => ({ id: 0, slug: "", name: "", description: "", monthly_price_cents: 0, yearly_price_cents: 0, currency: "INR", trial_days: 0, is_active: true, sort_order: 0, features: {}, limits: {},
  rules: { allow_upgrade: true, allow_downgrade: true, downgrade_timing: "period_end", prorate_upgrades: true, allowed_upgrade_to: [], allowed_downgrade_to: [] } });

export default function PlansPanel() {
  const qc = useQueryClient();
  const { data, error, isLoading } = useQuery({ queryKey: ["admin", "plans"], queryFn: () => api.get<PlansResp>("/admin/plans") });
  const [edit, setEdit] = useState<Plan | null>(null), [del, setDel] = useState<Plan | null>(null);
  const rm = useMutation({ mutationFn: (id: number) => api.del(`/admin/plans/${id}`), onSuccess: () => { setDel(null); qc.invalidateQueries({ queryKey: ["admin"] }); } });
  if (isLoading) return <Loading />;
  if (error || !data) return <ErrorNote error={error} />;
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between"><p className="text-sm text-slate-500">Plans control feature access and usage limits. Users without a subscription get the default <b>Free</b> plan.</p>
        <button className="btn-primary" onClick={() => setEdit(blank())}><Plus className="h-4 w-4" /> New plan</button></div>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {data.items.map((p) => (
          <Card key={p.id} className={p.is_active ? "" : "opacity-70"}>
            <div className="flex items-start justify-between gap-2">
              <div><h3 className="text-lg font-semibold">{p.name}</h3><p className="text-xs text-slate-500">{p.slug}{p.is_default && " · default"}</p></div>
              <div className="flex gap-1">{!p.is_active && <Badge tone="amber">disabled</Badge>}{p.trial_days > 0 && <Badge tone="brand">{p.trial_days}d trial</Badge>}</div>
            </div>
            <p className="mt-3 text-2xl font-semibold tabular-nums">{p.monthly_price_cents ? money(p.monthly_price_cents, p.currency) : "Free"}<span className="text-sm font-normal text-slate-500">{p.monthly_price_cents ? " /mo" : ""}</span></p>
            {p.yearly_price_cents > 0 && <p className="text-xs text-slate-500">{money(p.yearly_price_cents, p.currency)} /yr</p>}
            <ul className="mt-3 space-y-1 text-xs text-slate-600 dark:text-slate-300">
              {Object.entries(data.limits).map(([k, label]) => <li key={k} className="flex justify-between"><span>{label}</span><b className="tabular-nums">{p.limits[k] ?? "∞"}</b></li>)}
            </ul>
            <p className="mt-3 text-xs text-slate-500">{Object.values(p.features).filter(Boolean).length}/{Object.keys(data.features).length} features · {p.subscribers ?? 0} subscriber{p.subscribers === 1 ? "" : "s"}</p>
            <div className="mt-4 flex gap-2"><button className="btn-ghost flex-1" onClick={() => setEdit(structuredClone(p))}><Pencil className="h-4 w-4" /> Edit</button>
              {!p.is_default && <button className="btn-danger" aria-label={`Delete ${p.name}`} onClick={() => setDel(p)}><Trash2 className="h-4 w-4" /></button>}</div>
          </Card>))}
      </div>
      {edit && <PlanEditor plan={edit} meta={data} plans={data.items} onClose={() => setEdit(null)} />}
      {del && <Modal title="Delete plan" onClose={() => setDel(null)}>
        <p className="text-sm">Delete <b>{del.name}</b>? {del.subscribers ? <span className="text-red-600">It has {del.subscribers} subscriber(s) — deletion will be refused. Disable the plan instead.</span> : "This can't be undone."}</p>
        <div className="mt-3"><ErrorNote error={rm.error} /></div>
        <div className="mt-4 flex justify-end gap-2"><button className="btn-ghost" onClick={() => setDel(null)}>Cancel</button><button className="btn bg-red-600 text-white hover:bg-red-700" disabled={rm.isPending} onClick={() => rm.mutate(del.id)}>{rm.isPending && <Spinner />} Delete</button></div></Modal>}
    </div>
  );
}

function PlanEditor({ plan, meta, plans, onClose }: { plan: Plan; meta: PlansResp; plans: Plan[]; onClose: () => void }) {
  const qc = useQueryClient();
  const [p, setP] = useState<Plan>(plan);
  const isNew = !p.id;
  const up = <K extends keyof Plan>(k: K, v: Plan[K]) => setP((x) => ({ ...x, [k]: v }));
  const save = useMutation({
    mutationFn: () => { const { id, subscribers, is_default, ...body } = p; void id; void subscribers; void is_default; return isNew ? api.post("/admin/plans", body) : api.put(`/admin/plans/${p.id}`, body); },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["admin"] }); qc.invalidateQueries({ queryKey: ["billing"] }); onClose(); },
  });
  const cents = (v: number | null) => Math.round((v ?? 0) * 100);
  const others = plans.filter((x) => x.id !== p.id);
  const toggleId = (k: "allowed_upgrade_to" | "allowed_downgrade_to", id: number) => up("rules", { ...p.rules, [k]: p.rules[k].includes(id) ? p.rules[k].filter((i) => i !== id) : [...p.rules[k], id] });
  return (
    <Modal title={isNew ? "New plan" : `Edit ${plan.name}`} onClose={onClose} wide>
      <div className="space-y-5">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Name"><input className="input" value={p.name} onChange={(e) => up("name", e.target.value)} /></Field>
          <Field label="Slug" hint="Lowercase letters, numbers, dashes"><input className="input" value={p.slug} disabled={p.is_default} onChange={(e) => up("slug", e.target.value.toLowerCase())} /></Field>
          <Field label="Description" className="sm:col-span-2"><input className="input" value={p.description} onChange={(e) => up("description", e.target.value)} /></Field>
          <Field label="Monthly price"><NumInput step={0.01} value={p.monthly_price_cents / 100} onChange={(v) => up("monthly_price_cents", cents(v))} placeholder="0 = free" /></Field>
          <Field label="Yearly price"><NumInput step={0.01} value={p.yearly_price_cents / 100} onChange={(v) => up("yearly_price_cents", cents(v))} placeholder="0 = none" /></Field>
          <Field label="Currency"><input className="input" maxLength={3} value={p.currency} onChange={(e) => up("currency", e.target.value.toUpperCase())} /></Field>
          <Field label="Free trial (days)" hint="0 = no trial"><NumInput value={p.trial_days} onChange={(v) => up("trial_days", v ?? 0)} placeholder="0" /></Field>
          <Field label="Sort order"><NumInput value={p.sort_order} onChange={(v) => up("sort_order", v ?? 0)} placeholder="0" /></Field>
        </div>
        <Toggle label="Plan enabled" hint="Disabled plans are hidden from new signups; existing subscribers keep them." checked={p.is_active} onChange={(v) => up("is_active", v)} disabled={p.is_default} />
        <section><h3 className="label">Usage limits <span className="normal-case text-slate-400">(empty = unlimited)</span></h3>
          <div className="grid gap-3 sm:grid-cols-2">{Object.entries(meta.limits).map(([k, label]) => <Field key={k} label={label}><NumInput aria-label={label} value={p.limits[k]} onChange={(v) => up("limits", { ...p.limits, [k]: v })} /></Field>)}</div></section>
        <section><h3 className="label">Features</h3>
          <div className="grid gap-x-6 sm:grid-cols-2">{Object.entries(meta.features).map(([k, label]) => <Toggle key={k} label={label} checked={p.features[k] !== false} onChange={(v) => up("features", { ...p.features, [k]: v })} />)}</div></section>
        <section><h3 className="label">Upgrade & downgrade rules</h3>
          <Toggle label="Allow upgrades from this plan" checked={p.rules.allow_upgrade} onChange={(v) => up("rules", { ...p.rules, allow_upgrade: v })} />
          <Toggle label="Allow downgrades from this plan" checked={p.rules.allow_downgrade} onChange={(v) => up("rules", { ...p.rules, allow_downgrade: v })} />
          <Toggle label="Prorate upgrades" checked={p.rules.prorate_upgrades} onChange={(v) => up("rules", { ...p.rules, prorate_upgrades: v })} />
          <Field label="Downgrades take effect" className="mt-2 max-w-xs"><select className="input" value={p.rules.downgrade_timing} onChange={(e) => up("rules", { ...p.rules, downgrade_timing: e.target.value as "immediate" | "period_end" })}><option value="period_end">At end of billing period</option><option value="immediate">Immediately</option></select></Field>
          {others.length > 0 && (["allowed_upgrade_to", "allowed_downgrade_to"] as const).map((k) => (
            <div key={k} className="mt-3"><p className="text-xs text-slate-500">{k === "allowed_upgrade_to" ? "Can upgrade to" : "Can downgrade to"} <span className="text-slate-400">(none selected = any plan)</span></p>
              <div className="mt-1 flex flex-wrap gap-2">{others.map((o) => <button key={o.id} type="button" onClick={() => toggleId(k, o.id)} aria-pressed={p.rules[k].includes(o.id)} className={`rounded-full border px-3 py-1 text-xs ${p.rules[k].includes(o.id) ? "border-brand-600 bg-brand-50 text-brand-700 dark:bg-brand-500/15" : "border-slate-200 text-slate-600 dark:border-white/10"}`}>{o.name}</button>)}</div></div>))}
          <p className="mt-2 text-xs text-slate-500">Rules apply to self-service changes. Admins can always assign any plan from the Users page.</p>
        </section>
        <ErrorNote error={save.error} />
        <div className="flex justify-end gap-2 border-t border-slate-100 pt-4 dark:border-white/5"><button className="btn-ghost" onClick={onClose}>Cancel</button><button className="btn-primary" disabled={save.isPending || !p.name || !p.slug} onClick={() => save.mutate()}>{save.isPending ? <Spinner /> : <CreditCard className="h-4 w-4" />} {isNew ? "Create plan" : "Save plan"}</button></div>
      </div>
    </Modal>
  );
}
