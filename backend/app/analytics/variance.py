"""Variance analysis: actual vs target and current vs previous period."""
import pandas as pd

from backend.app.analytics.utils import jsonable
from backend.app.core.exceptions import AppError

KINDS = {"revenue", "cost", "profit"}
GRAIN = {"week": "W", "month": "M", "quarter": "Q", "year": "Y"}


def _status(variance: float, kind: str, tol_pct: float, pct: float | None) -> str:
    if pct is not None and abs(pct) <= tol_pct:
        return "on_target"
    good = variance > 0 if kind != "cost" else variance < 0  # for costs, spending less than target is favourable
    return "favourable" if good else "unfavourable"


def _row(label: str, group: str | None, actual: float, base: float, kind: str, tol: float) -> dict:
    var = actual - base
    pct = (var / abs(base) * 100) if base else None
    return {"metric": label, "group": group, "kind": kind, "actual": actual, "comparator": base, "variance": var,
            "variance_pct": pct, "status": _status(var, kind, tol, pct)}


def _check_num(df: pd.DataFrame, col: str) -> None:
    if col not in df.columns:
        raise AppError(f"Unknown column '{col}'")
    if not pd.api.types.is_numeric_dtype(df[col]):
        raise AppError(f"'{col}' must be numeric")


def actual_vs_target(df: pd.DataFrame, metrics: list[dict], group_by: str | None = None, tolerance_pct: float = 0.0, derive_profit: dict | None = None) -> dict:
    """metrics: [{column, kind, target_column?|target_value?}]; target_value is a total (applied to the overall row only)."""
    if not metrics:
        raise AppError("Add at least one metric")
    if group_by and group_by not in df.columns:
        raise AppError(f"Unknown column '{group_by}'")
    d = df.copy()
    specs = []
    for m in metrics:
        col, kind = m.get("column"), m.get("kind", "revenue")
        if kind not in KINDS:
            raise AppError(f"Unknown kind '{kind}'")
        _check_num(d, col)
        tc, tv = m.get("target_column"), m.get("target_value")
        if tc:
            _check_num(d, tc)
        elif tv is None:
            raise AppError(f"Metric '{col}' needs a target column or a target value")
        specs.append((col, kind, tc, tv))
    if derive_profit:  # profit = revenue - cost, for both actual and target where available
        r, c = derive_profit.get("revenue"), derive_profit.get("cost")
        _check_num(d, r); _check_num(d, c)
        d["__profit_actual__"] = d[r] - d[c]
        rt = next((s[2] for s in specs if s[0] == r), None)
        ct = next((s[2] for s in specs if s[0] == c), None)
        if rt and ct:
            d["__profit_target__"] = d[rt] - d[ct]
            specs.append(("__profit_actual__", "profit", "__profit_target__", None))
        else:
            tvr = next((s[3] for s in specs if s[0] == r), None)
            tvc = next((s[3] for s in specs if s[0] == c), None)
            if tvr is not None and tvc is not None:
                specs.append(("__profit_actual__", "profit", None, float(tvr) - float(tvc)))
            else:
                raise AppError("Profit variance needs targets for both revenue and cost")
    rows = []
    groups = [(None, d)] if not group_by else [("All", d)] + [(str(k), g) for k, g in d.groupby(group_by, observed=True)]
    for gname, g in groups:
        for col, kind, tc, tv in specs:
            label = "Profit" if col == "__profit_actual__" else col
            actual = float(g[col].sum())
            if tc:
                base = float(g[tc].sum())
            elif gname in (None, "All"):
                base = float(tv)
            else:
                continue  # a single overall target value can't be split per group
            rows.append(_row(label, gname, actual, base, kind, tolerance_pct))
    summary = {"favourable": sum(r["status"] == "favourable" for r in rows), "unfavourable": sum(r["status"] == "unfavourable" for r in rows),
               "on_target": sum(r["status"] == "on_target" for r in rows)}
    chart_rows = [r for r in rows if r["group"] in (None, "All")] if group_by and any(r["group"] == "All" for r in rows) and len(metrics) > 1 else \
        [r for r in rows if r["group"] != "All"]
    chart = {"type": "bar", "title": "Variance vs target", "x": "label", "y": ["variance"], "signed": True,
             "data": [{"label": f"{r['group'] + ' · ' if r['group'] and r['group'] != 'All' else ''}{r['metric']}", "variance": r["variance"]} for r in chart_rows[:40]]}
    return jsonable({"mode": "target", "rows": rows, "summary": summary, "chart": chart,
                     "interpretation": _sentence(rows[0]) if rows else "No comparable rows"})


