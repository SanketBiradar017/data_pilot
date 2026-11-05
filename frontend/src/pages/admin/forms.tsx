import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Check } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { api } from "../../api/client";
import { Card, ErrorNote, Loading, Spinner } from "../../components/ui";

export const money = (cents: number, cur = "INR") => new Intl.NumberFormat("en-IN", { style: "currency", currency: cur }).format(cents / 100);

export function Field({ label, hint, children, className }: { label: string; hint?: string; children: ReactNode; className?: string }) {
  return <label className={clsx("block", className)}><span className="label">{label}</span>{children}{hint && <span className="mt-1 block text-xs text-slate-500">{hint}</span>}</label>;
}

export function Toggle({ checked, onChange, label, hint, disabled }: { checked: boolean; onChange: (v: boolean) => void; label: string; hint?: string; disabled?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-4 py-2">
      <div className="min-w-0"><p className="text-sm font-medium text-slate-900 dark:text-slate-100">{label}</p>{hint && <p className="text-xs text-slate-500">{hint}</p>}</div>
      <button type="button" role="switch" aria-checked={checked} aria-label={label} disabled={disabled} onClick={() => onChange(!checked)}
        className={clsx("relative h-6 w-11 shrink-0 rounded-full transition disabled:opacity-50", checked ? "bg-brand-600" : "bg-slate-300 dark:bg-white/20")}>
        <span className={clsx("absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all", checked ? "left-[22px]" : "left-0.5")} />
      </button>
    </div>
  );
}

/** Number input where empty = null (unlimited / unset). */
export function NumInput({ value, onChange, placeholder = "Unlimited", min = 0, step, ...rest }: { value: number | null | undefined; onChange: (v: number | null) => void; placeholder?: string; min?: number; step?: number; "aria-label"?: string }) {
  return <input type="number" min={min} step={step} className="input" placeholder={placeholder} value={value ?? ""} aria-label={rest["aria-label"]}
    onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))} />;
}

export interface SettingsResp<T> { values: T; secrets?: Record<string, boolean>; runtime?: any; configured?: boolean; all_formats?: string[] }

/** Load a settings group, keep a local draft, save the diff. */
export function useSettingsForm<T extends Record<string, any>>(key: string) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["admin", "settings", key], queryFn: () => api.get<SettingsResp<T>>(`/admin/settings/${key}`) });
  const [draft, setDraft] = useState<T | null>(null);
  const [saved, setSaved] = useState(false);
  useEffect(() => { if (q.data && !draft) setDraft(q.data.values); }, [q.data]); // eslint-disable-line
  const save = useMutation({
    mutationFn: (patch: Partial<T>) => api.put<{ values: T }>(`/admin/settings/${key}`, patch),
    onSuccess: (r) => { setDraft(r.values); setSaved(true); setTimeout(() => setSaved(false), 2500); qc.invalidateQueries({ queryKey: ["admin", "settings", key] }); qc.invalidateQueries({ queryKey: ["platform"] }); qc.invalidateQueries({ queryKey: ["billing"] }); },
  });
  const set = <K extends keyof T>(k: K, v: T[K]) => { setSaved(false); setDraft((d) => (d ? { ...d, [k]: v } : d)); };
  const dirty = !!(q.data && draft && JSON.stringify(q.data.values) !== JSON.stringify(draft));
  const submit = (keys?: (keyof T)[]) => { if (!draft || !q.data) return; const patch: Partial<T> = {}; for (const k of keys ?? (Object.keys(draft) as (keyof T)[])) if (JSON.stringify(draft[k]) !== JSON.stringify(q.data.values[k])) patch[k] = draft[k]; save.mutate(patch); };
  return { q, draft, set, save, saved, dirty, submit };
}

export function SaveBar({ dirty, saving, saved, error, onSave, label = "Save changes" }: { dirty: boolean; saving: boolean; saved: boolean; error: unknown; onSave: () => void; label?: string }) {
  return (
    <div className="mt-5 flex flex-wrap items-center gap-3 border-t border-slate-100 pt-4 dark:border-white/5">
      <button className="btn-primary" disabled={!dirty || saving} onClick={onSave}>{saving && <Spinner />} {label}</button>
      {saved && <span className="inline-flex items-center gap-1 text-sm text-emerald-600"><Check className="h-4 w-4" /> Saved</span>}
      {dirty && !saving && <span className="text-xs text-slate-500">Unsaved changes</span>}
      <div className="min-w-0 flex-1"><ErrorNote error={error} /></div>
    </div>
  );
}

export function SettingsCard<T extends Record<string, any>>({ group, title, children, keys }: { group: string; title: string; keys?: (keyof T)[]; children: (f: ReturnType<typeof useSettingsForm<T>>) => ReactNode }) {
  const f = useSettingsForm<T>(group);
  if (f.q.isLoading || !f.draft) return <Card title={title}>{f.q.error ? <ErrorNote error={f.q.error} /> : <Loading />}</Card>;
  return <Card title={title}>{children(f)}<SaveBar dirty={f.dirty} saving={f.save.isPending} saved={f.saved} error={f.save.error} onSave={() => f.submit(keys)} /></Card>;
}

export const SecretBadge = ({ set, name }: { set?: boolean; name: string }) => (
  <p className={clsx("rounded-lg px-3 py-2 text-xs", set ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300" : "bg-amber-50 text-amber-800 dark:bg-amber-500/10 dark:text-amber-300")}>
    <code className="font-mono">{name}</code> {set ? "is set in the server environment." : "is not set. Add it to the server environment (.env) — secrets are never stored in the database or shown here."}
  </p>
);
