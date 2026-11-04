"""Plain-number formatting and histogram bins (no scientific notation anywhere in chart data or prose)."""
import re

import numpy as np
import pandas as pd
import pytest

from backend.app.analytics import hypothesis, regression
from backend.app.analytics.charts import auto_charts
from backend.app.analytics.profiling import profile_dataframe
from backend.app.analytics.utils import hist_rows, pfmt, pick_digits, plain, range_label

SCI = re.compile(r"\d[eE][+-]?\d")


@pytest.mark.parametrize("v,expected", [
    (12600.5, "12,601"), (6340, "6,340"), (31300, "31,300"), (1_000_000, "1,000,000"), (4.56, "4.56"), (123.456, "123.46"),
    (0.0123, "0.0123"), (0.000000123, "0.000000123"), (-1234.5, "-1,235"), (-2.5, "-2.5"), (0, "0"), (1e15, "1,000,000,000,000,000"),
])
def test_plain_numbers(v, expected):
    assert plain(v) == expected


def test_plain_handles_missing_and_never_uses_scientific_notation():
    assert plain(None) == plain(float("nan")) == plain(float("inf")) == "n/a"
    for v in (1.26e4, 1e21, 1e-7, 1.5e-10, -3.3e8, 123456789012345680000):
        assert not SCI.search(plain(v)), plain(v)


def test_pfmt_never_prints_scientific_p_values():
    assert pfmt(3.6e-76) == "< 0.0001" and pfmt(0.00004) == "< 0.0001"
    assert pfmt(0.0123) == "0.012" and pfmt(0.5) == "0.5" and pfmt(None) == "n/a"


def test_user_example_bins_become_integer_ranges():
    edges = [1, 13.4, 25.8, 38.1, 50.5, 62.9]
    labels = [range_label(a, b, True, i == len(edges) - 2, 1) for i, (a, b) in enumerate(zip(edges, edges[1:]))]
    assert labels == ["1–13", "14–25", "26–38", "39–50", "51–62"]


def test_edges_are_shown_exactly_with_one_shared_precision():
    assert pick_digits([0.5, 1.25, 2, 2.75]) == 2 and pick_digits([1, 13.4, 25.8]) == 1 and pick_digits([0, 10]) == 0
    assert range_label(6340, 12600, False, False, 0) == "6,340–12,600"


def test_round_off_edges_use_only_the_precision_the_bin_width_warrants():
    assert pick_digits([10.6, 35.761, 60.922, 86.083]) == 1
    assert [range_label(a, b, False, False, 1) for a, b in [(10.6, 35.761), (35.761, 60.922)]] == ["10.6–35.8", "35.8–60.9"]


def test_hist_rows_counts_are_exactly_numpys_and_integer_flag_is_right():
    rng = np.random.default_rng(0)
    ints = rng.integers(1, 63, 500)
    rows, integer = hist_rows(ints, 5)
    counts, edges = np.histogram(ints, bins=5)
    assert integer and [r["count"] for r in rows] == counts.tolist() and [r["start"] for r in rows] == edges[:-1].tolist()
    assert sum(r["pct"] for r in rows) == pytest.approx(100) and rows[0]["end"] == rows[1]["start"]
    floats, integer = hist_rows(rng.normal(20000, 5000, 400), 8)
    assert not integer and all(not SCI.search(r["bin"]) for r in floats)
    assert hist_rows([], 5) == ([], False) and hist_rows([np.nan, np.nan], 5) == ([], False)


def test_integer_bin_labels_partition_the_integers_exactly():
    vals = np.arange(1, 63)
    rows, _ = hist_rows(vals, 5)
    seen = []
    for r in rows:
        lo, _, hi = r["bin"].partition("–")
        a, b = int(lo.replace(",", "")), int((hi or lo).replace(",", ""))
        seen += list(range(a, b + 1))
        assert r["count"] == sum(1 for v in vals if a <= v <= b)       # label range really contains the counted values
    assert seen == list(range(1, 63))                                  # no overlap, no gap


def test_profile_and_auto_chart_histograms_carry_edges_and_no_scientific_notation():
    rng = np.random.default_rng(1)
    df = pd.DataFrame({"revenue": rng.normal(2.5e4, 8e3, 600), "units": rng.integers(1, 63, 600), "g": rng.choice(list("ab"), 600)})
    prof = {c["name"]: c for c in profile_dataframe(df)["column_profiles"]}
    assert prof["units"]["integer"] and not prof["revenue"]["integer"]
    for col in ("revenue", "units"):
        for b in prof[col]["histogram"]:
            assert {"start", "end", "count", "pct", "bin"} <= set(b) and not SCI.search(b["bin"])
    charts = [c for c in auto_charts(df) if c["type"] == "histogram"]
    assert charts and all("integer" in c and c["total"] == 600 and all("start" in r and "end" in r for r in c["data"]) for c in charts)
    assert not any(SCI.search(r["bin"]) for c in charts for r in c["data"])


def test_analysis_prose_has_no_scientific_notation():
    rng = np.random.default_rng(2)
    n = 400
    grp = rng.choice(["North", "South"], n)
    df = pd.DataFrame({"grp": grp, "rev": np.where(grp == "North", rng.normal(12600, 900, n), rng.normal(43800, 900, n))})
    df["x"] = df["rev"] * 3.1e3 + rng.normal(0, 1e6, n)
    txt = hypothesis.run_test(df, "t_welch", "rev", "grp", ["North", "South"])["interpretation"]
    assert not SCI.search(txt) and re.search(r"\d{2},\d{3}", txt)
    r = regression.run_regression(df, "x", ["rev"])
    assert not SCI.search(" ".join(r["interpretation"]))
    assert not any(SCI.search(b["bin"]) for b in r["charts"]["residual_histogram"])


def test_pdf_report_renders_histogram_with_readable_labels(tmp_path):
    from backend.app.services.reports import _chart_png

    rng = np.random.default_rng(3)
    spec = next(c for c in auto_charts(pd.DataFrame({"revenue": rng.normal(2.5e4, 8e3, 600)})) if c["type"] == "histogram")
    assert _chart_png(spec)[:4] == b"\x89PNG"
