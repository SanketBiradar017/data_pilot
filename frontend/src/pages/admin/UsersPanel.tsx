import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, Download, RotateCcw, Trash2, Users } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { Badge, Card, Empty, ErrorNote, Loading, Spinner } from "../../components/ui";
import { ago } from "../../lib/format";
import { useAuth } from "../../lib/auth";
import type { AdminUser, AdminUserDetail, Plan, Tx } from "../../lib/types";
import { money } from "./forms";
import { KV, Modal, Pager, SearchBox, Select, TableWrap, fmtBytes, fmtDate, fmtDateTime, fmtNum, useDebounced, type Paged } from "./common";

const statusTone = (s: string) => (s === "active" ? "green" : "red");
const roleTone = (r: string) => (r === "super_admin" ? "brand" : r === "admin" ? "amber" : "slate");

export default function UsersPanel() {
  const qc = useQueryClient();
  const [q, setQ] = useState(""), [status, setStatus] = useState(""), [role, setRole] = useState("");
  const [sort, setSort] = useState("created_at"), [order, setOrder] = useState<"asc" | "desc">("desc"), [page, setPage] = useState(1);
  const [openId, setOpenId] = useState<number | null>(null);
  const [exporting, setExporting] = useState(false), [exportErr, setExportErr] = useState<unknown>(null);
  const dq = useDebounced(q);
  useEffect(() => setPage(1), [dq, status, role, sort, order]);

  const params = new URLSearchParams({ sort, order });
  if (dq) params.set("q", dq); if (status) params.set("status", status); if (role) params.set("role", role);
  const { data, error, isLoading, isFetching } = useQuery({ queryKey: ["admin", "users", params.toString(), page], placeholderData: (p) => p,
    queryFn: () => api.get<Paged<AdminUser>>(`/admin/users?${params}&page=${page}&page_size=20`) });

  const exportCsv = async () => { setExporting(true); setExportErr(null); try { await api.download(`/admin/users/export.csv?${params}`, "users.csv"); } catch (e) { setExportErr(e); } finally { setExporting(false); } };
  const sortBy = (c: string) => { if (sort === c) setOrder(order === "asc" ? "desc" : "asc"); else { setSort(c); setOrder("asc"); } };
  const arrow = (c: string) => (sort === c ? (order === "asc" ? " ↑" : " ↓") : "");
  const refresh = () => { qc.invalidateQueries({ queryKey: ["admin"] }); };

  return (
    <Card pad={false}>
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 p-4 dark:border-white/5">
        <SearchBox value={q} onChange={setQ} placeholder="Search name or email…" />
        <Select label="Status" value={status} onChange={setStatus} options={[["", "All statuses"], ["active", "Active"], ["suspended", "Suspended"]]} />
        <Select label="Role" value={role} onChange={setRole} options={[["", "All roles"], ["analyst", "Analyst"], ["admin", "Admin"], ["super_admin", "Super admin"]]} />
        <button className="btn-ghost ml-auto" onClick={exportCsv} disabled={exporting}>{exporting ? <Spinner /> : <Download className="h-4 w-4" />} Export CSV</button>
      </div>
      {(error || exportErr) ? <div className="p-4"><ErrorNote error={error ?? exportErr} /></div> : null}
      {isLoading || !data ? <Loading /> : data.items.length === 0 ? <div className="p-6"><Empty icon={Users} title="No users match" text="Try a different search or filter." /></div> : (
        <div className={isFetching ? "opacity-70 transition-opacity" : ""}>
          <TableWrap>
            <thead><tr>
              <th className="th cursor-pointer" onClick={() => sortBy("email")}>User{arrow("email")}</th>
              <th className="th">Status</th><th className="th">Role</th><th className="th">Plan</th>
              <th className="th cursor-pointer" onClick={() => sortBy("created_at")}>Registered{arrow("created_at")}</th>
              <th className="th cursor-pointer" onClick={() => sortBy("last_login_at")}>Last login{arrow("last_login_at")}</th>
              <th className="th text-right">Datasets</th><th className="th text-right">Analyses</th>
            </tr></thead>
            <tbody>{data.items.map((u) => (
              <tr key={u.id} tabIndex={0} onClick={() => setOpenId(u.id)} onKeyDown={(e) => e.key === "Enter" && setOpenId(u.id)} className="cursor-pointer hover:bg-slate-50 focus:bg-slate-50 focus:outline-none dark:hover:bg-white/5 dark:focus:bg-white/5">
                <td className="td"><span className="block font-medium text-slate-900 dark:text-white">{u.name || "—"}</span><span className="text-xs text-slate-500">{u.email}</span></td>
                <td className="td"><Badge tone={statusTone(u.status)}>{u.status}</Badge></td>
                <td className="td"><Badge tone={roleTone(u.role)}>{u.role.replace("_", " ")}</Badge></td>
                <td className="td">{(u as AdminUser & { plan?: string }).plan ?? "Free"}</td>
                <td className="td">{fmtDate(u.created_at)}</td>
                <td className="td" title={fmtDateTime(u.last_login_at)}>{u.last_login_at ? ago(u.last_login_at) : <span className="text-slate-400">Never</span>}</td>
                <td className="td text-right tabular-nums">{u.datasets}</td><td className="td text-right tabular-nums">{u.analyses}</td>
              </tr>))}</tbody>
          </TableWrap>
          <Pager p={data} onPage={setPage} />
        </div>
      )}
      {openId != null && <UserDrawer id={openId} onClose={() => setOpenId(null)} onChanged={refresh} />}
    </Card>
  );
}

