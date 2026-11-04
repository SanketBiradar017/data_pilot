import pandas as pd

from backend.app.analytics.nl2sql import parse_spec, spec_sql
from backend.app.analytics.question import apply_filters, clarification, explain_empty, prepare, resolve_followup
from backend.tests.accuracy.test_chat_accuracy import messy


def df_():
    return messy(7)


def test_value_year_month_and_numeric_filters_are_extracted():
    df = df_()
    f = {x["op"]: x for x in prepare("total revenue for Toys in March 2023 where units above 5", df)["filters"]}
    assert f["in"]["value"] == ["Toys"] and f["year"]["value"] == [2023] and f["month"]["value"] == [3]
    assert f[">"]["col"] == "units" and f[">"]["value"] == 5
    assert prepare("revenue above 1.5 lakh", df)["filters"][0]["value"] == 150000
    # the filter is real: only matching rows are used
    spec = parse_spec("count of records in North in 2023", df)
    n = len(df[(df.region == "North") & (df.order_date.dt.year == 2023)])
    assert len(apply_filters(df, spec["filters"])) == n


def test_column_word_that_is_also_a_value_is_not_a_filter():
    df = pd.DataFrame({"dept": ["Sales", "Ops"] * 10, "sales": range(20)})
    assert prepare("total sales by dept", df)["filters"] == []
    assert prepare("total sales for Sales", df)["filters"][0]["value"] == ["Sales"]


def test_unknown_column_is_reported_not_substituted():
    df = df_()
    p = prepare("total headcount by region", df)
    assert p["missing"] == ["headcount"]
    c = clarification(p, df)
    assert "headcount" in c["message"] and "region" in c["columns"]
    assert prepare("predict churn next month", df)["missing"] == ["churn"]
    assert prepare("average order value", df)["missing"]  # order_id is a label, not a measure


def test_unknown_category_value_is_reported():
    df = df_()
    p = prepare("total revenue for Furniture", df)
    assert p["unknown_values"] == ["Furniture"]
    assert clarification(prepare("revenue for Norht", df), df)["suggestions"]["Norht"] == ["North"]
    assert not prepare("revenue for Toys", df)["unknown_values"]


def test_typos_and_synonyms_are_repaired_with_a_note():
    df = df_()
    p = prepare("average revnue by regon", df)
    assert not p["missing"] and len(p["notes"]) == 2
    s = prepare("total sales by quarter", df)
    assert not s["missing"] and any("sales" in n for n in s["notes"])
    assert parse_spec("total sales by region", df)["metric"] == "revenue"


def test_profit_is_derived_only_when_revenue_and_cost_exist():
    df = df_()
    spec = parse_spec("total profit by region", df)
    assert spec["metric_expr"] == {"rev": "revenue", "cost": "cost"} and "revenue" in spec_sql(spec, "t")
    assert prepare("total profit", df.drop(columns="cost"))["missing"] == ["profit"]


def test_relative_dates_are_flagged_not_guessed():
    p = prepare("revenue last month", df_())
    assert any("Relative dates" in n for n in p["notes"]) and not any(f["op"] in ("year", "month") for f in p["filters"])


def test_empty_filter_explains_itself():
    df = df_()
    f = prepare("revenue in 2030", df)["filters"]
    assert len(apply_filters(df, f)) == 0 and "covers 2022-03-01" in explain_empty(df, f)


FOLLOWUPS = [
    ("total revenue by region", "what about category?", "total revenue by category"),
    ("total revenue by region", "only North", "total revenue by region in North"),
    ("total revenue by region in North", "and South?", "total revenue by region in South"),
    ("total revenue by region", "now by month", "total revenue by month"),
    ("average revenue by category", "and the total?", "total revenue by category"),
    ("total revenue by region in 2023", "remove the filters", "total revenue by region"),
    ("how many customers", "by region?", "number of customer_id by region"),
    ("top 3 category by total revenue", "what about cost?", "top 3 category by total cost"),
]


def test_followups_are_merged_into_the_previous_meaning():
    df = df_()
    for prev, q, want in FOLLOWUPS:
        r = resolve_followup(q, df, prev)
        assert r["followup"] and r["question"] == want, (prev, q, r)


def test_standalone_questions_are_left_alone():
    df = df_()
    for q in ("total cost by category", "how many rows", "average units per region in 2023"):
        assert resolve_followup(q, df, "total revenue by region") == {"question": q, "followup": False, "note": None}
    assert resolve_followup("what about South?", df, None)["followup"] is False


def test_why_and_forecast_followups_keep_the_subject():
    df = df_()
    r = resolve_followup("why did it drop in March?", df, "total revenue by month")
    assert r["followup"] and "revenue" in r["question"]
    r = resolve_followup("forecast it", df, "total revenue in North")
    assert "revenue" in r["question"] and "North" in r["question"]


def test_every_term_in_a_list_is_checked():
    df = df_()
    assert prepare("total profit by region and headcount", df)["missing"] == ["headcount"]
    assert prepare("total revenue and shift by region", df)["missing"] == ["shift"]
    assert not prepare("total revenue and cost by region and category", df)["missing"]


def test_headcount_is_not_a_count_request():
    spec = parse_spec("total revenue by region and headcount", df_())
    assert spec["agg"] == "SUM" and spec["kind"] == "group_agg"
