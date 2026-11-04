import re

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel

from backend.app.agents.common import fmt
from backend.app.agents.state import AnalystState, RunContext
from backend.app.analytics.charts import auto_charts, chart_from_result
from backend.app.analytics.nl2sql import generate_sql
from backend.app.analytics.question import apply_filters, explain_empty
from backend.app.analytics.sql_engine import run_query
from backend.app.analytics.statistics import run_eda
from backend.app.analytics.utils import categorical_cols, numeric_cols, pfmt
from backend.app.config import settings


def sql_node(state: AnalystState, ctx: RunContext):
    table = ctx.primary
    df = ctx.tables[table]
    retry = state.get("retries", 0) > 0
    if retry:  # validation asked for a retry after a failed query: fall back to a safe summary
        gen = {"sql": f"SELECT * FROM {table} LIMIT 100", "rationale": "Fallback after failed query",
               "confidence": 0.2, "source": "fallback"}
    else:
        gen = generate_sql(state["question"], table, df, ctx.extra.get("prep"))
    try:
        res = run_query(ctx.tables, gen["sql"], settings.max_query_rows, settings.query_timeout_seconds)
    except Exception as e:
        return {"sql": {**gen, "error": str(e)}}, f"Query failed: {e}"
    ctx.extra["sql_df"] = res.pop("dataframe")
    out = {**gen, **res, "table": table, "error": None}
    spec = out.get("spec")
    filters = (spec or {}).get("filters") or []
    text = describe_result(out)
    if filters and len(apply_filters(df, filters)) == 0:
        out["empty_reason"] = text = explain_empty(df, filters)
    # numbers from our own parser are re-computed in pandas; LLM-written SQL can only be re-executed
    check = ({"fn": "sql_spec", "spec": spec} if spec else {"fn": "sql_rerun", "sql": out["sql"], "row_count": out["row_count"]})
    insights = list(state.get("insights", []))
    insights.append({
        "kind": "sql", "severity": "info", "text": text,
        "evidence": {"type": "sql", "sql": out["sql"], "rows": out["row_count"], "table": table, "check": check},
    })
    return ({"sql": out, "insights": insights, "interpretation": out.get("interpretation") or ""},
            f"{gen['rationale']} → {res['row_count']} row(s) in {res['elapsed_ms']} ms")


def describe_result(res: dict) -> str:
    rows, cols = res["rows"], res["columns"]
    if not rows:
        return "The query returned no rows."
    if len(rows) == 1:
        return "Result: " + ", ".join(f"{c} = {fmt(rows[0][c])}" for c in cols)
    head = rows[:5]
    lines = "; ".join(f"{fmt(r[cols[0]])}: {fmt(r[cols[1]])}" if len(cols) > 1 else fmt(r[cols[0]]) for r in head)
    return f"Query returned {res['row_count']} rows ({cols[0]} → {cols[1] if len(cols) > 1 else ''}). Top: {lines}"


def analytics_node(state: AnalystState, ctx: RunContext):
    df = ctx.tables[ctx.primary]
    eda = run_eda(df)
    ctx.extra["eda"] = eda
    insights = list(state.get("insights", []))
    t = ctx.primary

    for tr in eda["trends"][:2]:
        if tr["direction"] != "flat":
            insights.append({"kind": "trend", "severity": "info", "text": (
                f"{tr['metric']} is trending {tr['direction']} ({tr['frequency']} periods): "
                f"{fmt(tr['pct_change_first_last'])}% from first to last quarter of the series (median-based), "
                f"Kendall p={pfmt(tr['p_value'])}."),
                "evidence": {"type": "statistic", "table": t, "method": "Theil–Sen slope on periodic sums",
                             "check": {"fn": "trend_dir", "metric": tr["metric"], "time": tr["time_column"],
                                       "freq": tr["frequency"], "direction": tr["direction"]}}})
    for p in eda["correlations"]["pairs"][:3]:
        insights.append({"kind": "correlation", "severity": "info", "text": (
            f"{p['a']} and {p['b']} show a {p['strength']} {p['direction']} correlation "
            f"(r={p['r']:.2f}, n={p['n']}, p={pfmt(p['p_value'])})."),
            "evidence": {"type": "statistic", "table": t, "method": "Spearman rank correlation",
                         "check": {"fn": "corr", "a": p["a"], "b": p["b"], "value": p["r"]}}})
    for a in eda["anomalies"][:2]:
        insights.append({"kind": "anomaly", "severity": "warning", "text": (
            f"{a['column']} has {a['count']} anomalous value(s) ({a['pct']}% of rows) by robust z-score; "
            f"most extreme: {fmt(a['examples'][0]['value'])} at row {a['examples'][0]['row']}."),
            "evidence": {"type": "statistic", "table": t, "method": "median/MAD robust z-score",
                         "check": {"fn": "outlier_exists", "column": a["column"]}}})
    for g in [g for g in eda["group_tests"] if g["significant"]][:2]:
        insights.append({"kind": "comparison", "severity": "info", "text": (
            f"{g['metric']} differs significantly across {g['dimension']} ({g['test']}, p={pfmt(g['p_value'])}): "
            f"highest in '{g['top_group']}' (mean {fmt(g['top_mean'])}) vs lowest in '{g['bottom_group']}' "
            f"(mean {fmt(g['bottom_mean'])})."),
            "evidence": {"type": "statistic", "table": t, "method": g["test"],
                         "check": {"fn": "group_mean", "dim": g["dimension"], "metric": g["metric"],
                                   "group": g["top_group"], "value": g["top_mean"]}}})
    # concentration insight
    cats, nums = categorical_cols(df, 25), numeric_cols(df)
    if cats and nums:
        m = next((n for h in ("revenue", "sales", "amount", "total", "profit", "cost") for n in nums if h in n.lower()), nums[0])
        c = min(cats, key=lambda k: abs(df[k].nunique() - 8))
        grp = df.groupby(c)[m].sum().sort_values(ascending=False)
        total = grp.sum()
        if total and len(grp) > 1 and grp.iloc[0] / total > 0.3:
            insights.append({"kind": "concentration", "severity": "info", "text": (
                f"'{grp.index[0]}' accounts for {grp.iloc[0] / total * 100:.1f}% of total {m} by {c}."),
                "evidence": {"type": "statistic", "table": t, "method": "group share",
                             "check": {"fn": "group_share", "dim": c, "metric": m, "group": grp.index[0],
                                       "value": float(grp.iloc[0] / total)}}})
    return {"analytics": eda, "insights": insights}, (
        f"{len(eda['trends'])} trend(s), {len(eda['correlations']['pairs'])} notable correlation(s), "
        f"{len(eda['anomalies'])} anomalous column(s), {len(eda['group_tests'])} group test(s)")


