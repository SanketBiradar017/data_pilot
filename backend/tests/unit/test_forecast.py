import numpy as np
import pandas as pd
import pytest

from backend.app.analytics.forecast import fit_forecast, history_sql, parse_horizon, pick_grain, run_forecast, verify_forecast
from backend.app.analytics.nl2sql import parse_spec
from backend.app.analytics.sql_engine import run_query
from backend.app.core.exceptions import AppError


def monthly(values, start="2021-01-01"):
    """One row per day, so every month's total is exactly values[i]."""
    rows = []
    for i, v in enumerate(values):
        d = pd.Timestamp(start) + pd.DateOffset(months=i)
        days = pd.date_range(d, d + pd.offsets.MonthEnd(0))
        rows += [{"day": x, "revenue": v / len(days)} for x in days]
    return pd.DataFrame(rows)


def test_linear_series_is_continued_exactly():
    y = np.arange(100.0, 100 + 10 * 24, 10)  # 100,110,...: next values are 340,350,...
    fit = fit_forecast(y, 3, 12, True)
    assert fit["pred"] == pytest.approx([340, 350, 360], rel=1e-6)


def test_seasonal_pattern_is_recovered():
    season = np.array([10, 12, 15, 20, 30, 40, 38, 30, 20, 15, 12, 10], float)
    y = np.tile(season, 4) * (1 + 0.0 * np.arange(48))
    fit = fit_forecast(y, 6, 12, True)
    assert fit["pred"] == pytest.approx(season[:6], rel=1e-6)
    assert "season" in fit["model"] or "linear" in fit["model"]
    assert fit["confidence"] in ("high", "medium")


def test_forecast_is_never_negative_for_nonnegative_data():
    y = np.linspace(100, 5, 20)
    assert (fit_forecast(y, 12, 12, True)["pred"] >= 0).all()


def test_too_little_history_is_refused():
    df = monthly([100, 110, 120, 130, 140])
    spec = parse_spec("forecast revenue", df)
    with pytest.raises(AppError, match="at least 8"):
        run_forecast(df, spec, "monthly forecast revenue", "day", "revenue")


def test_partial_last_month_is_not_used_to_fit():
    df = monthly(list(range(100, 100 + 12 * 20, 20)))
    partial = pd.DataFrame({"day": pd.date_range("2022-01-01", periods=5), "revenue": 500.0})  # 5 days of January
    df = pd.concat([df, partial], ignore_index=True)
    res = run_forecast(df, parse_spec("forecast revenue", df), "monthly forecast revenue next 3 months", "day", "revenue")
    assert res["last_period"] == "2021-12" and any("partly covered" in n for n in res["notes"])
    assert res["forecast"][0]["label"] == "2022-01"


def test_history_matches_sql_and_forecast_reproduces():
    df = monthly(list(np.arange(100, 100 + 14 * 7, 7.0)))
    res = run_forecast(df, parse_spec("forecast revenue", df), "monthly forecast revenue next 4 months", "day", "revenue")
    assert res["horizon"] == 4 and res["periods_used"] == 14
    sql = run_query({"t": df}, history_sql(res, "t"))["dataframe"]
    assert verify_forecast(res, sql)[0]
    res["history"][3]["value"] += 50  # tampered history must be caught
    assert not verify_forecast(res, sql)[0]


def test_ranges_and_backtest_are_reported():
    rng = np.random.default_rng(0)
    df = monthly(list(200 + rng.normal(0, 25, 30)))
    res = run_forecast(df, parse_spec("forecast revenue", df), "monthly forecast revenue", "day", "revenue")
    f = res["forecast"][0]
    assert f["lower"] < f["value"] < f["upper"]
    assert res["confidence"] in ("low", "medium", "high") and res["backtest"]["rmse"] > 0


def test_horizon_and_grain_parsing():
    assert parse_horizon("forecast the next 6 months", "month") == (6, "next 6 months")
    assert parse_horizon("what about next quarter", "month")[0] == 3
    assert parse_horizon("forecast next year", "month")[0] == 12
    assert parse_horizon("forecast revenue", "month") == (3, None)
    assert pick_grain(900, "forecast") == "month" and pick_grain(100, "forecast") == "week" and pick_grain(20, "weekly") == "week"
