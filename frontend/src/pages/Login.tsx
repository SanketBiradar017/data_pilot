import { ArrowLeft, BarChart3, Check, Eye, EyeOff, ShieldCheck, Sparkles, Table2 } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Spinner } from "../components/ui";
import { Notice, useAuth } from "../lib/auth";
import { usePlatform } from "../lib/platform";

const FEATURES = [[Table2, "Any data source", "CSV, Excel, JSON, Parquet, SQL databases and documents"], [Sparkles, "Multi-agent analysis", "Planner, SQL, analytics, research and validation agents"], [ShieldCheck, "Evidence-verified", "Every numeric claim is re-computed from the raw data"]] as const;
const AGENTS = ["Planner", "Ingestion", "Profiler", "Cleaning", "SQL", "Analytics", "Validation", "Report"];
const WORDS = ["trends", "anomalies", "revenue by region", "correlations", "data quality"];

/** Types a rotating phrase — purely decorative copy, not a data claim. */
function Typewriter() {
  const [w, setW] = useState(0), [n, setN] = useState(0), [del, setDel] = useState(false);
  useEffect(() => {
    const word = WORDS[w];
    const t = setTimeout(() => {
      if (!del && n < word.length) setN(n + 1);
      else if (!del) setDel(true);
      else if (n > 0) setN(n - 1);
      else { setDel(false); setW((w + 1) % WORDS.length); }
    }, !del && n === word.length ? 1400 : del ? 35 : 70);
    return () => clearTimeout(t);
  }, [n, del, w]);
  return <span className="text-brand-400">{WORDS[w].slice(0, n)}<span className="ml-0.5 inline-block w-[3px] translate-y-1 bg-brand-400" style={{ height: "1em", animation: "caret 1s step-end infinite" }} /></span>;
}

function Ticker() {
  const [i, setI] = useState(0);
  useEffect(() => { const t = setInterval(() => setI((x) => (x + 1) % AGENTS.length), 900); return () => clearInterval(t); }, []);
  return (
    <div className="flex items-center gap-1.5" aria-hidden>
      {AGENTS.map((a, k) => <span key={a} title={a} className={`h-1.5 rounded-full transition-all duration-500 ${k === i ? "w-10 bg-brand-400" : k < i ? "w-4 bg-emerald-400/70" : "w-4 bg-white/15"}`} />)}
      <span className="ml-3 text-xs text-slate-400">{AGENTS[i]} agent</span>
    </div>
  );
}

