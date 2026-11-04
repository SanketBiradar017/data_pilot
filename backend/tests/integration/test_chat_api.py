"""The chat endpoint end to end: follow-ups, filters, missing columns, forecasts, verified numbers."""
import pytest

API = "/api/v1"


@pytest.fixture
def conv(client, auth, sales_dataset):
    c = client.post(f"{API}/chat/conversations", headers=auth, json={"dataset_ids": [sales_dataset["id"]]}).json()
    yield c["id"]
    client.delete(f"{API}/chat/conversations/{c['id']}", headers=auth)


def ask(client, auth, cid, text):
    r = client.post(f"{API}/chat/conversations/{cid}/messages", headers=auth, json={"content": text})
    assert r.status_code == 200, r.text
    return r.json()["assistant"]


def test_filtered_question_matches_pandas_and_is_explained(client, auth, conv, sales_df):
    a = ask(client, auth, conv, "total revenue for North in 2024 by category")
    p = a["payload"]
    d = sales_df[(sales_df.region == "North") & (sales_df.order_date.dt.year == 2024)]
    want = d.groupby("category")["revenue"].sum()
    got = {r["category"]: list(r.values())[1] for r in p["result_rows"]}
    assert got == pytest.approx(want.to_dict())
    assert "region = North" in p["interpretation"] and p["validation"]["status"] == "passed"
    assert all(c["title"] != "revenue by region" for c in p["charts"])  # charts describe the same filtered rows


def test_follow_up_uses_the_previous_question(client, auth, conv, sales_df):
    ask(client, auth, conv, "total revenue by region")
    a = ask(client, auth, conv, "what about only South?")
    p = a["payload"]
    assert p["resolved_question"] == "total revenue by region in South" and "Follow-up" in p["followup_note"]
    rows = {r["region"]: list(r.values())[1] for r in p["result_rows"]}
    assert rows == pytest.approx({"South": sales_df[sales_df.region == "South"].revenue.sum()})
    a = ask(client, auth, conv, "now by category")
    assert a["payload"]["resolved_question"] == "total revenue by category in South"
    a = ask(client, auth, conv, "average cost by region")  # a complete question is never rewritten
    assert a["payload"]["resolved_question"] == "average cost by region" and a["payload"]["followup_note"] is None


def test_unknown_column_gets_a_clear_answer_with_no_numbers(client, auth, conv):
    a = ask(client, auth, conv, "what is the total profit by region?")
    p = a["payload"]
    assert p["clarification"]["missing"] == ["profit"] and "won't guess" in a["content"]
    assert not p["result_rows"] and not p["charts"]
    b = ask(client, auth, conv, "total revenue for Furniture")
    assert b["payload"]["clarification"]["missing"] == ["Furniture"]
    # after a clarification the next question starts fresh rather than inheriting a failed one
    c = ask(client, auth, conv, "and by region?")
    assert c["payload"]["followup_note"] is None


def test_empty_filter_is_reported_not_replaced_by_sample_rows(client, auth, conv):
    a = ask(client, auth, conv, "total revenue in 2031")
    assert "No rows have year = 2031" in a["content"]
    assert a["payload"]["trace"] and a["payload"]["validation"]["status"] == "passed"


def test_forecast_is_labelled_estimate_and_verified(client, auth, conv, sales_df):
    a = ask(client, auth, conv, "weekly forecast of revenue for the next 4 weeks")
    p = a["payload"]
    assert "ESTIMATE" in a["content"] and "Confidence" in a["content"]
    assert p["validation"]["status"] == "passed" and any("re-summed with SQL" in c["detail"] for c in p["validation"]["checks"])
    ch = p["charts"][0]
    assert ch["type"] == "line" and "Forecast" in ch["y"] and sum("Forecast" in r for r in ch["data"]) >= 5
    assert p["recommendations"]


def test_forecast_of_missing_measure_is_refused(client, auth, conv):
    a = ask(client, auth, conv, "predict churn next month")
    assert a["payload"]["clarification"]["missing"] == ["churn"]


def test_how_many_counts_distinct_ids(client, auth, conv, sales_df):
    a = ask(client, auth, conv, "how many orders per region")
    got = {r["region"]: list(r.values())[1] for r in a["payload"]["result_rows"]}
    assert got == sales_df.groupby("region")["order_id"].nunique().to_dict()
