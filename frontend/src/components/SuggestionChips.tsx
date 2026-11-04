import { useQuery } from "@tanstack/react-query";
import { ChevronDown, Lightbulb } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api/client";

export interface Suggestion { question: string; category: string; reason: string }

const ORDER = ["Explore", "Trend", "Why", "What-if", "Summary", "Customers", "Quality", "Documents"];

/** Questions generated from the selected data (real columns, values, latest period). */
export function useSuggestions(datasetIds: number[]) {
  return useQuery({
    queryKey: ["suggestions", [...datasetIds].sort().join(",")], enabled: datasetIds.length > 0, staleTime: 0,
    queryFn: () => api.get<Suggestion[]>(`/analyses/suggestions?dataset_ids=${datasetIds.join(",")}`),
  });
}

const chip = "rounded-md bg-slate-100 px-2.5 py-1 text-xs text-slate-600 transition hover:bg-brand-50 hover:text-brand-700 dark:bg-white/5 dark:text-slate-300";

/**
 * Data-driven question ideas. Shows a varied first few; "More ideas" opens the whole pool with a filter per kind of question.
 * `only` restricts to some categories (e.g. just "Why" on the root-cause tab).
 */
export function SuggestionChips({ ids, onPick, only, initial = 6, className = "" }: { ids: number[]; onPick: (q: string) => void; only?: string[]; initial?: number; className?: string }) {
  const q = useSuggestions(ids);
  const [open, setOpen] = useState(false);
  const [cat, setCat] = useState("All");
  useEffect(() => { setOpen(false); setCat("All"); }, [ids.join(",")]);
  if (!ids.length) return null;
  if (q.isLoading) return <div className={`flex flex-wrap gap-2 ${className}`} aria-busy="true">{[120, 170, 140, 190, 150].map((w) => <span key={w} className="h-6 animate-pulse rounded-md bg-slate-100 dark:bg-white/5" style={{ width: w }} />)}</div>;
  const all = (q.data ?? []).filter((s) => !only || only.includes(s.category));
  if (!all.length) return null;
  const cats = ORDER.filter((c) => all.some((s) => s.category === c));
  const shown = open ? all.filter((s) => cat === "All" || s.category === cat) : all.slice(0, initial);
  const extra = all.length - initial;
  return (
    <div className={className} aria-label="Ideas for you">
      {open && cats.length > 1 && (
        <div className="mb-2 flex flex-wrap gap-1.5" role="tablist" aria-label="Kinds of question">
          {["All", ...cats].map((c) => (
            <button key={c} type="button" role="tab" aria-selected={cat === c} onClick={() => setCat(c)}
              className={`rounded-full border px-2.5 py-0.5 text-[11px] font-medium transition ${cat === c ? "border-brand-600 bg-brand-600 text-white" : "border-slate-300 text-slate-600 hover:border-brand-400 dark:border-white/15 dark:text-slate-300"}`}>
              {c}{c !== "All" && <span className="ml-1 opacity-70">{all.filter((s) => s.category === c).length}</span>}
            </button>))}
        </div>)}
      <div className="flex flex-wrap items-center gap-2">
        {shown.map((s) => <button key={s.question} type="button" title={`${s.category}: ${s.reason}`} onClick={() => onPick(s.question)} className={chip}>{open && cat === "All" && <span className="mr-1.5 text-[10px] font-semibold uppercase tracking-wide text-brand-600">{s.category}</span>}{s.question}</button>)}
        {extra > 0 && (
          <button type="button" onClick={() => { setOpen(!open); setCat("All"); }} aria-expanded={open}
            className="inline-flex items-center gap-1 rounded-md border border-dashed border-brand-400 px-2.5 py-1 text-xs font-medium text-brand-700 transition hover:bg-brand-50 dark:text-brand-300 dark:hover:bg-brand-500/10">
            <Lightbulb className="h-3.5 w-3.5" />{open ? "Fewer ideas" : `More ideas (${extra})`}<ChevronDown className={`h-3.5 w-3.5 transition ${open ? "rotate-180" : ""}`} />
          </button>)}
      </div>
    </div>
  );
}
