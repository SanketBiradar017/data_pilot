import io

import pandas as pd

API = "/api/v1/datasets"
CSV = (b"id,name,city,amount\n1,Ann,Pune,10\n2,Bob,Delhi,20\n3,Ann,Pune,10\n4,Cy,,30\n5,Cy,  ,30\n6,Bob,Delhi,20\n7,Bob,Delhi,20\n8,Eve,Pune,5\n")


def tagged(data: bytes, tag: str) -> bytes:
    """Same rows plus a constant `src` column, so every test uploads a different file (the app rejects byte-identical re-uploads)."""
    head, *rows = data.decode().strip().split("\n")
    return ("\n".join([head + ",src"] + [r + "," + tag for r in rows]) + "\n").encode()


def upload(client, auth, name="dups.csv", data=CSV, tag=None):
    r = client.post(API, headers=auth, files={"file": (name, tagged(data, tag or name) if name.endswith(".csv") else data)})
    assert r.status_code == 201, r.text
    return r.json()


def test_summary_is_detected_automatically_on_upload(client, auth):
    d = upload(client, auth)
    dups = d["profile"]["duplicates"]
    assert dups["rows"] == 8 and dups["duplicate_rows"] == 0                 # id differs on every row -> no exact duplicates
    d2 = upload(client, auth, "dups2.csv", CSV.replace(b"\n1,Ann", b"\n9,Ann"))   # different bytes, still unique ids
    assert d2["profile"]["duplicates"]["duplicate_rows"] == 0
    plain = upload(client, auth, "nid.csv", b"name,city,amount\nAnn,Pune,10\nBob,Delhi,20\nAnn,Pune,10\nCy,,30\nCy,  ,30\nBob,Delhi,20\nBob,Delhi,20\nEve,Pune,5\n")
    assert plain["profile"]["duplicates"] == {"rows": 8, "duplicate_rows": 4, "groups": 3, "pct": 50.0, "blank_cells": 1}


def test_analysis_endpoint_counts_groups_and_percentage(client, auth):
    d = upload(client, auth, "nid2.csv", b"name,city,amount\nAnn,Pune,10\nBob,Delhi,20\nAnn,Pune,10\nCy,,30\nCy,  ,30\nBob,Delhi,20\nBob,Delhi,20\nEve,Pune,5\n")
    r = client.post(f"{API}/{d['id']}/duplicates", headers=auth, json={}).json()
    assert (r["rows"], r["duplicate_rows"], r["groups"], r["rows_involved"]) == (8, 4, 3, 7)
    assert r["duplicate_pct"] == 50.0 and r["blank_cells_treated_as_missing"] == 1
    g = r["groups_list"]
    assert [x["count"] for x in g] == [3, 2, 2] and g[0]["values"]["name"] == "Bob" and g[0]["row_numbers"] == [2, 6, 7]
    assert [b["groups"] for b in r["distribution"]][:2] == [2, 1]
    strict = client.post(f"{API}/{d['id']}/duplicates", headers=auth, json={"blank_as_missing": False}).json()
    assert strict["duplicate_rows"] == 3                                      # "  " is a real value now (the empty field is still missing)
    sub = client.post(f"{API}/{d['id']}/duplicates", headers=auth, json={"columns": ["city"]}).json()
    assert sub["columns_used"] == ["city"] and sub["groups"] == 3 and sorted(g["count"] for g in sub["groups_list"]) == [2, 3, 3]   # Pune x3, Delhi x3, missing x2


def test_id_hint_exclusion_and_errors(client, auth):
    d = upload(client, auth, "hint.csv", CSV)
    r = client.post(f"{API}/{d['id']}/duplicates", headers=auth, json={}).json()
    assert r["duplicate_rows"] == 0 and r["hint"] and r["hint"]["columns"] == ["id"]
    ex = client.post(f"{API}/{d['id']}/duplicates", headers=auth, json={"exclude_id_like": True}).json()
    assert ex["duplicate_rows"] == r["hint"]["duplicate_rows"] and "id" not in ex["columns_used"]
    assert client.post(f"{API}/{d['id']}/duplicates", headers=auth, json={"columns": ["nope"]}).status_code == 400
    assert client.post(f"{API}/{d['id']}/duplicates", headers=auth, json={"limit": 0}).status_code == 422


