import { useQuery } from "@tanstack/react-query";
import { Calendar, Hash, Type } from "lucide-react";
import type { ReactNode } from "react";
import { api } from "../../api/client";
import { formatSig } from "../../lib/numfmt";
import type { FieldMeta, FieldsResponse } from "../../lib/types";

export const useFields = (datasetId: number | null) =>
  useQuery({ queryKey: ["fields", datasetId], enabled: datasetId != null, staleTime: 0, queryFn: () => api.get<FieldsResponse>(`/advanced/fields/${datasetId}`) });

export const KindIcon = ({ kind }: { kind: FieldMeta["kind"] }) =>
  kind === "numeric" ? <Hash className="h-3.5 w-3.5 text-emerald-500" /> : kind === "datetime" ? <Calendar className="h-3.5 w-3.5 text-sky-500" /> : <Type className="h-3.5 w-3.5 text-brand-500" />;

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return <div><label className="label">{label}</label>{children}{hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}</div>;
}

export function ColumnSelect({ fields, value, onChange, kinds, placeholder = "Select…", exclude = [], measureOnly = false }: {
  fields: FieldMeta[]; value: string; onChange: (v: string) => void; kinds?: FieldMeta["kind"][]; placeholder?: string; exclude?: string[]; measureOnly?: boolean;
}) {
  const items = fields.filter((f) => (!kinds || kinds.includes(f.kind)) && !exclude.includes(f.name) && (!measureOnly || f.measure));
  return (
    <select className="input" value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">{placeholder}</option>
      {items.map((f) => <option key={f.name} value={f.name}>{f.name}</option>)}
    </select>
  );
}

export const Stat2 = ({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: string; tone?: "good" | "bad" | "warn" }) => (
  <div className="rounded-lg bg-slate-50 px-3 py-2.5 dark:bg-white/5">
    <p className="text-xs text-slate-500">{label}</p>
    <p className={`text-lg font-semibold tabular-nums ${tone === "good" ? "text-emerald-600" : tone === "bad" ? "text-red-600" : tone === "warn" ? "text-amber-600" : ""}`}>{value}</p>
    {sub && <p className="text-xs text-slate-500">{sub}</p>}
  </div>
);

export const p = (v: number) => (v < 0.0001 ? "< 0.0001" : v.toPrecision(3));
export const n4 = (v: number | null | undefined) => (v == null ? "—" : formatSig(v, 4));
