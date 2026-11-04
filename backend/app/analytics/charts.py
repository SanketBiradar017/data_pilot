"""Chart specs consumed by the React frontend (Recharts). Data is embedded, so charts are
always backed by real query/analysis output."""
import numpy as np
import pandas as pd

from backend.app.analytics.utils import (
    categorical_cols,
    frame_records,
    hist_rows,
    jsonable,
    numeric_cols,
)


def spec(kind: str, title: str, data: list[dict], x: str, y: list[str], **extra) -> dict:
    return jsonable({"type": kind, "title": title, "x": x, "y": y, "data": data, **extra})


def auto_charts(df: pd.DataFrame, eda: dict | None = None, max_charts: int = 6) -> list[dict]:
    charts: list[dict] = []
    nums, cats = numeric_cols(df), categorical_cols(df, 25)
    eda = eda or {}

    for t in [t for t in (eda.get("trends") or []) if t["direction"] != "flat"][:2]:
        pts = [{"t": p["t"][:10], t["metric"]: p["value"]} for p in t["points"]]
        fc = [{"t": p["t"][:10], "forecast": p["value"]} for p in t["forecast"]]
        if pts and fc:
            pts[-1]["forecast"] = pts[-1][t["metric"]]
        charts.append(spec("line", f"{t['metric']} over time ({t['direction']})", pts + fc, "t",
                           [t["metric"], "forecast"], note="Dashed line is a 3-period linear projection"))

    if cats and nums:
        c = min(cats, key=lambda k: abs(df[k].nunique() - 8))
        m = next((n for h in ("revenue", "sales", "amount", "total", "profit", "cost", "price") for n in nums if h in n.lower()), nums[0])
        g = df.groupby(c)[m].sum().sort_values(ascending=False).head(12).reset_index()
        charts.append(spec("bar", f"{m} by {c}", frame_records(g), c, [m]))
        if df[c].nunique() <= 8:
            charts.append(spec("pie", f"Share of {m} by {c}", frame_records(g), c, [m]))

    for n in nums[:2]:
        d = df[n].dropna()
        if len(d) > 5:
            rows, integer = hist_rows(d, min(20, max(5, int(np.sqrt(len(d))))))
            charts.append(spec("histogram", f"Distribution of {n}", rows, "bin", ["count"], integer=integer, total=int(len(d))))

    corr = (eda.get("correlations") or {})
    if corr.get("pairs"):
        p = corr["pairs"][0]
        sample = df[[p["a"], p["b"]]].dropna().sample(min(400, len(df)), random_state=0)
        charts.append(spec("scatter", f"{p['a']} vs {p['b']} (r={p['r']:.2f})", frame_records(sample), p["a"], [p["b"]]))
    if len(corr.get("columns", [])) >= 3:
        charts.append(spec("heatmap", "Correlation matrix", corr["matrix"], "x", ["y"], columns=corr["columns"]))
    return charts[:max_charts]


def chart_from_result(df: pd.DataFrame, title: str) -> dict | None:
    """Pick a sensible chart for an arbitrary query result."""
    if df is None or df.empty or len(df.columns) < 2 or len(df) < 2:
        return None
    d = df.head(200)
    first = d.columns[0]
    nums = [c for c in d.columns[1:] if pd.api.types.is_numeric_dtype(d[c])]
    if not nums:
        return None
    if pd.api.types.is_datetime64_any_dtype(d[first]) or "period" in str(first).lower():
        data = [{**r, first: str(r[first])[:10]} for r in frame_records(d)]
        return spec("line", title, data, first, nums[:3])
    if pd.api.types.is_numeric_dtype(d[first]) and len(nums) >= 1 and len(d.columns) == 2:
        return spec("scatter", title, frame_records(d), first, nums[:1])
    return spec("bar", title, frame_records(d.head(25)), first, nums[:3])