function UserDrawer({ id, onClose, onChanged }: { id: number; onClose: () => void; onChanged: () => void }) {
  const { data: u, error, isLoading, refetch } = useQuery({ queryKey: ["admin", "user", id], queryFn: () => api.get<AdminUserDetail>(`/admin/users/${id}`) });
  const [confirmDelete, setConfirmDelete] = useState(false), [typed, setTyped] = useState("");
  const toggle = useMutation({ mutationFn: (act: "suspend" | "reactivate") => api.post(`/admin/users/${id}/${act}`), onSuccess: () => { refetch(); onChanged(); } });
  const del = useMutation({ mutationFn: () => api.post(`/admin/users/${id}/delete`, { confirm_email: typed }), onSuccess: () => { onChanged(); onClose(); } });
  const protectedUser = u?.role === "super_admin";

  return (
    <Modal title="User details" onClose={onClose} wide>
      {isLoading ? <Loading /> : error || !u ? <ErrorNote error={error} /> : (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center gap-3">
            <span className="flex h-11 w-11 items-center justify-center rounded-full bg-brand-600 text-lg font-semibold text-white">{(u.name || u.email)[0].toUpperCase()}</span>
            <div className="min-w-0 flex-1"><p className="truncate font-semibold text-slate-900 dark:text-white">{u.name || "—"}</p><p className="truncate text-sm text-slate-500">{u.email}</p></div>
            <Badge tone={statusTone(u.status)}>{u.status}</Badge><Badge tone={roleTone(u.role)}>{u.role.replace("_", " ")}</Badge>
          </div>
          <dl className="grid grid-cols-2 gap-4 sm:grid-cols-3">
            <KV k="Registered" v={fmtDate(u.created_at)} /><KV k="Last login" v={fmtDateTime(u.last_login_at)} /><KV k="Storage" v={fmtBytes(u.storage_bytes)} />
            <KV k="Datasets" v={u.datasets} /><KV k="Analyses" v={u.analyses} /><KV k="Reports" v={u.reports} />
            <KV k="API calls (30d)" v={fmtNum(u.api_requests_30d)} /><KV k="LLM calls" v={fmtNum(u.llm_calls)} /><KV k="Tokens in / out" v={`${fmtNum(u.input_tokens)} / ${fmtNum(u.output_tokens)}`} />
          </dl>
          <div className="grid gap-4 sm:grid-cols-2">
            <div><h3 className="label">Recent datasets</h3>{u.recent_datasets.length ? <ul className="space-y-1 text-sm">{u.recent_datasets.slice(0, 5).map((d) => <li key={d.id} className="flex justify-between gap-2"><span className="truncate">{d.name}</span><span className="shrink-0 text-xs text-slate-500">{fmtBytes(d.size_bytes)}</span></li>)}</ul> : <p className="text-sm text-slate-500">None</p>}</div>
            <div><h3 className="label">Recent activity</h3>{u.recent_activity.length ? <ul className="space-y-1 text-sm">{u.recent_activity.slice(0, 5).map((a) => <li key={a.id} className="flex justify-between gap-2"><span className="truncate font-mono text-xs">{a.action}</span><span className="shrink-0 text-xs text-slate-500">{ago(a.created_at)}</span></li>)}</ul> : <p className="text-sm text-slate-500">None</p>}</div>
          </div>
          <AccessSection u={u} onChanged={() => { refetch(); onChanged(); }} />
          <ErrorNote error={toggle.error ?? del.error} />
          {protectedUser ? <p className="rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-500 dark:bg-white/5">Super admin accounts can't be suspended or deleted from the panel.</p> : !confirmDelete ? (
            <div className="flex flex-wrap gap-2 border-t border-slate-100 pt-4 dark:border-white/5">
              {u.status === "active"
                ? <button className="btn-ghost" disabled={toggle.isPending} onClick={() => toggle.mutate("suspend")}>{toggle.isPending ? <Spinner /> : <Ban className="h-4 w-4" />} Suspend</button>
                : <button className="btn-ghost" disabled={toggle.isPending} onClick={() => toggle.mutate("reactivate")}>{toggle.isPending ? <Spinner /> : <RotateCcw className="h-4 w-4" />} Reactivate</button>}
              <button className="btn-danger ml-auto" onClick={() => setConfirmDelete(true)}><Trash2 className="h-4 w-4" /> Delete user…</button>
            </div>
          ) : (
            <div className="space-y-3 rounded-lg border border-red-200 bg-red-50 p-4 dark:border-red-500/30 dark:bg-red-500/10">
              <p className="text-sm text-red-800 dark:text-red-200">Permanently deletes this account and all of its datasets, analyses, conversations and reports. <b>This can't be undone.</b> Type <span className="font-mono">{u.email}</span> to confirm.</p>
              <input className="input" value={typed} onChange={(e) => setTyped(e.target.value)} placeholder={u.email} aria-label="Confirm email" autoFocus />
              <div className="flex gap-2">
                <button className="btn bg-red-600 text-white hover:bg-red-700" disabled={typed.trim().toLowerCase() !== u.email.toLowerCase() || del.isPending} onClick={() => del.mutate()}>{del.isPending ? <Spinner /> : <Trash2 className="h-4 w-4" />} Delete permanently</button>
                <button className="btn-ghost" onClick={() => { setConfirmDelete(false); setTyped(""); }}>Cancel</button>
              </div>
            </div>
          )}
        </div>
      )}
    </Modal>
  );
}


