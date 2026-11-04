"""End-to-end user journeys through the real API (no mocks)."""
import sqlite3

import pandas as pd

API = "/api/v1"


def test_chat_journey_with_evidence(client, auth, sales_dataset, sales_df):
    c = client.post(f"{API}/chat/conversations", headers=auth, json={"dataset_ids": [sales_dataset["id"]]}).json()
    r = client.post(f"{API}/chat/conversations/{c['id']}/messages", headers=auth, json={"content": "What is the total revenue by region?"})
    assert r.status_code == 200
    a = r.json()["assistant"]
    assert a["payload"]["sql"].startswith("SELECT") and a["payload"]["result_rows"]
    top = max(a["payload"]["result_rows"], key=lambda x: list(x.values())[1])
    expected = sales_df.groupby("region")["revenue"].sum()
    assert top["region"] == expected.idxmax()
    assert abs(list(top.values())[1] - expected.max()) < 1e-3          # numbers match pandas
    assert a["payload"]["validation"]["status"] == "passed" and a["payload"]["trace"]
    conv = client.get(f"{API}/chat/conversations/{c['id']}", headers=auth).json()
    assert [m["role"] for m in conv["messages"]] == ["user", "assistant"] and conv["title"].startswith("What is")
    assert client.delete(f"{API}/chat/conversations/{c['id']}", headers=auth).status_code == 204


def test_chat_without_dataset_is_honest(client, auth):
    c = client.post(f"{API}/chat/conversations", headers=auth, json={}).json()
    r = client.post(f"{API}/chat/conversations/{c['id']}/messages", headers=auth, json={"content": "total sales?"}).json()
    assert "Select a dataset" in r["assistant"]["content"]


def test_document_question_cites_source(client, auth):
    doc = ("Discount Policy\n\nSales representatives may grant discounts of up to 10% without approval from the manager.\n\n"
           "Returns\n\nElectronics may be returned within 30 days of delivery by any customer.")
    d = client.post(f"{API}/datasets", headers=auth, files={"file": ("policy.md", doc.encode())}).json()
    c = client.post(f"{API}/chat/conversations", headers=auth, json={"dataset_ids": [d["id"]]}).json()
    a = client.post(f"{API}/chat/conversations/{c['id']}/messages", headers=auth, json={"content": "How much discount can reps grant without approval?"}).json()["assistant"]
    assert a["payload"]["citations"][0]["source"] == "policy" and "10%" in a["content"]


def test_import_from_sql_database_then_analyze(client, auth, tmp_path):
    db = tmp_path / "ext.db"
    con = sqlite3.connect(db)
    pd.DataFrame({"team": ["a", "b", "a", "c"] * 10, "score": range(40)}).to_sql("results", con, index=False)
    con.close()
    r = client.post(f"{API}/datasets/from-sql", headers=auth, json={"url": f"sqlite:///{db}", "table": "results", "name": "ext_results"})
    assert r.status_code == 201 and r.json()["row_count"] == 40
    q = client.post(f"{API}/sql/query", headers=auth, json={"sql": "SELECT team, AVG(score) AS s FROM ext_results GROUP BY 1 ORDER BY 1"}).json()
    assert q["row_count"] == 3
    bad = client.post(f"{API}/datasets/from-sql", headers=auth, json={"url": f"sqlite:///{db}", "query": "DROP TABLE results", "name": "x"})
    assert bad.status_code == 400
    bad = client.post(f"{API}/datasets/from-sql", headers=auth, json={"url": "postgresql+psycopg://u:p@127.0.0.1:1/nope", "table": "t", "name": "x"})
    assert bad.status_code == 422


def test_join_across_datasets(client, auth):
    client.post(f"{API}/datasets", headers=auth, files={"file": ("orders_j.csv", b"cid,amt\n1,10\n2,20\n1,5\n")}).json()
    client.post(f"{API}/datasets", headers=auth, files={"file": ("people_j.csv", b"cid,nm\n1,Ann\n2,Bo\n")}).json()
    r = client.post(f"{API}/sql/query", headers=auth, json={"sql": "SELECT nm, SUM(amt) AS t FROM orders_j JOIN people_j USING (cid) GROUP BY 1 ORDER BY 1"}).json()
    assert r["rows"] == [{"nm": "Ann", "t": 15}, {"nm": "Bo", "t": 20}]
