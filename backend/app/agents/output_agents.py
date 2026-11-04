"""Validation (evidence re-computation) and Report generation agents."""
import numpy as np

from backend.app.agents.common import fmt
from backend.app.agents.state import AnalystState, RunContext
from backend.app.analytics.forecast import history_sql, verify_forecast
from backend.app.analytics.llm import llm_complete
from backend.app.analytics.question import verify_spec
from backend.app.analytics.sql_engine import run_query
from backend.app.analytics.utils import pfmt


def _close(a: float, b: float, tol: float = 0.02) -> bool:
    return abs(a - b) <= tol * max(abs(a), abs(b), 1e-9) or abs(a - b) < 1e-6


def verify(check: dict, ctx: RunContext) -> tuple[bool, str]:
    """Independently recompute a claim from raw data."""
    fn = check["fn"]
    df = ctx.tables.get(ctx.primary) if ctx.primary else None
    if fn == "sql_rerun":
        r = run_query(ctx.tables, check["sql"], 10_000, 30)
        ok = r["row_count"] == check["row_count"]
        return ok, f"re-executed query: {r['row_count']} rows (expected {check['row_count']})"
    if fn == "doc_contains":
        text = " ".join(ctx.documents.get(check["source"], "").split())
        ok = " ".join(check["snippet"].split()) in text
        return ok, "snippet found verbatim in source document" if ok else "snippet not found in source"
    if df is None:
        return False, "no table available"
    if fn == "sql_spec":
        return verify_spec(df, check["spec"], ctx.extra["sql_df"])
    if fn == "forecast":
        if "fc_check" not in ctx.extra:
            res = ctx.extra["forecast"]
            r = run_query(ctx.tables, history_sql(res, ctx.primary), 10_000, 30)
            ctx.extra["fc_check"] = verify_forecast(res, r["dataframe"])
        return ctx.extra["fc_check"]
    if fn == "corr":
        pair = df[[check["a"], check["b"]]].dropna()
        r = float(pair[check["a"]].rank().corr(pair[check["b"]].rank()))  # Spearman via ranks
        return _close(r, check["value"], 0.01), f"recomputed r={r:.3f}"
    if fn == "outlier_exists":
        d = df[check["column"]].dropna()
        q1, q3 = d.quantile(.25), d.quantile(.75)
        n = int(((d < q1 - 1.5 * (q3 - q1)) | (d > q3 + 1.5 * (q3 - q1))).sum())
        return n > 0, f"{n} value(s) outside 1.5×IQR fences"
    if fn == "group_mean":
        m = float(df.groupby(check["dim"])[check["metric"]].mean()[check["group"]])
        return _close(m, check["value"]), f"recomputed group mean={fmt(m)}"
    if fn == "group_share":
        s = df.groupby(check["dim"])[check["metric"]].sum()
        share = float(s[check["group"]] / s.sum())
        return _close(share, check["value"]), f"recomputed share={share:.3f}"
    if fn == "trend_dir":
        t = df.dropna(subset=[check["time"]]).set_index(check["time"]).sort_index()
        s = t[check["metric"]].resample(check["freq"]).sum(min_count=1).dropna()
        from scipy import stats as sps

        rho, p = sps.spearmanr(np.arange(len(s)), s.values)
        ok = (rho > 0) == (check["direction"] == "up") and p < 0.05
        return ok, f"recomputed Spearman rho={rho:.2f} (p={pfmt(p)})"
    return False, f"unknown check '{fn}'"


def validation_node(state: AnalystState, ctx: RunContext):
    insights = []
    checks, passed = [], 0
    for ins in state.get("insights", []):
        chk = ins.get("evidence", {}).get("check")
        ok, detail = (True, "no numeric claim") if not chk else _safe_verify(chk, ctx)
        insights.append({**ins, "verified": ok, "verification": detail})
        if chk:
            checks.append({"claim": ins["text"][:120], "passed": ok, "detail": detail})
            passed += ok
    sql = state.get("sql") or {}
    sql_failed = bool(sql.get("error"))
    empty = bool(sql) and not sql_failed and sql.get("row_count", 1) == 0 and not (sql.get("spec") or {}).get("filters")
    needs_retry = (sql_failed or empty) and state.get("retries", 0) < 1
    ver = state.get("verification") or {}
    if ver:  # numbers produced by the intelligence agents: SQL re-executed or formula re-evaluated
        ok_n = sum(bool(v["verified"]) for v in ver.values())
        checks.append({"claim": f"{len(ver)} calculations behind the narrative were re-executed (SQL / formula)", "passed": ok_n == len(ver), "detail": f"{ok_n}/{len(ver)} verified"})
        passed += ok_n == len(ver)
    failed = [c for c in checks if not c["passed"]]
    # drop insights that failed verification so unsupported claims never reach the answer
    kept = [i for i in insights if i["verified"]]
    val = {"checks": checks, "passed": passed, "total": len(checks), "dropped": len(insights) - len(kept),
           "sql_error": sql.get("error"), "retry": needs_retry,
           "status": "passed" if not failed and not sql_failed else "partial"}
    upd = {"validation": val, "insights": kept}
    if needs_retry:
        upd["retries"] = state.get("retries", 0) + 1
    summary = f"{passed}/{len(checks)} evidence checks passed" + (
        f"; {len(failed)} unsupported claim(s) removed" if failed else "") + ("; retrying SQL" if needs_retry else "")
    return upd, summary


