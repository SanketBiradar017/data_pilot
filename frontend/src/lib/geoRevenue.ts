import type { NumMode } from "./numfmt";

export type GeoMode = "revenue" | "loss" | "both";
export type GeoLevel = "world" | "country" | "state" | "city";

export interface GeoRegion {
  key: string; name: string; revenue: number | null; loss: number | null; profit: number | null; transactions: number;
  share?: number | null; iso3?: string; lat?: number | null; lon?: number | null; state?: string | null;
}
export interface GeoTotals { revenue: number | null; loss: number | null; profit: number | null; transactions: number }
export interface GeoSummary {
  level: GeoLevel; child_level: GeoLevel | null; country: string | null; state: string | null;
  totals: GeoTotals; regions: GeoRegion[]; unmapped: GeoTotals | null; scope_note: string | null;
  date_range: { min: string; max: string } | null; top: GeoRegion[]; bottom: GeoRegion[]; highest_loss: GeoRegion[];
  loss_basis: "loss_column" | "negative_profit" | "none"; capabilities: { revenue: boolean; loss: boolean; profit: boolean };
}
export const MAP_ROLES = ["country", "state", "city", "revenue", "expense", "loss", "profit", "date"] as const;
export type MapRole = (typeof MAP_ROLES)[number];
export type GeoMapping = Record<MapRole, string | null> & { assumed_country?: string | null };
export interface GeoDetection {
  mapping: Record<MapRole, string | null>; confidence: Record<MapRole, number>; alternatives: Record<MapRole, string[]>;
  assumed_country: string | null; needs_mapping: boolean; issues: string[]; columns: string[]; saved: GeoMapping | null;
}

export const GREEN = "16, 185, 129";
export const RED = "239, 68, 68";

/** Net result of a region: reported profit when available, else revenue minus loss. */
export function net(r: Pick<GeoRegion, "revenue" | "loss" | "profit">): number {
  if (r.profit != null) return r.profit;
  return (r.revenue ?? 0) - (r.loss ?? 0);
}

/** The magnitude that drives colour intensity for the active mode. */
export function metric(r: GeoRegion, mode: GeoMode): number {
  if (mode === "revenue") return r.revenue ?? 0;
  if (mode === "loss") return r.loss ?? 0;
  return net(r);
}

/** Largest absolute metric in a list, used to normalise intensities. */
export function maxMetric(regions: GeoRegion[], mode: GeoMode): number {
  return regions.reduce((m, r) => Math.max(m, Math.abs(metric(r, mode))), 0);
}

/** rgba fill for a region; null when it has nothing to show in this mode (render as neutral). */
export function fillFor(r: GeoRegion | undefined, mode: GeoMode, max: number): string | null {
  if (!r || max <= 0) return null;
  const v = metric(r, mode);
  if (v === 0 || (mode === "loss" && !r.loss)) return null;
  const t = Math.sqrt(Math.min(1, Math.abs(v) / max));  // sqrt keeps small regions visible next to giants
  const a = 0.28 + 0.67 * t;
  const rgb = mode === "loss" ? RED : mode === "revenue" ? (v >= 0 ? GREEN : RED) : v >= 0 ? GREEN : RED;
  return `rgba(${rgb}, ${a.toFixed(3)})`;
}

/** Marker radius in px (area-proportional). */
export function radiusFor(r: GeoRegion, mode: GeoMode, max: number, rMax = 18, rMin = 4): number {
  if (max <= 0) return rMin;
  const v = mode === "both" ? (r.revenue ?? Math.abs(net(r))) : Math.abs(metric(r, mode));
  return rMin + (rMax - rMin) * Math.sqrt(Math.min(1, Math.abs(v) / max));
}

export interface Crumb { level: GeoLevel; label: string }
export function crumbs(nav: { country?: { iso3: string; name: string } | null; state?: string | null; city?: string | null }): Crumb[] {
  const out: Crumb[] = [{ level: "world", label: "World" }];
  if (nav.country) out.push({ level: "country", label: nav.country.name });
  if (nav.country && nav.state) out.push({ level: "state", label: nav.state });
  if (nav.country && nav.city) out.push({ level: "city", label: nav.city });
  return out;
}

/** Compact money-ish text for map labels and the panel ("1.2M", "₹12.5 Cr"-style via en-IN). */
export function compact(v: number | null | undefined, mode: NumMode = "standard"): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const loc = mode === "standard" ? "en-US" : "en-IN";
  const out = new Intl.NumberFormat(loc, { notation: "compact", maximumFractionDigits: Math.abs(v) < 1000 ? 2 : 1 }).format(Math.abs(v));
  return `${v < 0 ? "-" : ""}${mode === "inr" ? "₹" : ""}${out}`;
}

export const CHILD_LABEL: Record<GeoLevel, string> = { world: "countries", country: "states / provinces", state: "cities", city: "" };

/** Ease used for the camera. */
export const easeInOutCubic = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
