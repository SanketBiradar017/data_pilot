import numpy as np
import pandas as pd
import pytest
from scipy import stats

from backend.app.analytics import hypothesis, pareto, pivot, regression, variance
from backend.app.core.exceptions import AppError


@pytest.fixture(scope="module")
def sales():
    rng = np.random.default_rng(1)
    n = 600
    d = pd.DataFrame({
        "region": rng.choice(["North", "South", "East"], n), "category": rng.choice(["Electronics", "Furniture"], n),
        "units": rng.integers(1, 10, n), "price": rng.uniform(10, 100, n), "date": pd.date_range("2024-01-01", periods=n, freq="D"),
    })
    d["revenue"] = d["units"] * d["price"]
    return d


# ---------------- pivot ----------------
def test_pivot_matches_pandas(sales):
    r = pivot.pivot(sales, ["region"], ["category"], [{"column": "revenue", "agg": "sum"}])
    ref = pd.pivot_table(sales, index="region", columns="category", values="revenue", aggfunc="sum", margins=True)
    body = {x["region"]: x for x in r["rows"] if not x.get("__total__")}
    for reg in ["North", "South", "East"]:
        for cat in ["Electronics", "Furniture"]:
            assert body[reg][cat] == pytest.approx(ref.loc[reg, cat])
        assert body[reg]["Total"] == pytest.approx(ref.loc[reg, "All"])
    grand = r["rows"][-1]
    assert grand["__total__"] and grand["Total"] == pytest.approx(sales["revenue"].sum())


def test_pivot_user_example_layout():
    df = pd.DataFrame({"Region": ["North", "North", "South", "South"], "Category": ["Electronics", "Furniture"] * 2, "Sales": [200000, 80000, 300000, 120000]})
    r = pivot.pivot(df, ["Region"], ["Category"], [{"column": "Sales", "agg": "sum"}])
    assert r["columns"] == ["Region", "Electronics", "Furniture", "Total"]
    assert r["rows"][0] == {"Region": "North", "Electronics": 200000, "Furniture": 80000, "Total": 280000}
    assert r["rows"][1]["Total"] == 420000


def test_pivot_all_aggregations_and_multi_group(sales):
    for agg, fn in [("sum", "sum"), ("count", "count"), ("avg", "mean"), ("min", "min"), ("max", "max")]:
        r = pivot.pivot(sales, ["region", "category"], [], [{"column": "revenue", "agg": agg}], totals=False)
        label = r["value_labels"][0]
        for row in r["rows"]:
            exp = getattr(sales[(sales.region == row["region"]) & (sales.category == row["category"])]["revenue"], fn)()
            assert row[label] == pytest.approx(exp)


def test_pivot_grand_avg_is_true_mean_not_mean_of_means(sales):
    r = pivot.pivot(sales, ["region"], [], [{"column": "revenue", "agg": "avg"}])
    assert r["rows"][-1]["AVG of revenue"] == pytest.approx(sales["revenue"].mean())


def test_pivot_filters(sales):
    r = pivot.pivot(sales, ["region"], [], [{"column": "*", "agg": "count"}],
                    [{"column": "units", "op": "gte", "value": 5}, {"column": "category", "op": "in", "value": ["Electronics"]}])
    sub = sales[(sales.units >= 5) & (sales.category == "Electronics")]
    assert r["rows"][-1]["COUNT"] == len(sub) and r["source_rows"] == len(sub)
    r = pivot.pivot(sales, ["region"], [], [{"column": "*", "agg": "count"}], [{"column": "price", "op": "between", "value": [20, 40]}])
    assert r["source_rows"] == len(sales[sales.price.between(20, 40)])
    with pytest.raises(AppError, match="No rows match"):
        pivot.pivot(sales, ["region"], [], [{"column": "*", "agg": "count"}], [{"column": "units", "op": "gt", "value": 999}])


def test_pivot_blank_category_kept():
    df = pd.DataFrame({"g": ["a", None, "a"], "v": [1, 2, 3]})
    r = pivot.pivot(df, ["g"], [], [{"column": "v", "agg": "sum"}])
    assert {x["g"]: x["SUM of v"] for x in r["rows"] if not x.get("__total__")} == {"a": 4, "(blank)": 2}