def research_node(state: AnalystState, ctx: RunContext):
    chunks: list[tuple[str, int, str]] = []
    for name, text in ctx.documents.items():
        for i, para in enumerate(p.strip() for p in re.split(r"\n\s*\n", text) if len(p.strip()) > 40):
            for j in range(0, len(para), 700):
                chunks.append((name, len(chunks), para[j: j + 700]))
    if not chunks:
        return {"research": {"citations": []}}, "No document text to search"
    vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True)
    mat = vec.fit_transform([c[2] for c in chunks])
    sims = linear_kernel(vec.transform([state["question"]]), mat).ravel()
    order = sims.argsort()[::-1][:4]
    cites = [{"source": chunks[i][0], "chunk": chunks[i][1], "score": round(float(sims[i]), 3), "snippet": chunks[i][2]}
             for i in order if sims[i] > 0.04]
    insights = list(state.get("insights", []))
    for c in cites[:2]:
        insights.append({"kind": "document", "severity": "info",
                         "text": f"From “{c['source']}”: {c['snippet'][:280]}…",
                         "evidence": {"type": "document", "source": c["source"], "chunk": c["chunk"], "score": c["score"],
                                      "check": {"fn": "doc_contains", "source": c["source"], "snippet": c["snippet"][:60]}}})
    return {"research": {"citations": cites}, "insights": insights}, (
        f"Retrieved {len(cites)} passage(s) from {len(ctx.documents)} document(s)")


def visualization_node(state: AnalystState, ctx: RunContext):
    charts = list(state.get("charts", []))  # keep charts produced by root-cause / scenario agents
    if "autopilot" in (state.get("plan") or {}).get("intents", []) and ctx.primary:
        eda = ctx.extra.get("eda") or state.get("analytics")
        charts += auto_charts(ctx.tables[ctx.primary], eda, max_charts=max(0, 8 - len(charts)))
        return {"charts": charts}, f"{len(charts)} chart(s): business findings, root cause and exploratory views"
    if charts and any(k in state for k in ("root_cause", "scenario", "discovery", "executive", "forecast", "business")):
        return {"charts": charts}, f"Kept {len(charts)} chart(s) from the analysis agents"
    sql_df = ctx.extra.get("sql_df")
    if sql_df is not None and state.get("sql"):
        c = chart_from_result(sql_df, state["sql"].get("rationale", "Query result"))
        if c:
            charts.append(c)
    if ctx.primary:
        eda = ctx.extra.get("eda") or state.get("analytics")
        df = ctx.tables[ctx.primary]
        filters = ((state.get("sql") or {}).get("spec") or {}).get("filters") or []
        if filters:  # charts must describe the same rows as the answer
            df = apply_filters(df, filters)
            eda = None
        if len(df):
            charts += auto_charts(df, eda, max_charts=6 - len(charts))
    if not charts and state.get("executive"):
        charts = list(state["executive"].get("charts", []))
    return {"charts": charts}, f"Built {len(charts)} chart(s) from computed data"
