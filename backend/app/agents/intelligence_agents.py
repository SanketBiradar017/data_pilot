"""Root Cause, Scenario, Insight Discovery and Executive Summary agents (storytelling lives in story_node)."""
import re

import pandas as pd

from backend.app.agents.state import AnalystState, RunContext
from backend.app.analytics.business import business_findings
from backend.app.analytics.charts import spec as chart_spec
from backend.app.analytics.discovery import discover
from backend.app.analytics.executive import run_executive_summary
from backend.app.analytics.facts import FactBook
from backend.app.analytics.forecast import run_forecast
from backend.app.analytics.nl2sql import parse_spec
from backend.app.analytics.question import _match_cols, describe_filters
from backend.app.analytics.roles import detect_roles, is_additive
from backend.app.analytics.root_cause import parse_question, run_root_cause
from backend.app.analytics.scenario import run_scenarios
from backend.app.analytics.story import finalize, polish, root_cause_story, stmt
from backend.app.analytics.utils import datetime_cols, fmtnum, infer_types


def _mode(ctx: RunContext) -> str:
    return ctx.extra.get("number_mode", "standard")


def _tag(statements: list[dict], source: str) -> list[dict]:
    return [{**s, "source": source} for s in statements]


def root_cause_node(state: AnalystState, ctx: RunContext):
    table = ctx.primary
    df = ctx.tables[table]
    roles = detect_roles(df)
    hint = parse_question(state["question"], df, roles)
    if hint["unsupported"] and not hint["metric"]:
        raise ValueError(f"I can't explain changes in “{hint['unsupported']}” with this data; ask about revenue, cost, quantity or profit.")
    res = run_root_cause(df, table, metric=hint["metric"], grain=hint["grain"], question=state["question"], mode=_mode(ctx), month=hint["month"], year=hint["year"])
    story = root_cause_story(res)
    ver = res["verification"]
    summary = (f"{res['metric']} {res['direction']} {res['totals']['change_pct']:+.1f}% ({res['previous']} → {res['current']}); "
               f"{len(res['factors'])} contributing factor(s); {sum(v['verified'] for v in ver.values())}/{len(ver)} facts verified")
    return {"root_cause": {**res, "story": story}, "facts": res["facts"], "verification": ver, "statements": _tag(story["statements"], "root_cause"),
            "charts": res["charts"]}, summary


def discovery_node(state: AnalystState, ctx: RunContext):
    table = ctx.primary
    res = discover(ctx.tables[table], table, _mode(ctx))
    sts = [stmt(i["text"], i["facts"], "finding") for i in res["insights"] if i["facts"]][:6]
    kept, _ = finalize(sts, res["verification"], res["facts"])
    return {"discovery": res, "facts": res["facts"], "verification": res["verification"], "statements": _tag(kept, "discovery")}, (
        f"{len(res['insights'])} verified insight(s): " + ", ".join(f"{n} {t}" for t, n in res["summary"].items()) + (f"; {res['dropped_unverified']} unverified dropped" if res["dropped_unverified"] else ""))


def executive_node(state: AnalystState, ctx: RunContext):
    table = ctx.primary
    name = ctx.table_labels.get(table, table)
    res = run_executive_summary(ctx.tables[table], table, name, _mode(ctx))
    sts = list(res["performance"]) + [stmt(i["text"], i["facts"], "finding") for i in res["findings"] if i["facts"]]
    kept, _ = finalize(sts, res["verification"], res["facts"])
    return {"executive": res, "facts": res["facts"], "verification": res["verification"], "statements": _tag(kept, "executive")}, (
        f"Summary for {res['period']}: {len(res['kpis'])} KPIs, {len(res['risks'])} risk(s), {len(res['opportunities'])} opportunity(ies), {len(res['recommendations'])} recommendation(s)")


_NUM = r"(\d+(?:\.\d+)?)\s*%"


