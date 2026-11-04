import numpy as np
import pandas as pd

from backend.app.analytics.utils import categorical_cols, datetime_cols, hist_rows, jsonable, numeric_cols


def _semantic_type(s: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(s):
        return "boolean"
    if pd.api.types.is_numeric_dtype(s):
        return "numeric"
    if pd.api.types.is_datetime64_any_dtype(s):
        return "datetime"
    nn = s.dropna()
    if len(nn) and nn.nunique() / len(nn) > 0.9 and nn.astype(str).str.len().mean() > 30:
        return "text"
    return "categorical" if nn.nunique() <= 50 else "text"


def profile_column(s: pd.Series) -> dict:
    n = len(s)
    nn = s.dropna()
    p: dict = {
        "name": str(s.name),
        "dtype": str(s.dtype),
        "type": _semantic_type(s),
        "missing": int(s.isna().sum()),
        "missing_pct": round(float(s.isna().mean() * 100), 2) if n else 0.0,
        "unique": int(nn.nunique()),
        "unique_pct": round(float(nn.nunique() / len(nn) * 100), 2) if len(nn) else 0.0,
    }
    if p["type"] == "numeric" and len(nn):
        d = nn.astype(float)
        q1, q3 = d.quantile(0.25), d.quantile(0.75)
        p.update(
            min=d.min(), max=d.max(), mean=d.mean(), median=d.median(), std=d.std() if len(d) > 1 else 0.0,
            q1=q1, q3=q3, skew=d.skew() if len(d) > 2 else 0.0, zeros=int((d == 0).sum()),
            negatives=int((d < 0).sum()),
        )
        rows, integer = hist_rows(d, min(20, max(5, int(np.sqrt(len(d))))))
        p["histogram"], p["integer"] = rows, integer
    elif p["type"] == "datetime" and len(nn):
        p.update(min=nn.min(), max=nn.max(), span_days=(nn.max() - nn.min()).days)
    elif len(nn):
        vc = nn.astype(str).value_counts().head(10)
        p["top_values"] = [{"value": k, "count": int(v), "pct": round(v / len(nn) * 100, 2)} for k, v in vc.items()]
        p["avg_length"] = float(nn.astype(str).str.len().mean())
    return jsonable(p)


def profile_dataframe(df: pd.DataFrame) -> dict:
    cols = [profile_column(df[c]) for c in df.columns]
    return jsonable(
        {
            "rows": len(df),
            "columns": len(df.columns),
            "memory_bytes": int(df.memory_usage(deep=True).sum()),
            "numeric_columns": numeric_cols(df),
            "categorical_columns": categorical_cols(df),
            "datetime_columns": datetime_cols(df),
            "duplicate_rows": int(df.duplicated().sum()),
            "missing_cells": int(df.isna().sum().sum()),
            "column_profiles": cols,
        }
    )
