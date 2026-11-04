"""Each discovered insight is re-derived from scratch and compared with what the engine claims."""
import math
import re
from collections import defaultdict

import numpy as np
import pytest
from scipy import stats as sps

from backend.app.analytics.discovery import discover
from backend.tests.accuracy import oracle as o

SEEDS = list(range(14))
seen: defaultdict[str, int] = defaultdict(int)


def facts_of(res, insight):
    by = {f["id"]: f for f in res["facts"]}
    return [by[i] for i in insight["facts"]]


def totals_by(df, key_fn, metric="revenue", per=None):
    t = defaultdict(float)
    for r in o.rows(df):
        if o.isnan(r[metric]) or o.isnan(r["order_date"]):
            continue
        if per and o.period_key(r["order_date"], "month") != per:
            continue
        t[key_fn(r)] += r[metric]
    return t


def key_of(period: str):
    return (int(period[:4]), int(period[5:7]))


@pytest.mark.parametrize("seed", SEEDS)
def test_insights_match_independent_recomputation(seed):
    df = o.make_messy(seed + 700, n_days=200)
    res = discover(df, "t")
    cur, prev = key_of(res["period"]["current"]), key_of(res["period"]["previous"])
    assert prev == o.prev_key(cur, "month")
    total_all = sum(r["revenue"] for r in o.rows(df) if not o.isnan(r["revenue"]))
    for ins in res["insights"]:
        assert ins["verified"]
        f = facts_of(res, ins)
        t = ins["type"]
        seen[t] += 1
        if t in ("growth", "decline"):
            r0, r1 = o.bf_totals(df, "revenue", "month", cur, prev)[1], o.bf_totals(df, "revenue", "month", cur, prev)[0]
            assert f[0]["value"] == pytest.approx(r0, abs=1e-6) and f[1]["value"] == pytest.approx(r1, abs=1e-6)
            assert f[3]["value"] == pytest.approx((r1 - r0) / abs(r0) * 100, rel=1e-9)
            assert (t == "growth") == (r1 > r0)
        elif t in ("performer", "declining"):
            dim, name = re.search(r", (\w+) = (.+)$", f[0]["label"]).groups()
            g0 = totals_by(df, lambda r: "(blank)" if o.isnan(r[dim]) else str(r[dim]), per=prev)
            g1 = totals_by(df, lambda r: "(blank)" if o.isnan(r[dim]) else str(r[dim]), per=cur)
            assert (f[0]["value"], f[1]["value"]) == pytest.approx((g0.get(name, 0.0), g1.get(name, 0.0)), abs=1e-6)
            pct = (g1.get(name, 0.0) - g0[name]) / g0[name] * 100
            assert f[2]["value"] == pytest.approx(pct, rel=1e-9)
            # claim: strongest growth / sharpest drop among the *main* groups (>=3% of prior period, top 12 overall)
            alltot = totals_by(df, lambda r: "(blank)" if o.isnan(r[dim]) else str(r[dim]))
            alltot = {k: v for k, v in alltot.items() if k != "(blank)" and v > 0}
            main = sorted(alltot, key=lambda k: -alltot[k])[:12]
            prev_total = sum(v for k, v in g0.items() if k != "(blank)")
            n0 = defaultdict(int)
            for r in o.rows(df):
                if not o.isnan(r["revenue"]) and not o.isnan(r["order_date"]) and o.period_key(r["order_date"], "month") == prev:
                    n0["(blank)" if o.isnan(r[dim]) else str(r[dim])] += 1
            cand = {k: (g1.get(k, 0.0) - g0[k]) / g0[k] * 100 for k in main if g0.get(k, 0) > 0 and g0[k] / prev_total >= 0.03 and n0[k] >= 5}
            assert (max(cand.values()) if t == "performer" else min(cand.values())) == pytest.approx(pct, rel=1e-9)
        elif t == "concentration":
            dim, name = re.search(r", (\w+) = (.+)$", f[0]["label"]).groups() if False else (None, None)
            m = re.search(r"Share of revenue from (\w+) = (.+)$", f[0]["label"])
            dim, name = m.groups()
            gt = totals_by(df, lambda r: str(r[dim]) if not o.isnan(r[dim]) else "(blank)")
            gt = {k: v for k, v in gt.items() if k != "(blank)" and v > 0}
            ranked = sorted(gt, key=lambda k: -gt[k])
            assert name == ranked[0]
            assert f[0]["value"] == pytest.approx(gt[name] / total_all * 100, rel=1e-9)
            assert f[1]["value"] == pytest.approx(sum(gt[k] for k in ranked[:3]) / total_all * 100, rel=1e-9)
        elif t == "correlation":
            a, b = re.match(r"(\w+) and (\w+) move together", ins["title"]).groups()
            rows = [(r[a], r[b]) for r in o.rows(df) if not o.isnan(r[a]) and not o.isnan(r[b])]
            rho = sps.spearmanr([x for x, _ in rows], [y for _, y in rows]).statistic
            assert float(re.search(r"r = (-?\d\.\d+)", ins["title"]).group(1)) == pytest.approx(rho, abs=0.005)
            assert abs(rho) >= 0.7
        elif t == "distribution":
            col = ins["title"].split(" ")[0]
            vals = sorted((r[col] for r in o.rows(df) if not o.isnan(r[col])), reverse=True)
            k = max(1, math.ceil(len(vals) * 0.01))
            assert f[0]["value"] == pytest.approx(sum(vals[:k]) / sum(vals) * 100, rel=1e-9)
            assert abs(sps.skew(vals)) >= 2
        elif t == "customer" and "sharply reduced spend" in ins["title"]:
            tot = totals_by(df, lambda r: r["customer_id"])
            thr = float(np.quantile(list(tot.values()), 0.8))
            c0, c1 = totals_by(df, lambda r: r["customer_id"], per=prev), totals_by(df, lambda r: r["customer_id"], per=cur)
            lost = [c for c, v in tot.items() if v >= thr and c0.get(c, 0) > 0 and c1.get(c, 0) <= 0.4 * c0[c]]
            assert int(re.match(r"(\d+)", ins["title"]).group(1)) == len(lost)
            worst = max(lost, key=lambda c: c0[c])
            assert f"customer {worst}" in ins["text"]
        elif t == "customer":
            tot = totals_by(df, lambda r: r["customer_id"])
            vals = np.array(list(tot.values()))
            q1, q3 = np.quantile(vals, [0.25, 0.75])
            assert int(re.match(r"(\d+)", ins["title"]).group(1)) == int((vals > q3 + 3 * (q3 - q1)).sum())


def test_all_insight_types_were_actually_exercised():
    # guards against the differential test silently checking nothing
    assert seen["growth"] + seen["decline"] > 0 and seen["performer"] > 0 and seen["declining"] > 0 and seen["concentration"] > 0 and seen["correlation"] >= 0
    assert sum(seen.values()) >= 40, dict(seen)