def parse_scenario(question: str, df: pd.DataFrame) -> dict:
    ql = question.lower()
    neg = r"(?:decreas|reduc|cut|lower|drop|fall|declin|dimin|slash)\w*"
    pos = r"(?:increas|rais|rise|grow|go up|goes up|hike|boost|up)\w*"

    def find(subject: str) -> float | None:
        for pat in (rf"(?:{subject})[^.?,;]*?({neg}|{pos})[^.?,;]*?{_NUM}", rf"({neg}|{pos})\s+(?:\w+\s+){{0,3}}(?:{subject})[^.?,;]*?{_NUM}"):
            m = re.search(pat, ql)
            if m:
                return float(m.group(2)) * (-1 if re.fullmatch(neg, m.group(1)) else 1)
        m = re.search(rf"{_NUM}\s+(?:\w+\s+){{0,2}}(?:{subject})\s+({neg}|{pos})", ql)  # "a 15% price cut"
        if m:
            return float(m.group(1)) * (-1 if re.fullmatch(neg, m.group(2)) else 1)
        return None

    sc = {"price_change_pct": find(r"pric\w*") or 0.0, "cost_change_pct": find(r"costs?|expenses?") or 0.0,
          "volume_change_pct": find(r"volume|demand|quantit\w*|units|sales volume") or 0.0}
    e = re.search(r"elasticity\s*(?:of|=|is)?\s*(-?\d+(?:\.\d+)?)", ql)
    if e:
        sc["elasticity"] = float(e.group(1))
    roles = detect_roles(df)
    for dim in roles["dimensions"]:  # "...for electronics" → segment
        vals = [str(v) for v in df[dim].dropna().astype(str).unique() if len(str(v).strip()) >= 3 and re.search(rf"\b{re.escape(str(v).lower().strip())}\b", ql)]
        if vals:
            sc["segment"] = {"column": dim, "values": vals}
            break
    parts = [f"price {sc['price_change_pct']:+g}%" if sc["price_change_pct"] else "", f"cost {sc['cost_change_pct']:+g}%" if sc["cost_change_pct"] else "", f"volume {sc['volume_change_pct']:+g}%" if sc["volume_change_pct"] else ""]
    sc["name"] = ", ".join(p for p in parts if p) or "Scenario"
    return sc


def scenario_node(state: AnalystState, ctx: RunContext):
    table = ctx.primary
    df = infer_types(ctx.tables[table])
    sc = parse_scenario(state["question"], df)
    if not (sc["price_change_pct"] or sc["cost_change_pct"] or sc["volume_change_pct"]):
        raise ValueError("I could not find an assumption to simulate. Try e.g. “What happens to profit if prices increase by 10%?”")
    res = run_scenarios(df, table, [sc], mode=_mode(ctx), baseline_scope="all")
    fb = FactBook.from_list(table, _mode(ctx), res["facts"])
    obs, s0 = res["observed"], res["scenarios"][0]
    f = s0["facts"]
    sts = []
    base_ids = [obs["revenue"]] + ([obs["cost"], obs["profit"], obs["margin"]] if "cost" in obs else [])
    sts.append(stmt(f"OBSERVED baseline ({res['baseline_scope']}): revenue {fb.text(obs['revenue'])}" + (f", cost {fb.text(obs['cost'])}, profit {fb.text(obs['profit'])} (margin {fb.text(obs['margin'])})." if "cost" in obs else "."), base_ids, "observed"))
    a = s0["assumptions"]
    assume = ", ".join(x for x in [f"prices {a['price_change_pct']:+g}%" if a["price_change_pct"] else "", f"costs {a['cost_change_pct']:+g}%" if a["cost_change_pct"] else "", f"volume {a['volume_change_pct']:+g}%" if a["volume_change_pct"] else "",
                                   f"elasticity {a['elasticity']:g}" if a["elasticity"] else "", f"limited to {s0['segment']}" if s0["segment"] != "all rows" else ""] if x)
    if "profit" in f:
        sts.append(stmt(f"ESTIMATE (not observed data) — if {assume}: revenue would be about {fb.text(f['revenue'])} ({fb.text(f['revenue_change_pct'], True)}), cost about {fb.text(f['cost'])}, and profit about {fb.text(f['profit'])} "
                        f"({fb.text(f['profit_change'], True)}, {fb.text(f['profit_change_pct'], True)} vs baseline).", [f["revenue"], f["revenue_change_pct"], f["cost"], f["profit"], f["profit_change"], f["profit_change_pct"]], "estimate"))
    else:
        sts.append(stmt(f"ESTIMATE (not observed data) — if {assume}: revenue would be about {fb.text(f['revenue'])} ({fb.text(f['revenue_change_pct'], True)} vs baseline).", [f["revenue"], f["revenue_change_pct"]], "estimate"))
    kept, _ = finalize(sts, res["verification"], res["facts"])
    ch = {"type": "bar", "title": "Baseline (observed) vs scenario (ESTIMATE)", "x": "label", "y": ["Observed baseline", "Scenario estimate"],
          "data": [{"label": lbl, "Observed baseline": fb.value(obs[k]), "Scenario estimate": fb.value(f[k])} for k, lbl in (("revenue", "Revenue"), ("cost", "Cost"), ("profit", "Profit")) if k in obs and k in f]}
    return {"scenario": res, "facts": res["facts"], "verification": res["verification"], "statements": _tag(kept, "scenario"), "charts": [ch]}, (
        f"Simulated “{sc['name']}” on {res['baseline_scope']}; baseline observed, outcome flagged as estimate")


