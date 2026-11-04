import { Activity, AlertTriangle, ArrowRight, CheckCircle2, Crown, Link2, ShieldAlert, TrendingDown, TrendingUp, UserX } from "lucide-react";
import type { ReactNode } from "react";
import type { Insight } from "../../lib/types";

const META: Record<string, { icon: ReactNode; label: string }> = {
  growth: { icon: <TrendingUp className="h-4 w-4" />, label: "Growth" }, decline: { icon: <TrendingDown className="h-4 w-4" />, label: "Decline" },
  performer: { icon: <Crown className="h-4 w-4" />, label: "High performer" }, declining: { icon: <TrendingDown className="h-4 w-4" />, label: "Declining" },
  customer: { icon: <UserX className="h-4 w-4" />, label: "Customer behaviour" }, correlation: { icon: <Link2 className="h-4 w-4" />, label: "Correlation" },
  distribution: { icon: <Activity className="h-4 w-4" />, label: "Distribution" }, data_quality: { icon: <AlertTriangle className="h-4 w-4" />, label: "Data quality" }, concentration: { icon: <ShieldAlert className="h-4 w-4" />, label: "Concentration risk" },
};
const SEV: Record<string, string> = { high: "border-l-red-500", medium: "border-l-amber-500", low: "border-l-sky-500", info: "border-l-slate-300 dark:border-l-slate-600" };
const SEV_BADGE: Record<string, string> = { high: "bg-red-100 text-red-700 dark:bg-red-500/20 dark:text-red-300", medium: "bg-amber-100 text-amber-800 dark:bg-amber-500/20 dark:text-amber-300", low: "bg-sky-100 text-sky-700 dark:bg-sky-500/20 dark:text-sky-300", info: "bg-slate-100 text-slate-600 dark:bg-white/10 dark:text-slate-300" };

export function InsightCard({ i, onInvestigate }: { i: Insight; onInvestigate?: (i: Insight) => void }) {
  const m = META[i.type] ?? { icon: <AlertTriangle className="h-4 w-4" />, label: i.type };
  return (
    <article className={`card animate-fadeUp border-l-4 p-4 ${SEV[i.severity]}`}>
      <div className="flex items-center gap-2 text-xs"><span className="flex items-center gap-1.5 font-semibold text-slate-600 dark:text-slate-300">{m.icon}{m.label}</span>
        <span className={`rounded-full px-2 py-0.5 font-medium ${SEV_BADGE[i.severity]}`}>{i.severity}</span>
        {i.verified && <span title={i.verification_detail} className="ml-auto flex items-center gap-1 text-emerald-600"><CheckCircle2 className="h-3.5 w-3.5" /> verified</span>}</div>
      <h3 className="mt-2 font-semibold">{i.title}</h3>
      <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">{i.text}</p>
      {i.investigate && onInvestigate && <button onClick={() => onInvestigate(i)} className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-brand-600 hover:underline">{i.investigate.tool === "root_cause" ? "Find the root cause" : i.investigate.tool === "clean" ? "Fix on the data page" : "Analyse further"} <ArrowRight className="h-3.5 w-3.5" /></button>}
    </article>
  );
}
