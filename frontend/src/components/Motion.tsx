import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";

/** Fades/slides children in when scrolled into view. */
export function Reveal({ children, delay = 0, className = "", as: Tag = "div" }: { children: ReactNode; delay?: number; className?: string; as?: "div" | "li" | "section" }) {
  const ref = useRef<HTMLDivElement>(null);
  const [shown, setShown] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || !("IntersectionObserver" in window)) { setShown(true); return; }
    const io = new IntersectionObserver(([e]) => { if (e.isIntersecting) { setShown(true); io.disconnect(); } }, { threshold: 0.12 });
    io.observe(el);
    return () => io.disconnect();
  }, []);
  const style: CSSProperties = { transitionDelay: `${delay}ms` };
  return <Tag ref={ref as never} style={style} className={`reveal ${shown ? "reveal-in" : ""} ${className}`}>{children}</Tag>;
}

/** Animated number (ease-out). Non-numeric values render as-is. */
export function CountUp({ value, duration = 900 }: { value: number | string; duration?: number }) {
  const target = typeof value === "number" ? value : NaN;
  const [n, setN] = useState(0);
  useEffect(() => {
    if (Number.isNaN(target)) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) { setN(target); return; }
    let raf = 0; const t0 = performance.now();
    const tick = (t: number) => {
      const p = Math.min(1, (t - t0) / duration);
      setN(target * (1 - Math.pow(1 - p, 3)));
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, duration]);
  if (Number.isNaN(target)) return <>{value}</>;
  const dec = Number.isInteger(target) ? 0 : 1;
  return <>{n.toLocaleString(undefined, { maximumFractionDigits: dec, minimumFractionDigits: dec })}</>;
}
