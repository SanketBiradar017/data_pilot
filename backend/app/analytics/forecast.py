"""Time-series forecasting for chat questions ("forecast revenue for the next 6 months").

Honesty rules:
  * history is summed from the raw rows (re-summed with SQL during validation)
  * the first/last period are dropped when only partly covered by the data
  * several simple models are backtested on the most recent periods and the best one is used
  * the result carries its own backtest error and a confidence label, and every forecast figure is marked an ESTIMATE
"""
import re
import warnings

import numpy as np
import pandas as pd

from backend.app.analytics.question import FREQ, apply_filters, metric_series
from backend.app.core.exceptions import AppError

SEASON = {"D": 7, "W": 52, "M": 12, "Q": 4, "Y": 0}
DAYS = {"day": 1.0, "week": 7.0, "month": 30.44, "quarter": 91.31, "year": 365.25}
MAX_HORIZON = 24
MIN_PERIODS = 8


def pick_grain(span_days: float, question: str) -> str:
    """The period to model: the one the question names, else the one it asks about ("next 3 months" -> months) when the
    history has enough of them, else a finer one."""
    ql = question.lower()
    for g, rx in (("day", r"\bdaily\b|\bper day\b|\bby day\b"), ("week", r"\bweekly\b|\bper week\b|\bby week\b"),
                  ("month", r"\bmonthly\b|\bper month\b|\bby month\b"), ("quarter", r"\bquarterly\b|\bby quarter\b")):
        if re.search(rx, ql):
            return g
    m = re.search(r"next\s+(?:\d+\s+)?(day|week|month|quarter|year)", ql)
    if m:
        want = {"day": "day", "week": "week", "month": "month", "quarter": "month", "year": "month"}[m.group(1)]
        for g in ("month", "week", "day")[("month", "week", "day").index(want):]:
            if span_days / DAYS[g] >= MIN_PERIODS + 2:
                return g
        return "day"
    return "month" if span_days >= 365 * 1.5 else "week" if span_days >= 60 else "day"


def parse_horizon(question: str, grain: str) -> tuple[int, str | None]:
    """-> (periods ahead, phrase used). Converts 'next quarter' into the data's grain."""
    ql = question.lower()
    m = re.search(r"next\s+(\d+)\s+(day|week|month|quarter|year)s?", ql) or re.search(r"(\d+)\s+(day|week|month|quarter|year)s?\s+(?:ahead|from now|out)", ql)
    if m:
        n, unit = int(m.group(1)), m.group(2)
    else:
        m = re.search(r"next\s+(day|week|month|quarter|year)\b", ql)
        if not m:
            return 3, None
        n, unit = 1, m.group(1)
    periods = max(1, round(n * DAYS[unit] / DAYS[grain]))
    return periods, f"next {n} {unit}{'s' if n > 1 else ''}"


def period_series(df: pd.DataFrame, date_col: str, spec: dict, grain: str) -> tuple[pd.Series, list[str]]:
    """Sum (or mean / count) the metric per complete period. Returns the series and notes about what was adjusted."""
    notes: list[str] = []
    d = apply_filters(df, spec.get("filters") or []).dropna(subset=[date_col])
    if d.empty:
        raise AppError("No rows with a date remain after applying the filters, so there is nothing to forecast.")
    freq = FREQ[grain]
    per = d[date_col].dt.to_period(freq)
    agg = spec.get("agg") or "SUM"
    if agg == "COUNT":
        s = (d.groupby(per)[spec["distinct"]].nunique() if spec.get("distinct") else d.groupby(per).size()).astype(float)
    else:
        v = metric_series(d, spec)
        s = v.groupby(per).agg({"SUM": lambda x: x.sum(min_count=1), "AVG": "mean"}.get(agg, "mean")).astype(float)
    lo, hi = d[date_col].min(), d[date_col].max()
    full = pd.period_range(s.index.min(), s.index.max(), freq=freq)
    s = s.reindex(full)
    first, last = full[0], full[-1]
    span = lambda p: (p.end_time.normalize() - p.start_time.normalize()).days + 1  # noqa: E731
    if grain != "day" and (hi.normalize() - last.start_time.normalize()).days + 1 < 0.8 * span(last) and len(s) > 1:
        s = s.iloc[:-1]
        notes.append(f"The last {grain} ({last}) is only partly covered by the data, so it was left out of the model.")
    if grain != "day" and len(s) > 1 and (first.end_time.normalize() - lo.normalize()).days + 1 < 0.8 * span(first):
        s = s.iloc[1:]
        notes.append(f"The first {grain} ({first}) is only partly covered by the data, so it was left out of the model.")
    gaps = int(s.isna().sum())
    if gaps:
        if gaps > 0.2 * len(s):
            raise AppError(f"{gaps} of {len(s)} {grain}s have no data, which is too many gaps to forecast reliably.")
        s = s.interpolate(limit_direction="both")
        notes.append(f"{gaps} {grain}(s) with no rows were filled by linear interpolation.")
    return s, notes


