import clsx from "clsx";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, BarChart3, BrainCircuit, Calculator, CreditCard, Database, FileText, Globe2, History, LayoutDashboard, LogOut, Menu, MessageSquare, Settings, ShieldCheck, Sparkles, Terminal, X } from "lucide-react";
import { useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { api } from "../api/client";
import { useAuth } from "../lib/auth";
import { usePlatform } from "../lib/platform";
import type { BillingMe } from "../lib/types";
import { ADMIN_NAV } from "../pages/admin/nav";
import { ThemeToggle } from "./ThemeToggle";

const NAV: { to: string; label: string; icon: typeof Database; end?: boolean; feature?: string }[] = [
  { to: "/", label: "Overview", icon: LayoutDashboard, end: true },
  { to: "/datasets", label: "Data sources", icon: Database },
  { to: "/workspace", label: "Analysis workspace", icon: Sparkles, feature: "ai_agents" },
  { to: "/advanced", label: "Advanced analytics", icon: Calculator, feature: "eda" },
  { to: "/intelligence", label: "AI intelligence", icon: BrainCircuit, feature: "ai_agents" },
  { to: "/geo-revenue", label: "Global Revenue Intelligence", icon: Globe2 },
  { to: "/chat", label: "Ask your data", icon: MessageSquare, feature: "ai_chat" },
  { to: "/sql", label: "SQL editor", icon: Terminal, feature: "sql_analysis" },
  { to: "/reports", label: "Reports", icon: FileText },
  { to: "/history", label: "History", icon: History },
  { to: "/billing", label: "Plan & billing", icon: CreditCard },
  { to: "/settings", label: "Settings", icon: Settings },
];

export default function Layout() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const { pathname } = useLocation();
  const platform = usePlatform();
  const isAdmin = user?.role === "super_admin";
  const inAdmin = isAdmin && pathname.startsWith("/admin");
  const billing = useQuery({ queryKey: ["billing", "me"], staleTime: 60_000, retry: 0, queryFn: () => api.get<BillingMe>("/billing/me") });
  const off = (f?: string) => !!f && billing.data?.features[f] === false;  // hide nav for features that are disabled globally or on the plan
  const items = NAV.filter((n) => !off(n.feature));
  const link = (to: string, label: string, Icon: typeof Database, end?: boolean) => (
    <NavLink key={to} to={to} end={end} onClick={() => setOpen(false)}
      className={({ isActive }) => clsx("group flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-all duration-200",
        isActive ? "bg-gradient-to-r from-brand-600/40 to-white/5 text-white shadow-inner" : "text-white/65 hover:translate-x-0.5 hover:bg-white/5 hover:text-white")}>
      <Icon className="h-4 w-4 transition-transform group-hover:scale-110" /> {label}
    </NavLink>
  );
  if (platform.maintenance_mode && !isAdmin) return (
    <div className="flex h-full items-center justify-center p-6"><div className="card max-w-md p-8 text-center"><h1 className="text-lg font-semibold">Under maintenance</h1><p className="mt-2 text-sm text-slate-500">{platform.maintenance_message}</p><button onClick={logout} className="btn-ghost mt-5">Sign out</button></div></div>
  );
  const nav = (
    <nav className="flex min-h-0 flex-1 flex-col gap-0.5 overflow-y-auto px-3 py-4" aria-label="Main">
      {inAdmin ? (<>
        <NavLink to="/" onClick={() => setOpen(false)} className="mb-2 flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-medium text-white/60 hover:bg-white/5 hover:text-white"><ArrowLeft className="h-3.5 w-3.5" /> Back to app</NavLink>
        <p className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-wider text-white/40">Admin</p>
        {ADMIN_NAV.map((n) => link(`/admin/${n.slug}`, n.label, n.icon))}
      </>) : (<>
      {items.map((n) => (
        <NavLink key={n.to} to={n.to} end={n.end} onClick={() => setOpen(false)}
          className={({ isActive }) => clsx("group flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-all duration-200",
            isActive ? "bg-gradient-to-r from-brand-600/40 to-white/5 text-white shadow-inner" : "text-white/65 hover:translate-x-0.5 hover:bg-white/5 hover:text-white")}>
          <n.icon className="h-4 w-4 transition-transform group-hover:scale-110" /> {n.label}
        </NavLink>
      ))}
      {isAdmin && <><div className="my-2 border-t border-white/10" />{link("/admin/overview", "Super admin", ShieldCheck)}</>}
      </>)}
    </nav>
  );

  return (
    <div className="flex h-full">
      <aside className={clsx("fixed inset-y-0 left-0 z-40 flex w-64 flex-col bg-side transition-transform lg:static lg:translate-x-0 dark:border-r dark:border-white/10", open ? "translate-x-0" : "-translate-x-full")}>
        <div className="flex h-16 items-center gap-2.5 px-5">
          <span className="flex h-8 w-8 items-center justify-center overflow-hidden rounded-lg bg-brand-600">{platform.logo_url ? <img src={platform.logo_url} alt="" className="h-full w-full object-cover" /> : <BarChart3 className="h-4 w-4 text-white" />}</span>
          <span className="truncate text-lg font-semibold tracking-tight text-white">{platform.app_name}</span>
          <button className="ml-auto text-white/60 lg:hidden" onClick={() => setOpen(false)} aria-label="Close menu"><X className="h-5 w-5" /></button>
        </div>
        {nav}
        <div className="border-t border-white/10 p-3">
          <div className="flex items-center gap-3 rounded-lg px-2 py-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-full bg-brand-600 text-sm font-semibold text-white">{(user?.name || user?.email || "?")[0].toUpperCase()}</span>
            <div className="min-w-0 flex-1"><p className="truncate text-sm font-medium text-white">{user?.name}</p><p className="truncate text-xs text-white/60">{user?.email}</p></div>
            <ThemeToggle className="text-white/60 hover:text-white" />
            <button onClick={logout} className="rounded p-1.5 text-white/60 hover:bg-white/10 hover:text-white" aria-label="Sign out"><LogOut className="h-4 w-4" /></button>
          </div>
        </div>
      </aside>
      {open && <div className="fixed inset-0 z-30 bg-black/40 lg:hidden" onClick={() => setOpen(false)} />}
      <div className="flex h-full min-w-0 flex-1 flex-col">
        <header className="flex h-14 items-center border-b border-slate-200 bg-white px-4 lg:hidden dark:border-white/10 dark:bg-ink-900">
          <button onClick={() => setOpen(true)} aria-label="Open menu"><Menu className="h-5 w-5" /></button>
          <span className="ml-3 font-semibold">{platform.app_name}</span>
        </header>
        {platform.announcement && <div role="status" className={clsx("px-4 py-2 text-center text-sm", { info: "bg-brand-600 text-white", warn: "bg-amber-500 text-amber-950", success: "bg-emerald-600 text-white" }[platform.announcement_tone])}>{platform.announcement}</div>}
        {platform.maintenance_mode && isAdmin && <div role="alert" className="bg-red-600 px-4 py-1.5 text-center text-xs font-medium text-white">Maintenance mode is ON — the app is offline for non-admin users.</div>}
        {pathname.startsWith("/chat") || pathname.startsWith("/geo-revenue") ? (
          <main className="min-h-0 flex-1 overflow-hidden"><div key={pathname} className="page-enter h-full"><Outlet /></div></main>
        ) : (
          <main className="min-h-0 flex-1 overflow-y-auto"><div key={pathname} className="page-enter w-full max-w-[1680px] px-4 py-6 sm:px-8 sm:py-8"><Outlet /></div></main>
        )}
      </div>
    </div>
  );
}
