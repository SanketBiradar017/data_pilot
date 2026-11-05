import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, Cpu, Database, HardDrive, Trash2, UserCheck, UserPlus, Users } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../../api/client";
import { Badge, Card, Empty, ErrorNote, Loading, Stat } from "../../components/ui";
import { ago } from "../../lib/format";
import type { AdminActivity, AdminDataset, AdminOverview, ApiUsage, SystemHealth, TokenUsage } from "../../lib/types";
import { UploadSettings } from "./ConfigPanels";
import { AXIS, Modal, Pager, SearchBox, Select, TableWrap, fmtBytes, fmtDate, fmtNum, fmtUptime, shortDay, useDebounced, type Paged } from "./common";

const BRAND = "#6366f1", SKY = "#38bdf8", RED = "#ef4444";
const grid = <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,.2)" vertical={false} />;

function Query<T>({ q, children }: { q: { data?: T; error: unknown; isLoading: boolean }; children: (d: T) => ReactNode }) {
  if (q.isLoading) return <Loading />;
  if (q.error || !q.data) return <ErrorNote error={q.error} />;
  return <>{children(q.data)}</>;
}

// ------------------------------------------------------------------ overview
export function OverviewPanel() {
  const q = useQuery({ queryKey: ["admin", "overview"], queryFn: () => api.get<AdminOverview>("/admin/overview") });
  return <Query q={q}>{(o) => (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-3 xl:grid-cols-6">
        <Stat label="Registered users" value={o.total_users} icon={Users} hint={`${o.suspended_users} suspended`} />
        <Stat label="Active users (30d)" value={o.active_users} icon={UserCheck} tone="green" />
        <Stat label="New (7d)" value={o.new_users_7d} icon={UserPlus} tone="amber" hint={`${o.new_users_30d} in 30 days`} />
        <Stat label="Datasets" value={o.datasets} icon={Database} hint={fmtBytes(o.storage_bytes)} />
        <Stat label="Analyses" value={o.analyses} icon={Activity} hint={`${o.analyses_7d} this week`} />
        <Stat label="Failed (7d)" value={o.failed_analyses_7d} icon={Cpu} tone={o.failed_analyses_7d ? "red" : "green"} />
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="New registrations · 30 days"><Series data={o.signups_by_day} /></Card>
        <Card title="Analyses run · 30 days"><Series data={o.analyses_by_day} color={SKY} /></Card>
      </div>
    </div>
  )}</Query>;
}

