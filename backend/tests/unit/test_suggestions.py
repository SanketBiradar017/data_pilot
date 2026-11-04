"""Suggestions are generated from the data, and every one of them is actually answerable."""
import numpy as np
import pandas as pd
import pytest

from backend.app.agents.graph import run_workflow
from backend.app.agents.state import RunContext
from backend.app.analytics.suggestions import build_suggestions


def monthly(n_months=8, cost=True, extra=None, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for m, mult in enumerate([1.0, 1.1, 1.05, 1.2, 0.9, 1.0, 0.7, 0.8][:n_months]):
        for d in pd.date_range(f"2025-{m + 1:02d}-01", periods=26):
            for region in ("Delhi", "Mumbai", "Pune"):
                for prod in ("Widgets", "Gadgets"):
                    q = float(rng.integers(1, 6)) * mult
                    price = 20.0 if prod == "Widgets" else 45.0
                    row = {"order_date": d, "region": region, "product": prod, "quantity": q, "amount": q * price, "customer_id": int(rng.integers(1, 40))}
                    if cost:
                        row["cost"] = q * price * 0.6
                    rows.append(row)
    df = pd.DataFrame(rows)
    return df.assign(**(extra or {}))


DATASETS = {
    "sales_with_cost": lambda: monthly(),
    "sales_no_cost": lambda: monthly(cost=False),
    "no_date": lambda: monthly().drop(columns=["order_date"]),
    "no_measure": lambda: pd.DataFrame({"city": list("abcabcabcd") * 10, "tier": list("xyxyxyxyxy") * 10}),
    "numeric_only": lambda: pd.DataFrame({"a": np.arange(100.0), "b": np.arange(100.0) ** 2, "c": np.random.default_rng(1).normal(size=100)}),
    "tiny": lambda: pd.DataFrame({"x": [1, 2, 3], "label": ["a", "b", "c"]}),
}


def questions(df, name="data", quality=None):
    return build_suggestions([(name, df, quality)], [])


@pytest.mark.parametrize("name", list(DATASETS))
def test_every_suggestion_is_answered_by_the_workflow(name):
    df = DATASETS[name]()
    sugg = questions(df)
    assert sugg, f"no suggestions for {name}"
    for s in sugg:
        st = run_workflow(RunContext(question=s["question"], tables={"t": df}, table_labels={"t": name}))
        assert st["status"] == "completed" and not st["errors"], (name, s["question"], st["errors"])
        assert st["answer"] and "could not complete" not in st["answer"].lower(), (name, s["question"], st["answer"][:120])


def test_suggestions_change_with_the_data():
    a = [s["question"] for s in questions(monthly())]
    b = [s["question"] for s in questions(monthly(cost=False))]
    c = [s["question"] for s in questions(DATASETS["no_date"]())]
    assert a != b != c
    assert any("amount" in q for q in a) and any("region" in q.lower() or "regions" in q.lower() for q in a)
    assert any("profit" in q for q in a) and not any("profit" in q for q in b)           # profit only when a cost column exists
    assert not any("monthly" in q or "over time" in q or "Why did" in q for q in c)                             # no date -> no time questions
    assert any("Delhi" in q or "Widgets" in q or "Gadgets" in q or "Mumbai" in q or "Pune" in q for q in a)   # real values, not placeholders


def test_why_question_names_the_real_latest_period_and_the_real_direction():
    df = monthly()                                                                       # last month (Aug) is lower than July? check by data
    tot = df.groupby(df.order_date.dt.to_period("M")).amount.sum()
    want = "increase" if tot.iloc[-1] > tot.iloc[-2] else "decrease"
    q = next(s["question"] for s in questions(df) if s["category"] == "Why")
    assert f"Why did amount {want} in August 2025" in q
    df2 = df.assign(amount=df.amount * np.where(df.order_date.dt.month == 8, 3.0, 1.0))  # now August clearly up
    assert "increase in August 2025" in next(s["question"] for s in questions(df2) if s["category"] == "Why")
    df3 = df.assign(amount=df.amount * np.where(df.order_date.dt.month == 8, 0.2, 1.0))
    assert "decrease in August 2025" in next(s["question"] for s in questions(df3) if s["category"] == "Why")


def test_nothing_is_hardcoded_to_july_or_revenue():
    qs = " ".join(s["question"] for s in questions(monthly(3)))          # data covers Jan-Mar only
    assert "July" not in qs and "revenue" not in qs.lower().replace("amount", "")
    assert "March 2025" in qs


def test_quality_question_only_appears_when_there_is_a_problem():
    df = monthly()
    assert not any(s["category"] == "Quality" for s in questions(df, quality=99.0))
    assert any(s["category"] == "Quality" for s in questions(df, quality=71.0))


def test_document_suggestions_use_the_documents_own_topics():
    text = ("Refund policy\n\nCustomers may request a refund within thirty days of purchase. Refund requests need the original receipt.\n\n"
            "Shipping policy\n\nShipping to remote locations requires extra freight charges and additional delivery time.")
    sugg = build_suggestions([], [("handbook", text)])
    assert sugg and all(s["category"] == "Documents" for s in sugg)
    assert any("refund" in s["question"].lower() or "shipping" in s["question"].lower() or "policy" in s["question"].lower() for s in sugg)
    st = run_workflow(RunContext(question=sugg[0]["question"], tables={}, documents={"handbook": text}))
    assert st["status"] == "completed" and st["research"]["citations"]


def test_pool_is_large_varied_deduplicated_and_capped():
    sugg = questions(monthly())
    qs = [s["question"].lower() for s in sugg]
    assert 20 <= len(sugg) <= 48 and len(qs) == len(set(qs))
    assert len({s["category"] for s in sugg}) >= 6
    assert len({s["category"] for s in sugg[:6]}) >= 5, "the default view (first 6) must span several kinds of question"
    assert len(questions(DATASETS["tiny"]())) >= 2


def test_more_kinds_of_question_are_offered():
    qs = " | ".join(s["question"] for s in questions(monthly()))
    for needle in ("highest", "lowest", "average", "maximum", "distribution", "weekly", "growth trend", "decrease by 5%", "demand drops", "elasticity",
                   "costs rise 5%", "correlations", "outliers", "Top 10 customers", "Bottom 10 customers"):
        assert needle in qs, needle
    assert sum(1 for s in questions(monthly()) if s["category"] == "Why") >= 3          # amount, cost, profit ...


def test_data_quality_question_gets_a_real_quality_answer():
    df = monthly()
    df.loc[df.index[:30], "amount"] = np.nan
    df = pd.concat([df, df.head(7)], ignore_index=True)
    st = run_workflow(RunContext(question="Give me an overview of data quality", tables={"t": df}, table_labels={"t": "x"}))
    assert st["status"] == "completed" and st["plan"]["steps"][0] == "quality" and not st["errors"]
    assert f"{int(df.isna().any(axis=1).sum()):,} of them have at least one missing value" in st["answer"]
    assert f"{int(len(df) - len(df.drop_duplicates())):,} are exact duplicates" in st["answer"]
    assert f"“amount” is missing in {int(df['amount'].isna().sum())} rows" in st["answer"]
    assert st["validation"]["status"] == "passed" and all(f["verified"] for f in st["story"]["footnotes"])
    clean = run_workflow(RunContext(question="How many missing values and duplicate rows are there?", tables={"t": monthly().drop_duplicates()}))
    assert "No missing values and no duplicate rows" in clean["answer"]
