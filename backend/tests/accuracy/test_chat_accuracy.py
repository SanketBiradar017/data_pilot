"""Chat answers: the SQL we generate must agree with an independent pandas computation for every phrasing,
with missing values in measures and in labels, and every question must survive being rewritten for a follow-up."""
import numpy as np
import pandas as pd
import pytest

from backend.app.analytics.nl2sql import parse_spec, spec_sql
from backend.app.analytics.question import render_question, verify_spec
from backend.app.analytics.sql_engine import run_query


def messy(seed: int, n: int = 300) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({
        "order_id": np.arange(n), "customer_id": rng.integers(1, 40, n).astype(str),
        "order_date": pd.date_range("2022-03-01", periods=n, freq="D"),
        "region": rng.choice(["North", "South", "East", None], n), "category": rng.choice(["Electronics", "Toys", "Home"], n),
        "units": rng.integers(1, 9, n)})
    df["revenue"] = df.units * 20 + rng.normal(0, 3, n)
    df.loc[rng.choice(n, 30, replace=False), "revenue"] = np.nan
    df["cost"] = df.revenue * 0.6 + rng.normal(0, 1, n)
    return df


AGGS = ["total", "average", "maximum", "minimum", "median"]
BASE = [f"{a} {m}{b}" for a in AGGS for m in ("revenue", "cost", "profit") for b in ("", " by region", " by category", " by month", " by quarter")]
BASE += ["top 3 category by total revenue", "bottom 2 region by average cost", "top 5 rows by revenue", "count of records",
         "count of records by region", "number of customer_id", "number of customer_id by category", "number of customer_id by month"]
FILTERS = ["", " in North", " in North and South", " in 2023", " in March 2023", " in Q2", " where revenue above 100",
           " in Toys in 2022", " where units at most 3"]
KEYS = ["kind", "agg", "metric", "group", "grain", "limit", "distinct"]


@pytest.mark.parametrize("seed,flt", [(0, f) for f in FILTERS] + [(1, ""), (1, " in North and South"), (2, " in Q2")])
def test_generated_sql_matches_pandas_and_roundtrips(seed, flt):
    df = messy(seed)
    for b in BASE:
        q = b + flt
        spec = parse_spec(q, df)
        res = run_query({"t": df}, spec_sql(spec, "t"))["dataframe"]
        ok, detail = verify_spec(df, spec, res)
        assert ok, f"{q!r}: {detail}"
        again = parse_spec(render_question(spec), df)
        assert {k: spec[k] for k in KEYS} == {k: again[k] for k in KEYS} and spec["filters"] == again["filters"], q


def test_verifier_catches_a_wrong_number():
    df = messy(0)
    spec = parse_spec("total revenue by region", df)
    res = run_query({"t": df}, spec_sql(spec, "t"))["dataframe"].copy()
    res.iloc[0, 1] = res.iloc[0, 1] * 1.01
    assert verify_spec(df, spec, res)[0] is False
    res2 = run_query({"t": df}, spec_sql(spec, "t"))["dataframe"].iloc[:-1]
    assert verify_spec(df, spec, res2)[0] is False  # a missing group is also an error


def test_identifiers_are_counted_never_summed():
    df = messy(0)
    for q in ("how many customers", "total orders", "how many orders"):
        spec = parse_spec(q, df)
        assert spec["kind"] == "count" and spec["distinct"] in ("customer_id", "order_id"), q
    assert run_query({"t": df}, spec_sql(parse_spec("how many customers", df), "t"))["rows"][0]["unique_customer_id"] == df.customer_id.nunique()


def test_missing_values_are_not_silently_dropped_or_invented():
    df = messy(0)
    by_region = run_query({"t": df}, spec_sql(parse_spec("total revenue by region", df), "t"))["rows"]
    assert any(r["region"] is None for r in by_region)  # the blank-region group is reported, not dropped
    avg = run_query({"t": df}, spec_sql(parse_spec("average revenue", df), "t"))["rows"][0]
    assert avg["rows"] == len(df) and avg["avg_revenue"] == pytest.approx(df.revenue.mean())  # NaN ignored, not zero
