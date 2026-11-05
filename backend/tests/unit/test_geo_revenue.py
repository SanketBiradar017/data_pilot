import pandas as pd

from backend.app import geo as g
from backend.app.analytics import geo_revenue as gr


def test_name_resolution():
    for v in ("US", "usa", "United States of America", "U.S.A.", "united states"):
        assert g.resolve_country(v) == "USA"
    assert g.resolve_country("UK") == "GBR" and g.resolve_country("Côte d'Ivoire") == "CIV" and g.resolve_country("IN") == "IND"
    assert g.resolve_country("Narnia") is None
    assert g.resolve_state("USA", "CA") == "California" and g.resolve_state("USA", "new york") == "New York"
    assert g.resolve_state("IND", "Maharashtra") == "Maharashtra"


def test_region_column_content_beats_header():
    east_west = pd.DataFrame({"region": ["East", "West"] * 10, "revenue": range(20)})
    assert gr.detect_columns(east_west)["mapping"]["state"] is None
    us = pd.DataFrame({"region": ["Texas", "Ohio"] * 10, "revenue": range(20)})
    d = gr.detect_columns(us)
    assert d["mapping"]["state"] == "region" and d["assumed_country"] == "USA"


def test_string_amounts_and_profit_only():
    df = pd.DataFrame({"country": ["India", "India", "France"], "profit": ["$1,000", "(400)", "-50"]})
    m = {"country": "country", "profit": "profit"}
    f = gr.prepare(df, m)
    r = gr.summarize(f, "world")
    ind = next(x for x in r["regions"] if x["key"] == "IND")
    assert ind["profit"] == 600.0 and ind["loss"] == 400.0
    assert r["totals"]["revenue"] is None and r["capabilities"]["revenue"] is True  # profit-only data has no revenue figure


def test_validation_errors():
    import pytest

    from backend.app.core.exceptions import AppError
    df = pd.DataFrame({"a": ["x"], "b": ["y"]})
    with pytest.raises(AppError):
        gr.prepare(df, {"country": "a", "revenue": "b"})
    with pytest.raises(AppError):
        gr.prepare(df, {"revenue": "b"})


def test_state_column_mixing_countries_and_top_bottom_disjoint():
    df = pd.DataFrame({"State": ["California", "Maharashtra", "Bavaria", "Texas"] * 5, "Revenue": range(20)})
    assert gr.detect_columns(df)["mapping"]["state"] == "State"
    f = gr.prepare(pd.DataFrame({"country": ["India", "France", "Peru"], "revenue": [3, 2, 1]}), {"country": "country", "revenue": "revenue"})
    r = gr.summarize(f, "world")
    assert {x["key"] for x in r["top"]}.isdisjoint({x["key"] for x in r["bottom"]})