def quality_node(state: AnalystState, ctx: RunContext):
    """Answers data-quality questions with SQL-verified counts (missing values per column, rows with any gap, exact duplicates)."""
    from backend.app.analytics.facts import q, verify_facts

    table = ctx.primary
    df = ctx.tables[table]
    fb = FactBook(table, _mode(ctx), "Q")
    total = fb.base("Rows", float(len(df)), f"SELECT COUNT(*) FROM {table}", "count")
    miss = df.isna().sum().sort_values(ascending=False)
    miss = miss[miss > 0]
    any_cols = " OR ".join(f"{q(c)} IS NULL" for c in df.columns[:200])
    any_miss = fb.base("Rows with at least one missing value", float(df.isna().any(axis=1).sum()), f"SELECT COUNT(*) FROM {table} WHERE {any_cols}", "count")
    distinct = len(df.drop_duplicates())
    dup = fb.base("Exact duplicate rows", float(len(df) - distinct), f"SELECT (SELECT COUNT(*) FROM {table}) - (SELECT COUNT(*) FROM (SELECT DISTINCT * FROM {table}))", "count")
    sts = [stmt(f"The table has {fb.text(total)} rows; {fb.text(any_miss)} of them have at least one missing value and {fb.text(dup)} are exact duplicates.", [total, any_miss, dup], "quality")]
    for col, n in list(miss.items())[:3]:
        f = fb.base(f"Missing values in {col}", float(n), f"SELECT COUNT(*) FROM {table} WHERE {q(col)} IS NULL", "count")
        pct = fb.derived(f"Share of rows missing {col}", "share", [f, total], "pct")
        sts.append(stmt(f"“{col}” is missing in {fb.text(f)} rows ({fb.text(pct)}).", [f, pct], "quality"))
    if not len(miss) and not fb.value(dup):
        sts = [stmt(f"No missing values and no duplicate rows were found in {fb.text(total)} rows.", [total, any_miss, dup], "quality")]
    qual = (state.get("quality") or {}).get("tables", {}).get(table, {})
    recs = [f"Fix: {i['message']}" + (f" in “{i['column']}”" if i.get("column") else "") + f" (suggested action: {i['fix'].replace('_', ' ')})." for i in qual.get("issues", [])[:4]]
    ver = verify_facts(fb.facts, {table: df}, only_key=False)
    kept, _ = finalize(sts, ver, fb.facts)
    res = {"rows": len(df), "score": qual.get("score"), "grade": qual.get("grade"), "issues": qual.get("issues", []), "recommendations": recs}
    return {"quality_report": res, "facts": fb.facts, "verification": ver, "statements": _tag(kept, "quality")}, (
        f"{len(miss)} column(s) with missing values; {int(len(df) - distinct):,} duplicate row(s); {len(recs)} suggested fix(es)")


