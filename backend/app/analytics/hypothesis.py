"""Classical hypothesis tests with confidence intervals, effect sizes and plain-English interpretation."""
import numpy as np
import pandas as pd
from scipy import stats

from backend.app.analytics.utils import jsonable, pfmt, plain
from backend.app.core.exceptions import AppError

TESTS = {"t_independent", "t_welch", "t_paired", "anova", "chi_square"}


def _num(df, col):
    if col not in df.columns:
        raise AppError(f"Unknown column '{col}'")
    if not pd.api.types.is_numeric_dtype(df[col]):
        raise AppError(f"'{col}' must be numeric")


def _cat(df, col):
    if col not in df.columns:
        raise AppError(f"Unknown column '{col}'")


def _gstats(groups: dict[str, np.ndarray], conf: float) -> list[dict]:
    out = []
    for name, v in groups.items():
        n = len(v)
        sd = float(np.std(v, ddof=1)) if n > 1 else 0.0
        se = sd / np.sqrt(n) if n > 1 else 0.0
        h = stats.t.ppf((1 + conf) / 2, n - 1) * se if n > 1 else 0.0
        out.append({"group": name, "n": n, "mean": float(np.mean(v)), "std": sd, "median": float(np.median(v)),
                    "ci_low": float(np.mean(v) - h), "ci_high": float(np.mean(v) + h)})
    return out


def _cohen_d(a, b, paired=False):
    if paired:
        d = a - b
        return float(d.mean() / d.std(ddof=1)) if d.std(ddof=1) else 0.0
    na, nb = len(a), len(b)
    sp = np.sqrt(((na - 1) * a.var(ddof=1) + (nb - 1) * b.var(ddof=1)) / (na + nb - 2))
    return float((a.mean() - b.mean()) / sp) if sp else 0.0


def _size(d: float) -> str:
    d = abs(d)
    return "negligible" if d < 0.2 else "small" if d < 0.5 else "medium" if d < 0.8 else "large"


def _bar(title, rows, x="group", y="mean"):
    return {"type": "bar", "title": title, "x": x, "y": [y], "data": jsonable(rows)}


