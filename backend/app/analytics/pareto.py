"""Pareto (80/20) and ABC classification."""
import pandas as pd

from backend.app.analytics.utils import jsonable
from backend.app.core.exceptions import AppError


def run_pareto(df: pd.DataFrame, category: str, value: str | None = None, a_cut: float = 80.0, b_cut: float = 95.0, top_chart: int = 30) -> dict:
    if category not in df.columns:
        raise AppError(f"Unknown column '{category}'")
    if not 0 < a_cut < b_cut <= 100:
        raise AppError("Thresholds must satisfy 0 < A < B <= 100")
    notes = []
    if value:
        if value not in df.columns or not pd.api.types.is_numeric_dtype(df[value]):
            raise AppError(f"'{value}' must be a numeric column")
        d = df[[category, value]].dropna(subset=[category])
        neg = int((d[value] < 0).sum())
        if neg:
            notes.append(f"{neg} negative value(s) were excluded from the ranking.")
            d = d[d[value] >= 0]
        s = d.groupby(category)[value].sum()
        measure = f"SUM of {value}"
    else:
        s = df[category].dropna().value_counts()
        measure = "COUNT of rows"
    s = s[s > 0].sort_values(ascending=False)
    if s.empty or s.sum() == 0:
        raise AppError("No positive values to analyse")
    total = float(s.sum())
    share = s / total * 100
    cum = share.cumsum()
    n = len(s)
    classes = []
    prev_cum = 0.0
    for c in cum:
        # an item is in class A if the cumulative share *before* it is still below the A threshold
        classes.append("A" if prev_cum < a_cut else "B" if prev_cum < b_cut else "C")
        prev_cum = c
    rows = [{"rank": i + 1, "category": str(k), "value": float(s.iloc[i]), "share_pct": float(share.iloc[i]),
             "cum_pct": float(min(cum.iloc[i], 100.0)), "class": classes[i]} for i, k in enumerate(s.index)]
    counts = {k: classes.count(k) for k in "ABC"}
    vals = {k: float(sum(r["value"] for r in rows if r["class"] == k)) for k in "ABC"}
    summary = [{"class": k, "items": counts[k], "items_pct": counts[k] / n * 100, "value": vals[k], "value_pct": vals[k] / total * 100} for k in "ABC"]
    k80 = next(i + 1 for i, r in enumerate(rows) if r["cum_pct"] >= 80 - 1e-9)
    pct80 = k80 / n * 100
    verdict = (f"{k80} of {n} {category} values ({pct80:.1f}%) account for 80% of {measure}."
               + (" This follows the 80/20 rule closely." if pct80 <= 25 else " The distribution is more even than 80/20." if pct80 > 40 else ""))
    chart_rows = rows[:top_chart]
    return jsonable({
        "category": category, "measure": measure, "total": total, "n_items": n, "thresholds": {"a": a_cut, "b": b_cut},
        "rows": rows, "summary": summary, "items_for_80pct": k80, "items_for_80pct_pct": pct80, "interpretation": verdict, "notes": notes,
        "chart": {"type": "pareto", "title": f"Pareto of {measure} by {category}" + (f" (top {top_chart})" if n > top_chart else ""),
                  "x": "category", "y": ["value", "cum_pct"], "data": chart_rows},
    })
