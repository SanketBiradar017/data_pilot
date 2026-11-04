"""OLS regression (statsmodels) with diagnostics, plus holdout validation (scikit-learn)."""
import numpy as np
import pandas as pd
import statsmodels.api as sm
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import train_test_split
from statsmodels.stats.diagnostic import het_breuschpagan
from statsmodels.stats.outliers_influence import variance_inflation_factor
from statsmodels.stats.stattools import durbin_watson, jarque_bera

from backend.app.analytics.utils import hist_rows, jsonable, pfmt, plain
from backend.app.core.exceptions import AppError

MAX_LEVELS = 12
SAMPLE = 500


def _design(df: pd.DataFrame, target: str, features: list[str]) -> tuple[pd.Series, pd.DataFrame, int]:
    if target not in df.columns:
        raise AppError(f"Unknown target column '{target}'")
    if not pd.api.types.is_numeric_dtype(df[target]):
        raise AppError(f"Target '{target}' must be numeric")
    if not features:
        raise AppError("Select at least one predictor")
    if target in features:
        raise AppError("The target cannot also be a predictor")
    parts = []
    for f in features:
        if f not in df.columns:
            raise AppError(f"Unknown column '{f}'")
        s = df[f]
        if pd.api.types.is_bool_dtype(s):
            parts.append(s.astype(float).rename(f))
        elif pd.api.types.is_numeric_dtype(s):
            parts.append(s.astype(float))
        else:
            if s.nunique(dropna=True) > MAX_LEVELS:
                raise AppError(f"'{f}' has more than {MAX_LEVELS} categories; pick a numeric or lower-cardinality predictor")
            parts.append(pd.get_dummies(s, prefix=f, drop_first=True, dtype=float))
    X = pd.concat(parts, axis=1)
    before = len(df)
    data = pd.concat([df[target].astype(float), X], axis=1).replace([np.inf, -np.inf], np.nan).dropna()
    dropped = before - len(data)
    return data[target], data.drop(columns=[target]), dropped


def _fit(y: pd.Series, X: pd.DataFrame):
    return sm.OLS(y, sm.add_constant(X, has_constant="add")).fit()


def _backward(y: pd.Series, X: pd.DataFrame, alpha: float) -> tuple[pd.DataFrame, list[str]]:
    """Backward elimination on p-value; never drops below one predictor."""
    removed: list[str] = []
    while X.shape[1] > 1:
        p = _fit(y, X).pvalues.drop("const")
        worst = p.idxmax()
        if p[worst] <= alpha:
            break
        X = X.drop(columns=[worst])
        removed.append(worst)
    return X, removed


