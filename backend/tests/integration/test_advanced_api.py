import io

import pandas as pd
import pytest

API = "/api/v1/advanced"


def test_fields_endpoint(client, auth, sales_dataset):
    f = client.get(f"{API}/fields/{sales_dataset['id']}", headers=auth).json()
    by = {c["name"]: c for c in f["columns"]}
    assert by["region"]["kind"] == "category" and set(by["region"]["values"]) == {"North", "South", "East"}
    assert by["revenue"]["kind"] == "numeric" and by["revenue"]["measure"] and by["order_date"]["kind"] == "datetime"


def test_pivot_endpoint_and_exports(client, auth, sales_dataset, sales_df):
    body = {"dataset_id": sales_dataset["id"], "rows": ["region"], "columns": ["category"],
            "values": [{"column": "revenue", "agg": "sum"}], "filters": [{"column": "units", "op": "gte", "value": 3}]}
    r = client.post(f"{API}/pivot", headers=auth, json=body)
    assert r.status_code == 200, r.text
    j = r.json()
    sub = sales_df[sales_df.units >= 3]
    assert j["rows"][-1]["Total"] == pytest.approx(sub.revenue.sum()) and j["chart"]["type"] == "bar"
    csv = client.post(f"{API}/pivot/export", headers=auth, json={**body, "format": "csv"})
    assert csv.status_code == 200 and "text/csv" in csv.headers["content-type"]
    got = pd.read_csv(io.StringIO(csv.text))
    assert list(got.columns) == j["columns"] and len(got) == len(j["rows"])
    xl = client.post(f"{API}/pivot/export", headers=auth, json={**body, "format": "xlsx"})
    assert xl.status_code == 200 and xl.content[:2] == b"PK"
    sheets = pd.read_excel(io.BytesIO(xl.content), sheet_name=None)
    assert set(sheets) == {"Pivot", "Definition"} and len(sheets["Pivot"]) == len(j["rows"])
    assert client.post(f"{API}/pivot/export", headers=auth, json={**body, "format": "pdf"}).status_code == 422


def test_pivot_errors(client, auth, sales_dataset):
    ok = {"dataset_id": sales_dataset["id"], "rows": ["region"], "values": [{"column": "revenue", "agg": "sum"}]}
    assert client.post(f"{API}/pivot", headers=auth, json={**ok, "values": []}).status_code == 422
    assert client.post(f"{API}/pivot", headers=auth, json={**ok, "rows": ["zzz"]}).status_code == 400
    assert client.post(f"{API}/pivot", headers=auth, json={**ok, "values": [{"column": "region", "agg": "sum"}]}).status_code == 400
    assert client.post(f"{API}/pivot", headers=auth, json={**ok, "dataset_id": 99999}).status_code == 404


def test_regression_endpoint(client, auth, sales_dataset):
    r = client.post(f"{API}/regression", headers=auth, json={"dataset_id": sales_dataset["id"], "target": "revenue", "features": ["units"]})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["coefficients"][0]["name"] == "const" and j["charts"]["actual_vs_predicted"]
    # the shared fixture contains one 99,999 outlier: it must wreck R² *and* be flagged as influential
    assert j["metrics"]["r2"] < 0.2 and j["influential_points"][0]["row"] == 5 and any("influence" in w for w in j["warnings"])
    assert client.post(f"{API}/regression", headers=auth, json={"dataset_id": sales_dataset["id"], "target": "region", "features": ["units"]}).status_code == 400
    assert client.post(f"{API}/regression", headers=auth, json={"dataset_id": sales_dataset["id"], "target": "revenue", "features": []}).status_code == 422


