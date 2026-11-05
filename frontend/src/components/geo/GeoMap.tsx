import type { Feature, FeatureCollection, Geometry } from "geojson";
import { geoArea, geoNaturalEarth1, geoPath } from "d3-geo";
import { interpolateZoom } from "d3-interpolate";
import { Minus, Plus } from "lucide-react";
import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { compact, easeInOutCubic, fillFor, maxMetric, net, radiusFor, type GeoLevel, type GeoMode, type GeoRegion } from "../../lib/geoRevenue";
import type { NumMode } from "../../lib/numfmt";

export type GeoFeature = Feature<Geometry, Record<string, any>>;
export interface MapNav { country: { iso3: string; name: string } | null; state: string | null; city: string | null }
type View = [number, number, number]; // centre x, centre y, visible width (projected px)

interface Props {
  level: GeoLevel;
  nav: MapNav;
  mode: GeoMode;
  numMode: NumMode;
  world: FeatureCollection<Geometry, Record<string, any>> | undefined;
  states: FeatureCollection<Geometry, Record<string, any>> | undefined;
  regions: GeoRegion[];           // children of the current level (countries / states / cities)
  childLevel: GeoLevel | null;
  inset: number;                  // px at the right covered by the details panel; the camera centres in the remaining area
  onSelect: (level: GeoLevel, region: GeoRegion) => void;
}

const reduced = () => typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/** Polygons smaller than 30% of the biggest one (Alaska-style exclaves, overseas territories) do not steer the zoom. */
function mainGeometry(g: Geometry): Geometry {
  if (g.type !== "MultiPolygon") return g;
  const areas = g.coordinates.map((c) => geoArea({ type: "Polygon", coordinates: c }));
  const max = Math.max(...areas);
  const keep = g.coordinates.filter((_, i) => areas[i] >= max * 0.3);
  return { type: "MultiPolygon", coordinates: keep };
}

