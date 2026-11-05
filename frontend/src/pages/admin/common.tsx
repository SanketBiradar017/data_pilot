import clsx from "clsx";
import { ChevronLeft, ChevronRight, Search, X } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

export interface Paged<T> { items: T[]; total: number; page: number; page_size: number; pages: number }

export const fmtBytes = (n: number) => { if (!n) return "0 B"; const u = ["B", "KB", "MB", "GB", "TB"]; const i = Math.min(u.length - 1, Math.floor(Math.log(n) / Math.log(1024))); return `${(n / 1024 ** i).toFixed(i ? 1 : 0)} ${u[i]}`; };
export const fmtNum = (n: number) => n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e4 ? `${(n / 1e3).toFixed(1)}k` : n.toLocaleString();
export const fmtDate = (iso?: string | null) => iso ? new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }) : "—";
export const fmtDateTime = (iso?: string | null) => iso ? new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "Never";
export const fmtUptime = (s: number) => { const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60); return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m`; };
export const shortDay = (d: string) => d.slice(5);

export const AXIS = { fontSize: 11, fill: "#94a3b8" };

export function useDebounced<T>(v: T, ms = 300) {
  const [d, setD] = useState(v);
  useEffect(() => { const t = setTimeout(() => setD(v), ms); return () => clearTimeout(t); }, [v, ms]);
  return d;
}

export function SearchBox({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder: string }) {
  return (
    <label className="relative block min-w-[220px] flex-1 sm:max-w-sm">
      <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
      <input className="input pl-9" value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} aria-label={placeholder} />
    </label>
  );
}

export const Select = ({ value, onChange, options, label }: { value: string; onChange: (v: string) => void; options: [string, string][]; label: string }) => (
  <select className="input w-auto" value={value} onChange={(e) => onChange(e.target.value)} aria-label={label}>
    {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
  </select>
);

export function Pager({ p, onPage }: { p: { total: number; page: number; pages: number; page_size: number }; onPage: (n: number) => void }) {
  const from = p.total ? (p.page - 1) * p.page_size + 1 : 0, to = Math.min(p.total, p.page * p.page_size);
  return (
    <div className="flex items-center justify-between gap-3 border-t border-slate-100 px-4 py-3 text-sm text-slate-500 dark:border-white/5">
      <span>{from}–{to} of {p.total.toLocaleString()}</span>
      <div className="flex items-center gap-1">
        <button className="btn-ghost !px-2 !py-1" disabled={p.page <= 1} onClick={() => onPage(p.page - 1)} aria-label="Previous page"><ChevronLeft className="h-4 w-4" /></button>
        <span className="px-2 tabular-nums">{p.page} / {p.pages}</span>
        <button className="btn-ghost !px-2 !py-1" disabled={p.page >= p.pages} onClick={() => onPage(p.page + 1)} aria-label="Next page"><ChevronRight className="h-4 w-4" /></button>
      </div>
    </div>
  );
}

/** Scrollable table wrapper (horizontal scroll on phones). */
export const TableWrap = ({ children }: { children: ReactNode }) => <div className="overflow-x-auto"><table className="min-w-full">{children}</table></div>;

export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  useEffect(() => { const k = (e: KeyboardEvent) => e.key === "Escape" && onClose(); window.addEventListener("keydown", k); return () => window.removeEventListener("keydown", k); }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 p-0 sm:items-center sm:p-4" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div role="dialog" aria-modal="true" aria-label={title} className={clsx("card max-h-[92vh] w-full overflow-y-auto rounded-b-none sm:rounded-b-xl", wide ? "sm:max-w-2xl" : "sm:max-w-md")}>
        <header className="sticky top-0 z-10 flex items-center justify-between border-b border-slate-100 bg-white px-5 py-3 dark:border-white/5 dark:bg-ink-900">
          <h2 className="font-semibold text-slate-900 dark:text-white">{title}</h2>
          <button onClick={onClose} className="rounded p-1 text-slate-400 hover:bg-slate-100 dark:hover:bg-white/10" aria-label="Close"><X className="h-4 w-4" /></button>
        </header>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

export const KV = ({ k, v }: { k: string; v: ReactNode }) => (
  <div><dt className="text-xs uppercase tracking-wide text-slate-500">{k}</dt><dd className="mt-0.5 text-sm font-medium text-slate-900 dark:text-slate-100">{v}</dd></div>
);
