"""Pivot table engine (pandas). Rows × columns × values with filters and totals."""
from typing import Any

import pandas as pd

from backend.app.analytics.utils import frame_records, jsonable
from backend.app.core.exceptions import AppError

AGGS = {"sum": "sum", "count": "count", "avg": "mean", "min": "min", "max": "max"}
OPS = {"eq", "ne", "gt", "gte", "lt", "lte", "in", "not_in", "contains", "between"}
MAX_ROWS, MAX_COL_COMBOS = 2000, 60
TOTAL = "Total"


def _check_cols(df: pd.DataFrame, cols: list[str]) -> None:
    for c in cols:
        if c not in df.columns:
            raise AppError(f"Unknown column '{c}'")


def apply_filters(df: pd.DataFrame, filters: list[dict]) -> pd.DataFrame:
    for f in filters or []:
        col, op, val = f.get("column"), f.get("op", "eq"), f.get("value")
        _check_cols(df, [col])
        if op not in OPS:
            raise AppError(f"Unknown filter operator '{op}'")
        s = df[col]
        numeric = pd.api.types.is_numeric_dtype(s)
        datetime = pd.api.types.is_datetime64_any_dtype(s)

        def conv(v: Any):
            if numeric:
                return float(v)
            if datetime:
                return pd.to_datetime(v)
            return str(v)

        try:
            if op in ("in", "not_in"):
                vals = [conv(v) for v in (val if isinstance(val, list) else [val])]
                mask = s.isin(vals) if not numeric else s.isin(vals)
                if op == "not_in":
                    mask = ~mask
            elif op == "contains":
                mask = s.astype(str).str.contains(str(val), case=False, na=False, regex=False)
            elif op == "between":
                lo, hi = conv(val[0]), conv(val[1])
                mask = s.between(lo, hi)
            else:
                v = conv(val)
                mask = {"eq": s == v, "ne": s != v, "gt": s > v, "gte": s >= v, "lt": s < v, "lte": s <= v}[op]
        except (ValueError, TypeError, IndexError) as e:
            raise AppError(f"Invalid filter value for '{col}': {e}") from e
        df = df[mask]
    return df


def _label(agg: str, col: str) -> str:
    return f"{agg.upper()} of {col}" if col != "*" else "COUNT"