# ---------------------------------------------------------------- models: each maps (history, h, season) -> forecast
def _linear_design(n: int, h: int, m: int, seasonal: bool) -> tuple[np.ndarray, np.ndarray]:
    t = np.arange(n + h)
    cols = [np.ones_like(t, dtype=float), t.astype(float)]
    if seasonal and m:
        cols += [(t % m == k).astype(float) for k in range(1, m)]
    X = np.column_stack(cols)
    return X[:n], X[n:]


def _m_naive(y, h, m):
    return np.repeat(y[-1], h)


def _m_seasonal_naive(y, h, m):
    return np.array([y[len(y) - m + (i % m)] for i in range(h)])


def _m_linear(y, h, m):
    X, Xf = _linear_design(len(y), h, m, False)
    return Xf @ np.linalg.lstsq(X, y, rcond=None)[0]


def _m_linear_seasonal(y, h, m):
    X, Xf = _linear_design(len(y), h, m, True)
    return Xf @ np.linalg.lstsq(X, y, rcond=None)[0]


def _m_holt(y, h, m):
    from statsmodels.tsa.holtwinters import ExponentialSmoothing

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        seasonal = "add" if m and len(y) >= 2 * m else None
        fit = ExponentialSmoothing(y, trend="add", damped_trend=True, seasonal=seasonal, seasonal_periods=m if seasonal else None,
                                   initialization_method="estimated").fit()
        return np.asarray(fit.forecast(h))


def _candidates(n: int, m: int) -> dict:
    c = {"naive (repeat the last period)": _m_naive, "linear trend": _m_linear, "damped trend (exponential smoothing)": _m_holt}
    if m and n >= 2 * m + 2:
        c["seasonal naive (same period last cycle)"] = _m_seasonal_naive
        c["linear trend + seasonality"] = _m_linear_seasonal
    return c


