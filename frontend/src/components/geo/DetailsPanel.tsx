import clsx from "clsx";
import { AlertTriangle, ChevronRight, PanelRightClose, PanelRightOpen } from "lucide-react";
import { CHILD_LABEL, compact, type GeoLevel, type GeoRegion, type GeoSummary } from "../../lib/geoRevenue";
import { formatCount, formatNumber, type NumMode } from "../../lib/numfmt";

interface Props {
  open: boolean; onToggle: () => void; summary: GeoSummary | undefined; title: string; level: GeoLevel; numMode: NumMode;
  focus: GeoRegion | null;           // the selected city, when one is chosen
  onPick: (r: GeoRegion) => void; loading: boolean;
}

function Kpi({ label, value, tone, sub }: { label: string; value: string; tone?: "green" | "red"; sub?: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white/60 p-3 dark:border-white/10 dark:bg-white/[0.03]">
      <p className="text-[11px] font-medium uppercase tracking-wide text-slate-500">{label}</p>
      <p className={clsx("mt-1 truncate text-xl font-semibold tabular-nums", tone === "green" && "text-emerald-600 dark:text-emerald-400", tone === "red" && "text-red-600 dark:text-red-400", !tone && "text-slate-900 dark:text-white")}>{value}</p>
      {sub && <p className="mt-0.5 text-[11px] text-slate-500">{sub}</p>}
    </div>
  );
}

function RegionList({ title, items, kind, numMode, onPick }: { title: string; items: GeoRegion[]; kind: "revenue" | "loss"; numMode: NumMode; onPick: (r: GeoRegion) => void }) {
  if (!items.length) return null;
  const top = Math.max(...items.map((r) => Math.abs((kind === "revenue" ? r.revenue : r.loss) ?? 0)), 1);
  return (
    <section>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</h3>
      <ul className="space-y-1">
        {items.map((r) => {
          const v = (kind === "revenue" ? r.revenue : r.loss) ?? 0;
          return (
            <li key={r.key}>
              <button onClick={() => onPick(r)} className="group relative w-full overflow-hidden rounded-lg px-2.5 py-1.5 text-left text-sm transition hover:bg-slate-100 dark:hover:bg-white/5">
                <span className={clsx("absolute inset-y-0 left-0 opacity-15", kind === "revenue" ? "bg-emerald-500" : "bg-red-500")} style={{ width: `${(Math.abs(v) / top) * 100}%` }} />
                <span className="relative flex items-center justify-between gap-2">
                  <span className="truncate font-medium text-slate-800 dark:text-slate-100">{r.name}</span>
                  <span className={clsx("tabular-nums", kind === "revenue" ? "text-emerald-700 dark:text-emerald-400" : "text-red-600 dark:text-red-400")}>{compact(v, numMode)}</span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

export function DetailsPanel({ open, onToggle, summary, title, level, numMode, focus, onPick, loading }: Props) {
  const t = focus ? { revenue: focus.revenue, loss: focus.loss, profit: focus.profit, transactions: focus.transactions } : summary?.totals;
  const full = (v: number | null | undefined) => (v == null ? "—" : formatNumber(v, numMode, 0));
  const child = summary?.child_level ? CHILD_LABEL[summary.child_level] : "";
  return (
    <>
      <button onClick={onToggle} aria-label={open ? "Collapse details panel" : "Expand details panel"} aria-expanded={open}
        className={clsx("absolute top-4 z-30 rounded-lg border border-slate-200 bg-white/95 p-2 shadow-card backdrop-blur transition-all duration-300 hover:bg-slate-50 dark:border-white/10 dark:bg-ink-900/95 dark:hover:bg-ink-800", open ? "right-[calc(min(22rem,88vw)+1.5rem)]" : "right-4")}>
        {open ? <PanelRightClose className="h-4 w-4" /> : <PanelRightOpen className="h-4 w-4" />}
      </button>
      <aside aria-label="Region details" aria-hidden={!open}
        className={clsx("absolute inset-y-4 right-4 z-20 flex w-[min(22rem,88vw)] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white/95 shadow-pop backdrop-blur-md transition-all duration-300 dark:border-white/10 dark:bg-ink-900/95",
          open ? "translate-x-0 opacity-100" : "pointer-events-none translate-x-[110%] opacity-0")}>
        <header className="border-b border-slate-100 px-5 py-4 dark:border-white/5">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-brand-600 dark:text-brand-400">{focus ? "City" : level === "world" ? "Worldwide" : level}</p>
          <h2 className="truncate text-lg font-semibold text-slate-900 dark:text-white">{focus?.name ?? title}</h2>
          {summary?.date_range && <p className="text-xs text-slate-500">Data {summary.date_range.min} → {summary.date_range.max}</p>}
        </header>
        <div className={clsx("flex-1 space-y-5 overflow-y-auto px-5 py-4", loading && "opacity-60 transition-opacity")}>
          {!t ? <p className="text-sm text-slate-500">Loading…</p> : (<>
            <div className="grid grid-cols-2 gap-2.5">
              <Kpi label="Total revenue" tone="green" value={full(t.revenue)} sub={t.revenue != null ? compact(t.revenue, numMode) : "no revenue column"} />
              <Kpi label="Total loss" tone="red" value={full(t.loss)} sub={t.loss != null ? compact(t.loss, numMode) : "not calculable"} />
              <Kpi label="Total profit" tone={t.profit == null ? undefined : t.profit >= 0 ? "green" : "red"} value={full(t.profit)} sub={t.profit == null ? "needs expense or profit column" : compact(t.profit, numMode)} />
              <Kpi label="Transactions" value={formatCount(t.transactions, numMode)} />
            </div>
            {summary?.loss_basis === "negative_profit" && !focus && <p className="text-[11px] leading-snug text-slate-500">Loss = sum of rows where expenses exceeded revenue (no loss column mapped).</p>}
            {summary?.scope_note && <p className="flex gap-2 rounded-lg bg-amber-50 p-2.5 text-xs text-amber-800 dark:bg-amber-500/10 dark:text-amber-300"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />{summary.scope_note}</p>}
            {!focus && summary && summary.regions.length > 0 && (<>
              <RegionList title="Top performing" items={summary.top} kind="revenue" numMode={numMode} onPick={onPick} />
              <RegionList title="Lowest performing" items={summary.bottom} kind="revenue" numMode={numMode} onPick={onPick} />
              <RegionList title="Highest losses" items={summary.highest_loss} kind="loss" numMode={numMode} onPick={onPick} />
              <p className="flex items-center gap-1 text-[11px] text-slate-400">{summary.regions.length} {child} with data <ChevronRight className="h-3 w-3" /> click one on the map to zoom</p>
            </>)}
            {!focus && summary?.unmapped && (
              <p className="rounded-lg bg-slate-100 p-2.5 text-xs text-slate-600 dark:bg-white/5 dark:text-slate-300">
                {formatCount(summary.unmapped.transactions, numMode)} transactions ({compact(summary.unmapped.revenue, numMode)} revenue) could not be placed on the map — their location is blank or not recognised. They are included in the totals above.
              </p>
            )}
            {!focus && summary && summary.regions.length === 0 && !summary.scope_note && <p className="text-sm text-slate-500">No regions with data for the current filters.</p>}
          </>)}
        </div>
      </aside>
    </>
  );
}