def test_hypothesis_endpoint(client, auth, sales_dataset):
    r = client.post(f"{API}/hypothesis", headers=auth, json={"dataset_id": sales_dataset["id"], "test": "anova", "value": "revenue", "group": "region"})
    assert r.status_code == 200 and 0 <= r.json()["p_value"] <= 1 and r.json()["interpretation"]
    r = client.post(f"{API}/hypothesis", headers=auth, json={"dataset_id": sales_dataset["id"], "test": "t_welch", "value": "revenue", "group": "region", "groups": ["North", "South"]})
    assert r.status_code == 200 and len(r.json()["groups"]) == 2
    r = client.post(f"{API}/hypothesis", headers=auth, json={"dataset_id": sales_dataset["id"], "test": "chi_square", "value": "region", "value2": "category"})
    assert r.status_code == 200 and r.json()["contingency"]["counts"]
    assert client.post(f"{API}/hypothesis", headers=auth, json={"dataset_id": sales_dataset["id"], "test": "t_welch", "value": "revenue", "group": "region"}).status_code == 400


def test_pareto_endpoint(client, auth, sales_dataset):
    r = client.post(f"{API}/pareto", headers=auth, json={"dataset_id": sales_dataset["id"], "category": "region", "value": "revenue"})
    assert r.status_code == 200 and r.json()["rows"][-1]["cum_pct"] == 100 and {x["class"] for x in r.json()["rows"]} <= {"A", "B", "C"}
    assert client.post(f"{API}/pareto", headers=auth, json={"dataset_id": sales_dataset["id"], "category": "region", "a_cut": 99, "b_cut": 90}).status_code == 400


def test_variance_endpoint(client, auth):
    d = client.post("/api/v1/datasets", headers=auth, files={"file": ("targets.csv", b"month,revenue,target\n2024-01-05,800,1000\n2024-02-05,1200,1000\n2024-03-05,900,1000\n")}).json()
    r = client.post(f"{API}/variance", headers=auth, json={"dataset_id": d["id"], "mode": "target", "metrics": [{"column": "revenue", "kind": "revenue", "target_column": "target"}]})
    assert r.status_code == 200
    row = r.json()["rows"][0]
    assert row["actual"] == 2900 and row["comparator"] == 3000 and row["variance"] == -100
    r = client.post(f"{API}/variance", headers=auth, json={"dataset_id": d["id"], "mode": "period", "date_column": "month", "period": "month", "metrics": [{"column": "revenue"}]})
    assert r.status_code == 200, r.text
    assert r.json()["current_period"] == "2024-03" and r.json()["rows"][0]["variance"] == -300
    assert client.post(f"{API}/variance", headers=auth, json={"dataset_id": d["id"], "mode": "period", "metrics": [{"column": "revenue"}]}).status_code == 400
    assert client.post(f"{API}/variance", headers=auth, json={"dataset_id": d["id"], "mode": "bogus", "metrics": [{"column": "revenue"}]}).status_code == 422


def test_advanced_requires_auth_and_isolation(client, other_auth, sales_dataset):
    body = {"dataset_id": sales_dataset["id"], "category": "region"}
    assert client.post(f"{API}/pareto", json=body).status_code == 401
    assert client.post(f"{API}/pareto", headers=other_auth, json=body).status_code == 404
    assert client.get(f"{API}/fields/{sales_dataset['id']}", headers=other_auth).status_code == 404


def test_document_dataset_rejected(client, auth):
    d = client.post("/api/v1/datasets", headers=auth, files={"file": ("memo.txt", b"Some words here.\n\nAnd a second paragraph of text to be safe.")}).json()
    assert client.post(f"{API}/pareto", headers=auth, json={"dataset_id": d["id"], "category": "x"}).status_code == 400


# ---------------- AI intelligence API ----------------
AI = "/api/v1/intelligence"


