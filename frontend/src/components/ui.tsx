import clsx from "clsx";
import { AlertTriangle, CheckCircle2, Loader2, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { cellText } from "../lib/format";
import { CountUp } from "./Motion";

export const Spinner = ({ className }: { className?: string }) => <Loader2 className={clsx("h-4 w-4 animate-spin", className)} />;

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900 dark:text-white">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{subtitle}</p>}
      </div>
      <div className="flex items-center gap-2">{actions}</div>
    </div>
  );
}

export function Card({ title, action, children, className, pad = true }: { title?: ReactNode; action?: ReactNode; children: ReactNode; className?: string; pad?: boolean }) {
  return (
    <section className={clsx("card animate-fadeUp transition-shadow duration-300 hover:shadow-pop", className)}>
      {(title || action) && (
        <header className="flex items-center justify-between border-b border-slate-100 px-5 py-3 dark:border-white/5">
          <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">{title}</h2>
          {action}
        </header>
      )}
      <div className={pad ? "p-5" : ""}>{children}</div>
    </section>
  );
}

export function Stat({ label, value, hint, icon: Icon, tone = "brand" }: { label: string; value: ReactNode; hint?: string; icon?: LucideIcon; tone?: "brand" | "green" | "amber" | "red" }) {
  const tones = { brand: "bg-brand-50 text-brand-600 dark:bg-brand-500/15 dark:text-brand-400", green: "bg-emerald-50 text-emerald-600 dark:bg-emerald-500/15", amber: "bg-amber-50 text-amber-600 dark:bg-amber-500/15", red: "bg-red-50 text-red-600 dark:bg-red-500/15" };
  return (
    <div className="card lift animate-fadeUp p-5">
      <div className="flex items-start justify-between">
        <p className="text-sm text-slate-500 dark:text-slate-400">{label}</p>
        {Icon && <span className={clsx("rounded-lg p-2", tones[tone])}><Icon className="h-4 w-4" /></span>}
      </div>
      <p className="mt-2 text-3xl font-semibold tabular-nums tracking-tight text-slate-900 dark:text-white">{typeof value === "number" ? <CountUp value={value} /> : value}</p>
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    </div>
  );
}

export function Badge({ children, tone = "slate" }: { children: ReactNode; tone?: "slate" | "green" | "amber" | "red" | "brand" }) {
  const t = { slate: "bg-slate-100 text-slate-600 dark:bg-white/10 dark:text-slate-300", green: "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300", amber: "bg-amber-50 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300", red: "bg-red-50 text-red-700 dark:bg-red-500/15 dark:text-red-300", brand: "bg-brand-50 text-brand-700 dark:bg-brand-500/15 dark:text-brand-200" };
  return <span className={clsx("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium", t[tone])}>{children}</span>;
}

export const SeverityBadge = ({ s }: { s: string }) => <Badge tone={s === "high" ? "red" : s === "medium" ? "amber" : "slate"}>{s}</Badge>;

export function Empty({ icon: Icon, title, text, action }: { icon: LucideIcon; title: string; text?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-slate-300 px-6 py-14 text-center dark:border-white/15">
      <span className="mb-3 rounded-full bg-brand-50 p-3 text-brand-600 dark:bg-brand-500/15"><Icon className="h-6 w-6" /></span>
      <p className="font-medium text-slate-900 dark:text-white">{title}</p>
      {text && <p className="mt-1 max-w-sm text-sm text-slate-500">{text}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <div role="alert" className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> <span>{(error as Error).message ?? String(error)}</span>
    </div>
  );
}

export const Loading = ({ label = "Loading…" }: { label?: string }) => (
  <div className="flex items-center justify-center gap-2 py-16 text-sm text-slate-500"><Spinner /> {label}</div>
);

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: { id: T; label: string }[]; value: T; onChange: (t: T) => void }) {
  return (
    <div className="mb-5 flex gap-1 border-b border-slate-200 dark:border-white/10" role="tablist">
      {tabs.map((t) => (
        <button key={t.id} role="tab" aria-selected={value === t.id} onClick={() => onChange(t.id)}
          className={clsx("-mb-px border-b-2 px-4 py-2 text-sm font-medium transition", value === t.id ? "border-brand-600 text-brand-700 dark:text-brand-400" : "border-transparent text-slate-500 hover:text-slate-800 dark:hover:text-slate-200")}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function DataTable({ columns, rows, maxHeight = 420 }: { columns: string[]; rows: Record<string, any>[]; maxHeight?: number }) {
  if (!rows.length) return <p className="py-6 text-center text-sm text-slate-500">No rows.</p>;
  return (
    <div className="overflow-auto rounded-lg border border-slate-200 dark:border-white/10" style={{ maxHeight }}>
      <table className="min-w-full">
        <thead className="sticky top-0"><tr>{columns.map((c) => <th key={c} className="th">{c}</th>)}</tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="hover:bg-slate-50 dark:hover:bg-white/5">
              {columns.map((c) => <td key={c} className={clsx("td", typeof r[c] === "number" && "text-right tabular-nums", r[c] == null && "text-slate-400")}>{cellText(r[c])}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export const Verified = ({ ok }: { ok?: boolean }) =>
  ok ? <span title="Independently re-computed from raw data" className="inline-flex items-center gap-1 text-xs font-medium text-emerald-600 dark:text-emerald-400"><CheckCircle2 className="h-3.5 w-3.5" /> verified</span> : null;
