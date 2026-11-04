"""Autonomous Data Analyst: one click, every area investigated, every number verified."""
import numpy as np
import pandas as pd

from backend.app.agents.graph import run_workflow
from backend.app.agents.state import RunContext
from backend.app.analytics.business import business_findings

API = "/api/v1"


def superstore(n: int = 2500) -> pd.DataFrame:
    rng = np.random.default_rng(2)
    sub = rng.choice(["Chairs", "Tables", "Phones", "Binders", "Copiers", "Bookcases"], n)
    df = pd.DataFrame({
        "order_id": np.arange(n), "order_date": np.tile(pd.date_range("2022-01-01", periods=500), 5)[:n],
        "customer_name": rng.choice([f"Cust{i}" for i in range(80)], n, p=np.r_[np.full(5, 0.08), np.full(75, 0.6 / 75)]),
        "region": rng.choice(["West", "East", "Central", "South"], n),
        "category": np.where(np.isin(sub, ["Chairs", "Tables", "Bookcases"]), "Furniture", "Technology"), "sub_category": sub,
        "discount": rng.choice([0, 0, 0, 0.1, 0.2, 0.4, 0.5], n), "sales": rng.uniform(20, 900, n)})
    df["profit"] = df.sales * (0.25 - df.discount * 0.9) - np.where(df.sub_category == "Tables", 60, 0)
    return df


def run(df, question="Analyse my data"):
    ctx = RunContext(question=question)
    ctx.tables["t"], ctx.table_labels["t"] = df, "Data"
    return run_workflow(ctx)


def test_autopilot_finds_the_planted_facts_and_verifies_them():
    df = superstore()
    st = run(df)
    r = st["report"]
    assert st["status"] == "completed" and {"quality", "analytics", "discovery", "business", "root_cause", "executive"} <= set(st["plan"]["steps"])
    ap = r["autopilot"]
    assert [s["id"] for s in ap["sections"]][:2] == ["executive", "business"]
    texts = " ".join(x["text"] for s in ap["sections"] for x in s["statements"])
    by_sub = df.groupby("sub_category").profit.sum()
    assert by_sub.idxmin() == "Tables" and "Tables" in texts and "lose money" in texts          # loss-making product found
    assert df.groupby("region").sales.sum().idxmax() in texts                                       # top region found
    assert "Discounts and profit move in opposite directions" in texts                              # discount effect found
    assert "most valuable customers" in texts
    assert r["validation"]["status"] == "passed" and r["recommendations"] and len(r["charts"]) >= 5
    assert not [t for t in st["trace"] if t["status"] == "failed"]


def test_every_business_number_is_recomputed_exactly():
    df = superstore()
    res = business_findings(df, "t")
    assert res["findings"] and all(v["verified"] for v in res["verification"].values())
    facts = {f["label"]: f["value"] for f in res["facts"]}
    assert facts["Profit of Tables"] == pytest_approx(df[df.sub_category == "Tables"].profit.sum())
    assert facts["Total sales"] == pytest_approx(df.sales.sum())
    assert facts["Average profit per row without a discount"] == pytest_approx(df[df.discount == 0].profit.mean())


def pytest_approx(v):
    import pytest
    return pytest.approx(v, rel=1e-9)


def test_findings_from_different_agents_are_all_kept():
    st = run(superstore())
    sources = {s["source"] for s in st["story"]["statements"]}
    assert {"executive", "business", "quality", "root_cause"} <= sources and st["story"]["dropped"] == 0


def test_dataset_without_money_columns_still_completes_honestly():
    df = pd.DataFrame({"city": ["A", "B", "C", "A"] * 10, "score": np.arange(40.0), "flag": ["y", "n"] * 20})
    st = run(df)
    assert st["status"] == "completed" and st["report"]["answer"]
    assert "root_cause" not in st["plan"]["steps"]
    assert st["report"]["autopilot"]["coverage"]["revenue"] is None


def test_autopilot_through_the_api(client, auth):
    csv = superstore(600).to_csv(index=False).encode()
    d = client.post(f"{API}/datasets", headers=auth, files={"file": ("superstore.csv", csv, "text/csv")}).json()
    a = client.post(f"{API}/analyses", headers=auth, json={"question": "Analyse my data", "dataset_ids": [d["id"]]}).json()
    got = client.get(f"{API}/analyses/{a['id']}", headers=auth).json()
    assert got["status"] == "completed"
    assert got["result"]["report"]["autopilot"]["sections"] and got["result"]["plan"]["steps"][0] == "quality"