@pytest.fixture(scope="module")
def monthly_ds(client, auth):
    import numpy as np

    rng = np.random.default_rng(2)
    rows = ["order_date,region,category,quantity,revenue,cost"]
    for m, mult in ((5, 1.0), (6, 1.1), (7, 0.8)):
        for day in range(1, 29):
            for reg in ("North", "South"):
                for cat, price in (("Gadgets", 20), ("Tools", 35)):
                    q = round(5 * mult * (0.6 if (m == 7 and reg == "South" and cat == "Tools") else 1) + rng.integers(0, 2), 2)
                    rows.append(f"2025-{m:02d}-{day:02d},{reg},{cat},{q},{q * price},{q * price * 0.55}")
    return client.post("/api/v1/datasets", headers=auth, files={"file": ("monthly.csv", "\n".join(rows).encode())}).json()


def test_roles_endpoint(client, auth, monthly_ds):
    r = client.get(f"{AI}/roles/{monthly_ds['id']}", headers=auth).json()
    assert r["revenue"] == "revenue" and r["cost"] == "cost" and r["quantity"] == "quantity" and r["date"] == "order_date"


def test_root_cause_endpoint(client, auth, monthly_ds):
    r = client.post(f"{AI}/root-cause", headers=auth, json={"dataset_id": monthly_ds["id"], "question": "Why did revenue decrease in July?", "number_mode": "indian"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["current"] == "2025-07" and j["direction"] == "decreased" and all(c["passed"] for c in j["reconciliation"])
    assert all(v["verified"] for v in j["verification"].values()) and j["story"]["statements"] and j["charts"]
    assert any("South" in s["text"] or "Tools" in s["text"] for s in j["story"]["statements"])
    j2 = client.post(f"{AI}/root-cause", headers=auth, json={"dataset_id": monthly_ds["id"], "metric": "revenue", "current": "2025-06", "previous": "2025-05"}).json()
    assert j2["direction"] == "increased"
    assert client.post(f"{AI}/root-cause", headers=auth, json={"dataset_id": monthly_ds["id"], "current": "2024-01"}).status_code == 400
    assert client.post(f"{AI}/root-cause", headers=auth, json={"dataset_id": monthly_ds["id"], "grain": "decade"}).status_code == 422


def test_discover_endpoint_and_cache(client, auth, monthly_ds):
    a = client.get(f"{AI}/discover/{monthly_ds['id']}", headers=auth).json()
    assert a["insights"] and all(i["verified"] for i in a["insights"]) and a["dropped_unverified"] == 0
    assert client.get(f"{AI}/discover/{monthly_ds['id']}?refresh=true", headers=auth).json()["insights"] == a["insights"]


def test_executive_summary_and_export(client, auth, monthly_ds):
    r = client.post(f"{AI}/executive-summary", headers=auth, json={"dataset_id": monthly_ds["id"], "number_mode": "inr"})
    assert r.status_code == 200
    j = r.json()
    assert j["kpis"] and all(k["verified"] for k in j["kpis"]) and j["performance"] and "₹" in j["performance"][0]["text"]
    for fmt, magic in (("pdf", b"%PDF"), ("xlsx", b"PK")):
        e = client.post(f"{AI}/executive-summary/export", headers=auth, json={"dataset_id": monthly_ds["id"], "format": fmt})
        assert e.status_code == 201, e.text
        dl = client.get(f"/api/v1/reports/{e.json()['id']}/download", headers=auth)
        assert dl.status_code == 200 and dl.content.startswith(magic)
    assert client.post(f"{AI}/executive-summary/export", headers=auth, json={"dataset_id": monthly_ds["id"], "format": "doc"}).status_code == 422


def test_scenario_endpoint(client, auth, monthly_ds):
    body = {"dataset_id": monthly_ds["id"], "scenarios": [{"name": "Price +10%", "price_change_pct": 10}, {"name": "Price +10%, elastic", "price_change_pct": 10, "elasticity": -1.2}], "group_by": "region"}
    r = client.post(f"{AI}/scenario", headers=auth, json=body)
    assert r.status_code == 200, r.text
    j = r.json()
    f = {x["id"]: x for x in j["facts"]}
    assert j["kind"] == "scenario_estimate" and len(j["scenarios"]) == 2 and all(v["verified"] for v in j["verification"].values())
    base_rev = f[j["observed"]["revenue"]]["value"]
    assert f[j["scenarios"][0]["facts"]["revenue"]]["value"] == pytest.approx(base_rev * 1.1)
    assert f[j["scenarios"][1]["facts"]["revenue"]]["value"] == pytest.approx(base_rev * 1.1 * (1 - 0.12))
    assert f[j["scenarios"][0]["facts"]["revenue"]]["estimate"] is True and f[j["observed"]["revenue"]].get("estimate") in (False, None)
    assert client.post(f"{AI}/scenario", headers=auth, json={**body, "scenarios": [{"price_change_pct": 999}]}).status_code == 400
    assert client.post(f"{AI}/scenario", headers=auth, json={**body, "scenarios": []}).status_code == 422


def test_intelligence_auth_isolation_and_non_date(client, auth, other_auth, monthly_ds, sales_dataset):
    assert client.get(f"{AI}/discover/{monthly_ds['id']}").status_code == 401
    assert client.get(f"{AI}/discover/{monthly_ds['id']}", headers=other_auth).status_code == 404
    assert client.post(f"{AI}/scenario", headers=other_auth, json={"dataset_id": monthly_ds["id"], "scenarios": [{"price_change_pct": 5}]}).status_code == 404
    d = client.post("/api/v1/datasets", headers=auth, files={"file": ("nodate.csv", b"a,b\n1,x\n2,y\n3,x\n4,y\n")}).json()
    assert client.post(f"{AI}/root-cause", headers=auth, json={"dataset_id": d["id"]}).status_code == 400


def test_chat_runs_root_cause_with_story(client, auth, monthly_ds):
    c = client.post("/api/v1/chat/conversations", headers=auth, json={"dataset_ids": [monthly_ds["id"]]}).json()
    a = client.post(f"/api/v1/chat/conversations/{c['id']}/messages", headers=auth, json={"content": "Why did revenue decrease in July?"}).json()["assistant"]
    assert "decreased" in a["content"] and a["payload"]["validation"]["status"] == "passed"
    assert any(t["agent"] == "root_cause" for t in a["payload"]["trace"]) and any(t["agent"] == "story" for t in a["payload"]["trace"])


def test_suggestions_endpoint(client, auth, other_auth, monthly_ds, sales_dataset):
    r = client.get(f"/api/v1/analyses/suggestions?dataset_ids={monthly_ds['id']}", headers=auth)
    assert r.status_code == 200
    qs = [s["question"] for s in r.json()]
    assert qs and all({"question", "category", "reason"} <= set(s) for s in r.json())
    assert any("revenue" in q for q in qs) and any(c in " ".join(qs) for c in ("North", "South", "Gadgets", "Tools"))
    other = [s["question"] for s in client.get(f"/api/v1/analyses/suggestions?dataset_ids={sales_dataset['id']}", headers=auth).json()]
    assert other != qs                                                       # different data -> different questions
    assert client.get(f"/api/v1/analyses/suggestions?dataset_ids={monthly_ds['id']}", headers=other_auth).status_code == 404
    assert client.get("/api/v1/analyses/suggestions?dataset_ids=abc", headers=auth).json() == []
    assert client.get(f"/api/v1/analyses/suggestions?dataset_ids={monthly_ds['id']}").status_code == 401


def test_regression_endpoint_never_returns_500_for_single_category_predictor(client, auth):
    d = client.post("/api/v1/datasets", headers=auth, files={"file": ("flat.csv", ("y,x,grp\n" + "\n".join(f"{i * 1.5},{i % 7},A" for i in range(40))).encode())}).json()
    r = client.post(f"{API}/regression", headers=auth, json={"dataset_id": d["id"], "target": "y", "features": ["grp"]})
    assert r.status_code == 400 and "nothing to compare" in r.json()["detail"]
    assert client.post(f"{API}/regression", headers=auth, json={"dataset_id": d["id"], "target": "y", "features": ["x", "grp"]}).status_code == 200
