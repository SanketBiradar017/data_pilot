import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Receipt, Undo2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { Badge, Card, Empty, ErrorNote, Loading, Spinner, Stat } from "../../components/ui";
import type { AdminUser, Plan, Tx } from "../../lib/types";
import { Modal, Pager, SearchBox, Select, TableWrap, fmtDateTime, useDebounced, type Paged } from "./common";
import { Field, SecretBadge, SettingsCard, Toggle, money } from "./forms";

const tone = (s: string) => (s === "succeeded" ? "green" : s === "failed" ? "red" : s === "refunded" ? "amber" : "slate") as "green" | "red" | "amber" | "slate";
type TxResp = Paged<Tx> & { summary: { gross_cents: number; refunded_cents: number; net_cents: number; failed: number; renewals: number } };

export default function PaymentsPanel() {
  const qc = useQueryClient();
  const [q, setQ] = useState(""), [status, setStatus] = useState(""), [kind, setKind] = useState(""), [page, setPage] = useState(1);
  const [record, setRecord] = useState(false), [refund, setRefund] = useState<Tx | null>(null);
  const dq = useDebounced(q);
  useEffect(() => setPage(1), [dq, status, kind]);
  const p = new URLSearchParams({ page: String(page) }); if (dq) p.set("q", dq); if (status) p.set("status", status); if (kind) p.set("kind", kind);
  const { data, error, isLoading } = useQuery({ queryKey: ["admin", "tx", p.toString()], placeholderData: (x) => x, queryFn: () => api.get<TxResp>(`/admin/transactions?${p}`) });
  const cur = data?.items[0]?.currency;
  return (
    <div className="space-y-6">
      {isLoading ? <Loading /> : error || !data ? <ErrorNote error={error} /> : (<>
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
          <Stat label="Gross revenue" value={money(data.summary.gross_cents, cur)} icon={Receipt} tone="green" /><Stat label="Refunds" value={money(data.summary.refunded_cents, cur)} tone="amber" />
          <Stat label="Net revenue" value={money(data.summary.net_cents, cur)} tone="green" /><Stat label="Failed payments" value={data.summary.failed} tone={data.summary.failed ? "red" : "green"} /><Stat label="Renewals" value={data.summary.renewals} />
        </div>
        <Card pad={false} title="Transactions" action={<button className="btn-primary !py-1" onClick={() => setRecord(true)}><Plus className="h-4 w-4" /> Record payment</button>}>
          <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 p-4 dark:border-white/5">
            <SearchBox value={q} onChange={setQ} placeholder="Search email, reference, promo…" />
            <Select label="Status" value={status} onChange={setStatus} options={[["", "All statuses"], ["succeeded", "Succeeded"], ["failed", "Failed"], ["pending", "Pending"], ["refunded", "Refunded"]]} />
            <Select label="Type" value={kind} onChange={setKind} options={[["", "All types"], ["subscription", "New subscription"], ["renewal", "Renewal"], ["refund", "Refund"]]} />
          </div>
          {data.items.length === 0 ? <div className="p-6"><Empty icon={Receipt} title="No transactions" text="Payments appear here when recorded by an admin or received from a payment gateway." /></div> : (<>
            <TableWrap><thead><tr><th className="th">Date</th><th className="th">User</th><th className="th">Plan</th><th className="th">Type</th><th className="th text-right">Amount</th><th className="th">Status</th><th className="th">Promo</th><th className="th" /></tr></thead>
              <tbody>{data.items.map((t) => (
                <tr key={t.id} className="hover:bg-slate-50 dark:hover:bg-white/5">
                  <td className="td text-slate-500">{fmtDateTime(t.created_at)}</td><td className="td">{t.user_email || "—"}</td><td className="td">{t.plan_name} <span className="text-xs text-slate-400">{t.interval}</span></td>
                  <td className="td"><Badge tone={t.kind === "refund" ? "amber" : "slate"}>{t.kind}</Badge></td>
                  <td className={`td text-right tabular-nums ${t.amount_cents < 0 ? "text-amber-600" : ""}`}>{money(t.amount_cents, t.currency)}{t.discount_cents > 0 && <span className="block text-xs text-slate-400">−{money(t.discount_cents, t.currency)}</span>}</td>
                  <td className="td"><Badge tone={tone(t.status)}>{t.status}</Badge></td><td className="td font-mono text-xs">{t.promo_code || "—"}</td>
                  <td className="td text-right">{t.status === "succeeded" && t.kind !== "refund" && t.amount_cents > 0 && <button className="btn-ghost !px-2 !py-1 text-xs" onClick={() => setRefund(t)}><Undo2 className="h-3.5 w-3.5" /> Refund</button>}</td>
                </tr>))}</tbody></TableWrap><Pager p={data} onPage={setPage} /></>)}
        </Card></>)}
      <SettingsCard group="payments" title="Payment gateway settings">{(f) => (
        <div className="space-y-4">
          <p className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600 dark:bg-white/5 dark:text-slate-300">Online checkout isn't connected yet: with the <b>manual</b> gateway, paid plans are assigned by an admin and payments are recorded here. These settings are stored for when a gateway integration is added.</p>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Gateway"><select className="input" value={f.draft!.gateway} onChange={(e) => f.set("gateway", e.target.value)}><option value="manual">Manual / invoice</option><option value="stripe">Stripe</option><option value="paypal">PayPal</option><option value="razorpay">Razorpay</option></select></Field>
            <Field label="Mode"><select className="input" value={f.draft!.mode} onChange={(e) => f.set("mode", e.target.value)}><option value="test">Test</option><option value="live">Live</option></select></Field>
            <Field label="Default currency"><input className="input" maxLength={3} value={f.draft!.currency} onChange={(e) => f.set("currency", e.target.value.toUpperCase())} /></Field>
            <Field label="Statement descriptor" hint="Max 22 characters"><input className="input" maxLength={22} value={f.draft!.statement_descriptor} onChange={(e) => f.set("statement_descriptor", e.target.value)} /></Field>
            <Field label="Webhook URL" className="sm:col-span-2"><input className="input" value={f.draft!.webhook_url} onChange={(e) => f.set("webhook_url", e.target.value)} placeholder="https://…" /></Field>
          </div>
          <Toggle label="Online payments enabled" checked={f.draft!.enabled} onChange={(v) => f.set("enabled", v)} />
          <SecretBadge name="PAYMENT_GATEWAY_SECRET" set={f.q.data?.secrets?.payment_gateway_secret_set} />
        </div>)}</SettingsCard>
      {record && <RecordModal onClose={() => setRecord(false)} />}
      {refund && <RefundModal tx={refund} onClose={() => setRefund(null)} onDone={() => qc.invalidateQueries({ queryKey: ["admin"] })} />}
    </div>
  );
}