def test_pivot_validation(sales):
    with pytest.raises(AppError, match="numeric"):
        pivot.pivot(sales, ["region"], [], [{"column": "category", "agg": "sum"}])
    with pytest.raises(AppError, match="both"):
        pivot.pivot(sales, ["region"], ["region"], [{"column": "*", "agg": "count"}])
    with pytest.raises(AppError, match="value field"):
        pivot.pivot(sales, ["region"], [], [])
    with pytest.raises(AppError, match="Unknown column"):
        pivot.pivot(sales, ["nope"], [], [{"column": "*", "agg": "count"}])
    with pytest.raises(AppError, match="aggregation"):
        pivot.pivot(sales, ["region"], [], [{"column": "revenue", "agg": "median"}])


def test_pivot_chart(sales):
    r = pivot.pivot(sales, ["region"], ["category"], [{"column": "revenue", "agg": "sum"}])
    c = pivot.pivot_chart(r)
    assert c["y"] == ["Electronics", "Furniture"] and len(c["data"]) == 3


# ---------------- regression ----------------
@pytest.fixture(scope="module")
def reg_df():
    rng = np.random.default_rng(7)
    n = 400
    d = pd.DataFrame({"ads": rng.uniform(0, 100, n), "discount": rng.uniform(0, 30, n), "price": rng.uniform(10, 50, n), "noise": rng.normal(size=n)})
    d["revenue"] = 500 + 8 * d.ads - 12 * d.discount + 3 * d.price + rng.normal(0, 20, n)
    return d


def test_multiple_regression_recovers_coefficients(reg_df):
    r = regression.run_regression(reg_df, "revenue", ["ads", "discount", "price"])
    coef = {c["name"]: c for c in r["coefficients"]}
    assert coef["ads"]["coef"] == pytest.approx(8, abs=0.3) and coef["discount"]["coef"] == pytest.approx(-12, abs=0.6) and coef["price"]["coef"] == pytest.approx(3, abs=0.8)
    assert r["metrics"]["r2"] > 0.99 and r["metrics"]["adj_r2"] <= r["metrics"]["r2"]
    # independent check with plain numpy least squares
    X = np.column_stack([np.ones(len(reg_df)), reg_df[["ads", "discount", "price"]].to_numpy()])
    beta = np.linalg.lstsq(X, reg_df.revenue.to_numpy(), rcond=None)[0]
    assert [coef[k]["coef"] for k in ("const", "ads", "discount", "price")] == pytest.approx(list(beta), rel=1e-6)
    assert all(c["ci_low"] < c["coef"] < c["ci_high"] for c in r["coefficients"])
    assert r["holdout"]["r2"] > 0.98 and r["kind"] == "multiple" and r["vif"]


def test_simple_regression_and_significance(reg_df):
    r = regression.run_regression(reg_df, "revenue", ["ads"])
    assert r["kind"] == "simple"
    slope = stats.linregress(reg_df.ads, reg_df.revenue)
    c = next(c for c in r["coefficients"] if c["name"] == "ads")
    assert c["coef"] == pytest.approx(slope.slope) and c["p_value"] == pytest.approx(slope.pvalue, abs=1e-12)
    assert r["metrics"]["r2"] == pytest.approx(slope.rvalue ** 2)
    r = regression.run_regression(reg_df, "revenue", ["ads", "noise"])
    assert not next(c for c in r["coefficients"] if c["name"] == "noise")["significant"]


def test_backward_selection_drops_noise(reg_df):
    r = regression.run_regression(reg_df, "revenue", ["ads", "discount", "noise"], select=True)
    assert "noise" in r["removed_by_selection"] and "noise" not in r["features"]


def test_regression_categorical_and_errors(reg_df):
    d = reg_df.assign(tier=np.where(reg_df.price > 30, "hi", "lo"))
    r = regression.run_regression(d, "revenue", ["ads", "tier"])
    assert "tier_lo" in r["features"] or "tier_hi" in r["features"]
    with pytest.raises(AppError, match="numeric"):
        regression.run_regression(d, "tier", ["ads"])
    with pytest.raises(AppError, match="Not enough rows"):
        regression.run_regression(reg_df.head(4), "revenue", ["ads", "discount", "price"])
    with pytest.raises(AppError, match="no variation"):
        regression.run_regression(reg_df.assign(c=1.0), "revenue", ["ads", "c"])
    with pytest.raises(AppError, match="target cannot"):
        regression.run_regression(reg_df, "revenue", ["revenue"])


def test_regression_flags_influential_point(reg_df):
    d = reg_df.copy()
    d.loc[10, "revenue"] = 50_000
    r = regression.run_regression(d, "revenue", ["ads"])
    assert r["influential_points"][0]["row"] == 10 and any("influence" in w for w in r["warnings"])


