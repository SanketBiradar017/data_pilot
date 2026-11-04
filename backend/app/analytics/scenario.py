"""Predictive scenario analysis ("what happens to profit if prices rise 10%?").

Observed baseline numbers are SQL-verified facts. Scenario numbers are ESTIMATES computed from explicit
assumptions (price, volume, elasticity, cost inflation, fixed-cost share, optional segment) and are always
labelled as estimates; they are never mixed with observed data."""
import numpy as np
import pandas as pd
import statsmodels.api as sm

from backend.app.analytics.facts import FactBook, labels, lit, period_cond, q, verify_facts
from backend.app.analytics.roles import detect_roles
from backend.app.analytics.root_cause import _complete, _periods
from backend.app.analytics.utils import infer_types, jsonable
from backend.app.core.exceptions import AppError

DISCLAIMER = ("Scenario figures are model ESTIMATES based on the assumptions shown. They are not observed data and "
              "will differ from reality if customers, competitors or costs behave differently.")


def _seg_sql(col: str, values: list[str]) -> tuple[str, str]:
    vals = ", ".join(lit(v) for v in values)
    return f"{q(col)} IN ({vals})", f"NOT COALESCE({q(col)} IN ({vals}), false)"


def elasticity_hint(df: pd.DataFrame, price: str | None, qty: str | None) -> dict | None:
    """Observed log-log relationship between price and quantity (indicative only)."""
    if not price or not qty or price not in df.columns or qty not in df.columns:
        return None
    d = df[[price, qty]].dropna()
    d = d[(d[price] > 0) & (d[qty] > 0)]
    if len(d) < 30 or d[price].nunique() < 4:
        return {"available": False, "message": "Not enough price variation in the data to estimate how demand responds to price."}
    X = sm.add_constant(np.log(d[price]))
    res = sm.OLS(np.log(d[qty]), X).fit()
    e, pv = float(res.params.iloc[1]), float(res.pvalues.iloc[1])
    if pv >= 0.05:
        return {"available": False, "elasticity": e, "p_value": pv, "message": "No statistically reliable relationship between price and quantity was found in this data."}
    return {"available": True, "elasticity": e, "p_value": pv, "r2": float(res.rsquared), "n": int(len(d)),
            "message": f"In this data, a 1% higher unit price is associated with about {abs(e):.2f}% {'lower' if e < 0 else 'higher'} quantity (observational, not causal)."}