def pivot(df: pd.DataFrame, rows: list[str], columns: list[str], values: list[dict],
          filters: list[dict] | None = None, totals: bool = True) -> dict:
    if not values:
        raise AppError("Add at least one value field (e.g. SUM of revenue)")
    if not rows and not columns:
        raise AppError("Add at least one row or column field")
    spec = []
    for v in values:
        agg, col = v.get("agg", "sum"), v.get("column", "*")
        if agg not in AGGS:
            raise AppError(f"Unknown aggregation '{agg}'. Use: {', '.join(AGGS)}")
        if col != "*":
            _check_cols(df, [col])
            if agg in ("sum", "avg") and not pd.api.types.is_numeric_dtype(df[col]):
                raise AppError(f"{agg.upper()} needs a numeric column; '{col}' is not numeric")
        elif agg != "count":
            raise AppError("Only COUNT can be used without a column")
        spec.append((agg, col))
    _check_cols(df, rows + columns)
    if set(rows) & set(columns):
        raise AppError("A field cannot be in both rows and columns")

    d = apply_filters(df, filters or [])
    if d.empty:
        raise AppError("No rows match the filters")
    d = d.copy()
    for c in rows + columns:  # keep missing categories visible instead of silently dropping them
        if not pd.api.types.is_numeric_dtype(d[c]) or d[c].isna().any():
            d[c] = d[c].astype(object).where(d[c].notna(), "(blank)")
    if columns and d[columns].drop_duplicates().shape[0] > MAX_COL_COMBOS:
        raise AppError(f"Too many column combinations (> {MAX_COL_COMBOS}). Use fewer/lower-cardinality column fields or filter first.")

    # count of "*" -> count a helper column
    d["__one__"] = 1
    agg_map: dict[str, list[str]] = {}
    for agg, col in spec:
        agg_map.setdefault("__one__" if col == "*" else col, []).append(AGGS[agg])

    group_keys = rows + columns
    g = d.groupby(group_keys, dropna=False, sort=True, observed=True).agg(agg_map)
    g.columns = [f"{a}::{c}" for c, a in g.columns]  # c=column, a=aggfunc name
    inv = {v: k for k, v in AGGS.items()}
    # reorder & rename to requested value labels
    want = []
    for agg, col in spec:
        src = f"{AGGS[agg]}::{'__one__' if col == '*' else col}"
        want.append((src, _label(agg, col)))
    g = g[[w[0] for w in want]]
    g.columns = [w[1] for w in want]
    del inv

    def totals_for(frame: pd.DataFrame) -> list[Any]:
        out = []
        for agg, col in spec:
            s = frame["__one__"] if col == "*" else frame[col]
            out.append(getattr(s, AGGS[agg])())
        return out

    if columns:
        wide = g.unstack(columns)  # columns: (value label, *column keys)
        flat = {}
        multi_val = len(spec) > 1
        labels = [w[1] for w in want]
        keys = sorted({tuple(k[1:]) if isinstance(k, tuple) else () for k in wide.columns})
        for ck in keys:  # category-major, value fields in the order requested
            for label in labels:
                name = " | ".join(str(x) for x in ck)
                flat[f"{name} · {label}" if multi_val else name] = wide[(label, *ck)]
        table = pd.DataFrame(flat)
        if totals:
            if rows:
                row_tot = d.groupby(rows, dropna=False, observed=True).apply(lambda f: pd.Series(totals_for(f), index=[w[1] for w in want]), include_groups=False)
                for lbl in [w[1] for w in want]:
                    table[f"{TOTAL} · {lbl}" if multi_val else TOTAL] = row_tot[lbl]
            else:
                tot = totals_for(d)
                for lbl, t in zip([w[1] for w in want], tot):
                    table[f"{TOTAL} · {lbl}" if multi_val else TOTAL] = t
        table = table.reset_index() if rows else table.reset_index(drop=True)
    else:
        table = g.reset_index()

    if len(table) > MAX_ROWS:
        raise AppError(f"Result has {len(table):,} rows (limit {MAX_ROWS}). Add filters or use fewer row fields.")
    grand = None
    if totals and rows:
        tot = totals_for(d)
        grand = {rows[0]: f"Grand {TOTAL}", **{c: None for c in rows[1:]}}
        if columns:
            for c in table.columns[len(rows):]:
                part = str(c).split(" · ")
                lbl = part[-1] if len(part) > 1 else want[0][1]
                col_key = part[0]
                if col_key == TOTAL:
                    grand[c] = tot[[w[1] for w in want].index(lbl)] if lbl in [w[1] for w in want] else tot[0]
                else:
                    sub = d
                    for cname, cval in zip(columns, col_key.split(" | ")):
                        sub = sub[sub[cname].astype(str) == cval]
                    ai = [w[1] for w in want].index(lbl) if lbl in [w[1] for w in want] else 0
                    grand[c] = totals_for(sub)[ai] if len(sub) else None
        else:
            for lbl, t in zip([w[1] for w in want], tot):
                grand[lbl] = t
    recs = frame_records(table)
    if grand:
        grand["__total__"] = True
        recs.append(jsonable(grand))
    cols = [str(c) for c in table.columns]
    return {"row_fields": rows, "column_fields": columns, "value_labels": [w[1] for w in want],
            "columns": cols, "rows": recs, "row_count": len(table), "source_rows": int(len(d)),
            "has_totals": bool(grand)}


def pivot_chart(result: dict) -> dict | None:
    """Clustered bar chart of the pivot (excludes total row/column)."""
    nrows = len(result["row_fields"])
    value_cols = [c for c in result["columns"][nrows:] if not str(c).split(" · ")[0] == TOTAL and c != TOTAL]
    body = [r for r in result["rows"] if not r.get("__total__")]
    if not value_cols or not body:
        return None
    if nrows:
        data = [{"label": " / ".join(str(r[f]) for f in result["row_fields"]), **{c: r.get(c) for c in value_cols}} for r in body[:40]]
    else:
        data = [{"label": "All", **{c: body[0].get(c) for c in value_cols}}]
    return {"type": "bar", "title": "Pivot result", "x": "label", "y": value_cols[:8], "data": jsonable(data)}


def pivot_to_frame(result: dict) -> pd.DataFrame:
    df = pd.DataFrame([{k: v for k, v in r.items() if k != "__total__"} for r in result["rows"]])
    return df[result["columns"]] if not df.empty else df
