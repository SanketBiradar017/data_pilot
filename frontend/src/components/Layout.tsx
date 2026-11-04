import clsx from "clsx";
import { BarChart3, BrainCircuit, Calculator, Database, FileText, History, LayoutDashboard, LogOut, Menu, MessageSquare, Settings, Sparkles, Terminal, X } from "lucide-react";
import { useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { ThemeToggle } from "./ThemeToggle";

const NAV = [
  { to: "/", label: "Overview", icon: LayoutDashboard, end: true },
  { to: "/datasets", label: "Data sources", icon: Database },
  { to: "/workspace", label: "Analysis workspace", icon: Sparkles },
  { to: "/advanced", label: "Advanced analytics", icon: Calculator },
  { to: "/intelligence", label: "AI intelligence", icon: BrainCircuit },
  { to: "/chat", label: "Ask your data", icon: MessageSquare },
  { to: "/sql", label: "SQL editor", icon: Terminal },
  { to: "/reports", label: "Reports", icon: FileText },
  { to: "/history", label: "History", icon: History },
  { to: "/settings", label: "Settings", icon: Settings },
];

export default function Layout() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const { pathname } = useLocation();

  const nav = (
    <nav className="flex flex-1 flex-col gap-0.5 px-3 py-4" aria-label="Main">
      {NAV.map((n) => (
        <NavLink key={n.to} to={n.to} end={n.end} onClick={() => setOpen(false)}
          className={({ isActive }) => clsx("group flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-all duration-200",
            isActive ? "bg-gradient-to-r from-brand-600/40 to-white/5 text-white shadow-inner" : "text-white/65 hover:translate-x-0.5 hover:bg-white/5 hover:text-white")}>
          <n.icon className="h-4 w-4 transition-transform group-hover:scale-110" /> {n.label}
        </NavLink>
      ))}
    </nav>
  );

  return (
    <div className="flex h-full">
      <aside className={clsx("fixed inset-y-0 left-0 z-40 flex w-64 flex-col bg-side transition-transform lg:static lg:translate-x-0 dark:border-r dark:border-white/10", open ? "translate-x-0" : "-translate-x-full")}>
        <div className="flex h-16 items-center gap-2.5 px-5">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-600"><BarChart3 className="h-4 w-4 text-white" /></span>
          <span className="text-lg font-semibold tracking-tight text-white">DataPilot <span className="text-brand-400">AI</span></span>
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
          <span className="ml-3 font-semibold">DataPilot AI</span>
        </header>
        {pathname.startsWith("/chat") ? (
          <main className="min-h-0 flex-1 overflow-hidden"><div key={pathname} className="page-enter h-full"><Outlet /></div></main>
        ) : (
          <main className="min-h-0 flex-1 overflow-y-auto"><div key={pathname} className="page-enter w-full max-w-[1680px] px-4 py-6 sm:px-8 sm:py-8"><Outlet /></div></main>
        )}
      </div>
    </div>
  );
}