def run_scenarios(df: pd.DataFrame, table: str, scenarios: list[dict], revenue: str | None = None, cost: str | None = None, quantity: str | None = None,
                  date_col: str | None = None, baseline_scope: str = "all", grain: str = "month", group_by: str | None = None, mode: str = "standard") -> dict:
    df = infer_types(df)
    roles = detect_roles(df)
    revenue = revenue or roles["revenue"]
    cost = cost or roles["cost"]
    quantity = quantity or roles["quantity"]
    if not revenue or revenue not in df.columns:
        raise AppError("Choose the revenue column for the scenario")
    for c in (revenue, cost, quantity):
        if c and (c not in df.columns or not pd.api.types.is_numeric_dtype(df[c])):
            raise AppError(f"'{c}' must be a numeric column")
    if not scenarios:
        raise AppError("Add at least one scenario")
    if len(scenarios) > 5:
        raise AppError("At most 5 scenarios can be compared")
    date = date_col or roles["date"]
    base = df
    scope_label, cond = "all data", ""
    if baseline_scope == "latest":
        if not date:
            raise AppError("Baseline 'latest period' needs a date column")
        per = _periods(df.dropna(subset=[date]), date, grain)
        avail = sorted(per.unique())
        cur = avail[-1] if _complete(df.dropna(subset=[date]), date, grain, avail[-1]) or len(avail) < 2 else avail[-2]
        base = df.dropna(subset=[date])[per == cur]
        scope_label, cond = f"{grain} {cur}", period_cond(date, grain, str(cur.start_time.date()))
    fb = FactBook(table, mode, "S")
    data_notes: list[str] = []
    pair = ""
    if cost:  # profit needs revenue and cost for the SAME rows
        ok = base[revenue].notna() & base[cost].notna()
        if not ok.all():
            data_notes.append(f"{int((~ok).sum())} of {len(base)} rows have a missing revenue or cost value and are excluded from this analysis so profit compares like with like.")
            base = base[ok]
        pair = f"{q(revenue)} IS NOT NULL AND {q(cost)} IS NOT NULL"

    def total(col: str, extra: str = "") -> str:
        w = " AND ".join(x for x in (cond, pair, extra) if x)
        return f"SELECT COALESCE(SUM({q(col)}), 0) FROM {table}" + (f" WHERE {w}" if w else "")

    # observed baseline (verified)
    obs = {"revenue": fb.base(f"Observed revenue ({scope_label})", float(base[revenue].sum()), total(revenue), "currency")}
    if cost:
        obs["cost"] = fb.base(f"Observed cost ({scope_label})", float(base[cost].sum()), total(cost), "currency")
        obs["profit"] = fb.derived("Observed profit", "diff", [obs["revenue"], obs["cost"]], "currency")
        obs["margin"] = fb.derived("Observed profit margin", "share", [obs["profit"], obs["revenue"]], "pct")
    if quantity:
        obs["quantity"] = fb.base(f"Observed quantity ({scope_label})", float(base[quantity].sum()), total(quantity), "number")

    out_scn = []
    for k, sc in enumerate(scenarios):
        p = float(sc.get("price_change_pct") or 0)
        v = float(sc.get("volume_change_pct") or 0)
        e = float(sc.get("elasticity") or 0)
        c = float(sc.get("cost_change_pct") or 0)
        phi = float(sc.get("fixed_cost_pct") or 0)
        if not -90 <= p <= 500 or not -100 <= v <= 500 or not -50 <= c <= 500 or not 0 <= phi <= 100 or not -10 <= e <= 10:
            raise AppError("Assumption out of range (price −90…500 %, volume −100…500 %, cost −50…500 %, fixed cost 0…100 %, elasticity −10…10)")
        seg = sc.get("segment") or None
        name = sc.get("name") or f"Scenario {k + 1}"
        if seg and seg.get("column") and seg.get("values"):
            col, vals = seg["column"], [str(x) for x in seg["values"]]
            if col not in df.columns:
                raise AppError(f"Unknown segment column '{col}'")
            mask = base[col].astype(str).isin(vals)
            in_sql, out_sql = _seg_sql(col, vals)
            seg_label = f"{col} in {', '.join(vals)}"
        else:
            mask, in_sql, out_sql, seg_label = pd.Series(True, index=base.index), None, None, "all rows"

        def seg_fact(label, colname, which):
            if in_sql is None:
                return fb.base(label, float(base[colname].sum()) if which == "in" else 0.0, total(colname) if which == "in" else "SELECT 0", "currency")
            m = mask if which == "in" else ~mask
            return fb.base(label, float(base.loc[m, colname].sum()), total(colname, in_sql if which == "in" else out_sql), "currency")

        rm, ro = seg_fact(f"Revenue in scope ({seg_label})", revenue, "in"), seg_fact("Revenue outside scope", revenue, "out")
        srev = fb.derived(f"{name}: estimated revenue", "scn_revenue", [rm, ro], "currency", extra=[p, v, e], estimate=True)
        res_ids = {"revenue": srev}
        if cost:
            cm, co = seg_fact(f"Cost in scope ({seg_label})", cost, "in"), seg_fact("Cost outside scope", cost, "out")
            scost = fb.derived(f"{name}: estimated cost", "scn_cost", [cm, co], "currency", extra=[p, v, e, c, phi], estimate=True)
            res_ids["cost"] = scost
            res_ids["profit"] = fb.derived(f"{name}: estimated profit", "diff", [srev, scost], "currency", estimate=True)
            res_ids["margin"] = fb.derived(f"{name}: estimated profit margin", "share", [res_ids["profit"], srev], "pct", estimate=True)
            res_ids["profit_change"] = fb.derived(f"{name}: profit change vs baseline", "diff", [res_ids["profit"], obs["profit"]], "currency", estimate=True)
            res_ids["profit_change_pct"] = fb.derived(f"{name}: profit change % vs baseline", "pct_change", [res_ids["profit"], obs["profit"]], "pct", estimate=True)
        res_ids["revenue_change"] = fb.derived(f"{name}: revenue change vs baseline", "diff", [srev, obs["revenue"]], "currency", estimate=True)
        res_ids["revenue_change_pct"] = fb.derived(f"{name}: revenue change % vs baseline", "pct_change", [srev, obs["revenue"]], "pct", estimate=True)
        if quantity:
            qm, qo = seg_fact(f"Quantity in scope ({seg_label})", quantity, "in"), seg_fact("Quantity outside scope", quantity, "out")
            res_ids["quantity"] = fb.derived(f"{name}: estimated quantity", "scn_quantity", [qm, qo], "number", extra=[p, v, e], estimate=True)
        vol_factor = max(0.0, (1 + v / 100) * (1 + e * p / 100))
        notes = []
        if p and e == 0 and v == 0:
            notes.append("Assumes volume does not react to the price change (elasticity 0). In practice demand usually falls when prices rise: try an elasticity such as −1.")
        if (1 + v / 100) * (1 + e * p / 100) < 0:
            notes.append("The assumptions imply negative volume; it was floored at zero.")
        if not cost:
            notes.append("No cost column selected, so profit cannot be estimated.")
        # breakdown by group (estimate)
        breakdown = []
        if group_by and group_by in base.columns:
            for gname, gdf in base.groupby(labels(base[group_by]), observed=True):
                gin = mask.loc[gdf.index]
                r0g = float(gdf[revenue].sum())
                r1g = float(gdf.loc[gin, revenue].sum()) * (1 + p / 100) * vol_factor + float(gdf.loc[~gin, revenue].sum())
                row = {"group": str(gname), "baseline_revenue": r0g, "scenario_revenue": r1g}
                if cost:
                    c0g = float(gdf[cost].sum())
                    c1g = float(gdf.loc[gin, cost].sum()) * ((1 - phi / 100) * vol_factor + phi / 100) * (1 + c / 100) + float(gdf.loc[~gin, cost].sum())
                    row.update(baseline_cost=c0g, scenario_cost=c1g, baseline_profit=r0g - c0g, scenario_profit=r1g - c1g)
                breakdown.append(row)
        out_scn.append({"name": name, "segment": seg_label, "assumptions": {"price_change_pct": p, "volume_change_pct": v, "elasticity": e, "cost_change_pct": c, "fixed_cost_pct": phi},
                        "facts": res_ids, "notes": notes, "breakdown": breakdown})

    # sensitivity of the first scenario to the price assumption (estimate)
    sens = []
    s0 = scenarios[0]
    seg0 = s0.get("segment")
    m0 = base[seg0["column"]].astype(str).isin([str(x) for x in seg0["values"]]) if seg0 and seg0.get("column") in base.columns and seg0.get("values") else pd.Series(True, index=base.index)
    Rm, Ro = float(base.loc[m0, revenue].sum()), float(base.loc[~m0, revenue].sum())
    Cm, Co = (float(base.loc[m0, cost].sum()), float(base.loc[~m0, cost].sum())) if cost else (0.0, 0.0)
    e0, v0, c0, phi0 = float(s0.get("elasticity") or 0), float(s0.get("volume_change_pct") or 0), float(s0.get("cost_change_pct") or 0), float(s0.get("fixed_cost_pct") or 0)
    from backend.app.analytics.facts import OPS
    for pp in range(-20, 21, 5):
        rv = OPS["scn_revenue"](Rm, Ro, pp, v0, e0)
        row = {"price_change_pct": pp, "revenue": rv}
        if cost:
            cs = OPS["scn_cost"](Cm, Co, pp, v0, e0, c0, phi0)
            row.update(cost=cs, profit=rv - cs)
        sens.append(row)

    verification = verify_facts(fb.facts, {table: df}, only_key=False)
    for f in fb.facts:
        f["scenario_estimate"] = bool(f.get("estimate"))
    return jsonable({
        "kind": "scenario_estimate", "disclaimer": DISCLAIMER, "baseline_scope": scope_label, "mode": mode,
        "columns": {"revenue": revenue, "cost": cost, "quantity": quantity},
        "observed": obs, "scenarios": out_scn, "sensitivity": sens, "elasticity_hint": elasticity_hint(base, roles["price"], quantity),
        "facts": fb.facts, "verification": verification, "data_notes": data_notes,
    })
