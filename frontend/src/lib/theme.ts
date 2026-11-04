const KEY = "datapilot.theme";
export type ThemePref = "light" | "dark" | "system";

export const storedTheme = (): ThemePref => {
  try { return (localStorage.getItem(KEY) as ThemePref) || "system"; } catch { return "system"; }
};
export const isDark = (pref: ThemePref) => pref === "dark" || (pref === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);

/** Apply immediately and remember locally (works before login too). */
export function setTheme(pref: ThemePref) {
  try { localStorage.setItem(KEY, pref); } catch { /* private mode */ }
  document.documentElement.classList.toggle("dark", isDark(pref));
  window.dispatchEvent(new Event("datapilot:theme"));
}
export function initTheme() {
  setTheme(storedTheme());
  // "System" must follow the OS when it switches between light and dark
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { if (storedTheme() === "system") setTheme("system"); });
}
