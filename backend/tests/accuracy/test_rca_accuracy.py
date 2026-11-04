"""Differential tests: Root Cause results must equal a brute-force recomputation on random messy data."""
import pandas as pd
import pytest

from backend.app.analytics.root_cause import run_root_cause
from backend.tests.accuracy import oracle as o

SEEDS = list(range(12))
GRAINS = ["month", "month", "week", "quarter"]


def pick_periods(df, grain):
    keys = sorted({o.period_key(t, grain) for t in df["order_date"].dropna()})
    for cur in reversed(keys):
        if o.prev_key(cur, grain) in keys:
            return cur, o.prev_key(cur, grain)
    pytest.skip("no consecutive periods")


def period_str(k, grain):
    return {"month": f"{k[0]}-{k[1]:02d}", "quarter": f"{k[0]}Q{k[1]}", "year": str(k[0]), "week": None}[grain] if grain != "week" else None


@pytest.mark.parametrize("seed", SEEDS)
def test_totals_and_dimension_contributions_match_bruteforce(seed):
    grain = GRAINS[seed % len(GRAINS)]
    df = o.make_messy(seed, n_days=400 if grain in ("quarter", "week") else 220)
    cur, prev = pick_periods(df, grain)
    cur_s = pd.Period(pd.Timestamp(*cur[:3]) if grain == "week" else (pd.Timestamp(cur[0], cur[1] * (3 if grain == "quarter" else 1) - (2 if grain == "quarter" else 0), 1)), freq={"month": "M", "quarter": "Q", "week": "W"}[grain])
    res = run_root_cause(df, "t", metric="revenue", grain=grain, current=str(cur_s))
    R0, R1 = o.bf_totals(df, "revenue", grain, cur, prev)[1], o.bf_totals(df, "revenue", grain, cur, prev)[0]
    t = res["totals"]
    assert t["previous"] == pytest.approx(R0, abs=1e-6) and t["current"] == pytest.approx(R1, abs=1e-6)
    assert t["change"] == pytest.approx(R1 - R0, abs=1e-6)
    for dm in res["dimensions"]:
        exp = o.bf_group_change(df, "revenue", dm["dimension"], grain, cur, prev)
        assert sum(v[2] for v in exp.values()) == pytest.approx(R1 - R0, abs=1e-6), "oracle sanity"
        for g in dm["top"]:
            assert g["group"] in exp, f"{dm['dimension']}: unknown group {g['group']}"
            e0, e1, ed = exp[g["group"]]
            assert (g["previous"], g["current"], g["change"]) == pytest.approx((e0, e1, ed), abs=1e-6)
        # top list must be the true largest movers, in order
        want = sorted(exp.items(), key=lambda kv: -abs(kv[1][2]))[: len(dm["top"])]
        assert [round(abs(g["change"]), 6) for g in dm["top"]] == pytest.approx([round(abs(v[2]), 6) for _, v in want], abs=1e-6)
    assert all(c["passed"] for c in res["reconciliation"]), res["reconciliation"]
    assert all(v["verified"] for v in res["verification"].values())


@pytest.mark.parametrize("seed", SEEDS[:8])
def test_volume_mix_price_matches_bruteforce(seed):
    df = o.make_messy(seed + 100, n_days=220)
    cur, prev = pick_periods(df, "month")
    res = run_root_cause(df, "t", metric="revenue", grain="month", current=f"{cur[0]}-{cur[1]:02d}")
    d = res["drivers"]
    # overall effects by definition
    Q1 = sum(r["quantity"] for r in o.rows(df) if not o.isnan(r["revenue"]) and not o.isnan(r["order_date"]) and o.period_key(r["order_date"], "month") == cur)
    Q0 = sum(r["quantity"] for r in o.rows(df) if not o.isnan(r["revenue"]) and not o.isnan(r["order_date"]) and o.period_key(r["order_date"], "month") == prev)
    R0, R1 = o.bf_totals(df, "revenue", "month", cur, prev)[1], o.bf_totals(df, "revenue", "month", cur, prev)[0]
    assert d["volume_effect"] == pytest.approx((Q1 - Q0) * R0 / Q0, rel=1e-9, abs=1e-6)
    vol, mix, price = o.bf_pvm(df, "revenue", "quantity", d["mix_dimension"], "month", cur, prev)
    assert d["mix_effect"] == pytest.approx(mix, abs=1e-6) and d["like_for_like_price_effect"] == pytest.approx(price, abs=1e-6)
    assert d["volume_effect"] + d["mix_effect"] + d["like_for_like_price_effect"] == pytest.approx(R1 - R0, abs=1e-6)
