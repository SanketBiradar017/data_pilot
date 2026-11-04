import clsx from "clsx";
import { Check, Circle, X } from "lucide-react";
import { Spinner } from "./ui";
import type { Analysis, TraceEvent } from "../lib/types";

const ORDER = ["planner", "ingestion", "profiler", "cleaning", "sql", "analytics", "research", "visualization", "validation", "story", "report"];
const LABEL: Record<string, string> = { planner: "Planner", ingestion: "Data Ingestion", profiler: "Resource Profiler", cleaning: "Data Cleaning", sql: "SQL", analytics: "Analytics", root_cause: "Root Cause", scenario: "Scenario", discovery: "Insight Discovery", executive: "Executive Summary", quality: "Data Quality", forecast: "Forecast", business: "Business Insight", story: "Storytelling", research: "Research", visualization: "Visualization", validation: "Validation", report: "Report" };

/** Live agent workflow. Steps come from the planner's pipeline; the first not-yet-completed step is "running". */
export function AgentTimeline({ trace, plan, status, compact }: { trace: TraceEvent[]; plan?: Analysis["plan"]; status: Analysis["status"]; compact?: boolean }) {
  const pipeline = plan?.pipeline ?? ["planner", ...ORDER.slice(1, 4), "validation", "report"];
  const done = new Map<string, TraceEvent>();
  trace.forEach((t) => done.set(t.agent, t)); // later events (retries) win
  const activeIdx = status === "running" || status === "queued" ? pipeline.findIndex((a) => !done.has(a)) : -1;
  return (
    <ol className={clsx("relative space-y-1", compact ? "text-xs" : "text-sm")}>
      {pipeline.map((a, i) => {
        const ev = done.get(a);
        const running = i === activeIdx;
        return (
          <li key={a} className={clsx("flex gap-3 rounded-lg px-2 py-1.5 transition", running && "bg-brand-50 dark:bg-brand-500/10")}>
            <span className={clsx("mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border",
              ev?.status === "completed" && "border-emerald-500 bg-emerald-500 text-white", ev?.status === "failed" && "border-red-500 bg-red-500 text-white",
              running && "border-brand-500 text-brand-600", !ev && !running && "border-slate-300 text-slate-300 dark:border-white/15")}>
              {ev?.status === "completed" ? <Check className="h-3 w-3" /> : ev?.status === "failed" ? <X className="h-3 w-3" /> : running ? <Spinner className="h-3 w-3" /> : <Circle className="h-2 w-2" />}
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline justify-between gap-2">
                <span className={clsx("font-medium", !ev && !running && "text-slate-400")}>{LABEL[a] ?? a} Agent</span>
                {ev && <span className="shrink-0 tabular-nums text-xs text-slate-400">{ev.duration_ms < 1000 ? `${Math.round(ev.duration_ms)} ms` : `${(ev.duration_ms / 1000).toFixed(1)} s`}</span>}
                {running && <span className="animate-pulseDot text-xs text-brand-600">working…</span>}
              </div>
              {ev && !compact && <p className="mt-0.5 break-words text-xs text-slate-500 dark:text-slate-400">{ev.summary}</p>}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
