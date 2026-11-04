import { Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import { tokenStore } from "../api/client";
import { setTheme } from "../lib/theme";

export function ThemeToggle({ className = "" }: { className?: string }) {
  const read = () => document.documentElement.classList.contains("dark");
  const [dark, setDark] = useState(read);
  useEffect(() => { const f = () => setDark(read()); window.addEventListener("datapilot:theme", f); return () => window.removeEventListener("datapilot:theme", f); }, []);
  const toggle = () => {
    const next = dark ? "light" : "dark";
    setTheme(next);
    if (tokenStore.get()) api.put("/settings", { theme: next }).catch(() => undefined); // best-effort sync
  };
  return (
    <button onClick={toggle} aria-label={dark ? "Switch to light theme" : "Switch to dark theme"} title={dark ? "Light mode" : "Dark mode"}
      className={`group relative overflow-hidden rounded-lg p-2 transition hover:bg-slate-500/10 ${className}`}>
      <Sun className={`h-4 w-4 transition-all duration-500 ${dark ? "rotate-0 scale-100" : "-rotate-90 scale-0"}`} />
      <Moon className={`absolute inset-0 m-auto h-4 w-4 transition-all duration-500 ${dark ? "rotate-90 scale-0" : "rotate-0 scale-100"}`} />
    </button>
  );
}
