import io
import time

import pandas as pd

API = "/api/v1"


def test_health_and_root(client):
    assert client.get(f"{API}/health").json()["status"] == "ok"
    root = client.get("/")  # API banner, or the SPA when frontend/dist is built
    assert root.status_code == 200
    assert client.get("/api/v1/nope").status_code == 404


def test_auth_required_everywhere(client):
    for path in ["/datasets", "/analyses", "/reports", "/dashboard/overview", "/sql/schema", "/settings", "/chat/conversations"]:
        assert client.get(API + path).status_code == 401, path
    assert client.get(f"{API}/datasets", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_register_login_validation(client, auth):
    assert client.post(f"{API}/auth/register", json={"email": "owner@test.io", "password": "password123"}).status_code == 409
    assert client.post(f"{API}/auth/register", json={"email": "bad", "password": "password123"}).status_code == 422
    assert client.post(f"{API}/auth/register", json={"email": "x@y.io", "password": "short"}).status_code == 422
    assert client.post(f"{API}/auth/login", json={"email": "owner@test.io", "password": "wrong-pass"}).status_code == 401
    r = client.post(f"{API}/auth/login", json={"email": "OWNER@test.io", "password": "password123"})
    assert r.status_code == 200 and r.json()["user"]["role"] == "admin"
    assert client.get(f"{API}/auth/me", headers=auth).json()["email"] == "owner@test.io"


def test_upload_profile_preview(client, auth, sales_dataset, sales_df):
    d = sales_dataset
    assert d["row_count"] == len(sales_df) and d["kind"] == "table"
    assert d["profile"]["column_profiles"] and d["quality"]["score"] > 0
    p = client.get(f"{API}/datasets/{d['id']}/preview?limit=5&offset=10", headers=auth).json()
    assert len(p["rows"]) == 5 and p["total"] == len(sales_df) and p["offset"] == 10
    assert client.get(f"{API}/datasets/{d['id']}/download", headers=auth).text.startswith("order_id")
    assert d["id"] in [x["id"] for x in client.get(f"{API}/datasets", headers=auth).json()]


def test_upload_rejections(client, auth, sales_dataset, sales_df):
    csv = sales_df.to_csv(index=False).encode()
    assert client.post(f"{API}/datasets", headers=auth, files={"file": ("again.csv", csv)}).status_code == 409
    assert client.post(f"{API}/datasets", headers=auth, files={"file": ("a.exe", b"MZxx")}).status_code == 422
    assert client.post(f"{API}/datasets", headers=auth, files={"file": ("e.csv", b"")}).status_code == 422
    assert client.post(f"{API}/datasets", headers=auth, files={"file": ("../../evil.csv", b"a,b\n1,2\n")}).status_code == 201


def test_multi_format_upload(client, auth):
    df = pd.DataFrame({"k": ["a", "b", "c"], "v": [1, 2, 3]})
    buf = io.BytesIO(); df.to_excel(buf, index=False)
    r = client.post(f"{API}/datasets", headers=auth, files={"file": ("book.xlsx", buf.getvalue())})
    assert r.status_code == 201 and r.json()["row_count"] == 3
    r = client.post(f"{API}/datasets", headers=auth, files={"file": ("rows.json", df.to_json(orient="records").encode())})
    assert r.status_code == 201
    r = client.post(f"{API}/datasets", headers=auth, files={"file": ("note.txt", b"Refund policy.\n\nRefunds take 5 business days to process for all customers.")})
    assert r.status_code == 201 and r.json()["kind"] == "document"


def test_cleaning_improves_quality(client, auth):
    dirty = pd.DataFrame({"x": [1.0, None, 3.0, None] * 10, "y": ["a ", " b", "a", "b"] * 10})
    d = client.post(f"{API}/datasets", headers=auth, files={"file": ("dirty.csv", dirty.to_csv(index=False).encode())}).json()
    r = client.post(f"{API}/datasets/{d['id']}/clean", headers=auth, json={"op": "auto_clean"})
    assert r.status_code == 200 and r.json()["quality_after"] >= r.json()["quality_before"]
    assert r.json()["dataset"]["profile"]["missing_cells"] == 0
    assert client.post(f"{API}/datasets/{d['id']}/clean", headers=auth, json={"op": "explode"}).status_code == 400
    assert client.post(f"{API}/datasets/{d['id']}/clean", headers=auth, json={"op": "drop_column", "column": "zzz"}).status_code == 400


def test_sql_endpoints(client, auth, sales_dataset, sales_df):
    t = sales_dataset["table_name"]
    r = client.post(f"{API}/sql/query", headers=auth, json={"sql": f"SELECT region, SUM(revenue) AS r FROM {t} GROUP BY 1 ORDER BY 2 DESC"})
    assert r.status_code == 200 and r.json()["row_count"] == 3 and r.json()["chart"]["type"] == "bar"
    assert abs(sum(x["r"] for x in r.json()["rows"]) - sales_df["revenue"].sum()) < 1e-3
    assert client.post(f"{API}/sql/query", headers=auth, json={"sql": f"DROP TABLE {t}"}).status_code == 400
    assert client.post(f"{API}/sql/query", headers=auth, json={"sql": "SELECT * FROM missing_table"}).status_code == 400
    g = client.post(f"{API}/sql/generate", headers=auth, json={"question": "average revenue by category", "dataset_id": sales_dataset["id"]}).json()
    assert "AVG" in g["sql"]
    assert client.get(f"{API}/sql/schema", headers=auth).json()[0]["columns"]
    s = client.post(f"{API}/sql/saved", headers=auth, json={"name": "q", "sql": "SELECT 1"}).json()
    assert client.get(f"{API}/sql/saved", headers=auth).json()[0]["id"] == s["id"]
    assert client.post(f"{API}/sql/saved", headers=auth, json={"name": "bad", "sql": "DELETE FROM x"}).status_code == 400
    assert client.delete(f"{API}/sql/saved/{s['id']}", headers=auth).status_code == 204


def wait_done(client, auth, aid, timeout=30):
    for _ in range(timeout * 10):
        a = client.get(f"{API}/analyses/{aid}", headers=auth).json()
        if a["status"] in ("completed", "failed"):
            return a
        time.sleep(.1)
    raise AssertionError("analysis timed out")


def test_analysis_report_flow(client, auth, sales_dataset):
    r = client.post(f"{API}/analyses", headers=auth, json={"question": "Analyze revenue trends and anomalies", "dataset_ids": [sales_dataset["id"]]})
    assert r.status_code == 202
    a = wait_done(client, auth, r.json()["id"])
    assert a["status"] == "completed" and a["result"]["validation"]["status"] == "passed"
    assert [t["agent"] for t in a["trace"]][-1] == "report"
    for fmt, magic in (("pdf", b"%PDF"), ("xlsx", b"PK")):
        rep = client.post(f"{API}/reports", headers=auth, json={"analysis_id": a["id"], "format": fmt}).json()
        dl = client.get(f"{API}/reports/{rep['id']}/download", headers=auth)
        assert dl.status_code == 200 and dl.content.startswith(magic)
    assert len(client.get(f"{API}/reports", headers=auth).json()) >= 2
    assert client.post(f"{API}/reports", headers=auth, json={"analysis_id": a["id"], "format": "doc"}).status_code == 422


def test_analysis_bad_dataset(client, auth):
    assert client.post(f"{API}/analyses", headers=auth, json={"question": "hello?", "dataset_ids": [99999]}).status_code == 404
    assert client.post(f"{API}/analyses", headers=auth, json={"question": "hello?", "dataset_ids": []}).status_code == 422


def test_tenant_isolation(client, auth, other_auth, sales_dataset):
    did = sales_dataset["id"]
    assert client.get(f"{API}/datasets/{did}", headers=other_auth).status_code == 404
    assert client.delete(f"{API}/datasets/{did}", headers=other_auth).status_code == 404
    assert client.post(f"{API}/sql/query", headers=other_auth, json={"sql": f"SELECT * FROM {sales_dataset['table_name']}"}).status_code == 404
    assert client.get(f"{API}/datasets", headers=other_auth).json() == []
    assert client.post(f"{API}/analyses", headers=other_auth, json={"question": "steal data", "dataset_ids": [did]}).status_code == 404


def test_dashboard_and_settings(client, auth, sales_dataset):
    o = client.get(f"{API}/dashboard/overview", headers=auth).json()
    assert o["kpis"]["datasets"] >= 1 and o["kpis"]["total_rows"] > 0 and o["kpis"]["avg_quality"]
    s = client.put(f"{API}/settings", headers=auth, json={"theme": "dark", "default_row_limit": 500}).json()
    assert s["preferences"]["theme"] == "dark"
    assert client.put(f"{API}/settings", headers=auth, json={"theme": "neon"}).status_code == 422
    assert client.get(f"{API}/settings", headers=auth).json()["system"]["llm_enabled"] is False


def test_accounts_persist_across_app_restart(client):
    """A new app lifespan (= server restart) must not wipe users."""
    from fastapi.testclient import TestClient

    from backend.app.main import app

    creds = {"email": "persist@test.io", "password": "password123"}
    assert client.post(f"{API}/auth/register", json=creds).status_code == 201
    with TestClient(app) as restarted:
        r = restarted.post(f"{API}/auth/login", json=creds)
        assert r.status_code == 200
        assert restarted.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {r.json()['token']}"}).json()["email"] == creds["email"]


def test_relative_storage_paths_resolve_against_project_root(tmp_path, monkeypatch):
    """Server launched from another folder must still find files (regression: 'advanced analytics not working')."""
    from backend.app.config import ROOT, Settings

    monkeypatch.chdir(tmp_path)
    s = Settings(upload_directory="./data/uploads", processed_directory="./data/processed", report_directory="./storage/reports")
    assert s.processed_directory == (ROOT / "data" / "processed").resolve()
    assert s.upload_directory.is_absolute() and s.report_directory.is_absolute()


def test_legacy_relative_path_is_healed_and_missing_file_is_explained(client, auth, tmp_path, monkeypatch):
    import shutil

    from backend.app.config import settings
    from backend.app.db.session import SessionLocal
    from backend.app.models import Dataset
    from backend.app.services.datasets import heal_paths

    d = client.post(f"{API}/datasets", headers=auth, files={"file": ("legacy.csv", b"a,b\n1,2\n3,4\n5,6\n")}).json()
    db = SessionLocal()
    ds = db.get(Dataset, d["id"])
    real = ds.data_path
    # simulate an old record: relative path pointing at a launch-directory-relative copy
    legacy_root = tmp_path / "other_cwd"
    (legacy_root / "data" / "processed").mkdir(parents=True)
    shutil.move(real, legacy_root / "data" / "processed" / "legacy.parquet")
    monkeypatch.chdir(legacy_root)
    ds.data_path = "data/processed/legacy.parquet"
    db.commit()
    assert heal_paths(db) == 1
    db.refresh(ds)
    assert ds.data_path.startswith(str(settings.processed_directory)) and ds.data_path.endswith(".parquet")
    assert client.get(f"{API}/datasets/{d['id']}/preview", headers=auth).json()["total"] == 3
    # genuinely missing file -> clear 410, not a 500
    import os
    os.remove(ds.data_path)
    r = client.get(f"{API}/datasets/{d['id']}/preview", headers=auth)
    assert r.status_code == 410 and "missing on disk" in r.json()["detail"]
    assert client.post(f"{API}/advanced/pareto", headers=auth, json={"dataset_id": d["id"], "category": "a"}).status_code == 410
    db.close()