def story_node(state: AnalystState, ctx: RunContext):
    """Storytelling agent: assemble verified statements into a narrative; nothing without a verified fact reaches the user."""
    ver = state.get("verification", {})
    sts, dropped = finalize(state.get("statements", []), ver, state.get("facts", []))
    if not sts:
        return {"story": {}}, "No analytical statements to narrate"
    order = ["executive", "business", "quality", "root_cause", "scenario", "discovery"]
    sts.sort(key=lambda s: order.index(s["source"]) if s["source"] in order else 9)
    # re-number fact references as footnotes, in order of first use
    foot: dict[str, int] = {}
    for s in sts:
        s["refs"] = [foot.setdefault(f, len(foot) + 1) for f in s["facts"]]
    text = " ".join(s["text"] for s in sts if s.get("kind") != "estimate" or True)
    facts_by = {f["id"]: f for f in state.get("facts", [])}
    footnotes = [{"n": n, "fact": fid, "label": facts_by[fid]["label"], "value": facts_by[fid]["value"], "unit": facts_by[fid]["unit"], "sql": facts_by[fid].get("sql"),
                  "op": facts_by[fid].get("op"), "inputs": facts_by[fid].get("inputs"), "estimate": bool(facts_by[fid].get("estimate")), "verified": ver.get(fid, {}).get("verified"),
                  "detail": ver.get(fid, {}).get("detail")} for fid, n in foot.items() if fid in facts_by]
    recs = (state.get("quality_report") or {}).get("recommendations", []) + (state.get("root_cause") or {}).get("story", {}).get("recommendations", []) + [r["text"] for r in (state.get("executive") or {}).get("recommendations", [])][:5] + (state.get("business") or {}).get("recommendations", [])
    if not recs and state.get("discovery"):
        recs = [f"Look into: {i['title']}" for i in state["discovery"]["insights"] if i["severity"] in ("high", "medium")][:4]
    narrative = polish(text, footnotes) if text else ""
    return {"story": {"statements": sts, "footnotes": footnotes, "text": narrative, "recommendations": recs, "dropped": dropped}}, (
        f"{len(sts)} statement(s) cite {len(footnotes)} verified calculation(s)" + (f"; {dropped} dropped (unverified)" if dropped else ""))


def _u(n: int, unit: str) -> str:
    return f"{n} {unit}{'' if n == 1 else 's'}"


def _n(v: float, mode: str) -> str:
    return fmtnum(v, mode, 0 if abs(v) >= 100 else 2)