export default function Login() {
  const { login } = useAuth();
  const platform = usePlatform();
  const [params] = useSearchParams();
  const lastEmail = (() => { try { return localStorage.getItem("datapilot.email") ?? ""; } catch { return ""; } })();
  // returning users (an email was remembered) land on Sign in even if they came via "Get started"
  const [mode, setMode] = useState<"login" | "register">(params.get("mode") === "register" && !lastEmail ? "register" : "login");
  const [f, setF] = useState({ email: lastEmail, password: "", name: "" });
  const [err, setErr] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [show, setShow] = useState(false);
  const [shake, setShake] = useState(0);
  const [done, setDone] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); setErr(null);
    try { await login(f.email, f.password, mode === "register" ? { name: f.name } : undefined); try { localStorage.setItem("datapilot.email", f.email.trim().toLowerCase()); } catch { /* ignore */ } setDone(true); }
    catch (x) { if (x instanceof Notice) { setNotice(x.message); setMode("login"); setErr(null); } else { setErr((x as Error).message); setNotice(null); setShake((s) => s + 1); } setBusy(false); }
  };
  const strength = Math.min(4, (f.password.length >= 8 ? 1 : 0) + (/[A-Z]/.test(f.password) ? 1 : 0) + (/\d/.test(f.password) ? 1 : 0) + (/[^A-Za-z0-9]/.test(f.password) ? 1 : 0));

  return (
    <div className="themed relative isolate flex min-h-full items-center overflow-hidden bg-ink-950 text-slate-200">
      {/* animated backdrop */}

      <Link to="/" className="absolute left-5 top-5 z-10 flex items-center gap-2.5 text-lg font-semibold text-white">
        <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-600"><BarChart3 className="h-5 w-5" /></span>DataPilot <span className="-ml-1 text-brand-400">AI</span>
      </Link>
      <Link to="/" className="absolute right-5 top-5 z-10 flex items-center gap-1 text-sm text-slate-400 transition hover:text-white"><ArrowLeft className="h-4 w-4" /> Home</Link>

      <div className="mx-auto grid w-full max-w-6xl items-center gap-12 px-5 py-24 lg:grid-cols-[1.1fr_1fr]">
        <div className="hidden lg:block">
          <h2 className="animate-fadeUp text-5xl font-bold leading-[1.1] tracking-tight text-white">Your autonomous data analyst, finding <br /><Typewriter /></h2>
          <p className="animate-fadeUp mt-5 max-w-md text-slate-400 [animation-delay:120ms]">Grounded in evidence: every number is checked against your raw data before you see it.</p>
          <ul className="mt-10 space-y-5">
            {FEATURES.map(([I, t, d], k) => (
              <li key={t} className="animate-fadeUp group flex gap-4" style={{ animationDelay: `${250 + k * 140}ms` }}>
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-white/5 text-brand-300 ring-1 ring-white/10 transition duration-300 group-hover:scale-110 group-hover:bg-brand-500/25 group-hover:ring-brand-400/50"><I className="h-5 w-5" /></span>
                <div><p className="font-medium text-white">{t}</p><p className="text-sm text-slate-400">{d}</p></div>
              </li>
            ))}
          </ul>
          <div className="animate-fadeUp mt-10" style={{ animationDelay: "800ms" }}><Ticker /></div>
        </div>

        <div className="animate-fadeUp mx-auto w-full max-w-md [animation-delay:150ms]">
          <div>
            <div className="auth-card rounded-2xl border border-white/10 shadow-[0_20px_50px_-20px_rgba(0,0,0,.6)]">
              <div key={shake} className={`auth-inner rounded-2xl bg-ink-900 p-8 sm:p-9 ${shake ? "shake" : ""}`}>
                {done ? (
                  <div className="flex flex-col items-center py-14 text-center">
                    <span className="flex h-16 w-16 items-center justify-center rounded-full bg-emerald-500 text-white" style={{ animation: "pop .5s both" }}><Check className="h-8 w-8" /></span>
                    <p className="mt-5 text-lg font-semibold text-white">You're in. Loading your workspace…</p>
                  </div>
                ) : (
                  <form onSubmit={submit} className="space-y-4">
                    <div key={mode} className="swap">
                      <h1 className="text-2xl font-semibold tracking-tight text-white">{mode === "login" ? "Welcome back" : "Create your account"}</h1>
                      <p className="mt-1 text-sm text-slate-400">{mode === "login" ? "Sign in to continue to your workspace." : "The first account becomes the workspace admin."}</p>
                    </div>
                    {mode === "register" && <div className="swap"><label className="label !text-slate-400" htmlFor="n">Name</label><input id="n" className="field" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} autoComplete="name" placeholder="Ada Lovelace" /></div>}
                    <div><label className="label !text-slate-400" htmlFor="e">Email</label><input id="e" type="email" required className="field" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} autoComplete="email" placeholder="you@company.com" /></div>
                    <div>
                      <label className="label !text-slate-400" htmlFor="p">Password</label>
                      <div className="relative">
                        <input id="p" type={show ? "text" : "password"} required minLength={8} className="field pr-10" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} autoComplete={mode === "login" ? "current-password" : "new-password"} placeholder="••••••••" />
                        <button type="button" onClick={() => setShow(!show)} className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 transition hover:text-white" aria-label={show ? "Hide password" : "Show password"}>{show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}</button>
                      </div>
                      {mode === "register" && (
                        <div className="swap mt-2"><div className="flex gap-1">{[0, 1, 2, 3].map((k) => <span key={k} className={`h-1 flex-1 rounded-full transition-all duration-500 ${k < strength ? ["bg-red-400", "bg-amber-400", "bg-lime-400", "bg-emerald-400"][strength - 1] : "bg-white/10"}`} />)}</div>
                          <p className="mt-1 text-xs text-slate-500">At least 8 characters. Mix upper-case, numbers and symbols for strength.</p></div>)}
                    </div>
                    {notice && <div role="status" className="swap rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300">{notice}</div>}
                    {err && <div role="alert" className="swap rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">{err}</div>}
                    <button className={`btn-primary w-full py-3 text-base `} disabled={busy}>{busy && <Spinner />} {mode === "login" ? "Sign in" : "Create account"}</button>
                    {mode === "login" && !platform.registration_open ? <p className="text-center text-sm text-slate-500">New registrations are currently closed.</p> :
                    <p className="text-center text-sm text-slate-400">{mode === "login" ? "New here? " : "Already registered? "}
                      <button type="button" className="font-medium text-brand-400 transition hover:text-brand-300 hover:underline" onClick={() => { setMode(mode === "login" ? "register" : "login"); setErr(null); }}>{mode === "login" ? "Create an account" : "Sign in"}</button></p>}
                  </form>
                )}
              </div>
            </div>
          </div>
          <p className="mt-5 text-center text-xs text-slate-500">Secure by default · Read-only SQL · Per-user data isolation</p>
        </div>
      </div>
    </div>
  );
}
