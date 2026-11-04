/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      fontFamily: { sans: ["Inter", "system-ui", "sans-serif"], mono: ["JetBrains Mono", "ui-monospace", "monospace"] },
      colors: {
        // Theme-aware palettes (see :root / .dark in src/index.css)
        brand: Object.fromEntries([50, 100, 200, 400, 500, 600, 700, 900].map((k) => [k, `rgb(var(--brand-${k}) / <alpha-value>)`])),
        slate: Object.fromEntries([50, 100, 200, 300, 400, 500, 600, 700, 800, 900].map((k) => [k, `rgb(var(--slate-${k}) / <alpha-value>)`])),
        side: "rgb(var(--side) / <alpha-value>)",
        ink: { 950: "#0b1020", 900: "#111832", 800: "#1a2244" },
      },
      boxShadow: { card: "0 1px 2px rgba(16,24,40,.04), 0 1px 3px rgba(16,24,40,.06)", pop: "0 12px 32px -8px rgba(16,24,40,.18)" },
      keyframes: { fadeUp: { "0%": { opacity: 0, transform: "translateY(6px)" }, "100%": { opacity: 1, transform: "none" } },
                   pulseDot: { "0%,100%": { opacity: 1 }, "50%": { opacity: .35 } } },
      animation: { fadeUp: "fadeUp .3s ease-out both", pulseDot: "pulseDot 1.2s ease-in-out infinite" },
    },
  },
  plugins: [],
};
