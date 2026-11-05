import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Tag, Trash2 } from "lucide-react";
import { useState } from "react";
import { api } from "../../api/client";
import { Badge, Card, Empty, ErrorNote, Loading, Spinner, Stat } from "../../components/ui";
import type { Plan, Promo } from "../../lib/types";
import { Modal, TableWrap, fmtDate } from "./common";
import { Field, NumInput, Toggle, money } from "./forms";

const blank = { id: 0, code: "", description: "", discount_type: "percent" as const, value: 10, expires_at: null as string | null, max_uses: null as number | null, per_user_limit: 1, plan_ids: [] as number[], first_time_only: false, is_active: true };
type Draft = typeof blank | (Omit<typeof blank, "discount_type"> & { discount_type: "percent" | "fixed" });

export default function PromosPanel() {
  const qc = useQueryClient();
  const promos = useQuery({ queryKey: ["admin", "promos"], queryFn: () => api.get<{ items: Promo[] }>("/admin/promos") });
  const plans = useQuery({ queryKey: ["admin", "plans"], queryFn: () => api.get<{ items: Plan[] }>("/admin/plans") });
  const [edit, setEdit] = useState<Draft | null>(null), [del, setDel] = useState<Promo | null>(null);
  const toggle = useMutation({ mutationFn: (p: Promo) => api.put(`/admin/promos/${p.id}`, { code: p.code, description: p.description, discount_type: p.discount_type, value: p.value, expires_at: p.expires_at, max_uses: p.max_uses, per_user_limit: p.per_user_limit, plan_ids: p.plan_ids, first_time_only: p.first_time_only, is_active: !p.is_active }), onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "promos"] }) });
  const rm = useMutation({ mutationFn: (id: number) => api.del(`/admin/promos/${id}`), onSuccess: () => { setDel(null); qc.invalidateQueries({ queryKey: ["admin", "promos"] }); } });
  if (promos.isLoading) return <Loading />;
  if (promos.error || !promos.data) return <ErrorNote error={promos.error} />;
  const items = promos.data.items;
  const uses = items.reduce((a, p) => a + p.uses, 0), disc = items.reduce((a, p) => a + p.discount_given_cents, 0), rev = items.reduce((a, p) => a + p.revenue_cents, 0);
  const label = (p: Promo) => (p.discount_type === "percent" ? `${p.value}% off` : `${money(p.value)} off`);
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Active codes" value={items.filter((p) => p.is_active && !p.expired).length} icon={Tag} /><Stat label="Redemptions" value={uses} tone="green" />
        <Stat label="Discounts given" value={money(disc)} tone="amber" hint="revenue impact" /><Stat label="Revenue from promo sales" value={money(rev)} tone="green" />
      </div>
      <Card pad={false} title="Promo codes" action={<button className="btn-primary !py-1" onClick={() => setEdit({ ...blank })}><Plus className="h-4 w-4" /> New code</button>}>
        {items.length === 0 ? <div className="p-6"><Empty icon={Tag} title="No promo codes yet" /></div> : (
          <TableWrap><thead><tr><th className="th">Code</th><th className="th">Discount</th><th className="th">Uses</th><th className="th">Expires</th><th className="th">Applies to</th><th className="th text-right">Discounted</th><th className="th">Active</th><th className="th" /></tr></thead>
            <tbody>{items.map((p) => (
              <tr key={p.id} className="hover:bg-slate-50 dark:hover:bg-white/5">
                <td className="td"><span className="font-mono font-semibold">{p.code}</span>{p.first_time_only && <Badge tone="brand"> first-time</Badge>}</td>
                <td className="td">{label(p)}</td><td className="td tabular-nums">{p.uses}{p.max_uses ? ` / ${p.max_uses}` : ""}<span className="text-xs text-slate-400"> · {p.per_user_limit}/user</span></td>
                <td className="td">{p.expires_at ? <span className={p.expired ? "text-red-600" : ""}>{fmtDate(p.expires_at)}{p.expired && " (expired)"}</span> : "Never"}</td>
                <td className="td text-slate-500">{p.plan_ids.length ? p.plan_ids.map((id) => plans.data?.items.find((x) => x.id === id)?.name ?? id).join(", ") : "All plans"}</td>
                <td className="td text-right tabular-nums">{money(p.discount_given_cents)}</td>
                <td className="td"><Toggle label={`${p.code} active`} checked={p.is_active} onChange={() => toggle.mutate(p)} disabled={toggle.isPending} /></td>
                <td className="td text-right whitespace-nowrap"><button className="rounded p-1.5 text-slate-400 hover:bg-slate-100 dark:hover:bg-white/10" aria-label={`Edit ${p.code}`} onClick={() => setEdit({ ...p })}><Pencil className="h-4 w-4" /></button>
                  <button className="rounded p-1.5 text-slate-400 hover:bg-red-50 hover:text-red-600" aria-label={`Delete ${p.code}`} onClick={() => setDel(p)}><Trash2 className="h-4 w-4" /></button></td>
              </tr>))}</tbody></TableWrap>)}
      </Card>
      <ErrorNote error={toggle.error} />
      {edit && <PromoEditor draft={edit} plans={plans.data?.items ?? []} onClose={() => setEdit(null)} />}
      {del && <Modal title="Delete promo code" onClose={() => setDel(null)}><p className="text-sm">Delete <b className="font-mono">{del.code}</b>? Codes that were redeemed can't be deleted (disable them instead to keep history).</p>
        <div className="mt-3"><ErrorNote error={rm.error} /></div><div className="mt-4 flex justify-end gap-2"><button className="btn-ghost" onClick={() => setDel(null)}>Cancel</button><button className="btn bg-red-600 text-white hover:bg-red-700" disabled={rm.isPending} onClick={() => rm.mutate(del.id)}>{rm.isPending && <Spinner />} Delete</button></div></Modal>}
    </div>
  );
}

