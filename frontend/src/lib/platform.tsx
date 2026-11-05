import { useQuery } from "@tanstack/react-query";
import { createContext, useContext, useEffect, type ReactNode } from "react";
import { api } from "../api/client";
import type { PlatformInfo } from "./types";

const FALLBACK: PlatformInfo = { app_name: "DataPilot AI", tagline: "", primary_color: "", logo_url: "", support_email: "", maintenance_mode: false, maintenance_message: "", announcement: "", announcement_tone: "info", email_verification: false, registration_open: true };
const Ctx = createContext<PlatformInfo>(FALLBACK);
export const usePlatform = () => useContext(Ctx);

const hex = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
const mix = (c: number[], t: number, k: number) => c.map((v) => Math.round(v + (t - v) * k)).join(" ");

export function PlatformProvider({ children }: { children: ReactNode }) {
  const { data } = useQuery({ queryKey: ["platform"], staleTime: 60_000, retry: 0, queryFn: () => api.get<PlatformInfo>("/platform") });
  const p = data ?? FALLBACK;
  useEffect(() => { document.title = p.app_name; }, [p.app_name]);
  useEffect(() => {
    const root = document.documentElement.style;
    const keys = ["--brand-500", "--brand-600", "--brand-700"];
    if (/^#[0-9a-f]{6}$/i.test(p.primary_color)) {
      const c = hex(p.primary_color);
      root.setProperty("--brand-600", c.join(" ")); root.setProperty("--brand-500", mix(c, 255, 0.15)); root.setProperty("--brand-700", mix(c, 0, 0.2));
    } else keys.forEach((k) => root.removeProperty(k));
  }, [p.primary_color]);
  return <Ctx.Provider value={p}>{children}</Ctx.Provider>;
}