def _safe_verify(chk, ctx):
    try:
        return verify(chk, ctx)
    except Exception as e:
        return False, f"verification error: {e}"


def _forecast_recs(fc: dict) -> list[str]:
    chg, conf, label, unit = fc.get("change_pct"), fc["confidence"], fc["metric"], fc["grain"]
    recs = []
    if chg is not None and chg >= 5:
        recs.append(f"The model expects {label} to grow about {chg:.0f}% over the next {fc['horizon']} {unit}{'' if fc['horizon'] == 1 else 's'}: check that capacity, stock and staffing can keep up.")
    elif chg is not None and chg <= -5:
        recs.append(f"The model expects {label} to fall about {abs(chg):.0f}% over the next {fc['horizon']} {unit}{'' if fc['horizon'] == 1 else 's'}: find which segments are driving it (ask “why did {label} drop?”) and plan a response now.")
    elif chg is not None:
        recs.append(f"{label.capitalize()} is expected to stay roughly flat ({chg:+.0f}%): growth will need a deliberate change in price, volume or mix.")
    if conf == "low":
        recs.append("Forecast confidence is low: collect more history or re-run it after the next period closes before committing budgets to it.")
    elif fc["backtest"]["skill_vs_naive"] < 0.05:
        recs.append("The model barely beats simply repeating the last period, so there is little predictable trend or seasonality; use ranges, not point values, when planning.")
    return recs


def _recommendations(state: AnalystState) -> list[str]:
    recs = []
    prim = next(iter((state.get("quality") or {}).get("tables", {}).values()), {})
    for i in prim.get("issues", [])[:3]:
        if i["severity"] in ("high", "medium"):
            recs.append(f"Fix data quality: {i['message']}" + (f" in '{i['column']}'" if i.get("column") else "")
                        + f" (suggested action: {i['fix'].replace('_', ' ')}).")
    for ins in state.get("insights", []):
        k = ins["kind"]
        if k == "forecast":
            continue
        if k == "trend" and "down" in ins["text"]:
            recs.append("Investigate the declining metric: segment by category/region to find where the drop originates.")
        elif k == "trend":
            recs.append("Sustain the upward trend: identify which segments drive growth and allocate resources to them.")
        elif k == "concentration":
            recs.append("High concentration detected: assess dependency risk and diversification options.")
        elif k == "anomaly":
            recs.append("Review anomalous records for data-entry errors or genuine exceptional events before relying on averages.")
        elif k == "correlation":
            recs.append("Test whether the strongly correlated variables are causally related (e.g. controlled experiment) before acting.")
        elif k == "comparison":
            recs.append("Replicate best-performing group practices in lower-performing groups.")
    fc = state.get("forecast")
    if fc:
        recs += _forecast_recs(fc)
    seen, out = set(), []
    for r in recs:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out[:6]


_SECTIONS = [("executive", "Executive summary"), ("business", "Business findings"), ("quality", "Data quality"),
             ("root_cause", "Why performance changed"), ("discovery", "Other insights worth a look")]
_STAT_KINDS = {"trend": "Trends", "anomaly": "Anomalies and unusual values", "correlation": "Relationships", "comparison": "Group differences", "concentration": "Concentration"}