def forecast_node(state: AnalystState, ctx: RunContext):
    """Predicts a measure over time. Every forecast figure is labelled an ESTIMATE and carries its own backtest error."""
    table = ctx.primary
    df = ctx.tables[table]
    dts = datetime_cols(df)
    if not dts:
        raise ValueError("A forecast needs a date column, and this dataset has none.")
    spec = parse_spec(state["question"], df, ctx.extra.get("prep"))
    notes = []
    date_col = (_match_cols(state["question"], dts) or dts)[0]
    # years/months in a forecast question name the target period, not a filter on the history
    dropped = [f for f in spec["filters"] if f["op"] in ("year", "month", "quarter")]
    spec["filters"] = [f for f in spec["filters"] if f not in dropped]
    if dropped:
        notes.append(f"“{describe_filters(dropped)}” was read as the period to predict, so all history is used to fit the model.")
    if spec.get("group"):
        notes.append(f"A breakdown by {spec['group']} was not applied; this is the overall forecast.")
        spec["group"] = None
    if spec["kind"] in ("count", "group_count") or spec["agg"] == "COUNT":
        spec["agg"] = "COUNT"
    else:
        spec["agg"] = "AVG" if (not spec["explicit"]["agg"] and spec["metric"] and not spec.get("metric_expr") and not is_additive(spec["metric"])) else (
            spec["agg"] if spec["agg"] in ("SUM", "AVG") else "SUM")
        if not spec["metric"]:
            raise ValueError("There is no numeric column to forecast in this dataset.")
        if not spec["explicit"]["metric"]:
            notes.append(f"No measure was named, so “{spec['metric']}” is forecast.")
    spec["kind"] = "forecast"
    label = ("profit" if spec.get("metric_expr") else spec["metric"]) if spec["agg"] != "COUNT" else (f"distinct {spec['distinct']}" if spec.get("distinct") else "row count")
    res = run_forecast(df, spec, state["question"], date_col, label)
    res["notes"] = notes + res["notes"]
    ctx.extra["forecast"] = res
    mode = _mode(ctx)
    fc, hist, bt = res["forecast"], res["history"], res["backtest"]
    word = {"SUM": "total", "AVG": "average", "COUNT": ""}[res["agg"]]
    nxt = fc[0]
    last, prev = hist[-1], hist[-2]
    ev = {"type": "forecast", "table": table, "method": res["model"], "check": {"fn": "forecast"}}
    insights = list(state.get("insights", []))
    unit = res["grain"]
    chg = res["change_pct"]
    total_txt = (f"; over the next {_u(res['horizon'], unit)} the {word + ' ' if word else ''}{label} comes to about {_n(res['forecast_total'], mode)}"
                 + (f" versus {_n(res['recent_total'], mode)} in the last {res['horizon']} observed ({chg:+.1f}%)" if chg is not None else ""))
    insights.append({"kind": "forecast", "severity": "info", "evidence": dict(ev), "text": (
        f"ESTIMATE (not observed data): {label} is forecast at about {_n(nxt['value'], mode)} for {nxt['label']} "
        f"(likely range {_n(nxt['lower'], mode)} to {_n(nxt['upper'], mode)}){total_txt}.")})
    mape = f"{bt['mape']:.1f}%" if bt["mape"] is not None else "n/a"
    insights.append({"kind": "forecast", "severity": "info" if res["confidence"] != "low" else "warning", "evidence": dict(ev), "text": (
        f"Basis: {res['periods_used']} complete {unit}s ({res['first_period']} to {res['last_period']}). Of {len(bt['tried'])} models tested on the latest "
        f"{bt['periods']} {unit}s, “{res['model']}” fit best and was off by {mape} on average. Confidence: {res['confidence']}"
        + (". Treat this as a rough indication only." if res["confidence"] == "low" else "."))})
    if prev["value"]:
        insights.append({"kind": "forecast", "severity": "info", "evidence": dict(ev), "text": (
            f"Observed: the last complete {unit} ({last['label']}) was {_n(last['value'], mode)}, "
            f"{(last['value'] - prev['value']) / abs(prev['value']) * 100:+.1f}% versus {prev['label']}.")})
    for n in res["notes"]:
        insights.append({"kind": "note", "severity": "info", "text": n})
    keep = hist[-36:]
    rows = [{"t": h["t"], label: h["value"]} for h in keep]
    rows[-1]["Forecast"] = rows[-1][label]
    rows += [{"t": f["t"], "Forecast": f["value"], "Low (80%)": f["lower"], "High (80%)": f["upper"]} for f in fc]
    chart = chart_spec("line", f"{label} — history and forecast (ESTIMATE)", rows, "t", [label, "Forecast", "Low (80%)", "High (80%)"],
                       note="Dashed lines are model estimates, not observed data")
    where = f", only where {describe_filters(spec['filters'])}" if spec["filters"] else ""
    interp = f"Forecast of {label} for the next {_u(res['horizon'], unit)}, fitted on {date_col}{where}"
    return {"forecast": res, "insights": insights, "charts": [chart], "interpretation": interp}, (
        f"{res['model']} on {res['periods_used']} {unit}s; backtest error {mape}; confidence {res['confidence']}; {_u(res['horizon'], unit)} ahead")


def business_node(state: AnalystState, ctx: RunContext):
    """Answers the questions a manager asks of sales data: top performers, loss-makers, profit contribution, key customers, discounts."""
    table = ctx.primary
    res = business_findings(ctx.tables[table], table, _mode(ctx))
    cov = res["coverage"]
    if not res["findings"]:
        return {"business": res}, "No revenue/profit/customer/discount structure found to analyse"
    charts = list(state.get("charts", [])) + res["charts"]
    return {"business": res, "facts": res["facts"], "verification": res["verification"], "statements": _tag(res["statements"], "business"), "charts": charts}, (
        f"{len(res['findings'])} verified finding(s) from {', '.join(k for k in ('revenue', 'profit', 'customer', 'discount') if cov.get(k))}"
        + (f"; {res['dropped_unverified']} unverified dropped" if res["dropped_unverified"] else ""))