function RecordModal({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const [email, setEmail] = useState(""), [planId, setPlanId] = useState(0), [interval, setInterval] = useState("monthly"), [promo, setPromo] = useState(""), [status, setStatus] = useState("succeeded"), [ref, setRef] = useState(""), [note, setNote] = useState("");
  const de = useDebounced(email, 250);
  const users = useQuery({ queryKey: ["admin", "usersearch", de], enabled: de.length >= 2, queryFn: () => api.get<Paged<AdminUser>>(`/admin/users?q=${encodeURIComponent(de)}&page_size=5`) });
  const plans = useQuery({ queryKey: ["admin", "plans"], queryFn: () => api.get<{ items: Plan[] }>("/admin/plans") });
  const [uid, setUid] = useState<number | null>(null);
  const save = useMutation({ mutationFn: () => api.post("/admin/transactions", { user_id: uid, plan_id: planId, interval, status, promo_code: promo, gateway_ref: ref, note }), onSuccess: () => { qc.invalidateQueries({ queryKey: ["admin"] }); onClose(); } });
  return (
    <Modal title="Record payment" onClose={onClose}>
      <div className="space-y-3">
        <Field label="User" hint="Search by email or name"><input className="input" value={email} onChange={(e) => { setEmail(e.target.value); setUid(null); }} placeholder="user@example.com" /></Field>
        {!uid && users.data?.items.map((u) => <button key={u.id} className="block w-full rounded-lg border border-slate-200 px-3 py-1.5 text-left text-sm hover:bg-slate-50 dark:border-white/10 dark:hover:bg-white/5" onClick={() => { setUid(u.id); setEmail(u.email); }}>{u.email}</button>)}
        <Field label="Plan"><select className="input" value={planId} onChange={(e) => setPlanId(Number(e.target.value))}><option value={0}>Select…</option>{plans.data?.items.map((p) => <option key={p.id} value={p.id}>{p.name} — {money(p.monthly_price_cents, p.currency)}/mo</option>)}</select></Field>
        <div className="grid grid-cols-2 gap-3"><Field label="Billing"><select className="input" value={interval} onChange={(e) => setInterval(e.target.value)}><option value="monthly">Monthly</option><option value="yearly">Yearly</option></select></Field>
          <Field label="Status"><select className="input" value={status} onChange={(e) => setStatus(e.target.value)}><option value="succeeded">Succeeded</option><option value="pending">Pending</option><option value="failed">Failed</option></select></Field></div>
        <Field label="Promo code" hint="Validated against its rules"><input className="input font-mono uppercase" value={promo} onChange={(e) => setPromo(e.target.value.toUpperCase())} /></Field>
        <Field label="Reference"><input className="input" value={ref} onChange={(e) => setRef(e.target.value)} placeholder="Invoice / transfer ID" /></Field>
        <Field label="Note"><input className="input" value={note} onChange={(e) => setNote(e.target.value)} /></Field>
        <p className="text-xs text-slate-500">A succeeded payment activates the plan for the user.</p>
        <ErrorNote error={save.error} />
        <div className="flex justify-end gap-2"><button className="btn-ghost" onClick={onClose}>Cancel</button><button className="btn-primary" disabled={!uid || !planId || save.isPending} onClick={() => save.mutate()}>{save.isPending && <Spinner />} Record</button></div>
      </div>
    </Modal>
  );
}

function RefundModal({ tx, onClose, onDone }: { tx: Tx; onClose: () => void; onDone: () => void }) {
  const [note, setNote] = useState("");
  const m = useMutation({ mutationFn: () => api.post(`/admin/transactions/${tx.id}/refund`, { note }), onSuccess: () => { onDone(); onClose(); } });
  return (
    <Modal title="Refund payment" onClose={onClose}>
      <p className="text-sm">Refund <b>{money(tx.amount_cents, tx.currency)}</b> to {tx.user_email}?</p>
      <p className="mt-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:bg-amber-500/10 dark:text-amber-300">This records the refund in DataPilot's books. If the money was taken through a payment gateway, issue the refund there as well.</p>
      <div className="mt-3"><Field label="Reason (optional)"><input className="input" value={note} onChange={(e) => setNote(e.target.value)} /></Field></div>
      <div className="mt-3"><ErrorNote error={m.error} /></div>
      <div className="mt-4 flex justify-end gap-2"><button className="btn-ghost" onClick={onClose}>Cancel</button><button className="btn bg-red-600 text-white hover:bg-red-700" disabled={m.isPending} onClick={() => m.mutate()}>{m.isPending && <Spinner />} Refund</button></div>
    </Modal>
  );
}
