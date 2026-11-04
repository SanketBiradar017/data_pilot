"""Root cause analysis: why did a metric change between two periods?

Decomposes the change (all components reconcile exactly to the total):
  * by dimension (region, category, …) and by the strongest 2-way cell
  * volume / mix / price (when a quantity column exists) or order-count / average-order-value
  * seasonality check against the same period one year earlier
Every number is a Fact (SQL-verified or derived from verified facts)."""
import re

import pandas as pd

from backend.app.analytics.facts import FactBook, eq_cond, labels, period_cond, q, verify_facts
from backend.app.analytics.roles import detect_roles, is_additive
from backend.app.analytics.utils import infer_types, jsonable
from backend.app.core.exceptions import AppError

GRAIN_FREQ = {"day": "D", "week": "W", "month": "M", "quarter": "Q", "year": "Y"}
MONTHS = {m: i + 1 for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"])}
MONTHS.update({k[:3]: v for k, v in list(MONTHS.items())})


_UNSUPPORTED = {"price", "prices", "margin", "margins", "orders", "order", "customers", "customer", "discount", "discounts", "traffic", "conversion", "churn", "rate", "rates"}
_MONTH_RX = "|".join(sorted(MONTHS, key=len, reverse=True))


def parse_question(question: str, df: pd.DataFrame, roles: dict) -> dict:
    """Pull metric, period and direction hints out of free text ('Why did revenue decrease in July?').
    Returns metric=None when no metric is named; sets `unsupported` when a metric is named that cannot be explained."""
    ql = question.lower()
    metric = unsupported = None
    for c in roles["measures"]:
        if re.search(rf"\b{re.escape(c.lower().replace('_', ' '))}\b|\b{re.escape(c.lower())}\b", ql):
            metric = c
            break
    if not metric:
        for pat, col in ((r"\brevenues?\b|\bsales\b|\bincome\b|\bturnover\b", roles["revenue"]), (r"\bcosts?\b|\bexpenses?\b|\bspend(ing)?\b", roles["cost"]),
                         (r"\bquantity\b|\bunits\b|\bvolumes?\b", roles["quantity"]), (r"\bprofits?\b", "profit" if roles["revenue"] and roles["cost"] else None)):
            if re.search(pat, ql):
                metric = col
                if col is None:
                    unsupported = re.search(pat, ql).group(0)
                break
    if not metric and not unsupported:
        bad = re.search(r"\b(" + "|".join(_UNSUPPORTED) + r")\b", ql)
        unsupported = bad.group(1) if bad else None
    direction = ("decrease" if re.search(r"decreas|drop|declin|fell|fall|down|lower|dip|reduc|loss|shrank|shrink", ql)
                 else "increase" if re.search(r"increas|rise|rose|grew|growth|\bup\b|higher|jump|improv|surge", ql) else None)
    # months must be introduced by a preposition when ambiguous ("may" is also a verb)
    m = re.search(rf"\b(?:in|during|for|of|on|from|since|than|to)\s+({_MONTH_RX})\b", ql) or re.search(r"\b(january|february|april|june|july|august|september|october|november|december|jan|feb|apr|jun|jul|aug|sept?|oct|nov|dec)\b", ql)
    month = MONTHS.get(m.group(1)) if m else None
    yr = re.search(r"\b(20\d{2})\b", ql)
    grain = "month" if month else "quarter" if re.search(r"\bquarter\b|\bq[1-4]\b", ql) else "week" if re.search(r"\bweek\b", ql) else "year" if re.search(r"\bannual|\byearly\b|\bthis year\b|\bfull year\b", ql) else "month"
    return {"metric": metric, "unsupported": unsupported, "direction": direction, "grain": grain, "month": month, "year": int(yr.group(1)) if yr else None}


def _periods(df: pd.DataFrame, date: str, grain: str) -> pd.Series:
    return df[date].dt.to_period(GRAIN_FREQ[grain])


def resolve_period(df: pd.DataFrame, date: str, grain: str, month: int | None, year: int | None, explicit: str | None) -> pd.Period:
    per = _periods(df.dropna(subset=[date]), date, grain)
    avail = sorted(per.unique())
    if explicit:
        try:
            p = pd.Period(explicit, freq=GRAIN_FREQ[grain])
        except Exception as e:
            raise AppError(f"Cannot read period '{explicit}' for {grain} grain") from e
        if p not in avail:
            raise AppError(f"No data in {p}. Data covers {avail[0]} to {avail[-1]}")
        return p
    if month and grain == "month":
        cands = [p for p in avail if p.month == month and (year is None or p.year == year)]
        if not cands:
            raise AppError(f"No data for that month. Data covers {avail[0]} to {avail[-1]}")
        return cands[-1]
    return avail[-1]


def _complete(df, date, grain, p) -> bool:
    days = df.loc[_periods(df, date, grain) == p, date].dt.normalize().nunique()
    span = (p.end_time.normalize() - p.start_time.normalize()).days + 1
    return days >= 0.8 * span


def _sql_total(fb: FactBook, metric: str, date: str, grain: str, p: pd.Period, extra: str = "", agg: str = "SUM") -> str:
    col = "*" if agg == "COUNT" else fb.col(metric)
    cond = period_cond(date, grain, str(p.start_time.date()))
    expr = f"{agg}({col})" if agg == "COUNT" else f"COALESCE({agg}({col}), 0)"
    return f"SELECT {expr} FROM {fb.table} WHERE {cond}{extra}"


def run_root_cause(df: pd.DataFrame, table: str, metric: str | None = None, date_col: str | None = None, grain: str = "month",
                   current: str | None = None, previous: str | None = None, dimensions: list[str] | None = None,
                   question: str | None = None, mode: str = "standard", month: int | None = None, year: int | None = None, prefix: str = "R") -> dict:
    df = infer_types(df)
    roles = detect_roles(df)
    date = date_col or roles["date"]
    if not date or date not in df.columns or not pd.api.types.is_datetime64_any_dtype(df[date]):
        raise AppError("Root cause analysis needs a date column")
    hint = parse_question(question, df, roles) if question else {"unsupported": None}
    if question and hint.get("unsupported") and not metric:
        ok = ", ".join(x for x in ([roles["revenue"], roles["cost"], roles["quantity"], "profit" if roles["revenue"] and roles["cost"] else None] + roles["additive"]) if x)
        raise AppError(f"I can't explain changes in “{hint['unsupported']}” because it is not an additive measure in this dataset. Try one of: {ok}.")
    metric = metric or roles["revenue"] or (roles["additive"][0] if roles["additive"] else None)
    d = df.dropna(subset=[date]).copy()
    derived = None
    if metric == "profit" and "profit" not in df.columns:
        if not (roles["revenue"] and roles["cost"]):
            raise AppError("Profit needs both a revenue and a cost column")
        d["profit"] = d[roles["revenue"]] - d[roles["cost"]]
        derived = f'({q(roles["revenue"])} - {q(roles["cost"])})'
    if not metric or metric not in d.columns or not pd.api.types.is_numeric_dtype(d[metric]):
        raise AppError("Choose a numeric metric to explain")
    if not derived and not is_additive(metric):
        raise AppError(f"“{metric}” looks like a price / rate / percentage, which cannot be summed across rows. Choose an additive metric such as {roles['revenue'] or 'revenue'}.")
    per = _periods(d, date, grain)
    cur = resolve_period(d, date, grain, month, year, current)
    if not current and month is None:  # default: latest *complete* period
        avail = sorted(per.unique())
        if not _complete(d, date, grain, cur) and len(avail) > 1:
            cur = avail[-2]
    prev = pd.Period(previous, freq=GRAIN_FREQ[grain]) if previous else cur - 1
    if prev not in set(per.unique()):
        raise AppError(f"No data in the previous {grain} ({prev}), so there is nothing to compare with")
    d["__p__"] = per
    dims_all = [x for x in (dimensions or roles["dimensions"]) if x in d.columns and x != metric]
    for x in set(dims_all) | ({roles["product"]} if roles["product"] else set()):
        d[f"__L_{x}"] = labels(d[x])
    c1, c0 = d[d["__p__"] == cur], d[d["__p__"] == prev]
    fb = FactBook(table, mode, prefix)
    if derived:
        fb.exprs[metric] = derived
    r1 = fb.base(f"{metric} in {cur}", float(c1[metric].sum()), _sql_total(fb, metric, date, grain, cur), "currency")
    r0 = fb.base(f"{metric} in {prev}", float(c0[metric].sum()), _sql_total(fb, metric, date, grain, prev), "currency")
    delta = fb.derived(f"Change in {metric}", "diff", [r1, r0], "currency")
    pct = fb.derived(f"% change in {metric}", "pct_change", [r1, r0], "pct")
    total = fb.value(delta)
    direction = "increased" if total > 0 else "decreased" if total < 0 else "was unchanged"
    sign = 1 if total >= 0 else -1

    # ---- dimension contributions (exact: group deltas sum to total delta)
    dims = [x for x in (dimensions or roles["dimensions"]) if x in d.columns and x != metric][:6]
    if roles["customer"] and roles["customer"] not in dims and not dimensions:
        pass  # customers are analysed in discovery, not as a driver of period change
    dim_results, checks = [], []
    for dim in dims:
        g = d[d["__p__"].isin([cur, prev]) & d[metric].notna()].groupby([f"__L_{dim}", "__p__"], observed=True)[metric].sum().unstack(fill_value=0)
        g = g.reindex(columns=[prev, cur], fill_value=0)
        g["delta"] = g[cur] - g[prev]
        checks.append({"check": f"{dim}: group changes sum to total change", "passed": abs(g["delta"].sum() - total) <= 1e-6 * max(1, abs(total))})
        g = g.reindex(g["delta"].abs().sort_values(ascending=False).index)
        top = []
        for name, row in g.head(8).iterrows():
            cond = " AND " + eq_cond(dim, name)
            a1 = fb.base(f"{metric} in {cur}, {dim} = {name}", float(row[cur]), _sql_total(fb, metric, date, grain, cur, cond), "currency", key=len(top) < 3)
            a0 = fb.base(f"{metric} in {prev}, {dim} = {name}", float(row[prev]), _sql_total(fb, metric, date, grain, prev, cond), "currency", key=len(top) < 3)
            dd = fb.derived(f"Change in {metric}, {dim} = {name}", "diff", [a1, a0], "currency", key=len(top) < 3)
            sh = fb.derived(f"Share of total change, {dim} = {name}", "share", [dd, delta], "pct", key=len(top) < 3)
            top.append({"group": str(name), "previous": float(row[prev]), "current": float(row[cur]), "change": float(row["delta"]),
                        "share_of_change_pct": fb.value(sh), "facts": [a0, a1, dd, sh]})
        concentration = abs(float(g["delta"].iloc[0])) / max(1e-12, float(g["delta"].abs().sum())) if len(g) else 0
        dim_results.append({"dimension": dim, "top": top, "n_groups": int(len(g)), "concentration": concentration,
                            "explained_by_top_pct": fb.value(top[0]["facts"][3]) if top else None})
    dim_results.sort(key=lambda r: -r["concentration"])

    # ---- strongest 2-way cell
    cells = []
    if len(dims) >= 2:
        d1, d2 = dim_results[0]["dimension"], dim_results[1]["dimension"]
        g = d[d["__p__"].isin([cur, prev]) & d[metric].notna()].groupby([f"__L_{d1}", f"__L_{d2}", "__p__"], observed=True)[metric].sum().unstack(fill_value=0).reindex(columns=[prev, cur], fill_value=0)
        g["delta"] = g[cur] - g[prev]
        g = g.reindex(g["delta"].abs().sort_values(ascending=False).index)
        for (a, b), row in g.head(5).iterrows():
            cond = f" AND {eq_cond(d1, a)} AND {eq_cond(d2, b)}"
            k = len(cells) < 2
            f1 = fb.base(f"{metric} in {cur}, {d1} = {a} & {d2} = {b}", float(row[cur]), _sql_total(fb, metric, date, grain, cur, cond), "currency", key=k)
            f0 = fb.base(f"{metric} in {prev}, {d1} = {a} & {d2} = {b}", float(row[prev]), _sql_total(fb, metric, date, grain, prev, cond), "currency", key=k)
            fd = fb.derived(f"Change in {metric}, {d1} = {a} & {d2} = {b}", "diff", [f1, f0], "currency", key=k)
            fs = fb.derived(f"Share of total change, {d1} = {a} & {d2} = {b}", "share", [fd, delta], "pct", key=k)
            cells.append({"dim1": d1, "value1": str(a), "dim2": d2, "value2": str(b), "previous": float(row[prev]), "current": float(row[cur]),
                          "change": float(row["delta"]), "share_of_change_pct": fb.value(fs), "facts": [f0, f1, fd, fs]})

    # ---- volume / mix / price  (or order count / average order value)
    # Uses only rows where BOTH metric and quantity are known, so revenue and quantity cover identical rows;
    # any change coming from rows without a quantity is reported as "unattributed" so everything still reconciles.
    drivers, qty = {}, roles["quantity"]
    is_money = metric != qty and qty is not None
    tol = lambda x: abs(x) <= 1e-6 * max(1.0, abs(total))  # noqa: E731
    if is_money:
        both = f" AND {q(qty)} IS NOT NULL AND {fb.col(metric)} IS NOT NULL"
        s1_, s0_ = c1[c1[metric].notna() & c1[qty].notna()], c0[c0[metric].notna() & c0[qty].notna()]
        r1s = fb.base(f"{metric} in {cur} (rows with {qty})", float(s1_[metric].sum()), _sql_total(fb, metric, date, grain, cur, both), "currency")
        r0s = fb.base(f"{metric} in {prev} (rows with {qty})", float(s0_[metric].sum()), _sql_total(fb, metric, date, grain, prev, both), "currency")
        q1 = fb.base(f"{qty} in {cur}", float(s1_[qty].sum()), _sql_total(fb, qty, date, grain, cur, both), "number")
        q0 = fb.base(f"{qty} in {prev}", float(s0_[qty].sum()), _sql_total(fb, qty, date, grain, prev, both), "number")
        qpct = fb.derived(f"% change in {qty}", "pct_change", [q1, q0], "pct")
        if fb.value(q0):
            vol = fb.derived("Volume effect", "volume_effect", [r0s, q0, q1], "currency")
            pr = fb.derived("Price & mix effect", "price_effect", [r0s, q0, r1s, q1], "currency")
            p0 = fb.derived(f"Average {metric} per {qty} ({prev})", "ratio", [r0s, q0], "currency")
            p1 = fb.derived(f"Average {metric} per {qty} ({cur})", "ratio", [r1s, q1], "currency")
            ppct = fb.derived(f"% change in average {metric} per {qty}", "pct_change", [p1, p0], "pct")
            u1 = fb.derived(f"{metric} in {cur} from rows without {qty}", "diff", [r1, r1s], "currency")
            u0 = fb.derived(f"{metric} in {prev} from rows without {qty}", "diff", [r0, r0s], "currency")
            una = fb.derived(f"Change from rows without {qty}", "diff", [u1, u0], "currency")
            drivers = {"kind": "volume_price", "quantity": qty, "volume_effect": fb.value(vol), "price_mix_effect": fb.value(pr), "unattributed": fb.value(una), "unattributed_fact": una,
                       "quantity_change_pct": fb.value(qpct), "unit_value_change_pct": fb.value(ppct), "facts": [q0, q1, qpct, vol, pr, p0, p1, ppct]}
            checks.append({"check": "volume + price/mix (+ rows without quantity) equal total change", "passed": tol(fb.value(vol) + fb.value(pr) + fb.value(una) - total)})
            pd_dim = roles["product"] or (dims[0] if dims else None)
            if pd_dim:  # split price & mix with a product-like dimension
                S = d[d["__p__"].isin([cur, prev]) & d[metric].notna() & d[qty].notna()]
                gg = S.groupby([f"__L_{pd_dim}", "__p__"], observed=True)[[metric, qty]].sum()
                Rg = gg[metric].unstack(fill_value=0).reindex(columns=[prev, cur], fill_value=0)
                Qg = gg[qty].unstack(fill_value=0).reindex(columns=[prev, cur], fill_value=0)
                Qt0, Qt1 = Qg[prev].sum(), Qg[cur].sum()
                mix = price = 0.0
                for name in Rg.index:
                    R0g, R1g, Q0g, Q1g = Rg.loc[name, prev], Rg.loc[name, cur], Qg.loc[name, prev], Qg.loc[name, cur]
                    P0g = R0g / Q0g if Q0g else (R1g / Q1g if Q1g else 0.0)
                    P1g = R1g / Q1g if Q1g else P0g
                    s0, s1 = (Q0g / Qt0 if Qt0 else 0), (Q1g / Qt1 if Qt1 else 0)
                    mix += Qt1 * (s1 - s0) * P0g
                    price += Q1g * (P1g - P0g)
                vol_sum = (Qt1 - Qt0) * fb.value(r0s) / Qt0 if Qt0 else 0.0
                drivers.update({"mix_effect": float(mix), "like_for_like_price_effect": float(price), "mix_dimension": pd_dim})
                checks.append({"check": f"volume + mix({pd_dim}) + price (+ rows without quantity) = total change", "passed": tol(vol_sum + mix + price + fb.value(una) - total)})
    if not drivers:  # orders × average order value
        nn = " AND " + fb.col(metric) + " IS NOT NULL"
        n1, n0 = int(c1[metric].notna().sum()), int(c0[metric].notna().sum())
        nn1 = fb.base(f"Number of records in {cur}", float(n1), _sql_total(fb, metric, date, grain, cur, nn, agg="COUNT"), "count")
        nn0 = fb.base(f"Number of records in {prev}", float(n0), _sql_total(fb, metric, date, grain, prev, nn, agg="COUNT"), "count")
        npct = fb.derived("% change in number of records", "pct_change", [nn1, nn0], "pct")
        if n0:
            vol = fb.derived("Record-count effect", "volume_effect", [r0, nn0, nn1], "currency")
            pr = fb.derived("Average-value effect", "price_effect", [r0, nn0, r1, nn1], "currency")
            drivers = {"kind": "count_value", "volume_effect": fb.value(vol), "price_mix_effect": fb.value(pr), "unattributed": 0.0, "quantity_change_pct": fb.value(npct), "facts": [nn0, nn1, npct, vol, pr]}
            checks.append({"check": "count + average-value effects equal total change", "passed": tol(fb.value(vol) + fb.value(pr) - total)})

    # ---- seasonality: did the same period move the same way a year earlier?
    season = None
    back = {"month": 12, "quarter": 4, "year": 1, "week": 52, "day": 365}[grain]
    cur_ly, prev_ly = cur - back, prev - back
    if cur_ly in set(per.unique()) and prev_ly in set(per.unique()):
        s1 = fb.base(f"{metric} in {cur_ly}", float(d.loc[d["__p__"] == cur_ly, metric].sum()), _sql_total(fb, metric, date, grain, cur_ly), "currency")
        s0 = fb.base(f"{metric} in {prev_ly}", float(d.loc[d["__p__"] == prev_ly, metric].sum()), _sql_total(fb, metric, date, grain, prev_ly), "currency")
        sp = fb.derived(f"% change in {metric}, {prev_ly} → {cur_ly}", "pct_change", [s1, s0], "pct")
        same = fb.value(sp) is not None and fb.value(pct) is not None and (fb.value(sp) > 0) == (fb.value(pct) > 0)
        season = {"prior_period": str(cur_ly), "prior_previous": str(prev_ly), "prior_change_pct": fb.value(sp), "same_direction": bool(same),
                  "likely_seasonal": bool(same and abs(fb.value(sp)) >= 0.5 * abs(fb.value(pct) or 0)), "facts": [s0, s1, sp]}

    # ---- rank contributing factors
    factors = []
    for dr in dim_results[:3]:
        t = dr["top"][0] if dr["top"] else None
        if t and t["share_of_change_pct"] is not None and t["share_of_change_pct"] >= 15:
            factors.append({"type": "dimension", "title": f"{dr['dimension']} = {t['group']}", "impact": t["change"], "share_pct": t["share_of_change_pct"], "facts": t["facts"]})
    if drivers:
        label = ("Volume (" + drivers.get("quantity", "records") + ")") if drivers["kind"] == "volume_price" else "Number of records"
        factors.append({"type": "volume", "title": label, "impact": drivers["volume_effect"], "share_pct": drivers["volume_effect"] / total * 100 if total else None, "facts": drivers["facts"][:4]})
        factors.append({"type": "price", "title": "Average price / mix" if drivers["kind"] == "volume_price" else "Average value per record", "impact": drivers["price_mix_effect"],
                        "share_pct": drivers["price_mix_effect"] / total * 100 if total else None, "facts": drivers["facts"][4:]})
    factors.sort(key=lambda f: -abs(f["impact"]))
    offsets = [t for dr in dim_results[:1] for t in dr["top"] if t["change"] * sign < 0][:3]

    verification = verify_facts(fb.facts, {table: d.drop(columns=["__p__"])})
    series = d.groupby("__p__")[metric].sum().sort_index().tail(13)
    trend = [{"t": str(k), metric: float(v)} for k, v in series.items()]
    charts = []
    if dim_results and dim_results[0]["top"]:
        dr0 = dim_results[0]
        charts.append({"type": "bar", "title": f"Change in {metric} by {dr0['dimension']} ({prev} → {cur})", "x": "label", "y": ["variance"], "signed": True,
                       "data": [{"label": t["group"], "variance": t["change"]} for t in dr0["top"]]})
    if drivers:
        comp = [("Volume", drivers["volume_effect"])]
        if "mix_effect" in drivers:
            comp += [("Product mix", drivers["mix_effect"]), ("Like-for-like price", drivers["like_for_like_price_effect"])]
        else:
            comp += [("Price / average value", drivers["price_mix_effect"])]
        charts.append({"type": "bar", "title": "What moved the number (reconciles to the total change)", "x": "label", "y": ["variance"], "signed": True, "data": [{"label": a, "variance": b} for a, b in comp]})
    charts.append({"type": "line", "title": f"{metric} by {grain}", "x": "t", "y": [metric], "data": trend})
    for c in checks:
        c["detail"] = "exact reconciliation"
    asked = parse_question(question, d, roles)["direction"] if question else None
    return jsonable({
        "asked_direction": asked, "metric": metric, "date_column": date, "grain": grain, "current": str(cur), "previous": str(prev), "direction": direction, "mode": mode,
        "totals": {"current": fb.value(r1), "previous": fb.value(r0), "change": total, "change_pct": fb.value(pct), "facts": [r0, r1, delta, pct]},
        "dimensions": dim_results, "cells": cells, "drivers": drivers, "seasonality": season, "factors": factors, "offsets": offsets,
        "facts": fb.facts, "verification": verification, "charts": charts,
        "reconciliation": checks,
        "complete_current_period": bool(_complete(d.drop(columns=["__p__"]), date, grain, cur)),
    })
