import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, DollarSign, HardDrive, TrendingUp, UserCheck, Users } from "lucide-react";
import { useState } from "react";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../../api/client";
import { Card, ErrorNote, Loading, Stat, Tabs } from "../../components/ui";
import type { AdminAnalytics } from "../../lib/types";
import { AXIS, fmtBytes, fmtNum, shortDay } from "./common";
import { ApiPanel, TokensPanel } from "./OtherPanels";
import { money } from "./forms";

const COLORS = ["#6366f1", "#38bdf8", "#10b981", "#f59e0b", "#ef4444", "#a855f7"];
const grid = <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,.2)" vertical={false} />;

export default function AnalyticsPanel() {
  const [tab, setTab] = useState<"business" | "tokens" | "api">("business");
  return (<>
    <Tabs tabs={[{ id: "business", label: "Business" }, { id: "tokens", label: "AI tokens & cost" }, { id: "api", label: "API usage" }]} value={tab} onChange={setTab} />
    {tab === "business" ? <Business /> : tab === "tokens" ? <TokensPanel /> : <ApiPanel />}
  </>);
}

function Business() {
  const { data: a, error, isLoading } = useQuery({ queryKey: ["admin", "analytics"], queryFn: () => api.get<AdminAnalytics>("/admin/analytics?days=30") });
  if (isLoading) return <Loading />;
  if (error || !a) return <ErrorNote error={error} />;
  const cur = a.currency;
  const errPct = a.api_requests_7d ? (a.api_errors_7d / a.api_requests_7d) * 100 : 0;
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Users" value={a.total_users} icon={Users} hint={`${a.paying_subscribers} paying`} /><Stat label="Daily active (today)" value={a.dau_today} icon={UserCheck} tone="green" hint={`${a.mau} monthly active`} />
        <Stat label="MRR" value={money(a.mrr_cents, cur)} icon={DollarSign} tone="green" hint={`ARR ${money(a.arr_cents, cur)}`} /><Stat label="AI cost (30d)" value={`$${a.ai_cost_30d_usd.toFixed(2)}`} icon={TrendingUp} tone="amber" hint={`${fmtNum(a.ai_tokens_30d)} tokens`} />
        <Stat label="API errors (7d)" value={a.api_errors_7d} icon={AlertTriangle} tone={a.api_errors_7d ? "red" : "green"} hint={`${errPct.toFixed(1)}% of ${fmtNum(a.api_requests_7d)}`} /><Stat label="Failed jobs (7d)" value={a.failed_jobs_7d} icon={AlertTriangle} tone={a.failed_jobs_7d ? "red" : "green"} />
        <Stat label="Storage" value={fmtBytes(a.storage_bytes)} icon={HardDrive} tone="amber" hint={a.storage_limit_gb ? `of ${a.storage_limit_gb} GB` : "no limit set"} /><Stat label="New users (30d)" value={a.signups.reduce((s, x) => s + x.count, 0)} icon={Users} />
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Daily active users · 30 days"><ResponsiveContainer width="100%" height={220}><AreaChart data={a.dau} margin={{ left: -20, right: 8, top: 4 }}>{grid}<XAxis dataKey="date" tickFormatter={shortDay} tick={AXIS} minTickGap={24} /><YAxis allowDecimals={false} tick={AXIS} /><Tooltip /><Area type="monotone" dataKey="count" name="Active users" stroke="#6366f1" fill="#6366f1" fillOpacity={0.15} strokeWidth={2} /></AreaChart></ResponsiveContainer></Card>
        <Card title="Revenue by month (net of refunds)"><ResponsiveContainer width="100%" height={220}><BarChart data={a.revenue_by_month.map((m) => ({ ...m, revenue: m.revenue_cents / 100 }))} margin={{ left: -10, right: 8, top: 4 }}>{grid}<XAxis dataKey="month" tick={AXIS} /><YAxis tick={AXIS} /><Tooltip formatter={(v: any) => money(Number(v) * 100, cur)} /><Bar dataKey="revenue" name="Revenue" fill="#10b981" radius={[3, 3, 0, 0]} /></BarChart></ResponsiveContainer></Card>
        <Card title="Most-used features · 30 days">{a.feature_usage.length ? <ResponsiveContainer width="100%" height={220}><BarChart data={a.feature_usage} layout="vertical" margin={{ left: 30, right: 8 }}><XAxis type="number" tick={AXIS} allowDecimals={false} /><YAxis type="category" dataKey="feature" width={110} tick={AXIS} /><Tooltip /><Bar dataKey="requests" name="Requests" fill="#6366f1" radius={[0, 4, 4, 0]} barSize={16} /></BarChart></ResponsiveContainer> : <p className="py-10 text-center text-sm text-slate-500">No usage recorded yet.</p>}</Card>
        <Card title="Users by plan"><div className="flex items-center gap-4"><ResponsiveContainer width="50%" height={200}><PieChart><Pie data={a.plan_distribution} dataKey="users" nameKey="plan" innerRadius={45} outerRadius={80} paddingAngle={2}>{a.plan_distribution.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}</Pie><Tooltip /></PieChart></ResponsiveContainer>
          <ul className="flex-1 space-y-1.5 text-sm">{a.plan_distribution.map((p, i) => <li key={p.plan} className="flex items-center justify-between gap-2"><span className="flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-full" style={{ background: COLORS[i % COLORS.length] }} />{p.plan}</span><b className="tabular-nums">{p.users}</b></li>)}</ul></div></Card>
      </div>
      <p className="text-xs text-slate-500">MRR counts active paid subscriptions at list price (yearly ÷ 12), before promo discounts. Trials and free plans are excluded.</p>
    </div>
  );
}