function Series({ data, color = BRAND }: { data: { date: string; count: number }[]; color?: string }) {
  return (
    <ResponsiveContainer width="100%" height={220}>
      <AreaChart data={data} margin={{ left: -20, right: 8, top: 4 }}>
        {grid}<XAxis dataKey="date" tickFormatter={shortDay} tick={AXIS} minTickGap={24} /><YAxis allowDecimals={false} tick={AXIS} />
        <Tooltip /><Area type="monotone" dataKey="count" name="Count" stroke={color} fill={color} fillOpacity={0.15} strokeWidth={2} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

// ------------------------------------------------------------------ datasets
export function DatasetsPanel() {
  const qc = useQueryClient();
  const [q, setQ] = useState(""), [kind, setKind] = useState(""), [page, setPage] = useState(1), [del, setDel] = useState<AdminDataset | null>(null);
  const dq = useDebounced(q);
  useEffect(() => setPage(1), [dq, kind]);
  const p = new URLSearchParams({ page: String(page) }); if (dq) p.set("q", dq); if (kind) p.set("kind", kind);
  const query = useQuery({ queryKey: ["admin", "datasets", p.toString()], placeholderData: (x) => x,
    queryFn: () => api.get<Paged<AdminDataset> & { totals: { datasets: number; size_bytes: number; rows: number }; by_source_type: { source_type: string; count: number }[] }>(`/admin/datasets?${p}`) });
  const rm = useMutation({ mutationFn: (id: number) => api.del(`/admin/datasets/${id}`), onSuccess: () => { setDel(null); qc.invalidateQueries({ queryKey: ["admin"] }); } });
  return <Query q={query}>{(d) => (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Datasets" value={d.totals.datasets} icon={Database} /><Stat label="Total rows" value={d.totals.rows} icon={Activity} tone="green" />
        <Stat label="Storage used" value={fmtBytes(d.totals.size_bytes)} icon={HardDrive} tone="amber" />
        <div className="card p-5"><p className="text-sm text-slate-500">By type</p><div className="mt-2 flex flex-wrap gap-1.5">{d.by_source_type.length ? d.by_source_type.map((s) => <Badge key={s.source_type} tone="brand">{s.source_type} · {s.count}</Badge>) : <span className="text-sm text-slate-400">—</span>}</div></div>
      </div>
      <Card pad={false}>
        <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 p-4 dark:border-white/5">
          <SearchBox value={q} onChange={setQ} placeholder="Search dataset or owner…" />
          <Select label="Kind" value={kind} onChange={setKind} options={[["", "All kinds"], ["table", "Tables"], ["document", "Documents"]]} />
        </div>
        {d.items.length === 0 ? <div className="p-6"><Empty icon={Database} title="No datasets" /></div> : (<>
          <TableWrap>
            <thead><tr><th className="th">Name</th><th className="th">Owner</th><th className="th">Type</th><th className="th text-right">Rows × cols</th><th className="th text-right">Size</th><th className="th text-right">Quality</th><th className="th">Created</th><th className="th" /></tr></thead>
            <tbody>{d.items.map((x) => (
              <tr key={x.id} className="hover:bg-slate-50 dark:hover:bg-white/5">
                <td className="td max-w-[240px] truncate font-medium">{x.name}</td><td className="td text-slate-500">{x.owner_email}</td>
                <td className="td"><Badge>{x.source_type}</Badge></td>
                <td className="td text-right tabular-nums">{x.kind === "table" ? `${x.row_count.toLocaleString()} × ${x.column_count}` : "—"}</td>
                <td className="td text-right tabular-nums">{fmtBytes(x.size_bytes)}</td><td className="td text-right tabular-nums">{x.quality_score ?? "—"}</td>
                <td className="td">{fmtDate(x.created_at)}</td>
                <td className="td text-right"><button className="rounded p-1.5 text-slate-400 hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-500/10" onClick={() => setDel(x)} aria-label={`Delete ${x.name}`}><Trash2 className="h-4 w-4" /></button></td>
              </tr>))}</tbody>
          </TableWrap><Pager p={d} onPage={setPage} /></>)}
      </Card>
      <UploadSettings />
      {del && (
        <Modal title="Delete dataset" onClose={() => setDel(null)}>
          <p className="text-sm text-slate-600 dark:text-slate-300">Delete <b>{del.name}</b> owned by {del.owner_email}? The data file is removed permanently.</p>
          <div className="mt-4"><ErrorNote error={rm.error} /></div>
          <div className="mt-4 flex justify-end gap-2"><button className="btn-ghost" onClick={() => setDel(null)}>Cancel</button><button className="btn bg-red-600 text-white hover:bg-red-700" disabled={rm.isPending} onClick={() => rm.mutate(del.id)}>Delete</button></div>
        </Modal>)}
    </div>
  )}</Query>;
}

// ------------------------------------------------------------------ activity
const actionTone = (a: string) => (a.startsWith("admin.") ? "brand" : a.endsWith("delete") ? "red" : a.startsWith("auth.") ? "green" : "slate") as "brand" | "red" | "green" | "slate";
export function ActivityPanel() {
  const [q, setQ] = useState(""), [days, setDays] = useState("30"), [page, setPage] = useState(1);
  const dq = useDebounced(q);
  useEffect(() => setPage(1), [dq, days]);
  const p = new URLSearchParams({ days, page: String(page) }); if (dq) p.set("q", dq);
  const query = useQuery({ queryKey: ["admin", "activity", p.toString()], placeholderData: (x) => x, queryFn: () => api.get<Paged<AdminActivity>>(`/admin/activity?${p}`) });
  return (
    <Card pad={false}>
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 p-4 dark:border-white/5">
        <SearchBox value={q} onChange={setQ} placeholder="Search action, detail or user…" />
        <Select label="Period" value={days} onChange={setDays} options={[["1", "Last 24 hours"], ["7", "Last 7 days"], ["30", "Last 30 days"], ["90", "Last 90 days"]]} />
      </div>
      <Query q={query}>{(d) => d.items.length === 0 ? <div className="p-6"><Empty icon={Activity} title="No activity" text="Nothing matches in this period." /></div> : (<>
        <TableWrap>
          <thead><tr><th className="th">When</th><th className="th">User</th><th className="th">Action</th><th className="th">Detail</th></tr></thead>
          <tbody>{d.items.map((a) => (
            <tr key={a.id} className="hover:bg-slate-50 dark:hover:bg-white/5">
              <td className="td text-slate-500" title={new Date(a.created_at!).toLocaleString()}>{ago(a.created_at!)}</td>
              <td className="td">{a.user_email ?? <span className="text-slate-400">system / deleted</span>}</td>
              <td className="td"><Badge tone={actionTone(a.action)}>{a.action}</Badge></td>
              <td className="td max-w-[420px] truncate text-slate-500" title={a.detail}>{a.detail || "—"}</td>
            </tr>))}</tbody>
        </TableWrap><Pager p={d} onPage={setPage} /></>)}</Query>
    </Card>
  );
}

// ------------------------------------------------------------------ AI tokens
export function TokensPanel() {
  const [days, setDays] = useState("30");
  const q = useQuery({ queryKey: ["admin", "tokens", days], placeholderData: (x) => x, queryFn: () => api.get<TokenUsage>(`/admin/usage/tokens?days=${days}`) });
  return <Query q={q}>{(t) => (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-slate-500">{t.llm_enabled ? <>Provider: <b>{t.provider}</b></> : "No LLM provider configured — analyses run in deterministic mode, so no tokens are consumed."}</p>
        <Select label="Period" value={days} onChange={setDays} options={[["7", "7 days"], ["30", "30 days"], ["90", "90 days"]]} />
      </div>
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="LLM calls" value={t.totals.calls} icon={Cpu} /><Stat label="Input tokens" value={fmtNum(t.totals.input_tokens)} icon={Activity} tone="green" />
        <Stat label="Output tokens" value={fmtNum(t.totals.output_tokens)} icon={Activity} tone="amber" /><Stat label="Failed calls" value={t.totals.failed_calls} icon={Cpu} tone={t.totals.failed_calls ? "red" : "green"} />
      </div>
      <Card title="Tokens per day">
        <ResponsiveContainer width="100%" height={240}>
          <BarChart data={t.by_day} margin={{ left: -10, right: 8, top: 4 }}>{grid}<XAxis dataKey="date" tickFormatter={shortDay} tick={AXIS} minTickGap={24} /><YAxis tick={AXIS} tickFormatter={fmtNum} /><Tooltip formatter={(v: any) => Number(v).toLocaleString()} /><Legend />
            <Bar dataKey="input_tokens" name="Input" stackId="a" fill={BRAND} /><Bar dataKey="output_tokens" name="Output" stackId="a" fill={SKY} radius={[3, 3, 0, 0]} /></BarChart>
        </ResponsiveContainer>
      </Card>
      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="By model" pad={false}>{t.by_model.length ? <TableWrap><thead><tr><th className="th">Model</th><th className="th text-right">Calls</th><th className="th text-right">In</th><th className="th text-right">Out</th></tr></thead>
          <tbody>{t.by_model.map((m) => <tr key={m.provider + m.model}><td className="td">{m.model || m.provider}</td><td className="td text-right tabular-nums">{m.calls}</td><td className="td text-right tabular-nums">{fmtNum(m.input_tokens)}</td><td className="td text-right tabular-nums">{fmtNum(m.output_tokens)}</td></tr>)}</tbody></TableWrap> : <p className="p-5 text-sm text-slate-500">No usage recorded.</p>}</Card>
        <Card title="Top users" pad={false}>{t.top_users.length ? <TableWrap><thead><tr><th className="th">User</th><th className="th text-right">Calls</th><th className="th text-right">Tokens</th></tr></thead>
          <tbody>{t.top_users.map((u) => <tr key={u.user_id}><td className="td">{u.email}</td><td className="td text-right tabular-nums">{u.calls}</td><td className="td text-right tabular-nums">{fmtNum(u.input_tokens + u.output_tokens)}</td></tr>)}</tbody></TableWrap> : <p className="p-5 text-sm text-slate-500">No usage recorded.</p>}</Card>
      </div>
    </div>
  )}</Query>;
}

// ------------------------------------------------------------------ API usage
export function ApiPanel() {
  const [days, setDays] = useState("14");
  const q = useQuery({ queryKey: ["admin", "api", days], placeholderData: (x) => x, queryFn: () => api.get<ApiUsage>(`/admin/usage/api?days=${days}`) });
  return <Query q={q}>{(a) => (
    <div className="space-y-6">
      <div className="flex justify-end"><Select label="Period" value={days} onChange={setDays} options={[["1", "24 hours"], ["7", "7 days"], ["14", "14 days"], ["60", "60 days"]]} /></div>
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Requests" value={a.totals.requests} icon={Activity} /><Stat label="Avg latency" value={`${a.totals.avg_ms} ms`} icon={Cpu} tone="green" />
        <Stat label="Client errors (4xx)" value={a.totals.client_errors} icon={Activity} tone="amber" /><Stat label="Server errors (5xx)" value={a.totals.server_errors} icon={Activity} tone={a.totals.server_errors ? "red" : "green"} />
      </div>
      <Card title="Requests per day">
        <ResponsiveContainer width="100%" height={240}>
          <BarChart data={a.by_day} margin={{ left: -10, right: 8, top: 4 }}>{grid}<XAxis dataKey="date" tickFormatter={shortDay} tick={AXIS} minTickGap={24} /><YAxis allowDecimals={false} tick={AXIS} /><Tooltip /><Legend />
            <Bar dataKey="count" name="Requests" fill={BRAND} radius={[3, 3, 0, 0]} /><Bar dataKey="errors" name="5xx errors" fill={RED} radius={[3, 3, 0, 0]} /></BarChart>
        </ResponsiveContainer>
      </Card>
      <div className="grid gap-6 lg:grid-cols-3">
        <Card title="Busiest endpoints" pad={false} className="lg:col-span-2">{a.top_routes.length ? <TableWrap><thead><tr><th className="th">Endpoint</th><th className="th text-right">Requests</th><th className="th text-right">Avg</th><th className="th text-right">Max</th><th className="th text-right">5xx</th></tr></thead>
          <tbody>{a.top_routes.map((r) => <tr key={r.method + r.route}><td className="td"><span className="mr-2 font-mono text-xs text-slate-400">{r.method}</span><span className="font-mono text-xs">{r.route.replace("/api/v1", "")}</span></td><td className="td text-right tabular-nums">{r.requests}</td><td className="td text-right tabular-nums">{r.avg_ms} ms</td><td className="td text-right tabular-nums">{Math.round(r.max_ms)} ms</td><td className="td text-right tabular-nums">{r.server_errors || "—"}</td></tr>)}</tbody></TableWrap> : <p className="p-5 text-sm text-slate-500">No requests recorded yet.</p>}</Card>
        <Card title="Top users" pad={false}>{a.top_users.length ? <TableWrap><thead><tr><th className="th">User</th><th className="th text-right">Requests</th></tr></thead>
          <tbody>{a.top_users.map((u) => <tr key={u.user_id}><td className="td">{u.email}</td><td className="td text-right tabular-nums">{u.requests}</td></tr>)}</tbody></TableWrap> : <p className="p-5 text-sm text-slate-500">—</p>}</Card>
      </div>
    </div>
  )}</Query>;
}

// ------------------------------------------------------------------ system health
const dot = { ok: "bg-emerald-500", warn: "bg-amber-500", down: "bg-red-500", off: "bg-slate-300 dark:bg-slate-600" };
export function SystemPanel() {
  const q = useQuery({ queryKey: ["admin", "system"], refetchInterval: 15_000, queryFn: () => api.get<SystemHealth>("/admin/system") });
  return <Query q={q}>{(s) => (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Overall" value={s.status === "ok" ? "Healthy" : s.status === "degraded" ? "Degraded" : "Down"} icon={Activity} tone={s.status === "ok" ? "green" : s.status === "degraded" ? "amber" : "red"} />
        <Stat label="Uptime" value={fmtUptime(s.uptime_seconds)} icon={Cpu} /><Stat label="DB latency" value={s.db_latency_ms != null ? `${s.db_latency_ms} ms` : "—"} icon={Database} tone="green" hint={s.database} />
        <Stat label="Disk used" value={s.disk ? `${s.disk.used_pct}%` : "—"} icon={HardDrive} tone={s.disk && s.disk.used_pct > 85 ? "red" : "amber"} hint={s.disk ? `${fmtBytes(s.disk.free)} free` : undefined} />
      </div>
      <Card title="Service checks" action={<span className="text-xs text-slate-400">auto-refresh 15s · {s.environment} · Python {s.python}</span>} pad={false}>
        <ul className="divide-y divide-slate-100 dark:divide-white/5">{s.checks.map((c) => (
          <li key={c.name} className="flex items-center gap-3 px-5 py-3"><span className={`h-2.5 w-2.5 shrink-0 rounded-full ${dot[c.status]}`} aria-hidden /><span className="w-40 shrink-0 text-sm font-medium">{c.name}</span><span className="min-w-0 flex-1 text-sm text-slate-500">{c.detail}</span><Badge tone={c.status === "ok" ? "green" : c.status === "warn" ? "amber" : c.status === "down" ? "red" : "slate"}>{c.status}</Badge></li>))}</ul>
      </Card>
    </div>
  )}</Query>;
}