interface BillingResp { plan: { id: number; name: string }; subscription: { status: string; interval: string; current_period_end: string | null; assigned_by_admin: boolean } | null; usage: Record<string, number>; limits: Record<string, number | null>; transactions: Tx[] }
const LIMIT_LABELS: Record<string, string> = { max_datasets: "Datasets", storage_mb: "Storage (MB)", ai_analyses_per_month: "AI analyses / mo", reports_per_month: "Reports / mo", chat_messages_per_month: "Chat msgs / mo" };

/** Role, subscription plan and billing history for one user. */
function AccessSection({ u, onChanged }: { u: AdminUserDetail; onChanged: () => void }) {
  const { user: me } = useAuth();
  const qc = useQueryClient();
  const bill = useQuery({ queryKey: ["admin", "user-billing", u.id], queryFn: () => api.get<BillingResp>(`/admin/users/${u.id}/billing`) });
  const plans = useQuery({ queryKey: ["admin", "plans"], queryFn: () => api.get<{ items: Plan[] }>("/admin/plans") });
  const [planId, setPlanId] = useState(0), [interval, setInterval] = useState("monthly"), [days, setDays] = useState("");
  const [role, setRole] = useState(u.role);
  const refresh = () => { qc.invalidateQueries({ queryKey: ["admin"] }); onChanged(); };
  const roleM = useMutation({ mutationFn: () => api.post(`/admin/users/${u.id}/role`, { role }), onSuccess: refresh });
  const planM = useMutation({ mutationFn: () => api.post(`/admin/users/${u.id}/subscription`, { plan_id: planId, interval, days: days ? Number(days) : null }), onSuccess: refresh });
  const self = me?.id === u.id;
  const b = bill.data;
  return (
    <div className="space-y-4 border-t border-slate-100 pt-4 dark:border-white/5">
      <div>
        <h3 className="label">Role</h3>
        <div className="flex flex-wrap items-center gap-2">
          <select className="input w-auto" value={role} disabled={self} onChange={(e) => setRole(e.target.value)} aria-label="Role"><option value="analyst">Analyst</option><option value="admin">Admin</option><option value="super_admin">Super admin</option></select>
          <button className="btn-ghost" disabled={self || role === u.role || roleM.isPending} onClick={() => roleM.mutate()}>{roleM.isPending && <Spinner />} Change role</button>
          {self && <span className="text-xs text-slate-500">You can't change your own role.</span>}
          {role === "super_admin" && role !== u.role && <span className="text-xs text-amber-600">Grants full control of the platform.</span>}
        </div>
      </div>
      <div>
        <h3 className="label">Subscription</h3>
        {bill.isLoading ? <Loading /> : b && (<>
          <p className="text-sm"><b>{b.plan.name}</b>{b.subscription ? <> · {b.subscription.status} · {b.subscription.interval}{b.subscription.current_period_end && <> · until {fmtDate(b.subscription.current_period_end)}</>}{b.subscription.assigned_by_admin && <span className="text-xs text-slate-400"> (assigned by admin)</span>}</> : <span className="text-slate-500"> · default plan</span>}</p>
          <ul className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1 text-xs sm:grid-cols-3">{Object.entries(LIMIT_LABELS).map(([k, l]) => <li key={k} className="flex justify-between"><span className="text-slate-500">{l}</span><b className="tabular-nums">{b.usage[k] ?? 0} / {b.limits[k] ?? "∞"}</b></li>)}</ul></>)}
        <div className="mt-3 flex flex-wrap items-end gap-2">
          <select className="input w-auto" value={planId} onChange={(e) => setPlanId(Number(e.target.value))} aria-label="Plan"><option value={0}>Assign plan…</option>{plans.data?.items.map((p) => <option key={p.id} value={p.id}>{p.name}{p.is_active ? "" : " (disabled)"}</option>)}</select>
          <select className="input w-auto" value={interval} onChange={(e) => setInterval(e.target.value)} aria-label="Billing interval"><option value="monthly">Monthly</option><option value="yearly">Yearly</option></select>
          <input className="input w-28" type="number" min={1} placeholder="Days (opt.)" value={days} onChange={(e) => setDays(e.target.value)} aria-label="Access length in days" />
          <button className="btn-primary" disabled={!planId || planM.isPending} onClick={() => planM.mutate()}>{planM.isPending && <Spinner />} Assign</button>
        </div>
        <p className="mt-1 text-xs text-slate-500">Assigning a plan manually does not charge the user. Use Payments → Record payment to log revenue.</p>
      </div>
      {b && b.transactions.length > 0 && <div><h3 className="label">Payment history</h3><ul className="space-y-1 text-sm">{b.transactions.slice(0, 5).map((t) => <li key={t.id} className="flex justify-between gap-2"><span className="truncate">{fmtDate(t.created_at)} · {t.plan_name} · {t.kind}</span><span className="shrink-0 tabular-nums">{money(t.amount_cents, t.currency)} <Badge tone={t.status === "succeeded" ? "green" : t.status === "failed" ? "red" : "amber"}>{t.status}</Badge></span></li>)}</ul></div>}
      <ErrorNote error={roleM.error ?? planM.error} />
    </div>
  );
}
