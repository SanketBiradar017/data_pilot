import pandas as pd

from backend.app.analytics.utils import is_text, jsonable, numeric_cols


def quality_report(df: pd.DataFrame) -> dict:
    """Score 0-100 plus concrete, fixable issues."""
    rows, ncols = len(df), len(df.columns)
    issues: list[dict] = []
    if rows == 0:
        return {"score": 0, "issues": [], "dimensions": {}}

    total_cells = rows * ncols
    missing = int(df.isna().sum().sum())
    completeness = 100 * (1 - missing / total_cells)
    for c in df.columns:
        pct = df[c].isna().mean() * 100
        if pct >= 1:
            issues.append({"severity": "high" if pct > 30 else "medium" if pct > 5 else "low",
                           "column": c, "type": "missing_values",
                           "message": f"{pct:.1f}% missing ({int(df[c].isna().sum())} rows)",
                           "fix": "fill_missing" if pct <= 60 else "drop_column"})

    dups = int(df.duplicated().sum())
    uniqueness = 100 * (1 - dups / rows)
    if dups:
        issues.append({"severity": "medium" if dups / rows > 0.01 else "low", "column": None,
                       "type": "duplicate_rows", "message": f"{dups} duplicate rows", "fix": "drop_duplicates"})

    outlier_cells = 0
    for c in numeric_cols(df):
        d = df[c].dropna()
        if len(d) < 8:
            continue
        q1, q3 = d.quantile(0.25), d.quantile(0.75)
        iqr = q3 - q1
        if iqr == 0:
            continue
        n_out = int(((d < q1 - 3 * iqr) | (d > q3 + 3 * iqr)).sum())
        outlier_cells += n_out
        if n_out:
            issues.append({"severity": "medium" if n_out / len(d) > 0.01 else "low", "column": c,
                           "type": "outliers", "message": f"{n_out} extreme outliers (3×IQR)", "fix": "clip_outliers"})
    validity = 100 * (1 - outlier_cells / max(total_cells, 1))

    for c in df.columns:
        s = df[c]
        if is_text(s):
            sv = s.dropna().astype(str)
            if len(sv) and (sv != sv.str.strip()).any():
                issues.append({"severity": "low", "column": c, "type": "whitespace",
                               "message": "Leading/trailing whitespace in values", "fix": "trim_whitespace"})
            lower = sv.str.strip().str.lower()
            if len(sv) and sv.nunique() > lower.nunique():
                issues.append({"severity": "low", "column": c, "type": "inconsistent_case",
                               "message": "Same value in different capitalisation", "fix": "standardize_case"})
        if s.nunique(dropna=True) <= 1 and rows > 1:
            issues.append({"severity": "low", "column": c, "type": "constant_column",
                           "message": "Column has a single constant value", "fix": "drop_column"})

    consistency = 100 - min(30, 3 * sum(1 for i in issues if i["type"] in ("whitespace", "inconsistent_case", "constant_column")))
    score = round(0.4 * completeness + 0.2 * uniqueness + 0.2 * validity + 0.2 * consistency, 1)
    sev = {"high": 0, "medium": 1, "low": 2}
    issues.sort(key=lambda i: sev[i["severity"]])
    return jsonable({
        "score": score,
        "grade": "A" if score >= 90 else "B" if score >= 80 else "C" if score >= 65 else "D",
        "dimensions": {"completeness": round(completeness, 1), "uniqueness": round(uniqueness, 1),
                       "validity": round(validity, 1), "consistency": round(consistency, 1)},
        "missing_cells": missing, "duplicate_rows": dups, "issues": issues,
    })
