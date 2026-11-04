import { ArrowRight, BarChart3, BrainCircuit, Database, FileText, FileUp, GitBranch, LineChart, MessageSquare, SearchCheck, ShieldCheck, Sparkles, Table2, Terminal, Wand2, type LucideIcon } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Reveal } from "../components/Motion";
import { ThemeToggle } from "../components/ThemeToggle";

const AGENTS = ["Planner", "Ingestion", "Profiler", "Cleaning", "SQL", "Analytics", "Research", "Visualization", "Validation", "Report"];

const FEATURES: { icon: LucideIcon; title: string; text: string }[] = [
  { icon: FileUp, title: "Ingest anything", text: "CSV, Excel, JSON, Parquet, SQLite, PDF, DOCX, Markdown — or import straight from a SQL database." },
  { icon: SearchCheck, title: "Auto profiling", text: "Per-column stats, distributions and types the moment data lands, plus a 0–100 quality score." },
  { icon: Wand2, title: "One-click cleaning", text: "Fix duplicates, missing values, outliers, whitespace and casing — every change is logged." },
  { icon: LineChart, title: "Automated EDA", text: "Trends with projections, correlations, anomaly detection and significance tests, ranked by relevance." },
  { icon: MessageSquare, title: "Ask in plain English", text: "“Top 5 categories by revenue” becomes SQL, a chart and a verified answer." },
  { icon: Terminal, title: "SQL editor", text: "Read-only DuckDB across every source, with joins, saved queries and instant charts." },
  { icon: BrainCircuit, title: "Multi-agent workflow", text: "A LangGraph pipeline of specialised agents with conditional routing and live status." },
  { icon: ShieldCheck, title: "Evidence-verified", text: "Every number is re-computed from raw data a second way. Unsupported claims are dropped." },
  { icon: FileText, title: "Document research", text: "Ask questions of PDFs and docs; get cited passages, quoted verbatim." },
  { icon: BarChart3, title: "Interactive charts", text: "Bar, line, pie, scatter, histogram and correlation heatmaps with CSV export." },
  { icon: GitBranch, title: "Transparent trace", text: "See which agent did what, how long it took and what evidence it produced." },
  { icon: Database, title: "PDF & Excel reports", text: "Export findings, charts, SQL, citations and recommendations in one click." },
];

function Pipeline() {
  const [i, setI] = useState(0);
  useEffect(() => { const t = setInterval(() => setI((x) => (x + 1) % (AGENTS.length + 2)), 700); return () => clearInterval(t); }, []);
  return (
    <div className="flex flex-wrap items-center justify-center gap-2" aria-label="Agent pipeline">
      {AGENTS.map((a, k) => (
        <div key={a} className="flex items-center gap-2">
          <span className={`rounded-full border px-3.5 py-1.5 text-sm font-medium transition-all duration-500 ${k < i ? "border-emerald-400/50 bg-emerald-400/10 text-emerald-300" : k === i ? "scale-110 border-brand-400 bg-brand-500/30 text-white shadow-[0_0_24px_rgba(99,102,241,.7)]" : "border-white/10 text-slate-500"}`}>
            {k < i ? "✓ " : ""}{a}
          </span>
          {k < AGENTS.length - 1 && <ArrowRight className={`h-3.5 w-3.5 transition-colors duration-500 ${k < i ? "text-emerald-400" : "text-slate-600"}`} />}
        </div>
      ))}
    </div>
  );
}