def run_test(df: pd.DataFrame, test: str, value: str | None = None, group: str | None = None,
             groups: list[str] | None = None, value2: str | None = None, alpha: float = 0.05) -> dict:
    if test not in TESTS:
        raise AppError(f"Unknown test '{test}'. Use: {', '.join(sorted(TESTS))}")
    if not 0 < alpha < 1:
        raise AppError("alpha must be between 0 and 1")
    conf = 1 - alpha
    notes: list[str] = []

    if test in ("t_independent", "t_welch"):
        if not value or not group:
            raise AppError("Choose a numeric value column and a group column")
        _num(df, value); _cat(df, group)
        levels = [str(x) for x in df[group].dropna().unique()]
        if not groups:
            if len(levels) != 2:
                raise AppError(f"'{group}' has {len(levels)} groups; choose exactly two to compare")
            groups = levels
        if len(groups) != 2 or groups[0] == groups[1]:
            raise AppError("Choose exactly two different groups")
        a = df.loc[df[group].astype(str) == str(groups[0]), value].dropna().to_numpy(float)
        b = df.loc[df[group].astype(str) == str(groups[1]), value].dropna().to_numpy(float)
        if len(a) < 2 or len(b) < 2:
            raise AppError("Each group needs at least 2 observations")
        welch = test == "t_welch"
        r = stats.ttest_ind(a, b, equal_var=not welch)
        ci = r.confidence_interval(conf)
        lev = stats.levene(a, b).pvalue
        if not welch and lev < alpha:
            notes.append(f"Levene's test suggests unequal variances (p = {pfmt(lev)}); consider the Welch t-test.")
        if welch and lev >= alpha:
            notes.append(f"Variances look similar (Levene p = {pfmt(lev)}); Welch is still valid.")
        for nm, v in ((groups[0], a), (groups[1], b)):
            if len(v) < 5000 and len(v) >= 3 and stats.shapiro(v).pvalue < alpha:
                notes.append(f"Group '{nm}' deviates from normality (Shapiro–Wilk); with small n treat the result cautiously.")
        d = _cohen_d(pd.Series(a), pd.Series(b))
        gs = _gstats({str(groups[0]): a, str(groups[1]): b}, conf)
        diff = float(a.mean() - b.mean())
        sig = bool(r.pvalue < alpha)
        verdict = (f"The average {value} differs significantly between {groups[0]} ({plain(a.mean())}) and {groups[1]} ({plain(b.mean())}): "
                   f"difference {plain(diff)} (CI {plain(ci.low)} to {plain(ci.high)}), p = {pfmt(r.pvalue)}."
                   if sig else f"No significant difference in average {value} between {groups[0]} and {groups[1]} "
                               f"(difference {plain(diff)}, CI {plain(ci.low)} to {plain(ci.high)}, p = {pfmt(r.pvalue)}).")
        return jsonable({"test": test, "name": "Welch t-test" if welch else "Independent t-test (equal variance)", "statistic": r.statistic,
                         "p_value": r.pvalue, "df": r.df, "alpha": alpha, "significant": sig, "mean_difference": diff,
                         "ci_low": ci.low, "ci_high": ci.high, "confidence": conf, "effect_size": {"name": "Cohen's d", "value": d, "label": _size(d)},
                         "groups": gs, "notes": notes, "interpretation": verdict,
                         "chart": _bar(f"Mean {value} by {group}", gs)})

    if test == "t_paired":
        if not value or not value2:
            raise AppError("Choose two numeric columns (before / after)")
        _num(df, value); _num(df, value2)
        pair = df[[value, value2]].dropna()
        if len(pair) < 2:
            raise AppError("Need at least 2 complete pairs")
        a, b = pair[value].to_numpy(float), pair[value2].to_numpy(float)
        r = stats.ttest_rel(a, b)
        ci = r.confidence_interval(conf)
        d = _cohen_d(pair[value], pair[value2], paired=True)
        diff = float((a - b).mean())
        gs = _gstats({value: a, value2: b}, conf)
        sig = bool(r.pvalue < alpha)
        verdict = (f"{value} and {value2} differ significantly: mean paired difference {plain(diff)} (CI {plain(ci.low)} to {plain(ci.high)}), p = {pfmt(r.pvalue)}."
                   if sig else f"No significant paired difference between {value} and {value2} (mean difference {plain(diff)}, p = {pfmt(r.pvalue)}).")
        if len(pair) < len(df):
            notes.append(f"{len(df) - len(pair)} row(s) with missing values were excluded.")
        return jsonable({"test": test, "name": "Paired t-test", "statistic": r.statistic, "p_value": r.pvalue, "df": r.df, "alpha": alpha,
                         "significant": sig, "mean_difference": diff, "ci_low": ci.low, "ci_high": ci.high, "confidence": conf,
                         "effect_size": {"name": "Cohen's d (paired)", "value": d, "label": _size(d)}, "groups": gs, "notes": notes,
                         "interpretation": verdict, "chart": _bar(f"Mean of {value} vs {value2}", gs)})

    if test == "anova":
        if not value or not group:
            raise AppError("Choose a numeric value column and a group column")
        _num(df, value); _cat(df, group)
        d = df[[value, group]].dropna()
        data = {str(k): g[value].to_numpy(float) for k, g in d.groupby(group, observed=True) if len(g) >= 2}
        if len(data) < 3:
            raise AppError("ANOVA needs at least 3 groups with 2+ observations each (for two groups use a t-test)")
        arrs = list(data.values())
        r = stats.f_oneway(*arrs)
        grand = np.concatenate(arrs)
        ss_b = sum(len(v) * (v.mean() - grand.mean()) ** 2 for v in arrs)
        ss_t = ((grand - grand.mean()) ** 2).sum()
        eta = float(ss_b / ss_t) if ss_t else 0.0
        dfb, dfw = len(arrs) - 1, len(grand) - len(arrs)
        lev = stats.levene(*arrs).pvalue
        if lev < alpha:
            notes.append(f"Levene's test suggests unequal variances (p = {pfmt(lev)}); interpret ANOVA cautiously.")
        gs = _gstats(data, conf)
        top, bot = max(gs, key=lambda g: g["mean"]), min(gs, key=lambda g: g["mean"])
        sig = bool(r.pvalue < alpha)
        verdict = (f"{value} differs significantly across {group} (F({dfb}, {dfw}) = {plain(r.statistic)}, p = {pfmt(r.pvalue)}); highest mean in "
                   f"'{top['group']}' ({plain(top['mean'])}), lowest in '{bot['group']}' ({plain(bot['mean'])})."
                   if sig else f"No significant difference in {value} across {group} groups (F({dfb}, {dfw}) = {plain(r.statistic)}, p = {pfmt(r.pvalue)}).")
        if sig:
            notes.append("ANOVA shows that at least one group differs; run pairwise t-tests (with a multiple-comparison correction) to see which.")
        return jsonable({"test": test, "name": "One-way ANOVA", "statistic": r.statistic, "p_value": r.pvalue, "df": [dfb, dfw], "alpha": alpha,
                         "significant": sig, "effect_size": {"name": "Eta squared (η²)", "value": eta, "label": "small" if eta < .06 else "medium" if eta < .14 else "large"},
                         "groups": gs, "notes": notes, "interpretation": verdict, "chart": _bar(f"Mean {value} by {group}", gs)})

    # chi-square test of independence
    if not value or not value2:
        raise AppError("Choose two categorical columns")
    _cat(df, value); _cat(df, value2)
    d = df[[value, value2]].dropna()
    ct = pd.crosstab(d[value].astype(str), d[value2].astype(str))
    if ct.shape[0] < 2 or ct.shape[1] < 2:
        raise AppError("Each column needs at least 2 categories")
    if ct.shape[0] * ct.shape[1] > 400:
        raise AppError("Too many category combinations (> 400); use lower-cardinality columns")
    chi2, p, dof, exp = stats.chi2_contingency(ct)
    low = float((exp < 5).mean())
    if low > 0.2:
        notes.append(f"{low * 100:.0f}% of expected counts are below 5; the chi-square approximation may be unreliable.")
    nobs = ct.to_numpy().sum()
    v = float(np.sqrt(chi2 / (nobs * (min(ct.shape) - 1))))
    sig = bool(p < alpha)
    verdict = (f"{value} and {value2} are significantly associated (χ²({dof}) = {plain(chi2)}, p = {pfmt(p)}, Cramér's V = {v:.2f})."
               if sig else f"No significant association between {value} and {value2} (χ²({dof}) = {plain(chi2)}, p = {pfmt(p)}).")
    flat = [{"group": str(r), "category": str(c), "count": int(ct.loc[r, c])} for r in ct.index for c in ct.columns]
    wide = [{"group": str(r), **{str(c): int(ct.loc[r, c]) for c in ct.columns}} for r in ct.index]
    return jsonable({"test": test, "name": "Chi-square test of independence", "statistic": chi2, "p_value": p, "df": dof, "alpha": alpha,
                     "significant": sig, "effect_size": {"name": "Cramér's V", "value": v, "label": "small" if v < .3 else "medium" if v < .5 else "large"},
                     "contingency": {"rows": [str(x) for x in ct.index], "columns": [str(x) for x in ct.columns], "counts": ct.to_numpy().tolist()},
                     "groups": [], "notes": notes, "interpretation": verdict,
                     "chart": {"type": "bar", "title": f"{value} × {value2} (counts)", "x": "group", "y": [str(c) for c in ct.columns], "data": wide},
                     "flat": flat})
