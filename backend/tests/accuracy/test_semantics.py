"""Semantic accuracy: the right question is answered, units/precision are honest, nothing is altered silently."""
import numpy as np
import pandas as pd
import pytest

from backend.app.agents.graph import run_workflow
from backend.app.agents.state import RunContext
from backend.app.analytics.discovery import discover
from backend.app.analytics.facts import FactBook
from backend.app.analytics.roles import detect_roles, is_additive
from backend.app.analytics.root_cause import parse_question, run_root_cause
from backend.app.core.exceptions import AppError
from backend.tests.accuracy import oracle as o


@pytest.fixture(scope="module")
def df():
    return o.make_messy(901, n_days=200)


def test_question_parsing_edge_cases(df):
    roles = detect_roles(df)
    p = lambda q: parse_question(q, df, roles)  # noqa: E731
    assert p("Why did revenue decrease in July?")["month"] == 7
    assert p("Why may revenue have dropped?")["month"] is None                      # "may" the verb is not May
    assert p("Why did sales fall in May?")["month"] == 5
    assert p("Why did revenue drop in July compared with last year?")["grain"] == "month"   # "year" must not flip the grain
    assert p("Why did revenue fall in Q3?")["grain"] == "quarter" and p("why did revenue fall last week")["grain"] == "week"
    assert p("Why did profit fall?")["metric"] == "profit"
    assert p("Why did cost increase in March?")["metric"] == "cost" and p("Why did cost increase in March?")["month"] == 3
    assert p("Why did the number of orders drop?")["unsupported"] == "orders" and p("Why did the number of orders drop?")["metric"] is None
    assert p("Why did the weekend sales drop?")["grain"] == "month"                  # 'weekend' is not 'week'


def test_profit_root_cause_matches_bruteforce(df):
    res = run_root_cause(df, "t", metric="profit", grain="month", current="2024-06")
    cur, prev = (2024, 6), (2024, 5)
    tot = {}
    for r in o.rows(df):
        if o.isnan(r["revenue"]) or o.isnan(r["cost"]):
            continue
        k = o.period_key(r["order_date"], "month")
        tot[k] = tot.get(k, 0.0) + r["revenue"] - r["cost"]
    assert res["totals"]["current"] == pytest.approx(tot[cur], abs=1e-6) and res["totals"]["previous"] == pytest.approx(tot[prev], abs=1e-6)
    assert all(c["passed"] for c in res["reconciliation"]) and all(v["verified"] for v in res["verification"].values())
    assert any('"revenue" - "cost"' in (f.get("sql") or "") for f in res["facts"])      # SQL evidence uses the real profit expression


def test_does_not_silently_substitute_another_metric(df):
    with pytest.raises(AppError, match="not an additive measure"):
        run_root_cause(df, "t", question="Why did the number of orders drop in June?")
    with pytest.raises(AppError, match="cannot be summed"):
        run_root_cause(df.assign(unit_price=3.0), "t", metric="unit_price")
    st = run_workflow(RunContext(question="Why did customers drop in June?", tables={"t": df}))
    assert any("can't explain" in e for e in st["errors"]) and "could not complete" in st["answer"].lower()


def test_ratio_columns_never_chosen_as_default_metric():
    d = pd.DataFrame({"order_date": pd.date_range("2025-01-01", periods=120), "discount_pct": np.linspace(1, 9, 120), "gross_margin": 0.3, "sales": 100.0})
    roles = detect_roles(d)
    assert roles["revenue"] == "sales" and not is_additive("discount_pct") and not is_additive("unit_price") and is_additive("revenue")


def test_small_numbers_are_not_rounded_to_integers():
    fb = FactBook("t", "standard")
    a = fb.base("a", 4.56, "SELECT 1", "currency")
    b = fb.base("b", 0.07, "SELECT 1", "currency")
    c = fb.base("c", 1234.5, "SELECT 1", "currency")
    d = fb.base("d", 999.99999999, "SELECT 1", "currency")
    n = fb.base("n", 1212, "SELECT 1", "count")
    assert (fb.text(a), fb.text(b), fb.text(c), fb.text(d), fb.text(n)) == ("4.56", "0.07", "1,234", "1,000", "1,212")  # noqa: PT018
    assert fb.text(a, True) == "+4.56"


def test_graph_never_alters_the_stored_data():
    d = pd.DataFrame({"order_date": pd.date_range("2025-01-01", periods=90), "region": [" north ", "North", "South"] * 30, "revenue": 10.0})
    before = d.copy()
    ctx = RunContext(question="What is total revenue by region?", tables={"t": d.copy()})
    st = run_workflow(ctx)
    pd.testing.assert_frame_equal(ctx.tables["t"], before)                       # analysed exactly as stored
    regions = {r["region"]: r for r in st["sql"]["rows"]}
    assert " north " in regions and "North" in regions                           # variants stay visible, not silently merged
    assert "nothing altered" in next(t["summary"] for t in st["trace"] if t["agent"] == "cleaning")