def _autopilot(state: AnalystState, ctx: RunContext, story: dict, kpis: list) -> dict:
    """The one-page result of an autonomous run: what was looked at, then verified findings grouped by topic."""
    sts = story.get("statements") or []
    seen: set[str] = set()
    sections = []
    for k, t in _SECTIONS:  # a finding reported by two agents is shown once, under the first section that has it
        own = [s for s in sts if s.get("source") == k and s["text"] not in seen]
        seen |= {s["text"] for s in own}
        sections.append({"id": k, "title": t, "statements": own})
    stats = [i for i in state.get("insights", []) if i["kind"] in _STAT_KINDS]
    if stats:
        sections.append({"id": "statistics", "title": "Statistics, anomalies and trends",
                         "statements": [], "notes": [{"kind": _STAT_KINDS[i["kind"]], "text": i["text"], "verified": i.get("verified")} for i in stats]})
    sections = [s for s in sections if s["statements"] or s.get("notes")]
    biz = state.get("business") or {}
    n_find = len(biz.get("findings", [])) + len((state.get("discovery") or {}).get("insights", [])) + len(stats)
    prim = ctx.primary
    prof = (state.get("profile") or {}).get("tables", {}).get(prim, {})
    qual = (state.get("quality") or {}).get("tables", {}).get(prim, {})
    ran = [a for a in ("quality", "analytics", "discovery", "business", "root_cause", "executive") if a in state.get("completed", [])]
    head = [f"Analysed {prof.get('rows', 0):,} rows and {prof.get('columns', 0)} columns" + (f" (data quality {qual.get('score')}/100)" if qual.get("score") is not None else "") + f": {n_find} finding(s), every calculation re-checked."]
    top = [f["text"] for f in biz.get("findings", []) if f["severity"] == "high"][:2]
    if top:
        head.append("Needs attention: " + " ".join(top))
    val = state.get("validation") or {}
    return {"headline": " ".join(head), "sections": sections, "coverage": biz.get("coverage"), "steps_run": ran, "findings": n_find,
            "verified": f"{val.get('passed', 0)}/{val.get('total', 0)}", "kpis": kpis}


def report_node(state: AnalystState, ctx: RunContext):
    insights = state.get("insights", [])
    sql = state.get("sql") or {}
    parts = []
    if sql and not sql.get("error"):
        parts.append(next((i["text"] for i in insights if i["kind"] == "sql"), ""))
    parts += [i["text"] for i in insights if i["kind"] not in ("sql",)][:5]
    if state.get("errors") and not parts:
        parts.append("I could not complete the analysis: " + "; ".join(state["errors"][:2]))
    if not parts:
        parts.append("No significant findings were detected for this question.")
    answer = "\n".join(f"• {p}" if len(parts) > 1 else p for p in parts if p)
    clar = state.get("clarification")
    if clar:
        answer, parts = clar["message"], []
    story = state.get("story") or {}
    if story.get("statements"):  # narrative built only from verified, cited statements
        answer = story["text"] if story["text"] != " ".join(x["text"] for x in story["statements"]) else "\n".join(f"• {x['text']}" for x in story["statements"])

    llm = llm_complete(
        "You are a data analyst. Rewrite the verified findings as a concise answer to the question. "
        "Use ONLY the facts given; do not add numbers. Max 120 words.",
        f"Question: {state['question']}\nVerified findings:\n" + "\n".join(f"- {p}" for p in parts),
        max_tokens=400,
    )
    if llm and not clar:
        answer = llm

    prim = ctx.primary
    prof = (state.get("profile") or {}).get("tables", {}).get(prim, {})
    qual = (state.get("quality") or {}).get("tables", {}).get(prim, {})
    kpis = []
    if prof:
        kpis += [{"label": "Rows", "value": prof["rows"]}, {"label": "Columns", "value": prof["columns"]}]
    if qual:
        kpis.append({"label": "Quality score", "value": qual.get("score")})
    val = state.get("validation") or {}
    if val.get("total"):
        kpis.append({"label": "Evidence verified", "value": f"{val['passed']}/{val['total']}"})

    evidence = [i["evidence"] | {"text": i["text"], "verified": i.get("verified")}
                for i in insights if i.get("evidence")]
    for ev in evidence:
        ev.pop("check", None)
    report = {
        "title": f"Analysis: {state['question'][:80]}", "question": state["question"], "answer": answer,
        "kpis": kpis, "insights": [{k: v for k, v in i.items() if k != "evidence"} | {"evidence_type": i["evidence"]["type"]}
                                    for i in insights if "evidence" in i],
        "recommendations": (story.get("recommendations") or _recommendations(state)), "sql": sql.get("sql"),
        "result_columns": sql.get("columns"), "result_rows": (sql.get("rows") or [])[:200],
        "charts": state.get("charts", []), "citations": (state.get("research") or {}).get("citations", []),
        "quality": qual, "validation": val, "story": story or None,
        "quality_report": state.get("quality_report") or None,
        "root_cause": state.get("root_cause") or None,
        "scenario": state.get("scenario") or None,
        "discovery": state.get("discovery") or None,
        "executive": state.get("executive") or None, "forecast": state.get("forecast") or None,
        "clarification": clar or None, "notes": state.get("notes") or [], "interpretation": state.get("interpretation") or None,
        "datasets": list(ctx.table_labels.values()) + list(ctx.documents),
    }
    if "autopilot" in (state.get("plan") or {}).get("intents", []):
        report["autopilot"] = _autopilot(state, ctx, story, kpis)
        answer = report["answer"] = report["autopilot"]["headline"]
    return {"answer": answer, "report": report | {"evidence": evidence}}, f"Compiled answer with {len(evidence)} evidence item(s) and {len(report['recommendations'])} recommendation(s)"
