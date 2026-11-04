"""Executive summary and scenario numbers vs a row-by-row brute-force computation on messy data."""
import random

import pytest

from backend.app.analytics.executive import run_executive_summary
from backend.app.analytics.scenario import run_scenarios
from backend.tests.accuracy import oracle as o

SEEDS = list(range(10))


def kpi(res, label):
    return next(k for k in res["kpis"] if k["label"] == label)


@pytest.mark.parametrize("seed", SEEDS)
def test_executive_kpis_match_bruteforce(seed):
    df = o.make_messy(seed + 300, n_days=200)
    res = run_executive_summary(df, "t", "demo")
    R = [r for r in o.rows(df) if not o.isnan(r["revenue"])]
    C = [r for r in o.rows(df) if not o.isnan(r["cost"])]
    P = [r for r in o.rows(df) if not o.isnan(r["revenue"]) and not o.isnan(r["cost"])]
    assert kpi(res, "revenue")["value"] == pytest.approx(sum(r["revenue"] for r in R), abs=1e-6)
    assert kpi(res, "cost")["value"] == pytest.approx(sum(r["cost"] for r in C), abs=1e-6)
    assert kpi(res, "profit")["value"] == pytest.approx(sum(r["revenue"] - r["cost"] for r in P), abs=1e-6)   # paired rows only
    assert kpi(res, "records")["value"] == len(df)
    assert res["data_notes"] and "rows that have both revenue and cost" in res["data_notes"][0]
    # period KPIs
    grain = res["grain"]
    cur_s = res["period"]
    cur = (int(cur_s[:4]), int(cur_s[5:7]))
    prev = o.prev_key(cur, "month")
    assert grain == "month"
    rc, rp = o.bf_totals(df, "revenue", "month", cur, prev)
    assert kpi(res, "revenue")["period_value"] == pytest.approx(rc, abs=1e-6)
    assert kpi(res, "revenue")["change_pct"] == pytest.approx((rc - rp) / abs(rp) * 100, rel=1e-9)
    pr = {}
    for r in P:
        k = o.period_key(r["order_date"], "month")
        pr[k] = pr.get(k, 0.0) + r["revenue"] - r["cost"]
    assert kpi(res, "profit")["period_value"] == pytest.approx(pr.get(cur, 0.0), abs=1e-6)
    assert kpi(res, "profit")["change_pct"] == pytest.approx((pr.get(cur, 0.0) - pr[prev]) / abs(pr[prev]) * 100, rel=1e-9)
    assert all(v["verified"] for v in res["verification"].values())


def bf_scenario(df, p, v, e, c, phi, seg=None, scope_rows=None):
    """Row-by-row simulation (paired rows only)."""
    rev = cost = qty = brev = bcost = bqty = 0.0
    fv = max(0.0, (1 + v / 100) * (1 + e * p / 100))
    for r in o.rows(df):
        if o.isnan(r["revenue"]) or o.isnan(r["cost"]):
            continue
        brev += r["revenue"]; bcost += r["cost"]; bqty += 0.0 if o.isnan(r["quantity"]) else r["quantity"]
        inside = seg is None or r[seg[0]] in seg[1]
        q_ = 0.0 if o.isnan(r["quantity"]) else r["quantity"]
        if inside:
            rev += r["revenue"] * (1 + p / 100) * fv
            cost += r["cost"] * ((1 - phi / 100) * fv + phi / 100) * (1 + c / 100)
            qty += q_ * fv
        else:
            rev += r["revenue"]; cost += r["cost"]; qty += q_
    return {"base": (brev, bcost, brev - bcost, bqty), "scn": (rev, cost, rev - cost, qty)}


@pytest.mark.parametrize("seed", SEEDS)
def test_scenario_matches_bruteforce(seed):
    rnd = random.Random(seed)
    df = o.make_messy(seed + 500, n_days=120)
    p, v, e = rnd.choice([-20, -10, 0, 5, 10, 25]), rnd.choice([-15, 0, 0, 8]), rnd.choice([0, -0.8, -1.5, 0.3])
    c, phi = rnd.choice([0, 5, -3, 12]), rnd.choice([0, 30, 100])
    seg = ("category", ["Alpha", "Beta"]) if seed % 2 else None
    sc = {"price_change_pct": p, "volume_change_pct": v, "elasticity": e, "cost_change_pct": c, "fixed_cost_pct": phi,
          **({"segment": {"column": seg[0], "values": seg[1]}} if seg else {})}
    r = run_scenarios(df, "t", [sc], revenue="revenue", cost="cost", quantity="quantity", group_by="region")
    exp = bf_scenario(df, p, v, e, c, phi, seg)
    val = {f["id"]: f["value"] for f in r["facts"]}
    ob, f = r["observed"], r["scenarios"][0]["facts"]
    assert (val[ob["revenue"]], val[ob["cost"]], val[ob["profit"]], val[ob["quantity"]]) == pytest.approx(exp["base"], abs=1e-6)
    assert (val[f["revenue"]], val[f["cost"]], val[f["profit"]], val[f["quantity"]]) == pytest.approx(exp["scn"], abs=1e-6)
    assert val[f["profit_change"]] == pytest.approx(exp["scn"][2] - exp["base"][2], abs=1e-6)
    if exp["base"][2]:
        assert val[f["profit_change_pct"]] == pytest.approx((exp["scn"][2] - exp["base"][2]) / abs(exp["base"][2]) * 100, rel=1e-9)
    # breakdown by group must add up to the totals
    bd = r["scenarios"][0]["breakdown"]
    assert sum(x["scenario_revenue"] for x in bd) == pytest.approx(exp["scn"][0], abs=1e-6)
    assert sum(x["baseline_profit"] for x in bd) == pytest.approx(exp["base"][2], abs=1e-6)
    assert r["data_notes"], "rows with missing revenue/cost must be disclosed"
    assert all(v_["verified"] for v_ in r["verification"].values())
    assert all(x["estimate"] for x in r["facts"] if x["id"] in f.values()) and not any(x.get("estimate") for x in r["facts"] if x["id"] in ob.values())
