import io

import pandas as pd
import pytest

from backend.tests.conftest import _auth


@pytest.fixture(scope="module")
def h(client):
    return _auth(client, "geo1@test.io")


@pytest.fixture(scope="module")
def geo_ds(client, h):
    return _upload(client, h, GEO)


def _csv(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode()


def _upload(client, headers, df, name="geo.csv"):
    r = client.post("/api/v1/datasets", files={"file": (name, io.BytesIO(_csv(df)), "text/csv")}, headers=headers)
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


GEO = pd.DataFrame({
    "Country": ["United States", "USA", "India", "India", "Germany", "Atlantis"],
    "State": ["California", "Texas", "Maharashtra", "Karnataka", "Bavaria", "X"],
    "City": ["Los Angeles", "Austin", "Mumbai", "Bengaluru", "Munich", "Nowhere"],
    "Order Date": ["2024-01-05", "2024-02-10", "2024-01-20", "2024-03-01", "2024-02-02", "2024-02-03"],
    "Sales": [1000.0, 500.0, 800.0, 200.0, 300.0, 50.0],
    "Cost": [600.0, 700.0, 500.0, 250.0, 100.0, 10.0],
})


def test_detect_and_summary_world(client, h, geo_ds):
    ds = geo_ds
    m = client.get(f"/api/v1/geo-revenue/mapping/{ds}", headers=h).json()
    assert m["mapping"]["country"] == "Country" and m["mapping"]["state"] == "State" and m["mapping"]["city"] == "City"
    assert m["mapping"]["revenue"] == "Sales" and m["mapping"]["expense"] == "Cost" and m["mapping"]["date"] == "Order_Date"
    r = client.post("/api/v1/geo-revenue/summary", json={"dataset_id": ds, "level": "world"}, headers=h).json()
    by = {x["key"]: x for x in r["regions"]}
    assert by["USA"]["revenue"] == 1500.0 and by["USA"]["loss"] == 200.0  # row-level shortfall: Texas 500-700
    assert by["IND"]["revenue"] == 1000.0 and by["IND"]["profit"] == 250.0
    assert r["totals"]["revenue"] == 2850.0 and r["totals"]["transactions"] == 6
    assert r["unmapped"]["transactions"] == 1  # Atlantis
    assert r["loss_basis"] == "negative_profit"


def test_drilldown_and_dates(client, h, geo_ds):
    ds = geo_ds
    st = client.post("/api/v1/geo-revenue/summary", json={"dataset_id": ds, "level": "country", "country": "IND"}, headers=h).json()
    assert {x["key"] for x in st["regions"]} == {"Maharashtra", "Karnataka"}
    ci = client.post("/api/v1/geo-revenue/summary", json={"dataset_id": ds, "level": "state", "country": "IND", "state": "Maharashtra"}, headers=h).json()
    assert ci["regions"][0]["name"] == "Mumbai" and ci["regions"][0]["lat"] is not None
    d = client.post("/api/v1/geo-revenue/summary", json={"dataset_id": ds, "level": "world", "date_from": "2024-02-01", "date_to": "2024-02-29"}, headers=h).json()
    assert d["totals"]["revenue"] == 500.0 + 300.0 + 50.0
    assert d["date_range"] == {"min": "2024-01-05", "max": "2024-03-01"}


def test_manual_mapping_save_and_errors(client, h):
    df = pd.DataFrame({"loc": ["France", "France", "Spain"], "v": [10, 20, 5], "l": [1, -4, 0]})
    ds = _upload(client, h, df, "odd.csv")
    m = client.get(f"/api/v1/geo-revenue/mapping/{ds}", headers=h).json()
    assert m["needs_mapping"] is True
    bad = client.put(f"/api/v1/geo-revenue/mapping/{ds}", json={"country": "nope", "revenue": "v"}, headers=h)
    assert bad.status_code == 400
    ok = client.put(f"/api/v1/geo-revenue/mapping/{ds}", json={"country": "loc", "revenue": "v", "loss": "l"}, headers=h)
    assert ok.status_code == 200
    r = client.post("/api/v1/geo-revenue/summary", json={"dataset_id": ds, "level": "world"}, headers=h).json()
    fr = next(x for x in r["regions"] if x["key"] == "FRA")
    assert fr["revenue"] == 30.0 and fr["loss"] == 5.0 and r["loss_basis"] == "loss_column"
    assert client.delete(f"/api/v1/geo-revenue/mapping/{ds}", headers=h).status_code == 204


def test_ownership_and_auth(client, h, geo_ds):
    h2 = _auth(client, "geo-b@test.io")
    ds = geo_ds
    assert client.post("/api/v1/geo-revenue/summary", json={"dataset_id": ds}, headers=h2).status_code == 404
    assert client.get(f"/api/v1/geo-revenue/mapping/{ds}", headers=h2).status_code == 404
    assert client.post("/api/v1/geo-revenue/summary", json={"dataset_id": ds}).status_code == 401
    assert client.get("/api/v1/geo-revenue/boundaries/world").status_code == 401


def test_boundaries(client, h):
    w = client.get("/api/v1/geo-revenue/boundaries/world", headers=h)
    assert w.status_code == 200 and len(w.json()["features"]) > 200
    s = client.get("/api/v1/geo-revenue/boundaries/IND/states", headers=h)
    assert s.status_code == 200 and len(s.json()["features"]) >= 30
    assert client.get("/api/v1/geo-revenue/boundaries/ZZZ/states", headers=h).status_code == 404
    assert client.get("/api/v1/geo-revenue/boundaries/..%2Fx/states", headers=h).status_code in (404, 422)
    assert client.get("/api/v1/geo-revenue/boundaries/IND/cities", headers=h).json()["cities"]