function GeoMapInner({ level, nav, mode, numMode, world, states, regions, childLevel, inset, onSelect }: Props) {
  const wrap = useRef<HTMLDivElement>(null);
  const gRef = useRef<SVGGElement>(null);
  const markerRef = useRef<SVGGElement>(null);
  const [size, setSize] = useState({ w: 900, h: 500 });
  const [hover, setHover] = useState<{ r: GeoRegion | null; name: string; x: number; y: number } | null>(null);
  const view = useRef<View>([450, 250, 900]);
  const anim = useRef<number | null>(null);
  const drag = useRef<{ x: number; y: number; moved: number } | null>(null);

  useLayoutEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize({ w: Math.max(320, el.clientWidth), h: Math.max(260, el.clientHeight) }));
    ro.observe(el);
    setSize({ w: Math.max(320, el.clientWidth), h: Math.max(260, el.clientHeight) });
    return () => ro.disconnect();
  }, []);

  const projection = useMemo(() => geoNaturalEarth1().fitExtent([[8, 8], [size.w - 8, size.h - 8]], { type: "Sphere" }), [size]);
  const path = useMemo(() => geoPath(projection), [projection]);

  /** Write the camera to the DOM directly: 60fps without re-rendering hundreds of paths. */
  const apply = useCallback((v: View) => {
    view.current = v;
    const k = size.w / v[2];
    const tx = size.w / 2 - v[0] * k, ty = size.h / 2 - v[1] * k;
    gRef.current?.setAttribute("transform", `translate(${tx} ${ty}) scale(${k})`);
    const m = markerRef.current;
    if (m) for (const c of Array.from(m.children)) {
      const el = c as SVGGElement;
      el.setAttribute("transform", `translate(${Number(el.dataset.x) * k + tx} ${Number(el.dataset.y) * k + ty})`);
    }
  }, [size]);

  /** Camera that frames `b` inside the part of the canvas not covered by the panel. */
  const viewFor = useCallback((b: [[number, number], [number, number]], pad = 1.25): View => {
    const bw = Math.max(b[1][0] - b[0][0], 1), bh = Math.max(b[1][1] - b[0][1], 1);
    const avail = Math.max(size.w - inset, size.w * 0.4);
    const k = avail / Math.max(bw * pad, bh * pad * (avail / size.h));
    return [(b[0][0] + b[1][0]) / 2 + (size.w - avail) / 2 / k, (b[0][1] + b[1][1]) / 2, size.w / k];
  }, [size, inset]);

  const flyTo = useCallback((to: View) => {
    if (anim.current) cancelAnimationFrame(anim.current);
    const from = view.current;
    if (reduced()) { apply(to); return; }
    const i = interpolateZoom(from, to);
    const dur = Math.min(1400, Math.max(550, i.duration * 0.7));
    const t0 = performance.now();
    const step = (now: number) => {
      const t = Math.min(1, (now - t0) / dur);
      apply(i(easeInOutCubic(t)) as View);
      anim.current = t < 1 ? requestAnimationFrame(step) : null;
    };
    anim.current = requestAnimationFrame(step);
  }, [apply]);

  // ---- camera target for the current navigation ----
  const worldView = useMemo<View>(() => viewFor(path.bounds({ type: "Sphere" }), 1.04), [path, viewFor]);
  const countryFeature = useMemo(() => nav.country ? world?.features.find((f) => f.properties.iso3 === nav.country!.iso3) : undefined, [world, nav.country]);
  const stateFeature = useMemo(() => nav.state ? states?.features.find((f) => f.properties.name === nav.state) : undefined, [states, nav.state]);
  const cityRegion = useMemo(() => nav.city ? regions.find((r) => r.name === nav.city) : undefined, [regions, nav.city]);

  const target = useMemo<View | null>(() => {
    const bounds = (f: GeoFeature) => path.bounds({ type: "Feature", properties: {}, geometry: mainGeometry(f.geometry) });
    if (cityRegion?.lon != null && cityRegion.lat != null) {
      const p = projection([cityRegion.lon, cityRegion.lat]);
      if (p) return viewFor([[p[0] - size.w / 140, p[1] - size.w / 140 * size.h / size.w], [p[0] + size.w / 140, p[1] + size.w / 140 * size.h / size.w]], 1);
    }
    if (nav.state && stateFeature) return viewFor(bounds(stateFeature));
    if (nav.country && countryFeature) return viewFor(bounds(countryFeature));
    if (!nav.country) return worldView;
    return null; // data still loading
  }, [cityRegion, stateFeature, countryFeature, nav, path, projection, size, viewFor, worldView]);

  const targetKey = `${nav.country?.iso3 ?? ""}|${nav.state ?? ""}|${nav.city ?? ""}`;
  const lastKey = useRef<string | null>(null);
  const lastSize = useRef(size);
  useEffect(() => {
    if (!target) return;
    if (lastSize.current !== size) { lastSize.current = size; apply(target); lastKey.current = targetKey; return; } // resize: snap
    if (lastKey.current === null) apply(target); else flyTo(target);
    lastKey.current = targetKey;
  }, [target, targetKey, size, apply, flyTo]);
  useEffect(() => () => { if (anim.current) cancelAnimationFrame(anim.current); }, []);
  // markers mount after the camera was set: position them for the current view
  useLayoutEffect(() => { apply(view.current); });

  // ---- wheel zoom / drag pan / buttons ----
  const zoomBy = useCallback((f: number, cx = size.w / 2, cy = size.h / 2) => {
    if (anim.current) { cancelAnimationFrame(anim.current); anim.current = null; }
    const [vx, vy, vw] = view.current;
    const k = size.w / vw;
    const px = (cx - size.w / 2) / k + vx, py = (cy - size.h / 2) / k + vy;   // map point under the cursor
    const nw = Math.min(size.w * 1.05, Math.max(size.w / 400, vw / f));
    const nk = size.w / nw;
    apply([px - (cx - size.w / 2) / nk, py - (cy - size.h / 2) / nk, nw]);
  }, [apply, size]);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => { e.preventDefault(); const r = el.getBoundingClientRect(); zoomBy(Math.exp(-e.deltaY * 0.0015), e.clientX - r.left, e.clientY - r.top); };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [zoomBy]);

  const onDown = (e: React.PointerEvent) => { drag.current = { x: e.clientX, y: e.clientY, moved: 0 }; };
  const onMove = (e: React.PointerEvent) => {
    const d = drag.current;
    if (d && e.buttons) {
      const dx = e.clientX - d.x, dy = e.clientY - d.y;
      d.moved += Math.abs(dx) + Math.abs(dy);
      d.x = e.clientX; d.y = e.clientY;
      if (d.moved > 4) {
        if (anim.current) { cancelAnimationFrame(anim.current); anim.current = null; }
        const k = size.w / view.current[2];
        apply([view.current[0] - dx / k, view.current[1] - dy / k, view.current[2]]);
        setHover(null);
      }
    }
  };
  const clicked = (fn: () => void) => () => { if ((drag.current?.moved ?? 0) <= 4) fn(); };

  // ---- drawing ----
  const byKey = useMemo(() => new Map(regions.map((r) => [r.key, r])), [regions]);
  const max = useMemo(() => maxMetric(regions, mode), [regions, mode]);
  const colored = level === "world" || level === "country";   // below that, polygons are context and cities carry the data
  const polys = level === "world" ? world : states;
  const showCities = regions.some((r) => r.lat != null);

  const feats = useMemo(() => {
    const d = (f: GeoFeature) => path(f) ?? "";
    return {
      context: nav.country ? (world?.features ?? []).filter((f) => f.properties.iso3 !== nav.country!.iso3).map((f) => ({ id: f.properties.iso3 as string, d: d(f) })) : [],
      base: (polys?.features ?? []).map((f) => ({ f, id: (level === "world" ? f.properties.iso3 : f.properties.name) as string, d: d(f) })),
    };
  }, [world, polys, path, nav.country, level]);

  const regionOf = (id: string) => byKey.get(id);
  const tip = (e: React.MouseEvent, r: GeoRegion | undefined, name: string) => {
    const b = wrap.current!.getBoundingClientRect();
    setHover({ r: r ?? null, name, x: e.clientX - b.left, y: e.clientY - b.top });
  };

  const stateSelected = nav.state;
  const cities = useMemo(() => regions.filter((r) => r.lat != null && r.lon != null).map((r) => ({ r, p: projection([r.lon!, r.lat!]) })).filter((c) => c.p), [regions, projection]);

  return (
    <div ref={wrap} className="relative h-full w-full select-none overflow-hidden touch-none bg-slate-100 dark:bg-ink-950" onPointerDown={onDown} onPointerMove={onMove}
      onPointerLeave={() => setHover(null)} role="application" aria-label="Interactive revenue map">
      <svg width={size.w} height={size.h} className="block" style={{ cursor: drag.current && drag.current.moved > 4 ? "grabbing" : "grab" }}>
        <defs>
          <radialGradient id="geo-ocean" cx="50%" cy="45%" r="75%">
            <stop offset="0%" stopColor="rgb(var(--brand-500))" stopOpacity="0.10" /><stop offset="100%" stopColor="rgb(var(--brand-500))" stopOpacity="0" />
          </radialGradient>
        </defs>
        <rect width={size.w} height={size.h} fill="url(#geo-ocean)" />
        <g ref={gRef}>
          {/* context: every other country, dimmed */}
          <g className="fill-slate-200/70 stroke-white dark:fill-white/[0.04] dark:stroke-white/10" strokeWidth={0.5} style={{ vectorEffect: "non-scaling-stroke" }}>
            {(nav.country ? feats.context : []).map((c) => <path key={c.id} d={c.d} vectorEffect="non-scaling-stroke" />)}
          </g>
          {feats.base.map(({ f, id, d }) => {
            const r = colored ? regionOf(id) : undefined;
            const fill = fillFor(r, mode, max);
            const isSel = !colored && stateSelected === id;
            const dimmed = !colored && !isSel;
            const clickable = !!r;
            return (
              <path key={id} d={d} vectorEffect="non-scaling-stroke"
                className={`${fill ? "" : "fill-slate-200 dark:fill-white/[0.07]"} stroke-white transition-[fill,opacity] duration-300 dark:stroke-ink-900 ${clickable ? "cursor-pointer hover:brightness-110" : ""}`}
                style={{ fill: fill ?? undefined, opacity: dimmed ? 0.35 : 1, strokeWidth: isSel ? 2 : 0.7 }}
                onMouseMove={(e) => tip(e, r, f.properties.name as string)} onMouseLeave={() => setHover(null)}
                onClick={clicked(() => { if (r && clickable) onSelect(level === "world" ? "country" : "state", r); })}>
              </path>
            );
          })}
          {/* the clicked country's outline stays visible above the dim context */}
          {nav.country && countryFeature && <path d={path(countryFeature) ?? ""} fill="none" vectorEffect="non-scaling-stroke" className="stroke-brand-500" strokeWidth={1.5} pointerEvents="none" />}
        </g>
        {/* markers live outside the zoomed group so they keep a constant pixel size */}
        <g ref={markerRef}>
          {showCities && cities.map(({ r, p }) => {
            const fill = fillFor(r, mode, max) ?? `rgba(148,163,184,0.6)`;
            const sel = nav.city === r.name;
            return (
              <g key={r.key} data-x={p![0]} data-y={p![1]} className="cursor-pointer"
                onMouseMove={(e) => tip(e, r, r.name)} onMouseLeave={() => setHover(null)} onClick={clicked(() => onSelect("city", r))}>
                <circle r={radiusFor(r, mode, max)} fill={fill} className={sel ? "stroke-brand-500" : "stroke-white dark:stroke-ink-900"} strokeWidth={sel ? 2.5 : 1.25} />
                {radiusFor(r, mode, max) > 11 && <text textAnchor="middle" dy="0.35em" className="pointer-events-none fill-slate-900 text-[9px] font-semibold dark:fill-white">{compact(mode === "loss" ? r.loss : mode === "both" ? net(r) : r.revenue, numMode)}</text>}
              </g>
            );
          })}
        </g>
      </svg>

      <div className="absolute bottom-4 left-4 flex flex-col overflow-hidden rounded-lg border border-slate-200 bg-white/90 shadow-card backdrop-blur dark:border-white/10 dark:bg-ink-900/90">
        <button className="p-2 hover:bg-slate-100 dark:hover:bg-white/10" onClick={() => zoomBy(1.6)} aria-label="Zoom in"><Plus className="h-4 w-4" /></button>
        <button className="border-t border-slate-200 p-2 hover:bg-slate-100 dark:border-white/10 dark:hover:bg-white/10" onClick={() => zoomBy(1 / 1.6)} aria-label="Zoom out"><Minus className="h-4 w-4" /></button>
      </div>

      {hover && (
        <div className="pointer-events-none absolute z-20 w-56 rounded-lg border border-slate-200 bg-white/95 p-3 text-xs shadow-pop backdrop-blur dark:border-white/10 dark:bg-ink-900/95"
          style={{ left: Math.min(hover.x + 14, size.w - 232), top: Math.min(hover.y + 14, size.h - 150) }}>
          <p className="mb-1.5 text-sm font-semibold text-slate-900 dark:text-white">{hover.name}</p>
          {hover.r ? (<dl className="space-y-1 tabular-nums">
            {hover.r.revenue != null && <Row k="Revenue" v={compact(hover.r.revenue, numMode)} tone="text-emerald-600 dark:text-emerald-400" />}
            {hover.r.loss != null && <Row k="Loss" v={compact(hover.r.loss, numMode)} tone="text-red-600 dark:text-red-400" />}
            {hover.r.profit != null && <Row k="Profit" v={compact(hover.r.profit, numMode)} tone={hover.r.profit >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400"} />}
            <Row k="Transactions" v={hover.r.transactions.toLocaleString()} />
            {hover.r.share != null && <Row k="Share of revenue" v={`${(hover.r.share * 100).toFixed(1)}%`} />}
            <p className="pt-1 text-[11px] text-slate-400">{childLevel && level !== "city" ? "Click to zoom in" : ""}</p>
          </dl>) : <p className="text-slate-500">No data for this region</p>}
        </div>
      )}
    </div>
  );
}

const Row = ({ k, v, tone }: { k: string; v: string; tone?: string }) => (
  <div className="flex justify-between gap-3"><dt className="text-slate-500">{k}</dt><dd className={`font-medium ${tone ?? "text-slate-900 dark:text-white"}`}>{v}</dd></div>
);

export const GeoMap = memo(GeoMapInner);
