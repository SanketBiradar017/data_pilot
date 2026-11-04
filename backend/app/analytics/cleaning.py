"""Deterministic, logged data-cleaning operations."""
import pandas as pd

from backend.app.analytics.utils import categorical_cols, infer_types, is_text, numeric_cols
from backend.app.core.exceptions import AppError

OPS = {"infer_types", "trim_whitespace", "standardize_case", "drop_duplicates", "fill_missing",
       "drop_missing_rows", "drop_column", "clip_outliers", "auto_clean"}


def apply_operation(df: pd.DataFrame, op: str, column: str | None = None, strategy: str | None = None) -> tuple[pd.DataFrame, str]:
    if op not in OPS:
        raise AppError(f"Unknown cleaning operation '{op}'")
    if column and column not in df.columns:
        raise AppError(f"Unknown column '{column}'")
    df = df.copy()
    before_rows = len(df)

    if op == "auto_clean":
        msgs = []
        for step in ("infer_types", "trim_whitespace", "drop_duplicates", "fill_missing", "clip_outliers"):
            df, m = apply_operation(df, step)
            msgs.append(m)
        return df, "Auto-clean: " + "; ".join(msgs)

    if op == "infer_types":
        new = infer_types(df)
        changed = [c for c in df.columns if str(df[c].dtype) != str(new[c].dtype)]
        return new, f"Inferred types for {len(changed)} column(s)" + (f": {', '.join(changed)}" if changed else "")

    if op == "trim_whitespace":
        cols = [column] if column else [c for c in df.columns if is_text(df[c])]
        for c in cols:
            if is_text(df[c]):
                df[c] = df[c].map(lambda v: v.strip() if isinstance(v, str) else v)
        return df, f"Trimmed whitespace in {len(cols)} column(s)"

    if op == "standardize_case":
        cols = [column] if column else categorical_cols(df)
        n = 0
        for c in cols:
            if not is_text(df[c]):
                continue
            canon = df[c].dropna().astype(str).str.strip()
            if canon.nunique() > canon.str.lower().nunique():
                mapping = canon.groupby(canon.str.lower()).agg(lambda s: s.value_counts().idxmax())
                df[c] = df[c].map(lambda v: mapping.get(v.strip().lower(), v) if isinstance(v, str) else v)
                n += 1
        return df, f"Standardised capitalisation in {n} column(s)"

    if op == "drop_duplicates":
        df = df.drop_duplicates().reset_index(drop=True)
        return df, f"Removed {before_rows - len(df)} duplicate row(s)"

    if op == "drop_column":
        if not column:
            raise AppError("drop_column requires a column")
        return df.drop(columns=[column]), f"Dropped column '{column}'"

    if op == "drop_missing_rows":
        subset = [column] if column else None
        df = df.dropna(subset=subset).reset_index(drop=True)
        return df, f"Dropped {before_rows - len(df)} row(s) with missing values"

    if op == "fill_missing":
        cols = [column] if column else [c for c in df.columns if df[c].isna().any()]
        filled = 0
        for c in cols:
            n = int(df[c].isna().sum())
            if not n:
                continue
            if c in numeric_cols(df):
                v = df[c].median() if strategy in (None, "median") else df[c].mean() if strategy == "mean" else 0
            elif pd.api.types.is_datetime64_any_dtype(df[c]):
                df[c] = df[c].ffill().bfill()
                filled += n
                continue
            else:
                m = df[c].mode(dropna=True)
                v = m.iloc[0] if len(m) and strategy != "unknown" else "Unknown"
            df[c] = df[c].fillna(v)
            filled += n
        return df, f"Filled {filled} missing value(s) across {len(cols)} column(s) ({strategy or 'median/mode'})"

    if op == "clip_outliers":
        cols = [column] if column else numeric_cols(df)
        n = 0
        for c in cols:
            d = df[c].dropna()
            if len(d) < 8:
                continue
            q1, q3 = d.quantile(0.25), d.quantile(0.75)
            iqr = q3 - q1
            if iqr == 0:
                continue
            lo, hi = q1 - 3 * iqr, q3 + 3 * iqr
            mask = (df[c] < lo) | (df[c] > hi)
            n += int(mask.sum())
            df[c] = df[c].clip(lo, hi)
        return df, f"Clipped {n} extreme outlier value(s) (3×IQR)"
    raise AppError("unreachable")