def fit_forecast(y: np.ndarray, h: int, m: int, nonneg: bool) -> dict:
    """Pick the model with the lowest backtest error on the latest periods, then refit on all history."""
    n = len(y)
    hb = max(2, min(h, n // 3))
    train, test = y[:-hb], y[-hb:]
    models = _candidates(len(train), m)
    scores = {}
    for name, fn in models.items():
        try:
            pred = fn(train, hb, m)
            if nonneg:
                pred = np.maximum(pred, 0)
            err = test - pred
            scores[name] = {"rmse": float(np.sqrt(np.mean(err ** 2))), "mae": float(np.mean(np.abs(err))),
                            "mape": float(np.mean(np.abs(err[test != 0] / test[test != 0])) * 100) if np.any(test != 0) else None}
        except Exception:
            continue
    if not scores:
        raise AppError("Could not fit any forecasting model to this series.")
    best = min(scores, key=lambda k: scores[k]["rmse"])
    naive_name = next(iter(models))
    full_models = _candidates(n, m)
    fn = full_models.get(best, _m_naive)
    pred = fn(y, h, m)
    if nonneg:
        pred = np.maximum(pred, 0)
    rmse = scores[best]["rmse"]
    skill = 1 - rmse / scores[naive_name]["rmse"] if scores[naive_name]["rmse"] > 0 else 0.0
    mape = scores[best]["mape"]
    conf = "low" if (n < 12 or mape is None or mape > 25 or skill < 0) else "high" if (mape < 10 and n >= 18) else "medium"
    half = 1.28 * rmse  # about an 80% range if backtest errors are roughly normal
    lower, upper = pred - half, pred + half
    if nonneg:
        lower = np.maximum(lower, 0)
    return {"model": best, "pred": pred, "lower": lower, "upper": upper, "confidence": conf,
            "backtest": {"periods": hb, **scores[best], "naive_rmse": scores[naive_name]["rmse"], "skill_vs_naive": float(skill),
                         "tried": sorted(scores, key=lambda k: scores[k]["rmse"])}}


def run_forecast(df: pd.DataFrame, spec: dict, question: str, date_col: str, metric_label: str) -> dict:
    d = df.dropna(subset=[date_col])
    span_days = float((d[date_col].max() - d[date_col].min()).days) if len(d) else 0.0
    grain = pick_grain(span_days, question)
    horizon, phrase = parse_horizon(question, grain)
    s, notes = period_series(df, date_col, spec, grain)
    n = len(s)
    if n < MIN_PERIODS:
        raise AppError(f"A forecast needs at least {MIN_PERIODS} complete {grain}s of history; this data has {n}. "
                       f"Showing a prediction from so little data would be misleading.")
    if horizon > MAX_HORIZON or horizon > max(1, n // 2):
        cap = min(MAX_HORIZON, max(1, n // 2))
        notes.append(f"The horizon was limited to {cap} {grain}(s); looking further ahead than half the history is not reliable.")
        horizon = cap
    m = SEASON[FREQ[grain]]
    nonneg = bool((s >= 0).all())
    fit = fit_forecast(s.to_numpy(float), horizon, m, nonneg)
    idx = pd.period_range(s.index[-1] + 1, periods=horizon, freq=FREQ[grain])
    hist = [{"t": str(p.start_time.date()), "label": str(p), "value": float(v)} for p, v in s.items()]
    fc = [{"t": str(p.start_time.date()), "label": str(p), "value": float(v), "lower": float(lo), "upper": float(up)}
          for p, v, lo, up in zip(idx, fit["pred"], fit["lower"], fit["upper"], strict=True)]
    recent = float(s.iloc[-horizon:].sum()) if (spec.get("agg") or "SUM") in ("SUM", "COUNT") else float(s.iloc[-horizon:].mean())
    future = float(sum(f["value"] for f in fc)) if (spec.get("agg") or "SUM") in ("SUM", "COUNT") else float(np.mean([f["value"] for f in fc]))
    return {"metric": metric_label, "date_col": date_col, "grain": grain, "horizon": horizon, "horizon_phrase": phrase,
            "agg": spec.get("agg") or "SUM", "periods_used": n, "first_period": str(s.index[0]), "last_period": str(s.index[-1]),
            "history": hist, "forecast": fc, "model": fit["model"], "confidence": fit["confidence"], "backtest": fit["backtest"],
            "recent_total": recent, "forecast_total": future, "change_pct": ((future - recent) / abs(recent) * 100) if recent else None,
            "season": m, "notes": notes, "spec": spec}


def history_sql(res: dict, table: str) -> str:
    """The same per-period figures as plain SQL, run by DuckDB during validation."""
    from backend.app.analytics.nl2sql import _agg, _count, _q
    from backend.app.analytics.question import filters_sql

    spec, agg = res["spec"], res["agg"]
    expr = _count(spec) if agg == "COUNT" else _agg(spec, "SUM" if agg == "SUM" else "AVG")[0]
    where = " AND ".join(x for x in (filters_sql(spec.get("filters") or []), f"{_q(res['date_col'])} IS NOT NULL") if x)
    return (f"SELECT DATE_TRUNC('{res['grain']}', {_q(res['date_col'])}) AS p, {expr} AS v\nFROM {table}\nWHERE {where}\nGROUP BY 1\nORDER BY 1")


def verify_forecast(res: dict, sql_df: pd.DataFrame) -> tuple[bool, str]:
    """History must equal the SQL re-sum for every period that has rows, and the forecast must be reproducible from it."""
    by = {str(pd.Timestamp(p).date()): v for p, v in zip(sql_df["p"], sql_df["v"], strict=True)}
    bad = [h["t"] for h in res["history"] if h["t"] in by and by[h["t"]] is not None and abs(float(by[h["t"]]) - h["value"]) > 1e-6 * max(1.0, abs(h["value"]))]
    if bad:
        return False, f"history differs from SQL in {len(bad)} period(s), first {bad[0]}"
    y = np.array([h["value"] for h in res["history"]], float)
    again = fit_forecast(y, res["horizon"], res["season"], bool((y >= 0).all()))
    same = np.allclose(again["pred"], [f["value"] for f in res["forecast"]], rtol=1e-6, atol=1e-6)
    return same, f"{len(res['history'])} period(s) re-summed with SQL match; forecast {'reproduced' if same else 'NOT reproduced'} from them"