def run_regression(df: pd.DataFrame, target: str, features: list[str], select: bool = False,
                   alpha: float = 0.05, confidence: float = 0.95) -> dict:
    y, X, dropped = _design(df, target, features)
    k = X.shape[1]
    if k == 0:  # e.g. a categorical predictor with one category, or with only blank values
        raise AppError("The selected predictor(s) have nothing to compare: a categorical field with a single value (or only blanks) "
                       "cannot explain the outcome. Pick a field that varies, or add more predictors.")
    if len(y) == 0:
        raise AppError("No rows remain after removing rows with missing values in the selected columns.")
    if len(y) < k + 3:
        raise AppError(f"Not enough rows ({len(y)}) for {k} predictor term(s); need at least {k + 3}")
    if (X.std() == 0).any():
        const = X.columns[X.std() == 0].tolist()
        raise AppError(f"Predictor(s) with no variation: {', '.join(const)}")
    removed: list[str] = []
    if select:
        X, removed = _backward(y, X, alpha)
    res = _fit(y, X)
    ci = res.conf_int(alpha=1 - confidence)
    coefs = [{"name": n, "coef": res.params[n], "std_err": res.bse[n], "t": res.tvalues[n], "p_value": res.pvalues[n],
              "ci_low": ci.loc[n, 0], "ci_high": ci.loc[n, 1], "significant": bool(res.pvalues[n] < alpha)}
             for n in res.params.index]
    fitted, resid = res.fittedvalues, res.resid
    rmse = float(np.sqrt(np.mean(resid**2)))

    # holdout validation (independent implementation: scikit-learn)
    holdout = None
    if len(y) >= 30:
        try:  # the holdout check is an extra; it must never take the whole analysis down
            Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, random_state=42)
            lr = LinearRegression().fit(Xtr, ytr)
            pred = lr.predict(Xte)
            holdout = {"n_train": len(ytr), "n_test": len(yte), "r2": r2_score(yte, pred),
                       "rmse": float(np.sqrt(np.mean((yte - pred) ** 2))), "mae": mean_absolute_error(yte, pred)}
        except ValueError:
            holdout = None

    diag: dict = {"durbin_watson": durbin_watson(resid)}
    try:
        jb = jarque_bera(resid)
        diag["normality_p"] = jb[1]
        diag["skew"], diag["kurtosis"] = jb[2], jb[3]
    except Exception:
        pass
    try:
        diag["heteroscedasticity_p"] = het_breuschpagan(resid, sm.add_constant(X, has_constant="add"))[1]
    except Exception:
        pass
    influential = []
    try:
        cooks = res.get_influence().cooks_distance[0]
        thr = 4 / len(y)
        order = np.argsort(cooks)[::-1][:5]
        influential = [{"row": int(y.index[i]), "cooks_d": float(cooks[i]), "residual": float(resid.iloc[i])} for i in order if cooks[i] > thr]
        diag["max_cooks_d"] = float(cooks.max())
    except Exception:
        pass
    vif = []
    if X.shape[1] > 1:
        Xc = sm.add_constant(X, has_constant="add")
        for i, n in enumerate(Xc.columns):
            if n != "const":
                try:
                    vif.append({"name": n, "vif": float(variance_inflation_factor(Xc.values, i))})
                except Exception:
                    pass
    n = len(y)
    idx = np.random.default_rng(0).choice(n, min(n, SAMPLE), replace=False) if n > SAMPLE else np.arange(n)
    lo, hi = float(min(y.min(), fitted.min())), float(max(y.max(), fitted.max()))
    avp = [{"actual": y.iloc[i], "predicted": fitted.iloc[i]} for i in idx]
    rvf = [{"fitted": fitted.iloc[i], "residual": resid.iloc[i]} for i in idx]
    rhist, _ = hist_rows(resid.to_numpy(), min(25, max(8, int(np.sqrt(n)))))
    sig = [c for c in coefs if c["name"] != "const" and c["significant"]]
    interp = [f"The model explains {res.rsquared * 100:.1f}% of the variance in {target} (adjusted R² = {res.rsquared_adj:.3f}); "
              f"overall F-test p = {pfmt(res.f_pvalue)} ({'significant' if res.f_pvalue < alpha else 'not significant'} at α = {alpha})."]
    for c in sorted(sig, key=lambda c: c["p_value"])[:5]:
        interp.append(f"Holding other predictors constant, a 1-unit increase in {c['name']} changes {target} by {plain(c['coef'])} "
                      f"(95% CI {plain(c['ci_low'])} to {plain(c['ci_high'])}, p = {pfmt(c['p_value'])}).")
    ns = [c["name"] for c in coefs if c["name"] != "const" and not c["significant"]]
    if ns:
        interp.append(f"Not statistically significant: {', '.join(ns)}.")
    warn = []
    if diag.get("heteroscedasticity_p") is not None and diag["heteroscedasticity_p"] < 0.05:
        warn.append("Residual variance is not constant (Breusch–Pagan p < 0.05); standard errors may be unreliable.")
    if diag.get("normality_p") is not None and diag["normality_p"] < 0.05:
        warn.append("Residuals deviate from normality (Jarque–Bera p < 0.05); p-values and intervals are approximate.")
    if influential and influential[0]["cooks_d"] > 0.5:
        warn.append(f"Row {influential[0]['row']} has a very large influence on the fit (Cook's distance {influential[0]['cooks_d']:.2f}); "
                    "check it for data errors and consider refitting without it.")
    if any(v["vif"] > 10 for v in vif):
        warn.append("High multicollinearity (VIF > 10) among: " + ", ".join(v["name"] for v in vif if v["vif"] > 10) + ".")
    if res.rsquared - (holdout["r2"] if holdout else res.rsquared) > 0.15:
        warn.append("Holdout R² is much lower than in-sample R²: the model may be overfitting.")
    return jsonable({
        "target": target, "features": list(X.columns), "removed_by_selection": removed, "n": n, "dropped_rows": dropped,
        "kind": "simple" if X.shape[1] == 1 else "multiple",
        "metrics": {"r2": res.rsquared, "adj_r2": res.rsquared_adj, "f_stat": res.fvalue, "f_p_value": res.f_pvalue,
                    "rmse": rmse, "mae": float(np.mean(np.abs(resid))), "aic": res.aic, "bic": res.bic, "df_model": res.df_model, "df_resid": res.df_resid},
        "holdout": holdout, "coefficients": coefs, "diagnostics": diag, "vif": vif, "influential_points": influential,
        "charts": {"actual_vs_predicted": avp, "perfect_line": [{"actual": lo, "predicted": lo}, {"actual": hi, "predicted": hi}],
                   "residuals_vs_fitted": rvf, "residual_histogram": rhist,
                   "coefficient_bars": [{"name": c["name"], "coef": c["coef"]} for c in coefs if c["name"] != "const"]},
        "interpretation": interp, "warnings": warn,
    })