function PromoEditor({ draft, plans, onClose }: { draft: Draft; plans: Plan[]; onClose: () => void }) {
  const qc = useQueryClient();
  const [d, setD] = useState<Draft>(draft);
  const up = <K extends keyof Draft>(k: K, v: Draft[K]) => setD((x) => ({ ...x, [k]: v }));
  const isNew = !d.id;
  const save = useMutation({
    mutationFn: () => { const { id, ...body } = d; void id; const payload = { ...body, expires_at: body.expires_at ? new Date(body.expires_at).toISOString() : null }; return isNew ? api.post("/admin/promos", payload) : api.put(`/admin/promos/${d.id}`, payload); },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["admin", "promos"] }); onClose(); },
  });
  const dateVal = d.expires_at ? new Date(d.expires_at).toISOString().slice(0, 10) : "";
  return (
    <Modal title={isNew ? "New promo code" : `Edit ${d.code}`} onClose={onClose} wide>
      <div className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Code" hint="Letters, numbers, - and _ (case-insensitive)"><input className="input font-mono uppercase" value={d.code} onChange={(e) => up("code", e.target.value.toUpperCase())} /></Field>
          <Field label="Description"><input className="input" value={d.description} onChange={(e) => up("description", e.target.value)} /></Field>
          <Field label="Discount type"><select className="input" value={d.discount_type} onChange={(e) => up("discount_type", e.target.value as "percent" | "fixed")}><option value="percent">Percentage</option><option value="fixed">Fixed amount</option></select></Field>
          <Field label={d.discount_type === "percent" ? "Percent off (1–100)" : "Amount off"}><NumInput step={d.discount_type === "percent" ? 1 : 0.01} min={0} value={d.discount_type === "percent" ? d.value : d.value / 100} onChange={(v) => up("value", d.discount_type === "percent" ? (v ?? 0) : Math.round((v ?? 0) * 100))} placeholder="0" /></Field>
          <Field label="Expires" hint="Empty = never"><input type="date" className="input" value={dateVal} onChange={(e) => up("expires_at", e.target.value ? `${e.target.value}T23:59:59Z` : null)} /></Field>
          <Field label="Max total uses" hint="Empty = unlimited"><NumInput min={1} value={d.max_uses} onChange={(v) => up("max_uses", v)} /></Field>
          <Field label="Uses per user"><NumInput min={1} value={d.per_user_limit} onChange={(v) => up("per_user_limit", v ?? 1)} placeholder="1" /></Field>
        </div>
        <div><p className="label">Restrict to plans <span className="normal-case text-slate-400">(none = all)</span></p>
          <div className="flex flex-wrap gap-2">{plans.map((p) => { const on = d.plan_ids.includes(p.id); return <button key={p.id} type="button" aria-pressed={on} onClick={() => up("plan_ids", on ? d.plan_ids.filter((i) => i !== p.id) : [...d.plan_ids, p.id])} className={`rounded-full border px-3 py-1 text-xs ${on ? "border-brand-600 bg-brand-50 text-brand-700 dark:bg-brand-500/15" : "border-slate-200 text-slate-600 dark:border-white/10"}`}>{p.name}</button>; })}</div></div>
        <Toggle label="First-time customers only" hint="Only users with no previous successful payment" checked={d.first_time_only} onChange={(v) => up("first_time_only", v)} />
        <Toggle label="Active" checked={d.is_active} onChange={(v) => up("is_active", v)} />
        <ErrorNote error={save.error} />
        <div className="flex justify-end gap-2 border-t border-slate-100 pt-4 dark:border-white/5"><button className="btn-ghost" onClick={onClose}>Cancel</button><button className="btn-primary" disabled={save.isPending || d.code.length < 3} onClick={() => save.mutate()}>{save.isPending && <Spinner />} {isNew ? "Create code" : "Save"}</button></div>
      </div>
    </Modal>
  );
}