export default function Landing() {
  return (
    <div className="themed min-h-full overflow-x-hidden bg-ink-950 text-slate-200">
      <header className="sticky top-0 z-30 border-b border-white/5 bg-ink-950/70 backdrop-blur-lg">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-5">
          <span className="flex items-center gap-2.5 text-lg font-semibold text-white"><span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-600"><BarChart3 className="h-4 w-4" /></span>DataPilot <span className="-ml-1 text-brand-400">AI</span></span>
          <nav className="flex items-center gap-1 text-sm">
            <a href="#features" className="hidden rounded-lg px-3 py-2 text-slate-400 transition hover:text-white sm:block">Features</a>
            <a href="#how" className="hidden rounded-lg px-3 py-2 text-slate-400 transition hover:text-white sm:block">How it works</a>
            <ThemeToggle className="text-slate-400 hover:text-white" />
            <Link to="/login" className="hidden whitespace-nowrap rounded-lg px-3 py-2 text-slate-300 transition hover:text-white sm:block">Sign in</Link>
            <Link to="/login?mode=register" className="btn-primary whitespace-nowrap">Get started</Link>
          </nav>
        </div>
      </header>

      {/* hero */}
      <section className="relative px-5 pb-24 pt-20 text-center sm:pt-28">
        <div className="mx-auto max-w-4xl">
          <span className="animate-fadeUp inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-4 py-1.5 text-xs font-medium text-slate-300 backdrop-blur"><Sparkles className="h-3.5 w-3.5 text-brand-400" /> Multi-agent analytics, grounded in evidence</span>
          <h1 className="animate-fadeUp mt-6 text-5xl font-bold leading-[1.05] tracking-tight text-white [animation-delay:100ms] sm:text-7xl">Your data, <span className="gradient-text">analysed by a team of agents.</span></h1>
          <p className="animate-fadeUp mx-auto mt-6 max-w-2xl text-lg text-slate-400 [animation-delay:200ms]">Upload files or connect a database, ask questions in plain English, and get charts, SQL and insights — with every number re-checked against your raw data.</p>
          <div className="animate-fadeUp mt-9 flex flex-wrap items-center justify-center gap-3 [animation-delay:300ms]">
            <Link to="/login?mode=register" className="btn-primary px-6 py-3 text-base">Start analysing <ArrowRight className="h-4 w-4 transition group-hover:translate-x-1" /></Link>
            <a href="#features" className="btn border border-white/15 px-6 py-3 text-base text-slate-200 hover:bg-white/5">See what it can do</a>
          </div>
        </div>
        <div className="mx-auto mt-16 max-w-5xl animate-fadeUp rounded-2xl border border-white/10 bg-white/[.03] p-6 backdrop-blur [animation-delay:450ms]" style={{ animation: "fadeUp .6s .45s both, floaty 7s 1s ease-in-out infinite" }}>
          <p className="mb-4 text-xs font-medium uppercase tracking-widest text-slate-500">The workflow behind every answer</p>
          <Pipeline />
        </div>
      </section>

      {/* formats marquee */}
      <section className="border-y border-white/5 py-5" aria-label="Supported formats">
        <div className="overflow-hidden">
          <div className="marquee gap-10 text-sm font-medium text-slate-500">
            {[0, 1].map((r) => <div key={r} className="flex shrink-0 gap-10 pr-10">{["CSV", "Excel", "JSON", "Parquet", "SQLite", "PostgreSQL", "PDF", "DOCX", "Markdown", "TSV", "JSONL", "SQL import"].map((f) => <span key={f} className="flex items-center gap-2"><Table2 className="h-4 w-4 text-brand-500" />{f}</span>)}</div>)}
          </div>
        </div>
      </section>

      {/* features */}
      <section id="features" className="mx-auto max-w-6xl px-5 py-24">
        <Reveal className="mx-auto mb-14 max-w-2xl text-center">
          <h2 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">Everything an analyst does, automated</h2>
          <p className="mt-3 text-slate-400">From messy file to verified, shareable report — without writing a line of code.</p>
        </Reveal>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((f, k) => (
            <Reveal key={f.title} delay={(k % 3) * 90}>
              <div className="group h-full rounded-2xl border border-white/10 bg-white/[.03] p-6 transition duration-300 hover:-translate-y-1 hover:border-brand-400/50 hover:bg-white/[.06] hover:shadow-[0_20px_40px_-20px_rgba(99,102,241,.5)]">
                <span className="mb-4 inline-flex rounded-xl bg-brand-500/15 p-3 text-brand-300 transition duration-300 group-hover:scale-110 group-hover:rotate-3 group-hover:bg-brand-500/30"><f.icon className="h-5 w-5" /></span>
                <h3 className="font-semibold text-white">{f.title}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-slate-400">{f.text}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </section>

      {/* how */}
      <section id="how" className="border-t border-white/5 bg-white/[.02] px-5 py-24">
        <div className="mx-auto max-w-5xl">
          <Reveal className="mb-14 text-center"><h2 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">From question to verified answer</h2></Reveal>
          <div className="grid gap-8 md:grid-cols-3">
            {[["1", "Bring your data", "Drop files or connect a database. Profiling and quality checks run instantly."], ["2", "Ask anything", "The planner routes your question to the SQL, analytics, research and chart agents."], ["3", "Trust the result", "The validation agent re-computes each claim. You get evidence, trace and one-click export."]].map(([n, t, d], k) => (
              <Reveal key={n} delay={k * 120}>
                <div className="relative rounded-2xl border border-white/10 p-6">
                  <span className="absolute -top-4 left-6 flex h-8 w-8 items-center justify-center rounded-full bg-brand-600 text-sm font-bold text-white" style={{ animation: "pop .5s both" }}>{n}</span>
                  <h3 className="mt-3 font-semibold text-white">{t}</h3><p className="mt-1.5 text-sm text-slate-400">{d}</p>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* cta */}
      <section className="relative overflow-hidden px-5 py-24 text-center">
        <Reveal className="mx-auto max-w-2xl">
          <h2 className="text-3xl font-bold tracking-tight text-white sm:text-5xl">Ready to put an analyst team on your data?</h2>
          <p className="mt-4 text-slate-400">Free to run locally. Your data stays in your own database.</p>
          <Link to="/login?mode=register" className="btn-primary mt-8 px-7 py-3 text-base">Create your account <ArrowRight className="h-4 w-4" /></Link>
        </Reveal>
      </section>
      <footer className="border-t border-white/5 py-6 text-center text-xs text-slate-500">DataPilot AI · Read-only SQL sandbox · Per-user data isolation</footer>
    </div>
  );
}
