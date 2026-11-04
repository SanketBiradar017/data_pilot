"""Independent brute-force oracle: plain Python loops over rows, no pandas groupby / SQL / shared helpers."""
import datetime as dt
import math
from collections import defaultdict

import numpy as np
import pandas as pd


def make_messy(seed: int, n_days: int = 150, start: str = "2024-01-01", with_nan: bool = True, with_time: bool = True) -> pd.DataFrame:
    """Random business data with deliberately awkward features: NaN labels/metrics, lost & new groups, negatives, time-of-day, duplicates."""
    rng = np.random.default_rng(seed)
    n = int(rng.integers(300, 900))
    base = pd.Timestamp(start)
    days = rng.integers(0, n_days, n)
    secs = rng.integers(0, 86400, n) if with_time else np.zeros(n, dtype=int)
    dates = base + pd.to_timedelta(days, unit="D") + pd.to_timedelta(secs, unit="s")
    regions = rng.choice(["North", "South", "East", "West"], n, p=[.4, .3, .2, .1]).astype(object)
    cats = rng.choice(["Alpha", "Beta", "Gamma", "Delta", "Eps"], n).astype(object)
    qty = rng.integers(1, 12, n).astype(float)
    price = np.round(rng.uniform(5, 90, n), 2)
    price[cats == "Gamma"] *= 3
    rev = np.round(qty * price, 2)
    refund = rng.random(n) < 0.03
    rev[refund] *= -1                                        # refunds -> negative revenue
    cost = np.round(rev * rng.uniform(0.4, 0.8, n), 2)
    df = pd.DataFrame({"order_date": dates, "region": regions, "category": cats, "quantity": qty, "revenue": rev, "cost": cost,
                       "customer_id": rng.integers(1, 60, n)})
    # group lifecycle: Eps only sells early, Delta only late (lost / new groups)
    day_idx = (df["order_date"] - base).dt.days
    df.loc[(df["category"] == "Eps") & (day_idx > n_days * 0.55), "category"] = "Alpha"
    df.loc[(df["category"] == "Delta") & (day_idx < n_days * 0.45), "category"] = "Beta"
    if with_nan:
        df.loc[rng.random(n) < 0.04, "region"] = None
        df.loc[rng.random(n) < 0.03, "category"] = None
        df.loc[rng.random(n) < 0.03, "revenue"] = np.nan
    return pd.concat([df, df.sample(15, random_state=seed)], ignore_index=True)   # duplicates


def period_key(ts, grain: str):
    d = ts.date() if hasattr(ts, "date") else ts
    if grain == "month":
        return (d.year, d.month)
    if grain == "quarter":
        return (d.year, (d.month - 1) // 3 + 1)
    if grain == "year":
        return (d.year,)
    if grain == "week":
        iso = d - dt.timedelta(days=d.weekday())             # Monday start
        return (iso.year, iso.month, iso.day)
    return (d.year, d.month, d.day)


def prev_key(k, grain: str):
    if grain == "month":
        y, m = k
        return (y, m - 1) if m > 1 else (y - 1, 12)
    if grain == "quarter":
        y, qn = k
        return (y, qn - 1) if qn > 1 else (y - 1, 4)
    if grain == "year":
        return (k[0] - 1,)
    if grain == "week":
        return period_key(dt.date(*k) - dt.timedelta(days=7), "week")
    return period_key(dt.date(*k) - dt.timedelta(days=1), "day")


def rows(df: pd.DataFrame):
    return df.to_dict("records")


def isnan(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v))


def bf_totals(df, metric, grain, cur_key, prev_key_):
    """Totals per period computed row by row (NaN metric rows skipped, like SQL SUM)."""
    tot = defaultdict(float)
    for r in rows(df):
        if isnan(r["order_date"]) or isnan(r[metric]):
            continue
        tot[period_key(r["order_date"], grain)] += r[metric]
    return tot.get(cur_key, 0.0), tot.get(prev_key_, 0.0)


def bf_group_change(df, metric, dim, grain, cur_key, prev_key_):
    g0, g1 = defaultdict(float), defaultdict(float)
    for r in rows(df):
        if isnan(r[metric]) or isnan(r["order_date"]):
            continue
        k = period_key(r["order_date"], grain)
        label = "(blank)" if isnan(r[dim]) else str(r[dim])
        if k == cur_key:
            g1[label] += r[metric]
        elif k == prev_key_:
            g0[label] += r[metric]
    names = set(g0) | set(g1)
    return {n: (g0.get(n, 0.0), g1.get(n, 0.0), g1.get(n, 0.0) - g0.get(n, 0.0)) for n in names}


def bf_pvm(df, metric, qty, dim, grain, cur_key, prev_key_):
    """Volume / mix / price for each group, summed (formulas from first principles)."""
    R0, R1, Q0, Q1 = (defaultdict(float) for _ in range(4))
    for r in rows(df):
        if isnan(r[metric]) or isnan(r["order_date"]) or isnan(r[qty]):
            continue
        k = period_key(r["order_date"], grain)
        label = "(blank)" if isnan(r[dim]) else str(r[dim])
        q = r[qty]
        if k == cur_key:
            R1[label] += r[metric]; Q1[label] += q
        elif k == prev_key_:
            R0[label] += r[metric]; Q0[label] += q
    qt0, qt1 = sum(Q0.values()), sum(Q1.values())
    vol = mix = price = 0.0
    for g in set(R0) | set(R1):
        p0 = R0[g] / Q0[g] if Q0[g] else (R1[g] / Q1[g] if Q1[g] else 0.0)
        p1 = R1[g] / Q1[g] if Q1[g] else p0
        s0, s1 = (Q0[g] / qt0 if qt0 else 0.0), (Q1[g] / qt1 if qt1 else 0.0)
        vol += (qt1 - qt0) * s0 * p0
        mix += qt1 * (s1 - s0) * p0
        price += Q1[g] * (p1 - p0)
    return vol, mix, price
