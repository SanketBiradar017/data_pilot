"""EDA: descriptive stats, correlations, trends, anomalies, group comparison."""
import numpy as np
import pandas as pd
from scipy import stats as sps

from backend.app.analytics.utils import categorical_cols, datetime_cols, jsonable, numeric_cols


def descriptive(df: pd.DataFrame) -> list[dict]:
    out = []
    for c in numeric_cols(df):
        d = df[c].dropna()
        if d.empty:
            continue
        out.append({"column": c, "count": len(d), "mean": d.mean(), "std": d.std(), "min": d.min(),
                    "p25": d.quantile(.25), "median": d.median(), "p75": d.quantile(.75), "max": d.max(),
                    "skew": d.skew() if len(d) > 2 else 0})
    return jsonable(out)


def correlations(df: pd.DataFrame, threshold: float = 0.5) -> dict:
    cols = [c for c in numeric_cols(df) if df[c].nunique() > 1]
    if len(cols) < 2:
        return {"matrix": [], "columns": cols, "pairs": []}
    cols = cols[:25]
    corr = df[cols].corr(method="spearman")
    pairs = []
    for i, a in enumerate(cols):
        for b in cols[i + 1:]:
            pair = df[[a, b]].dropna()
            if len(pair) < 5:
                continue
            r, p = sps.spearmanr(pair[a], pair[b])
            if abs(r) >= threshold:
                pairs.append({"a": a, "b": b, "r": r, "p_value": p, "n": len(pair),
                              "strength": "strong" if abs(r) >= .7 else "moderate",
                              "direction": "positive" if r > 0 else "negative"})
    pairs.sort(key=lambda x: -abs(x["r"]))
    matrix = [{"x": a, "y": b, "value": corr.loc[a, b]} for a in cols for b in cols]
    return jsonable({"columns": cols, "matrix": matrix, "pairs": pairs})


def anomalies(df: pd.DataFrame, z: float = 3.0, max_per_col: int = 20) -> list[dict]:
    out = []
    for c in numeric_cols(df):
        d = df[c].dropna()
        if len(d) < 10 or d.std() == 0:
            continue
        med = d.median()
        mad = (d - med).abs().median()
        if mad == 0:
            score = (df[c] - d.mean()) / d.std()
        else:
            score = 0.6745 * (df[c] - med) / mad
        idx = score[score.abs() > max(z, 3.5 if mad else z)].dropna()
        if len(idx):
            top = idx.abs().sort_values(ascending=False).head(max_per_col).index
            out.append({"column": c, "count": int(len(idx)), "pct": round(len(idx) / len(d) * 100, 2),
                        "examples": [{"row": int(i), "value": df.loc[i, c], "score": float(score[i])} for i in top[:5]],
                        "lower_bound": float(med - 3.5 * mad / 0.6745) if mad else None,
                        "upper_bound": float(med + 3.5 * mad / 0.6745) if mad else None})
    out.sort(key=lambda a: -a["count"])
    return jsonable(out)


def _freq(df: pd.DataFrame, tcol: str) -> str:
    span = (df[tcol].max() - df[tcol].min()).days
    return "D" if span <= 90 else "W" if span <= 365 else "MS"


def trends(df: pd.DataFrame, max_series: int = 4) -> list[dict]:
    dts = datetime_cols(df)
    nums = [c for c in numeric_cols(df) if df[c].nunique() > 3]
    if not dts or not nums:
        return []
    tcol = dts[0]
    d = df.dropna(subset=[tcol]).sort_values(tcol)
    if len(d) < 6:
        return []
    freq = _freq(d, tcol)
    out = []
    for c in nums[:max_series]:
        series = d.set_index(tcol)[c].resample(freq).sum(min_count=1).dropna()
        if len(series) < 4:
            continue
        x = np.arange(len(series))
        # Robust to outliers: Theil–Sen slope with Kendall-tau significance
        ts = sps.theilslopes(series.values, x)
        tau, pval = sps.kendalltau(x, series.values)
        r2 = float(np.corrcoef(x, series.values)[0, 1] ** 2) if series.std() else 0.0
        res = type("R", (), {"slope": ts[0], "intercept": ts[1], "pvalue": pval, "rvalue": r2 ** 0.5})
        mean = series.median() or 1e-9
        k = max(1, len(series) // 4)
        first, last = series.iloc[:k].median(), series.iloc[-k:].median()
        pct_change = float((last - first) / abs(first) * 100) if first else None
        direction = "flat" if res.pvalue > 0.05 else "up" if res.slope > 0 else "down"
        out.append({
            "metric": c, "time_column": tcol, "frequency": freq, "direction": direction,
            "slope_per_period": res.slope, "slope_pct_of_mean": res.slope / abs(mean) * 100,
            "r_squared": res.rvalue ** 2, "p_value": res.pvalue, "pct_change_first_last": pct_change,
            "points": [{"t": t.isoformat(), "value": v} for t, v in series.items()],
            "forecast": [{"t": (series.index[-1] + (k + 1) * (series.index[1] - series.index[0])).isoformat(),
                          "value": res.intercept + res.slope * (len(series) + k)} for k in range(3)],
        })
    return jsonable(out)


def group_comparison(df: pd.DataFrame) -> list[dict]:
    """ANOVA / t-test of each numeric metric across the best categorical dimension."""
    cats = [c for c in categorical_cols(df, 20) if 2 <= df[c].nunique() <= 20]
    nums = [c for c in numeric_cols(df) if df[c].nunique() > 3]
    out = []
    for cat in cats[:3]:
        for num in nums[:4]:
            groups = [g[num].dropna().values for _, g in df.groupby(cat) if g[num].notna().sum() >= 3]
            if len(groups) < 2:
                continue
            try:
                stat, p = sps.f_oneway(*groups) if len(groups) > 2 else sps.ttest_ind(*groups, equal_var=False)
            except Exception:
                continue
            if np.isnan(p):
                continue
            means = df.groupby(cat)[num].mean().sort_values(ascending=False)
            out.append({"dimension": cat, "metric": num, "test": "ANOVA" if len(groups) > 2 else "Welch t-test",
                        "statistic": stat, "p_value": p, "significant": bool(p < 0.05),
                        "top_group": means.index[0], "top_mean": means.iloc[0],
                        "bottom_group": means.index[-1], "bottom_mean": means.iloc[-1]})
    out.sort(key=lambda r: r["p_value"])
    return jsonable(out[:8])


def run_eda(df: pd.DataFrame) -> dict:
    return {"descriptive": descriptive(df), "correlations": correlations(df), "anomalies": anomalies(df),
            "trends": trends(df), "group_tests": group_comparison(df)}
