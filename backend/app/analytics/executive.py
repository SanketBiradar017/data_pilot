"""Executive summary: management-level view built only from verified facts and discovered insights."""
import pandas as pd

from backend.app.analytics.charts import spec
from backend.app.analytics.discovery import _grain, discover
from backend.app.analytics.facts import FactBook, period_cond, q, verify_facts
from backend.app.analytics.roles import detect_roles
from backend.app.analytics.root_cause import _complete, _periods
from backend.app.analytics.story import finalize, stmt
from backend.app.analytics.utils import infer_types, jsonable
from backend.app.core.exceptions import AppError

RISK_TYPES = {"concentration", "declining", "decline", "customer", "data_quality"}
OPP_TYPES = {"performer", "growth"}


def _sum_sql(fb: FactBook, col: str, cond: str = "") -> str:
    return f"SELECT COALESCE(SUM({q(col)}), 0) FROM {fb.table}" + (f" WHERE {cond}" if cond else "")


def run_executive_summary(df: pd.DataFrame, table: str, dataset_name: str = "", mode: str = "standard", quality_score: float | None = None) -> dict:
    df = infer_types(df)
    roles = detect_roles(df)
    rev, cost, qty, date = roles["revenue"], roles["cost"], roles["quantity"], roles["date"]
    if not rev and not roles["measures"]:
        raise AppError("The dataset has no numeric measures to summarise")
    metric = rev or roles["measures"][0]
    fb = FactBook(table, mode, "K")
    statements, kpis = [], []
    grain = cur = prev = None
    d = None
    if date:
        d = df.dropna(subset=[date])
        grain = _grain(d, date)
        per = _periods(d, date, grain)
        avail = sorted(per.unique())
        if len(avail) >= 2:
            cur = avail[-1] if _complete(d, date, grain, avail[-1]) or len(avail) < 3 else avail[-2]
            prev = cur - 1 if (cur - 1) in set(avail) else None
    cols = [(metric, "currency")] + ([(cost, "currency")] if cost and cost != metric else []) + ([(qty, "number")] if qty and qty not in (metric, cost) else [])
    ids: dict[str, dict] = {}
    for col, unit in cols:
        tot = fb.base(f"Total {col}", float(df[col].sum()), _sum_sql(fb, col), unit)
        ent = {"label": col, "total": tot}
        if cur is not None and prev is not None:
            pc, pp = per == cur, per == prev
            c1 = fb.base(f"{col} in {cur}", float(d.loc[pc, col].sum()), _sum_sql(fb, col, period_cond(date, grain, str(cur.start_time.date()))), unit)
            c0 = fb.base(f"{col} in {prev}", float(d.loc[pp, col].sum()), _sum_sql(fb, col, period_cond(date, grain, str(prev.start_time.date()))), unit)
            ent.update(cur=c1, prev=c0, change=fb.derived(f"Change in {col}", "diff", [c1, c0], unit), pct=fb.derived(f"% change in {col}", "pct_change", [c1, c0], "pct"))
        ids[col] = ent
    notes: list[str] = []
    if cost and cost != metric:  # profit and margin: only rows where BOTH revenue and cost are known
        both = df[metric].notna() & df[cost].notna()
        pc_sql = f"{q(metric)} IS NOT NULL AND {q(cost)} IS NOT NULL"
        if not both.all():
            notes.append(f"Profit is calculated on the {int(both.sum()):,} of {len(df):,} rows that have both revenue and cost; the other {int((~both).sum()):,} rows are excluded from profit and margin.")
        rp = fb.base("Revenue (rows with cost)", float(df.loc[both, metric].sum()), _sum_sql(fb, metric, pc_sql), "currency")
        cp = fb.base("Cost (rows with revenue)", float(df.loc[both, cost].sum()), _sum_sql(fb, cost, pc_sql), "currency")
        ent = {"label": "profit", "total": fb.derived("Total profit", "diff", [rp, cp], "currency")}
        ent["margin"] = fb.derived("Overall profit margin", "share", [ent["total"], rp], "pct")
        if "cur" in ids[metric] and "cur" in ids[cost]:
            def per_sum(col, p):
                return _sum_sql(fb, col, period_cond(date, grain, str(p.start_time.date())) + " AND " + pc_sql)
            m1, m0 = (per == cur) & both, (per == prev) & both
            rc1 = fb.base(f"Revenue in {cur} (rows with cost)", float(d.loc[m1[d.index], metric].sum()), per_sum(metric, cur), "currency")
            rc0 = fb.base(f"Revenue in {prev} (rows with cost)", float(d.loc[m0[d.index], metric].sum()), per_sum(metric, prev), "currency")
            cc1 = fb.base(f"Cost in {cur} (rows with revenue)", float(d.loc[m1[d.index], cost].sum()), per_sum(cost, cur), "currency")
            cc0 = fb.base(f"Cost in {prev} (rows with revenue)", float(d.loc[m0[d.index], cost].sum()), per_sum(cost, prev), "currency")
            ent["cur"] = fb.derived(f"Profit in {cur}", "diff", [rc1, cc1], "currency")
            ent["prev"] = fb.derived(f"Profit in {prev}", "diff", [rc0, cc0], "currency")
            ent["pct"] = fb.derived("% change in profit", "pct_change", [ent["cur"], ent["prev"]], "pct")
            ent["margin_cur"] = fb.derived(f"Profit margin in {cur}", "share", [ent["cur"], rc1], "pct")
        ids["profit"] = ent
    nrec = fb.base("Number of records", float(len(df)), f"SELECT COUNT(*) FROM {table}", "count")

    for key, ent in ids.items():
        item = {"label": key, "fact": ent["total"], "value": fb.value(ent["total"]), "unit": "currency" if key != qty else "number", "period_fact": ent.get("cur"),
                "period_value": fb.value(ent["cur"]) if ent.get("cur") else None, "change_pct": fb.value(ent["pct"]) if ent.get("pct") else None}
        kpis.append(item)
    kpis.append({"label": "records", "fact": nrec, "value": fb.value(nrec), "unit": "count", "period_fact": None, "period_value": None, "change_pct": None})

    m = ids[metric]
    if "cur" in m:
        up = fb.value(m["change"]) >= 0
        statements.append(stmt(f"{metric.capitalize()} in {cur} was {fb.text(m['cur'])}, {'up' if up else 'down'} {fb.absolute(m['pct'])} on {prev} ({fb.text(m['prev'])}).", [m["cur"], m["prev"], m["pct"]], "performance"))
    statements.append(stmt(f"Across the whole dataset, total {metric} is {fb.text(m['total'])} over {fb.text(nrec)} records.", [m["total"], nrec], "performance"))
    if "profit" in ids:
        pr = ids["profit"]
        statements.append(stmt(f"Overall profit is {fb.text(pr['total'])}, a margin of {fb.text(pr['margin'])}." + (f" In {cur} profit was {fb.text(pr['cur'])} ({fb.text(pr['pct'], True)} vs {prev}, margin {fb.text(pr['margin_cur'])})." if "cur" in pr else ""),
                               [pr["total"], pr["margin"]] + ([pr["cur"], pr["pct"], pr["margin_cur"]] if "cur" in pr else []), "performance"))

    disc = discover(df, table, mode, max_insights=16, prefix="E")
    insights = disc["insights"]
    findings = [i for i in insights if i["severity"] in ("high", "medium")][:5] or insights[:4]
    risks = [i for i in insights if i["type"] in RISK_TYPES][:4]
    opps = [i for i in insights if i["type"] in OPP_TYPES][:3]
    recs: list[dict] = []
    for i in insights:
        tool = i.get("investigate")
        if i["type"] in ("decline", "declining"):
            recs.append({"text": f"Investigate: {i['title']}. Run a root-cause analysis to see which segment, volume or price effects drove it.", "insight": i["id"], "priority": "high"})
        elif i["type"] == "concentration":
            recs.append({"text": f"Reduce dependency: {i['title']}. Set targets to grow other segments and review contract / supply risk.", "insight": i["id"], "priority": "high"})
        elif i["type"] == "customer":
            recs.append({"text": f"Customer action: {i['title']}. Contact the affected accounts and review service, pricing and competitor activity.", "insight": i["id"], "priority": "medium"})
        elif i["type"] == "performer":
            recs.append({"text": f"Scale what works: {i['title']}. Allocate more stock, marketing or sales capacity there.", "insight": i["id"], "priority": "medium"})
        elif i["type"] == "growth":
            recs.append({"text": f"Sustain the momentum: {i['title']}. Confirm the drivers are repeatable (see root-cause analysis).", "insight": i["id"], "priority": "low"})
        elif i["type"] == "data_quality":
            recs.append({"text": f"Clean the data: {i['title']}. Use Data sources → Data quality → standardise case / trim whitespace, then re-run the analysis.", "insight": i["id"], "priority": "medium"})
        elif i["type"] == "distribution":
            recs.append({"text": f"Data caution: {i['title']}. Use medians and review extreme rows before setting targets.", "insight": i["id"], "priority": "low"})
        del tool
    if quality_score is not None and quality_score < 85:
        recs.append({"text": f"Improve data quality (score {quality_score:.0f}/100) before relying on detailed breakdowns.", "insight": None, "priority": "medium"})
    order = {"high": 0, "medium": 1, "low": 2}
    recs.sort(key=lambda r: order[r["priority"]])

    # verification of KPI facts (discovery verified its own)
    ver = verify_facts(fb.facts, {table: df}, only_key=False)
    ver.update(disc["verification"])
    facts_all_for_final = fb.facts + disc["facts"]
    kept, dropped = finalize(statements, ver, facts_all_for_final)
    for k in kpis:
        k["verified"] = bool(ver.get(k["fact"], {}).get("verified"))
    charts = []
    if date and d is not None and grain:
        s = d.assign(__p=_periods(d, date, grain).astype(str)).groupby("__p")[metric].sum().tail(14).reset_index()
        charts.append(spec("line", f"{metric} by {grain}", [{"t": r["__p"], metric: float(r[metric])} for _, r in s.iterrows()], "t", [metric]))
    dim = roles["product"] or (roles["dimensions"][0] if roles["dimensions"] else None)
    if dim:
        g = df.groupby(dim, observed=True)[metric].sum().sort_values(ascending=False).head(10).reset_index()
        charts.append(spec("bar", f"{metric} by {dim}", [{dim: str(r[dim]), metric: float(r[metric])} for _, r in g.iterrows()], dim, [metric]))
    period_txt = f"{cur}" if cur is not None else "all data"
    facts_all = fb.facts + disc["facts"]
    return jsonable({
        "title": f"Executive summary{' — ' + dataset_name if dataset_name else ''}", "period": period_txt, "grain": grain, "metric": metric,
        "performance": kept, "kpis": kpis, "findings": findings, "risks": risks, "opportunities": opps, "recommendations": recs[:8],
        "evidence": [{"id": f["id"], "label": f["label"], "value": f["value"], "unit": f["unit"], "sql": f.get("sql"), "op": f.get("op"), "inputs": f.get("inputs"),
                      "verified": ver.get(f["id"], {}).get("verified"), "detail": ver.get(f["id"], {}).get("detail")} for f in facts_all if f["id"] in ver],
        "facts": facts_all, "verification": ver, "dropped_statements": dropped, "dropped_insights": disc["dropped_unverified"], "charts": charts,
        "data_quality_score": quality_score, "mode": mode, "data_notes": notes,
    })
