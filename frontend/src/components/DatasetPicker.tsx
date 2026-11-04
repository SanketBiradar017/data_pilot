import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Dataset } from "../lib/types";

export function useDatasets() {
  return useQuery({ queryKey: ["datasets"], staleTime: 0, queryFn: () => api.get<Dataset[]>("/datasets") });
}

export function DatasetPicker({ value, onChange, kind }: { value: number | null; onChange: (id: number | null) => void; kind?: "table" | "document" }) {
  const { data = [] } = useDatasets();
  const items = kind ? data.filter((d) => d.kind === kind) : data;
  return (
    <select className="input min-w-[200px]" value={value ?? ""} onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)} aria-label="Dataset">
      <option value="">Select a data source…</option>
      {items.map((d) => <option key={d.id} value={d.id}>{d.name} · {d.kind === "table" ? `${d.row_count.toLocaleString()} rows` : "document"}</option>)}
    </select>
  );
}
