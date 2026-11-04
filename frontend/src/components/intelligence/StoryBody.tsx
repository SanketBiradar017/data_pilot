import { CheckCircle2, ChevronDown, FlaskConical, ShieldCheck } from "lucide-react";
import { useState } from "react";
import type { Fact, Footnote, StoryStatement, Verification } from "../../lib/types";
import { useNumFmt } from "../../lib/numfmt";

/** Footnotes (numbered citations) for statements that carry fact ids. */
export function toFootnotes(statements: StoryStatement[], facts: Fact[], ver: Verification): Footnote[] {
  const by = new Map(facts.map((f) => [f.id, f]));
  const order: string[] = [];
  statements.forEach((s) => s.facts.forEach((f) => { if (!order.includes(f) && by.has(f)) order.push(f); }));
  return order.map((id, i) => { const f = by.get(id)!; return { n: i + 1, fact: id, label: f.label, value: f.value, unit: f.unit, sql: f.sql, op: f.op, inputs: f.inputs, estimate: !!f.estimate, verified: ver[id]?.verified ?? null, detail: ver[id]?.detail }; });
}

const KIND: Record<string, { label: string; cls: string }> = {
  observed: { label: "OBSERVED", cls: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-300" },
  estimate: { label: "ESTIMATE", cls: "bg-amber-100 text-amber-800 dark:bg-amber-500/20 dark:text-amber-300" },
};

export function StoryBody({ statements, footnotes, bullets = true }: { statements: StoryStatement[]; footnotes: Footnote[]; bullets?: boolean }) {
  const { fmt } = useNumFmt();
  const [open, setOpen] = useState<number | null>(null);
  const [showAll, setShowAll] = useState(false);
  const nOf = (id: string) => footnotes.find((f) => f.fact === id)?.n;
  return (
    <div>
      <ul className={bullets ? "space-y-2.5" : "space-y-1"}>
        {statements.map((s, i) => {
          const k = KIND[s.kind];
          const refs = [...new Set(s.facts.map(nOf).filter((x): x is number => !!x))];
          return (
            <li key={i} className={`text-[15px] leading-relaxed ${s.kind === "estimate" ? "rounded-lg border border-dashed border-amber-400/70 bg-amber-50/60 px-3 py-2 dark:bg-amber-500/5" : ""}`}>
              {k && <span className={`mr-2 rounded px-1.5 py-0.5 align-middle text-[10px] font-bold tracking-wide ${k.cls}`}>{k.label}</span>}
              {s.text.replace(/^(OBSERVED baseline|ESTIMATE \(not observed data\) —)/, (m) => (k ? (m.startsWith("OBS") ? "Baseline" : "") : m)).trim()}
              {refs.map((n) => <button key={n} onClick={() => { setOpen(open === n ? null : n); setShowAll(true); }} className="ml-0.5 align-super text-[10px] font-semibold text-brand-600 hover:underline" aria-label={`Calculation ${n}`}>[{n}]</button>)}
            </li>
          );
        })}
      </ul>
      {footnotes.length > 0 && (
        <div className="mt-4 rounded-lg border border-slate-200 dark:border-white/10">
          <button onClick={() => setShowAll(!showAll)} className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm font-medium">
            <ShieldCheck className="h-4 w-4 text-emerald-600" /> Supporting calculations ({footnotes.length}) · {footnotes.filter((f) => f.verified).length} verified
            <ChevronDown className={`ml-auto h-4 w-4 transition ${showAll ? "rotate-180" : ""}`} />
          </button>
          {showAll && (
            <ol className="divide-y divide-slate-100 border-t border-slate-100 text-xs dark:divide-white/5 dark:border-white/5">
              {footnotes.map((f) => (
                <li key={f.fact} className={`px-3 py-2 ${open === f.n ? "bg-brand-50 dark:bg-brand-500/10" : ""}`}>
                  <div className="flex items-center gap-2"><span className="font-semibold text-brand-600">[{f.n}]</span><span className="font-medium">{f.label}</span>
                    <span className="ml-auto tabular-nums">{f.value == null ? "n/a" : f.unit === "pct" ? `${f.value.toFixed(2)}%` : fmt(f.value)}</span>
                    {f.estimate ? <span title="Model estimate, not observed data" className="flex items-center gap-1 text-amber-600"><FlaskConical className="h-3.5 w-3.5" /> estimate</span>
                      : f.verified ? <span className="flex items-center gap-1 text-emerald-600"><CheckCircle2 className="h-3.5 w-3.5" /> verified</span> : null}</div>
                  <p className="mt-1 text-slate-500">{f.sql ? <code className="break-all font-mono">{f.sql}</code> : <>Calculated as <b>{f.op}</b>({(f.inputs ?? []).join(", ")}) from facts{(f.inputs ?? []).map((i) => footnotes.find((x) => x.fact === i)?.n).filter(Boolean).length ? " " + (f.inputs ?? []).map((i) => footnotes.find((x) => x.fact === i)?.n).filter(Boolean).map((n) => `[${n}]`).join(" ") : ""}</>}
                    {f.detail && <span className="ml-1 text-slate-400">— {f.detail}</span>}</p>
                </li>))}
            </ol>)}
        </div>)}
    </div>
  );
}