def test_inspect_rows_and_exports(client, auth):
    d = upload(client, auth, "nid3.csv", b"name,city,amount\nAnn,Pune,10\nBob,Delhi,20\nAnn,Pune,10\nCy,,30\nCy,  ,30\nBob,Delhi,20\nBob,Delhi,20\nEve,Pune,5\n")
    rows = client.post(f"{API}/{d['id']}/duplicates/rows", headers=auth, json={"row_numbers": [2, 6, 7]}).json()
    assert rows["columns"] == ["name", "city", "amount", "src"] and [r["__row__"] for r in rows["rows"]] == [2, 6, 7] and all(r["name"] == "Bob" for r in rows["rows"])
    assert client.post(f"{API}/{d['id']}/duplicates/rows", headers=auth, json={"row_numbers": [99]}).status_code == 400
    csv = client.post(f"{API}/{d['id']}/duplicates/export", headers=auth, json={"format": "csv", "scope": "groups"})
    g = pd.read_csv(io.StringIO(csv.text))
    assert csv.status_code == 200 and g["occurrences"].tolist() == [3, 2, 2] and g["extra_copies"].sum() == 4
    allrows = pd.read_csv(io.StringIO(client.post(f"{API}/{d['id']}/duplicates/export", headers=auth, json={"format": "csv", "scope": "rows"}).text))
    assert allrows["row_number"].tolist() == [2, 6, 7, 1, 3, 4, 5] and allrows["occurrence"].tolist() == [1, 2, 3, 1, 2, 1, 2]
    xl = client.post(f"{API}/{d['id']}/duplicates/export", headers=auth, json={"format": "xlsx", "scope": "rows"})
    sheets = pd.read_excel(io.BytesIO(xl.content), sheet_name=None)
    assert xl.content[:2] == b"PK" and set(sheets) == {"Summary", "Groups", "Duplicate rows"} and len(sheets["Duplicate rows"]) == 7
    assert dict(zip(sheets["Summary"]["Metric"], sheets["Summary"]["Value"]))["Duplicate (extra) copies"] == 4
    assert client.post(f"{API}/{d['id']}/duplicates/export", headers=auth, json={"format": "pdf"}).status_code == 422


def test_remove_duplicates_then_summary_is_zero_and_quality_unchanged(client, auth):
    d = upload(client, auth, "nid4.csv", b"name,city,amount\nAnn,Pune,10\nBob,Delhi,20\nAnn,Pune,10\nBob,Delhi,20\nEve,Pune,5\n")
    before = client.get(f"{API}/{d['id']}", headers=auth).json()["quality"]
    assert any(i["type"] == "duplicate_rows" and "2 duplicate" in i["message"] for i in before["issues"])    # existing quality check still reports it
    client.post(f"{API}/{d['id']}/clean", headers=auth, json={"op": "drop_duplicates"})
    after = client.get(f"{API}/{d['id']}", headers=auth).json()
    assert after["profile"]["duplicates"]["duplicate_rows"] == 0 and after["row_count"] == 3
    assert client.post(f"{API}/{d['id']}/duplicates", headers=auth, json={}).json()["duplicate_rows"] == 0


def test_document_duplicates_and_isolation(client, auth, other_auth):
    text = b"Refund policy applies to all purchases within thirty days.\n\nShipping takes five business days.\n\nRefund policy applies to all purchases within thirty days.\n"
    doc = upload(client, auth, "policy.txt", text)
    assert doc["profile"]["duplicates"]["duplicate_rows"] == 1
    r = client.post(f"{API}/{doc['id']}/duplicates", headers=auth, json={}).json()
    assert r["unit"] == "paragraphs" and r["groups_list"][0]["row_numbers"] == [1, 3]
    rows = client.post(f"{API}/{doc['id']}/duplicates/rows", headers=auth, json={"row_numbers": [1, 3]}).json()
    assert rows["rows"][0]["paragraph"] == rows["rows"][1]["paragraph"]
    assert client.post(f"{API}/{doc['id']}/duplicates/export", headers=auth, json={"format": "csv"}).status_code == 200
    for path in ("duplicates", "duplicates/rows", "duplicates/export"):
        assert client.post(f"{API}/{doc['id']}/{path}", headers=other_auth, json={"row_numbers": [1]}).status_code == 404
        assert client.post(f"{API}/{doc['id']}/{path}", json={"row_numbers": [1]}).status_code == 401
