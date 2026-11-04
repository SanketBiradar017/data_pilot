import numpy as np
import pandas as pd

from backend.app.analytics.cleaning import apply_operation
from backend.app.analytics.nl2sql import heuristic_sql
from backend.app.analytics.profiling import profile_dataframe
from backend.app.analytics.quality import quality_report
from backend.app.analytics.sql_engine import run_query
from backend.app.analytics.statistics import anomalies, correlations, trends
from backend.app.analytics.utils import jsonable


def messy():
    return pd.DataFrame({"id": range(40), "name": [" Bob ", "bob", "Alice"] * 13 + [None],
                         "v": [1.0, None] * 20, "d": ["2024-01-01"] * 40})


def test_profile_counts(sales_df):
    p = profile_dataframe(sales_df)
    assert p["rows"] == len(sales_df)
    assert "revenue" in p["numeric_columns"] and "order_id" not in p["numeric_columns"]
    assert next(c for c in p["column_profiles"] if c["name"] == "revenue")["histogram"]


def test_quality_flags_issues():
    q = quality_report(messy())
    types = {i["type"] for i in q["issues"]}
    assert {"missing_values", "whitespace"} <= types
    assert 0 <= q["score"] <= 100


def test_cleaning_ops():
    df = messy()
    out, _ = apply_operation(df, "trim_whitespace")
    assert out["name"].dropna().str.strip().eq(out["name"].dropna()).all()
    out, _ = apply_operation(df, "fill_missing", "v", "mean")
    assert out["v"].isna().sum() == 0
    out, msg = apply_operation(pd.concat([df, df]), "drop_duplicates")
    assert len(out) == len(df)
    out, _ = apply_operation(df, "infer_types")
    assert pd.api.types.is_datetime64_any_dtype(out["d"])


def test_trend_and_correlation_and_anomaly(sales_df):
    t = trends(sales_df)
    assert next(x for x in t if x["metric"] == "revenue")["direction"] == "up"
    a = anomalies(sales_df)
    assert any(x["column"] == "revenue" for x in a)
    c = correlations(sales_df)
    assert any({p["a"], p["b"]} == {"units", "revenue"} for p in c["pairs"])


def test_nl2sql_executes_correctly(sales_df):
    g = heuristic_sql("total revenue by region", "sales", sales_df)
    res = run_query({"sales": sales_df}, g["sql"])
    expected = sales_df.groupby("region")["revenue"].sum()
    for row in res["rows"]:
        assert abs(row[res["columns"][1]] - expected[row["region"]]) < 1e-6
    g = heuristic_sql("top 2 category by revenue", "sales", sales_df)
    assert "LIMIT 2" in g["sql"] and run_query({"sales": sales_df}, g["sql"])["row_count"] == 2
    g = heuristic_sql("monthly revenue trend", "sales", sales_df)
    assert "DATE_TRUNC" in g["sql"] and run_query({"sales": sales_df}, g["sql"])["row_count"] > 3
    g = heuristic_sql("how many rows", "sales", sales_df)
    assert run_query({"sales": sales_df}, g["sql"])["rows"][0]["row_count"] == len(sales_df)


def test_jsonable_handles_nan():
    assert jsonable({"a": np.nan, "b": np.int64(3), "c": pd.Timestamp("2024-01-01")}) == {"a": None, "b": 3, "c": "2024-01-01T00:00:00"}