def test_regression_flags_heteroscedasticity():
    rng = np.random.default_rng(3)
    x = rng.uniform(1, 100, 500)
    d = pd.DataFrame({"x": x, "y": 2 * x + rng.normal(0, 1, 500) * x * 0.5})
    r = regression.run_regression(d, "y", ["x"])
    assert any("variance" in w for w in r["warnings"])


# ---------------- hypothesis ----------------
@pytest.fixture(scope="module")
def groups_df():
    rng = np.random.default_rng(11)
    return pd.DataFrame({"region": ["North"] * 80 + ["South"] * 90 + ["East"] * 70,
                         "revenue": np.concatenate([rng.normal(100, 15, 80), rng.normal(115, 25, 90), rng.normal(100, 15, 70)]),
                         "before": rng.normal(50, 5, 240), "tier": rng.choice(["a", "b", "c"], 240)}).assign(after=lambda d: d.before + rng.normal(2, 3, 240))


def test_independent_and_welch_match_scipy(groups_df):
    a = groups_df[groups_df.region == "North"].revenue.to_numpy()
    b = groups_df[groups_df.region == "South"].revenue.to_numpy()
    for test, ev in (("t_independent", True), ("t_welch", False)):
        r = hypothesis.run_test(groups_df, test, "revenue", "region", ["North", "South"])
        ref = stats.ttest_ind(a, b, equal_var=ev)
        assert r["p_value"] == pytest.approx(ref.pvalue) and r["statistic"] == pytest.approx(ref.statistic)
        assert r["ci_low"] < a.mean() - b.mean() < r["ci_high"] and r["significant"]
        assert "differs significantly" in r["interpretation"] and r["chart"]["type"] == "bar"
    assert r["name"] == "Welch t-test"


def test_paired_matches_scipy(groups_df):
    r = hypothesis.run_test(groups_df, "t_paired", "before", value2="after")
    ref = stats.ttest_rel(groups_df.before, groups_df.after)
    assert r["p_value"] == pytest.approx(ref.pvalue) and r["mean_difference"] == pytest.approx((groups_df.before - groups_df.after).mean())


def test_anova_matches_scipy(groups_df):
    r = hypothesis.run_test(groups_df, "anova", "revenue", "region")
    ref = stats.f_oneway(*[g.revenue for _, g in groups_df.groupby("region")])
    assert r["p_value"] == pytest.approx(ref.pvalue) and r["statistic"] == pytest.approx(ref.statistic)
    assert r["significant"] and 0 < r["effect_size"]["value"] < 1


def test_chi_square_matches_scipy():
    d = pd.DataFrame({"a": ["x"] * 60 + ["y"] * 40, "b": ["p"] * 45 + ["q"] * 15 + ["p"] * 15 + ["q"] * 25})
    r = hypothesis.run_test(d, "chi_square", "a", value2="b")
    ref = stats.chi2_contingency(pd.crosstab(d.a, d.b))
    assert r["p_value"] == pytest.approx(ref[1]) and r["statistic"] == pytest.approx(ref[0]) and r["significant"]


def test_hypothesis_errors(groups_df):
    with pytest.raises(AppError, match="exactly two"):
        hypothesis.run_test(groups_df, "t_welch", "revenue", "region")
    with pytest.raises(AppError, match="at least 3 groups"):
        hypothesis.run_test(groups_df[groups_df.region != "East"], "anova", "revenue", "region")
    with pytest.raises(AppError, match="Unknown test"):
        hypothesis.run_test(groups_df, "magic", "revenue", "region")
    with pytest.raises(AppError, match="numeric"):
        hypothesis.run_test(groups_df, "t_welch", "region", "tier", ["a", "b"])


# ---------------- pareto ----------------
def test_pareto_abc_classic():
    d = pd.DataFrame({"p": list("ABCDEF"), "v": [50, 30, 10, 5, 3, 2]})
    r = pareto.run_pareto(d, "p", "v")
    assert [x["cum_pct"] for x in r["rows"]] == pytest.approx([50, 80, 90, 95, 98, 100])
    assert [x["class"] for x in r["rows"]] == ["A", "A", "B", "B", "C", "C"]
    assert r["items_for_80pct"] == 2 and r["summary"][0]["value_pct"] == pytest.approx(80)
    assert r["chart"]["type"] == "pareto" and "2 of 6" in r["interpretation"]


def test_pareto_aggregates_and_counts(sales):
    r = pareto.run_pareto(sales, "region", "revenue")
    exp = sales.groupby("region").revenue.sum().sort_values(ascending=False)
    assert [x["category"] for x in r["rows"]] == list(exp.index) and r["total"] == pytest.approx(exp.sum())
    r = pareto.run_pareto(sales, "region")
    assert r["measure"] == "COUNT of rows" and r["rows"][-1]["cum_pct"] == pytest.approx(100)


