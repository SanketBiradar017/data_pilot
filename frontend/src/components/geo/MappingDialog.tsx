import clsx from "clsx";
import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { MAP_ROLES, type GeoDetection, type GeoMapping, type MapRole } from "../../lib/geoRevenue";
import { Badge, Spinner } from "../ui";

const LABEL: Record<MapRole, { name: string; hint: string }> = {
  country: { name: "Country", hint: "Name, ISO-2 or ISO-3 code" }, state: { name: "State / province", hint: "Name or code" },
  city: { name: "City", hint: "Optional" }, revenue: { name: "Revenue", hint: "Sales / income amount" },
  expense: { name: "Expense", hint: "Cost used to derive profit" }, loss: { name: "Loss", hint: "Explicit loss amount" },
  profit: { name: "Profit", hint: "Overrides revenue − expense" }, date: { name: "Date", hint: "Enables the date filter" },
};

interface Props { detection: GeoDetection; saving: boolean; error: string | null; onSave: (m: GeoMapping) => void; onReset: () => void; onClose: () => void }

export function MappingDialog({ detection, saving, error, onSave, onReset, onClose }: Props) {
  const initial = (detection.saved ?? detection.mapping) as GeoMapping;
  const [m, setM] = useState<GeoMapping>({ ...initial });
  useEffect(() => { const h = (e: KeyboardEvent) => e.key === "Escape" && onClose(); window.addEventListener("keydown", h); return () => window.removeEventListener("keydown", h); }, [onClose]);
  const noLoc = !m.country && !m.state && !m.city, noMeasure = !m.revenue && !m.profit && !m.loss;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-label="Column mapping" onClick={(e) => e.stopPropagation()} className="card flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden shadow-pop">
        <header className="flex items-start justify-between border-b border-slate-100 px-6 py-4 dark:border-white/5">
          <div><h2 className="text-lg font-semibold">Map your columns</h2><p className="text-sm text-slate-500">We detected these automatically. Adjust anything that looks wrong.</p></div>
          <button onClick={onClose} aria-label="Close" className="rounded p-1 text-slate-500 hover:bg-slate-100 dark:hover:bg-white/10"><X className="h-4 w-4" /></button>
        </header>
        <div className="space-y-4 overflow-y-auto px-6 py-5">
          {detection.issues.length > 0 && <ul className="space-y-1 rounded-lg bg-amber-50 p-3 text-sm text-amber-800 dark:bg-amber-500/10 dark:text-amber-300">{detection.issues.map((i) => <li key={i}>• {i}</li>)}</ul>}
          <div className="grid gap-3 sm:grid-cols-2">
            {MAP_ROLES.map((role) => {
              const conf = m[role] === detection.mapping[role] ? detection.confidence[role] : null;
              return (
                <label key={role} className="block text-sm">
                  <span className="mb-1 flex items-center justify-between font-medium">{LABEL[role].name}
                    {conf != null && m[role] && <Badge tone={conf >= 0.75 ? "green" : conf >= 0.5 ? "amber" : "red"}>{Math.round(conf * 100)}% sure</Badge>}</span>
                  <select className="input" value={m[role] ?? ""} onChange={(e) => setM({ ...m, [role]: e.target.value || null })}>
                    <option value="">— none —</option>
                    {detection.columns.map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                  <span className="mt-0.5 block text-xs text-slate-500">{LABEL[role].hint}</span>
                </label>
              );
            })}
          </div>
          {(noLoc || noMeasure) && <p className="text-sm text-red-600">{noLoc ? "Choose at least one location column. " : ""}{noMeasure ? "Choose revenue, profit or loss." : ""}</p>}
          {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
        </div>
        <footer className="flex items-center justify-between gap-2 border-t border-slate-100 px-6 py-4 dark:border-white/5">
          <button className="btn-ghost" onClick={onReset} disabled={saving || !detection.saved}>Reset to auto-detect</button>
          <div className="flex gap-2">
            <button className="btn-ghost" onClick={onClose}>Cancel</button>
            <button className={clsx("btn-primary")} disabled={saving || noLoc || noMeasure} onClick={() => onSave(m)}>{saving && <Spinner />} Save & apply</button>
          </div>
        </footer>
      </div>
    </div>
  );
}
