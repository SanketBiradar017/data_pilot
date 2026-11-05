import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import type { FeatureCollection, Geometry } from "geojson";
import { ChevronRight, Columns3, Globe2, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { DatasetPicker, useDatasets } from "../components/DatasetPicker";
import { DetailsPanel } from "../components/geo/DetailsPanel";
import { GeoMap, type MapNav } from "../components/geo/GeoMap";
import { MappingDialog } from "../components/geo/MappingDialog";
import { Empty, Loading, Spinner } from "../components/ui";
import { compact, crumbs, type GeoDetection, type GeoLevel, type GeoMapping, type GeoMode, type GeoRegion, type GeoSummary } from "../lib/geoRevenue";
import { useNumFmt, type NumMode } from "../lib/numfmt";

type Fc = FeatureCollection<Geometry, Record<string, any>>;
const MODES: { id: GeoMode; label: string }[] = [{ id: "revenue", label: "Revenue" }, { id: "loss", label: "Loss" }, { id: "both", label: "Both" }];
const EMPTY_NAV: MapNav = { country: null, state: null, city: null };

export default function GeoRevenue() {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const { data: datasets = [], isLoading } = useDatasets();
  const tables = datasets.filter((d) => d.kind === "table");
  const [datasetId, setDatasetId] = useState<number | null>(params.get("dataset") ? Number(params.get("dataset")) : null);
  const { mode: numMode, setMode: setNumMode } = useNumFmt();
  const [mode, setMode] = useState<GeoMode>("both");
  const [nav, setNav] = useState<MapNav>(EMPTY_NAV);
  const [from, setFrom] = useState(""), [to, setTo] = useState("");
  const [panel, setPanel] = useState(() => typeof window === "undefined" || window.innerWidth >= 1024);
  const [mapping, setMapping] = useState(false);
  const [wide, setWide] = useState(() => typeof window === "undefined" || window.innerWidth >= 1024);
  useEffect(() => { const h = () => setWide(window.innerWidth >= 1024); window.addEventListener("resize", h); return () => window.removeEventListener("resize", h); }, []);
  const autoOpened = useRef<number | null>(null);

  useEffect(() => { if (datasetId == null && tables.length) setDatasetId(tables[0].id); }, [tables, datasetId]);
  const pick = (id: number | null) => { setDatasetId(id); setNav(EMPTY_NAV); setFrom(""); setTo(""); autoOpened.current = null; if (id) setParams({ dataset: String(id) }, { replace: true }); };

  const level: GeoLevel = nav.city ? "city" : nav.state ? "state" : nav.country ? "country" : "world";
  const queryLevel = level === "city" ? "state" : level;

  const det = useQuery({ queryKey: ["geo", "mapping", datasetId], enabled: datasetId != null, staleTime: 60_000, queryFn: () => api.get<GeoDetection>(`/geo-revenue/mapping/${datasetId}`) });
  const needsDialog = !!det.data && !det.data.saved && det.data.issues.some((i) => /No (location|revenue)/.test(i));
  useEffect(() => { if (needsDialog && autoOpened.current !== datasetId) { autoOpened.current = datasetId; setMapping(true); } }, [needsDialog, datasetId]);

  const summary = useQuery({
    queryKey: ["geo", "summary", datasetId, queryLevel, nav.country?.iso3 ?? null, nav.state, from, to, det.data?.saved ?? null],
    enabled: datasetId != null && !!det.data && !needsDialog, placeholderData: keepPreviousData, retry: 0, staleTime: 30_000,
    queryFn: () => api.post<GeoSummary>("/geo-revenue/summary", { dataset_id: datasetId, level: queryLevel, country: nav.country?.iso3, state: nav.state, date_from: from || undefined, date_to: to || undefined }),
  });
  const world = useQuery({ queryKey: ["geo", "world"], staleTime: Infinity, gcTime: Infinity, queryFn: () => api.get<Fc>("/geo-revenue/boundaries/world") });
  const states = useQuery({ queryKey: ["geo", "states", nav.country?.iso3], enabled: !!nav.country, staleTime: Infinity, retry: 0, queryFn: () => api.get<Fc>(`/geo-revenue/boundaries/${nav.country!.iso3}/states`) });

  // the full date span comes from the unfiltered world response; keep the last one seen so the pickers do not jump
  const [bounds, setBounds] = useState<{ min: string; max: string } | null>(null);
  useEffect(() => { setBounds(null); }, [datasetId]);
  useEffect(() => { if (summary.data?.date_range) setBounds(summary.data.date_range); }, [summary.data]);

  const save = useMutation({
    mutationFn: (m: GeoMapping) => api.put(`/geo-revenue/mapping/${datasetId}`, m),
    onSuccess: () => { setMapping(false); setNav(EMPTY_NAV); qc.invalidateQueries({ queryKey: ["geo"] }); },
  });
  const reset = useMutation({
    mutationFn: () => api.del(`/geo-revenue/mapping/${datasetId}`),
    onSuccess: () => { setMapping(false); qc.invalidateQueries({ queryKey: ["geo"] }); },
  });

  const select = useCallback((l: GeoLevel, r: GeoRegion) => {
    if (l === "country") setNav({ country: { iso3: r.key, name: r.name }, state: null, city: null });
    else if (l === "state") setNav((n) => ({ ...n, state: r.key, city: null }));
    else setNav((n) => ({ ...n, city: r.name }));
  }, []);
  const goTo = useCallback((l: GeoLevel) => setNav((n) => l === "world" ? EMPTY_NAV : l === "country" ? { country: n.country, state: null, city: null } : l === "state" ? { ...n, city: null } : n), []);
  const up = useCallback(() => setNav((n) => n.city ? { ...n, city: null } : n.state ? { ...n, state: null } : EMPTY_NAV), []);
  useEffect(() => { const h = (e: KeyboardEvent) => { if (e.key === "Escape" && !mapping && (e.target as HTMLElement)?.tagName !== "SELECT") up(); }; window.addEventListener("keydown", h); return () => window.removeEventListener("keydown", h); }, [up, mapping]);

  const s = summary.data;
  const regions = useMemo(() => s?.regions ?? [], [s]);
  const focus = nav.city ? regions.find((r) => r.name === nav.city) ?? null : null;
  const stale = summary.isPlaceholderData;
  const title = nav.city ?? nav.state ?? nav.country?.name ?? "World";
  const lowConf = !!det.data && !det.data.saved && det.data.needs_mapping && !needsDialog;

  if (isLoading) return <Loading />;
  if (!tables.length) return <div className="p-8"><Empty icon={Globe2} title="No tabular data yet" text="Upload a dataset with country/state/city and revenue columns on the Data sources page to explore it on the map." /></div>;

  return (
    <div className="flex h-full flex-col">
      {/* toolbar */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-slate-200 bg-white px-4 py-2.5 dark:border-white/10 dark:bg-ink-900">
        <div className="mr-1 flex items-center gap-2"><Globe2 className="h-5 w-5 text-brand-600" /><h1 className="text-base font-semibold tracking-tight">Global Revenue Intelligence</h1></div>
        <div className="w-64 max-w-full"><DatasetPicker value={datasetId} onChange={pick} kind="table" /></div>
        <div role="group" aria-label="Visualization mode" className="inline-flex rounded-lg border border-slate-200 p-0.5 dark:border-white/10">
          {MODES.map((m) => (
            <button key={m.id} aria-pressed={mode === m.id} onClick={() => setMode(m.id)}
              className={clsx("rounded-md px-3 py-1 text-sm font-medium transition", mode === m.id ? (m.id === "loss" ? "bg-red-500 text-white" : m.id === "revenue" ? "bg-emerald-500 text-white" : "bg-brand-600 text-white") : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-white/10")}>{m.label}</button>))}
        </div>
        <div className="flex items-center gap-1.5 text-sm">
          <input type="date" aria-label="From date" className="input !w-auto !py-1.5" value={from} min={bounds?.min} max={to || bounds?.max} disabled={!bounds} onChange={(e) => setFrom(e.target.value)} />
          <span className="text-slate-400">→</span>
          <input type="date" aria-label="To date" className="input !w-auto !py-1.5" value={to} min={from || bounds?.min} max={bounds?.max} disabled={!bounds} onChange={(e) => setTo(e.target.value)} />
          {(from || to) && <button className="text-xs text-brand-600 hover:underline" onClick={() => { setFrom(""); setTo(""); }}>Clear</button>}
        </div>
        <select className="input !w-auto !py-1.5" value={numMode} onChange={(e) => setNumMode(e.target.value as NumMode)} aria-label="Number format">
          <option value="standard">1,234,567</option><option value="indian">12,34,567</option><option value="inr">₹ 12,34,567</option></select>
        <div className="ml-auto flex items-center gap-2">
          {lowConf && <button onClick={() => setMapping(true)} className="rounded-full bg-amber-100 px-2.5 py-1 text-xs font-medium text-amber-800 hover:bg-amber-200 dark:bg-amber-500/15 dark:text-amber-300">Low-confidence detection · review</button>}
          <button className="btn-ghost !py-1.5" onClick={() => setMapping(true)} disabled={!det.data}><Columns3 className="h-4 w-4" /> Columns</button>
        </div>
      </div>

      {/* map */}
      <div className="relative min-h-0 flex-1">
        <GeoMap level={level} nav={nav} mode={mode} numMode={numMode} world={world.data} states={states.data} regions={regions} childLevel={s?.child_level ?? null} inset={panel && wide ? 384 : 0} onSelect={select} />

        <nav aria-label="Map location" className="absolute left-4 top-4 z-10 flex max-w-[calc(100%-5rem)] items-center gap-1 rounded-xl border border-slate-200 bg-white/95 px-2 py-1.5 text-sm shadow-card backdrop-blur dark:border-white/10 dark:bg-ink-900/95">
          {crumbs(nav).map((c, i, arr) => (
            <span key={c.level} className="flex min-w-0 items-center gap-1">
              {i > 0 && <ChevronRight className="h-3.5 w-3.5 shrink-0 text-slate-400" />}
              {i === arr.length - 1 ? <span aria-current="page" className="truncate px-1.5 font-semibold">{c.label}</span>
                : <button onClick={() => goTo(c.level)} className="truncate rounded px-1.5 py-0.5 text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-white/10">{c.label}</button>}
            </span>
          ))}
          {level !== "world" && <button onClick={() => setNav(EMPTY_NAV)} className="ml-1 flex items-center gap-1 rounded-lg border border-slate-200 px-2 py-0.5 text-xs font-medium text-slate-600 hover:bg-slate-100 dark:border-white/10 dark:text-slate-300 dark:hover:bg-white/10"><RotateCcw className="h-3 w-3" /> Reset</button>}
        </nav>

        <Legend mode={mode} s={s} numMode={numMode} />
        {(summary.isFetching || world.isLoading || states.isFetching) && <div className="absolute bottom-4 right-1/2 z-10 translate-x-1/2 rounded-full bg-white/95 p-2 shadow-card dark:bg-ink-900/95"><Spinner className="text-brand-600" /></div>}
        {summary.error && !stale && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-white/70 p-6 backdrop-blur-sm dark:bg-ink-950/70">
            <div className="card max-w-md p-6 text-center"><p className="font-medium">Couldn't build the map</p><p className="mt-1 text-sm text-slate-500">{(summary.error as Error).message}</p>
              <button className="btn-primary mt-4" onClick={() => setMapping(true)}>Map columns</button></div>
          </div>)}
        {states.isError && nav.country && <p className="absolute bottom-16 left-4 z-10 rounded-lg bg-white/95 px-3 py-1.5 text-xs text-slate-600 shadow-card dark:bg-ink-900/95 dark:text-slate-300">No state boundaries are available for this country.</p>}

        <DetailsPanel open={panel} onToggle={() => setPanel((p) => !p)} summary={s} title={title} level={level} numMode={numMode} focus={focus} loading={stale}
          onPick={(r) => { if (level === "world") select("country", r); else if (s?.child_level === "state") select("state", r); else select("city", r); }} />
      </div>

      {mapping && det.data && <MappingDialog detection={det.data} saving={save.isPending || reset.isPending} error={(save.error as Error)?.message ?? null}
        onSave={(m) => save.mutate(m)} onReset={() => reset.mutate()} onClose={() => { if (!save.isPending) setMapping(false); }} />}
    </div>
  );
}

function Legend({ mode, s, numMode }: { mode: GeoMode; s: GeoSummary | undefined; numMode: NumMode }) {
  const max = useMemo(() => (s?.regions ?? []).reduce((m, r) => Math.max(m, Math.abs(mode === "revenue" ? r.revenue ?? 0 : mode === "loss" ? r.loss ?? 0 : r.profit ?? (r.revenue ?? 0) - (r.loss ?? 0))), 0), [s, mode]);
  const g = "linear-gradient(90deg, rgba(16,185,129,.3), rgba(16,185,129,.95))", r = "linear-gradient(90deg, rgba(239,68,68,.3), rgba(239,68,68,.95))";
  return (
    <div className="absolute bottom-4 left-1/2 z-10 -translate-x-1/2 rounded-xl border border-slate-200 bg-white/95 px-3 py-2 text-[11px] shadow-card backdrop-blur dark:border-white/10 dark:bg-ink-900/95" aria-label="Legend">
      <div className="flex items-center gap-2 text-slate-600 dark:text-slate-300">
        {mode === "both" ? (<><span>Loss</span><span className="h-2 w-16 rounded-full" style={{ background: "linear-gradient(90deg, rgba(239,68,68,.95), rgba(239,68,68,.3))" }} /><span className="text-slate-400">net result</span><span className="h-2 w-16 rounded-full" style={{ background: g }} /><span>Profit</span></>)
          : (<><span>{compact(0, numMode)}</span><span className="h-2 w-28 rounded-full" style={{ background: mode === "loss" ? r : g }} /><span>{compact(max, numMode)} {mode === "loss" ? "loss" : "revenue"}</span></>)}
      </div>
    </div>
  );
}