def test_label_variants_are_reported_with_exact_counts():
    rng = np.random.default_rng(3)
    d = pd.DataFrame({"order_date": pd.date_range("2025-01-01", periods=200), "revenue": rng.uniform(1, 9, 200),
                      "region": rng.choice(["North", "South"], 200)})
    d.loc[d.index[:17], "region"] = " north "
    d.loc[d.index[17:24], "region"] = "NORTH"
    res = discover(d, "t")
    ins = next(i for i in res["insights"] if i["type"] == "data_quality")
    # canonical spelling is the most common one among the variants of a group
    counts = d["region"].value_counts()
    group = [x for x in counts.index if x.strip().lower() == "north"]
    non_canon = int(counts[group[1:]].sum())
    nn = next(f for f in res["facts"] if f["label"].startswith("Rows in region using a variant"))
    assert nn["value"] == non_canon and ins["verified"] and "region" in ins["title"]
    assert discover(d.assign(region=d.region.str.strip().str.title()), "t")["summary"].get("data_quality") is None


def test_graph_and_api_agree_on_the_same_question(df):
    from backend.app.analytics.root_cause import run_root_cause as api_rc

    st = run_workflow(RunContext(question="Why did revenue change in June 2024?", tables={"t": df}))
    api = api_rc(df, "t", metric="revenue", grain="month", current="2024-06")
    assert st["root_cause"]["totals"]["change"] == pytest.approx(api["totals"]["change"], abs=1e-9)
    assert [d["top"][0]["group"] for d in st["root_cause"]["dimensions"]] == [d["top"][0]["group"] for d in api["dimensions"]]


def test_ambiguous_dates_are_not_silently_swapped():
    from backend.app.analytics.utils import infer_types

    # day > 12 appears in the first position -> unambiguously DD/MM
    dd = pd.DataFrame({"d": ["13/04/2025", "01/05/2025", "20/06/2025"] * 10, "v": range(30)})
    out = infer_types(dd)["d"]
    assert out.iloc[0] == pd.Timestamp("2025-04-13") and out.iloc[1] == pd.Timestamp("2025-05-01")
    # day > 12 in the second position -> unambiguously MM/DD
    mm = pd.DataFrame({"d": ["04/13/2025", "05/01/2025", "06/20/2025"] * 10, "v": range(30)})
    out = infer_types(mm)["d"]
    assert out.iloc[0] == pd.Timestamp("2025-04-13") and out.iloc[1] == pd.Timestamp("2025-05-01")
    # inconsistent column (13/04 and 04/13 both present) is left as text rather than guessed
    bad = pd.DataFrame({"d": ["13/04/2025", "04/13/2025"] * 10, "v": range(20)})
    assert not pd.api.types.is_datetime64_any_dtype(infer_types(bad)["d"])
    # fully ambiguous -> day-first, and ISO is untouched
    amb = pd.DataFrame({"d": ["03/04/2025"] * 20, "v": range(20)})
    assert infer_types(amb)["d"].iloc[0] == pd.Timestamp("2025-04-03")
    iso = pd.DataFrame({"d": ["2025-04-03"] * 20, "v": range(20)})
    assert infer_types(iso)["d"].iloc[0] == pd.Timestamp("2025-04-03")


def test_tiny_groups_are_not_called_performers():
    rng = np.random.default_rng(1)
    rows = []
    for d in pd.date_range("2025-04-01", "2025-05-31"):
        for _ in range(3):
            rows.append({"order_date": d, "product": rng.choice(["Core", "Core2"]), "revenue": float(rng.uniform(50, 60))})
    rows += [{"order_date": pd.Timestamp("2025-04-10"), "product": "Rare", "revenue": 120.0}, {"order_date": pd.Timestamp("2025-05-10"), "product": "Rare", "revenue": 900.0}]
    res = discover(pd.DataFrame(rows), "t")
    assert not any("Rare" in i["title"] for i in res["insights"])


def test_seasonality_prior_year_matches_bruteforce():
    d = o.make_messy(77, n_days=500, start="2023-01-01", with_time=False)
    res = run_root_cause(d, "t", metric="revenue", grain="month", current="2024-04")
    se = res["seasonality"]
    assert se is not None and (se["prior_period"], se["prior_previous"]) == ("2023-04", "2023-03")
    a, b = o.bf_totals(d, "revenue", "month", (2023, 4), (2023, 3))
    assert se["prior_change_pct"] == pytest.approx((a - b) / abs(b) * 100, rel=1e-9)


def test_undefined_values_do_not_crash_and_are_never_printed():
    """Seed 1074 of the soak test: a week with zero quantity makes 'average per unit' undefined."""
    from backend.app.analytics.story import root_cause_story

    df = o.make_messy(1074, n_days=400)
    res = run_root_cause(df, "t", metric="revenue", grain="week", current="2025-02-03/2025-02-09")
    assert all(v["verified"] for v in res["verification"].values())                 # undefined verifies as undefined
    s = root_cause_story(res)
    text = " ".join(x["text"] for x in s["statements"])
    assert "n/a" not in text and "None" not in text and "nan" not in text.lower()
    by = {f["id"]: f for f in res["facts"]}
    assert any(f["value"] is None for f in by.values()), "test no longer exercises the undefined-value path"