def period_over_period(df: pd.DataFrame, date_column: str, metrics: list[dict], period: str = "month", group_by: str | None = None,
                       tolerance_pct: float = 0.0, current: str | None = None, previous: str | None = None) -> dict:
    if period not in GRAIN:
        raise AppError(f"Unknown period '{period}'. Use: {', '.join(GRAIN)}")
    if date_column not in df.columns or not pd.api.types.is_datetime64_any_dtype(df[date_column]):
        raise AppError(f"'{date_column}' must be a date column")
    if not metrics:
        raise AppError("Add at least one metric")
    d = df.dropna(subset=[date_column]).copy()
    d["__p__"] = d[date_column].dt.to_period(GRAIN[period]).astype(str)
    periods = sorted(d["__p__"].unique())
    if len(periods) < 2:
        raise AppError(f"Need data in at least two {period}s to compare")
    cur = current or periods[-1]
    prev = previous or (periods[periods.index(cur) - 1] if cur in periods and periods.index(cur) > 0 else None)
    if cur not in periods or prev not in periods:
        raise AppError(f"Periods must be among: {periods[0]} … {periods[-1]}")
    rows, series = [], []
    for m in metrics:
        col, kind = m.get("column"), m.get("kind", "revenue")
        if kind not in KINDS:
            raise AppError(f"Unknown kind '{kind}'")
        _check_num(d, col)
        by = d.groupby("__p__")[col].sum().reindex(periods).fillna(0)
        for i in range(1, len(periods)):
            series.append({"period": periods[i], "metric": col, "value": float(by.iloc[i]), "previous": float(by.iloc[i - 1]),
                           "variance": float(by.iloc[i] - by.iloc[i - 1]),
                           "variance_pct": float((by.iloc[i] - by.iloc[i - 1]) / abs(by.iloc[i - 1]) * 100) if by.iloc[i - 1] else None})
        if group_by: 
            if group_by not in d.columns:
                raise AppError(f"Unknown column '{group_by}'")
            gp = d[d["__p__"].isin([cur, prev])].groupby([group_by, "__p__"])[col].sum().unstack(fill_value=0)
            for gk in gp.index:
                rows.append(_row(col, str(gk), float(gp.loc[gk].get(cur, 0)), float(gp.loc[gk].get(prev, 0)), kind, tolerance_pct))
        rows.insert(0 if not group_by else len([r for r in rows if r["metric"] != col]), _row(col, "All" if group_by else None, float(by[cur]), float(by[prev]), kind, tolerance_pct))
    first = next(m for m in metrics)
    chart_data = [{"period": s["period"], "variance": s["variance"]} for s in series if s["metric"] == first["column"]]
    chart = {"type": "bar", "title": f"{first['column']}: change vs previous {period}", "x": "period", "y": ["variance"], "signed": True, "data": chart_data}
    return jsonable({"mode": "period", "current_period": cur, "previous_period": prev, "periods": periods, "rows": rows, "series": series,
                     "summary": {"favourable": sum(r["status"] == "favourable" for r in rows), "unfavourable": sum(r["status"] == "unfavourable" for r in rows),
                                 "on_target": sum(r["status"] == "on_target" for r in rows)},
                     "chart": chart, "interpretation": _sentence(rows[0], cur, prev)})


def _sentence(r: dict, cur: str | None = None, prev: str | None = None) -> str:
    pct = f"{r['variance_pct']:+.1f}%" if r["variance_pct"] is not None else "n/a"
    base = f"{prev}" if prev else "target"
    word = {"favourable": "favourable", "unfavourable": "unfavourable", "on_target": "on target"}[r["status"]]
    return f"{r['metric']}: actual {r['actual']:,.2f} vs {base} {r['comparator']:,.2f} → variance {r['variance']:+,.2f} ({pct}), {word}."