def test_pareto_negatives_and_errors():
    d = pd.DataFrame({"p": ["a", "b", "c"], "v": [10, -5, 10]})
    r = pareto.run_pareto(d, "p", "v")
    assert r["notes"] and len(r["rows"]) == 2
    with pytest.raises(AppError):
        pareto.run_pareto(d, "p", "v", a_cut=90, b_cut=80)
    with pytest.raises(AppError, match="numeric"):
        pareto.run_pareto(d, "p", "p")


# ---------------- variance ----------------
def test_variance_user_example_revenue_target():
    d = pd.DataFrame({"revenue": [800_000.0], "target": [1_000_000.0]})
    r = variance.actual_vs_target(d, [{"column": "revenue", "kind": "revenue", "target_column": "target"}])
    row = r["rows"][0]
    assert row["variance"] == -200_000 and row["variance_pct"] == pytest.approx(-20) and row["status"] == "unfavourable"
    r = variance.actual_vs_target(d, [{"column": "revenue", "kind": "revenue", "target_value": 1_000_000}])
    assert r["rows"][0]["variance"] == -200_000


def test_variance_cost_direction_and_profit_and_groups():
    d = pd.DataFrame({"g": ["a", "a", "b", "b"], "rev": [100, 100, 50, 50], "rev_t": [90, 90, 80, 80], "cost": [60, 60, 20, 20], "cost_t": [50, 50, 30, 30]})
    r = variance.actual_vs_target(d, [{"column": "rev", "kind": "revenue", "target_column": "rev_t"}, {"column": "cost", "kind": "cost", "target_column": "cost_t"}],
                                  group_by="g", derive_profit={"revenue": "rev", "cost": "cost"})
    by = {(x["group"], x["metric"]): x for x in r["rows"]}
    assert by[("a", "rev")]["status"] == "favourable"                    # above target
    assert by[("a", "cost")]["status"] == "unfavourable"                 # spending over target
    assert by[("b", "cost")]["status"] == "favourable"                   # spending under target
    assert by[("All", "Profit")]["actual"] == (300 - 160) and by[("All", "Profit")]["comparator"] == (340 - 160)
    assert by[("b", "rev")]["status"] == "unfavourable"


def test_variance_tolerance_band():
    d = pd.DataFrame({"a": [101.0], "t": [100.0]})
    assert variance.actual_vs_target(d, [{"column": "a", "target_column": "t"}], tolerance_pct=2)["rows"][0]["status"] == "on_target"
    assert variance.actual_vs_target(d, [{"column": "a", "target_column": "t"}], tolerance_pct=0.5)["rows"][0]["status"] == "favourable"


def test_period_over_period(sales):
    r = variance.period_over_period(sales, "date", [{"column": "revenue", "kind": "revenue"}], "month")
    m = sales.assign(p=sales.date.dt.to_period("M").astype(str)).groupby("p").revenue.sum()
    cur, prev = r["current_period"], r["previous_period"]
    assert cur == m.index[-1] and prev == m.index[-2]
    assert r["rows"][0]["actual"] == pytest.approx(m.iloc[-1]) and r["rows"][0]["variance"] == pytest.approx(m.iloc[-1] - m.iloc[-2])
    assert len(r["series"]) == len(m) - 1
    r = variance.period_over_period(sales, "date", [{"column": "revenue"}], "quarter", group_by="region")
    assert any(x["group"] == "North" for x in r["rows"]) and r["rows"][0]["group"] == "All"
    with pytest.raises(AppError, match="date column"):
        variance.period_over_period(sales, "region", [{"column": "revenue"}])
    with pytest.raises(AppError, match="at least two"):
        variance.period_over_period(sales.head(10), "date", [{"column": "revenue"}], "year")


def test_predictors_without_variation_give_a_clear_error_not_a_crash():
    rng = np.random.default_rng(0)
    df = pd.DataFrame({"y": rng.normal(size=60), "x": rng.normal(size=60), "one_level": "A", "all_blank": np.nan, "mostly_blank": [None] * 59 + ["z"]})
    for feats in (["one_level"], ["all_blank"], ["one_level", "all_blank"]):
        with pytest.raises(AppError, match="nothing to compare|No rows remain"):
            regression.run_regression(df, "y", feats)
    r = regression.run_regression(df, "y", ["x", "one_level"])              # a usable predictor alongside a useless one still works
    assert r["features"] == ["x"]
