"""Duplicate analysis vs a brute-force oracle (plain tuples + Counter) on deliberately messy tables."""
import math
import re
from collections import Counter

import numpy as np
import pandas as pd
import pytest

from backend.app.analytics import duplicates as dup
from backend.app.core.exceptions import AppError

MISSING = ("<missing>",)


def messy(seed: int, n: int = 400) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    base = pd.DataFrame({
        "name": rng.choice(["Ann", "ann", " Ann ", "Bob", "Cy", "", "   ", None, np.nan], n),
        "qty": np.where(rng.random(n) < 0.1, np.nan, rng.integers(1, 5, n)).astype(float),
        "flag": rng.choice([True, False], n),
        "when": pd.to_datetime("2025-01-01") + pd.to_timedelta(np.where(rng.random(n) < 0.1, np.nan, rng.integers(0, 4, n)), unit="D"),
        "price": rng.choice([1.5, -0.0, 0.0, 2.25, np.nan], n),
        "city": rng.choice(["Pune", "pune", "Delhi", None], n),
    })
    extra = base.sample(int(n * 0.3), random_state=seed, replace=True)          # exact copies, some many times
    return pd.concat([base, extra, extra.head(25)], ignore_index=True).sample(frac=1, random_state=seed).reset_index(drop=True)


def cell(v, blank_as_missing, ignore):
    if v is None or (isinstance(v, float) and math.isnan(v)) or v is pd.NaT:
        return MISSING
    if isinstance(v, str):
        if blank_as_missing and v.strip() == "":
            return MISSING
        return re.sub(r"\s+", " ", v.strip()).lower() if ignore else v
    if isinstance(v, (float, np.floating)):
        return float(v) + 0.0                       # -0.0 == 0.0
    return v


def oracle(df, cols, blank_as_missing=True, ignore=False):
    keys = [tuple(cell(r[c], blank_as_missing, ignore) for c in cols) for r in df.to_dict("records")]
    cnt = Counter(keys)
    first = {}
    for i, k in enumerate(keys):
        first.setdefault(k, i)
    groups = sorted(((k, c) for k, c in cnt.items() if c > 1), key=lambda kc: (-kc[1], first[kc[0]]))
    return {"extra": sum(c - 1 for _, c in groups), "groups": [(c, first[k] + 1) for k, c in groups], "involved": sum(c for _, c in groups), "unique": sum(1 for c in cnt.values() if c == 1)}


@pytest.mark.parametrize("seed", range(14))
@pytest.mark.parametrize("blank,ignore", [(True, False), (False, False), (True, True), (False, True)])
def test_matches_bruteforce(seed, blank, ignore):
    df = messy(seed)
    res = dup.analyze_duplicates(df, None, blank, ignore, False, 500)
    exp = oracle(df, list(df.columns), blank, ignore)
    assert res["duplicate_rows"] == exp["extra"] and res["groups"] == len(exp["groups"]) and res["rows_involved"] == exp["involved"]
    assert res["unique_rows"] == exp["unique"]
    assert [(g["count"], g["first_row"]) for g in res["groups_list"]] == exp["groups"][:500]
    assert res["duplicate_pct"] == pytest.approx(exp["extra"] / len(df) * 100)
    assert sum(c["value"] for c in res["composition"]) == len(df)                       # unique + first copies + extra copies = every row
    assert sum(b["extra_rows"] for b in res["distribution"]) == exp["extra"] and sum(b["groups"] for b in res["distribution"]) == len(exp["groups"])
    # every listed row number really belongs to the group
    for g in res["groups_list"][:10]:
        keys = {tuple(cell(df.iloc[r - 1][c], blank, ignore) for c in df.columns) for r in g["row_numbers"]}
        assert len(keys) == 1 and len(g["row_numbers"]) == min(g["count"], 50)


@pytest.mark.parametrize("seed", range(6))
def test_subset_of_columns_matches_bruteforce(seed):
    df = messy(seed + 50)
    cols = ["name", "city"]
    res = dup.analyze_duplicates(df, cols, True, False, False, 500)
    exp = oracle(df, cols)
    assert res["duplicate_rows"] == exp["extra"] and [(g["count"], g["first_row"]) for g in res["groups_list"]] == exp["groups"]
    assert res["columns_used"] == cols and set(res["groups_list"][0]["values"]) == set(cols)


def test_missing_and_blank_rules():
    df = pd.DataFrame({"a": ["x", "x", "", None, np.nan, "  ", "y"], "b": [1.0, 1.0, np.nan, np.nan, np.nan, np.nan, 2.0]})
    r = dup.analyze_duplicates(df)                                   # blanks == missing: rows 3-6 are all the same record
    assert r["duplicate_rows"] == 1 + 3 and r["groups"] == 2 and r["blank_cells_treated_as_missing"] == 2
    r2 = dup.analyze_duplicates(df, blank_as_missing=False)         # '' and '  ' stay distinct from missing
    assert r2["duplicate_rows"] == 1 + 1 and r2["groups"] == 2       # (x,1)x2 and (None,nan)+(nan,nan) share NaN
    assert dup.analyze_duplicates(pd.DataFrame({"a": ["Smith", "smith ", "SMITH"]}))["duplicate_rows"] == 0
    assert dup.analyze_duplicates(pd.DataFrame({"a": ["Smith", "smith ", "SMITH"]}), ignore_case_space=True)["duplicate_rows"] == 2


def test_types_that_look_alike_are_not_confused():
    df = pd.DataFrame({"a": [1, 1.0, 2, 2], "b": ["1", "1", "2", "2"]})
    assert dup.analyze_duplicates(df)["duplicate_rows"] == 2          # 1 == 1.0 within a numeric column, text '1' separate column
    z = pd.DataFrame({"v": [0.0, -0.0, np.nan, np.nan]})
    assert dup.analyze_duplicates(z)["duplicate_rows"] == 2


def test_edge_tables():
    assert dup.analyze_duplicates(pd.DataFrame({"a": []}))["duplicate_rows"] == 0
    one = dup.analyze_duplicates(pd.DataFrame({"a": [1]}))
    assert one["duplicate_rows"] == 0 and one["duplicate_pct"] == 0 and one["groups_list"] == []
    same = dup.analyze_duplicates(pd.DataFrame({"a": [7] * 50, "b": ["x"] * 50}))
    assert same["duplicate_rows"] == 49 and same["groups"] == 1 and same["largest_group"] == 50 and same["duplicate_pct"] == pytest.approx(98.0)
    assert same["groups_list"][0]["count"] == 50 and len(same["groups_list"][0]["row_numbers"]) == 50
    none = dup.analyze_duplicates(pd.DataFrame({"a": range(30)}))
    assert none["duplicate_rows"] == 0 and none["unique_rows"] == 30


def test_distribution_buckets():
    df = pd.DataFrame({"k": [1] * 2 + [2] * 3 + [3] * 4 + [4] * 7 + [5] * 12 + [6] * 12 + [7]})
    d = {b["label"]: b for b in dup.analyze_duplicates(df)["distribution"]}
    assert (d["2×"]["groups"], d["3×"]["groups"], d["4×"]["groups"], d["5–9×"]["groups"], d["10×+"]["groups"]) == (1, 1, 1, 1, 2)
    assert d["10×+"]["extra_rows"] == 22 and d["5–9×"]["rows"] == 7


def test_id_like_columns_hint_and_exclusion():
    df = pd.DataFrame({"order_id": range(1, 41), "item": ["a", "b"] * 20, "qty": [1, 2] * 20})
    r = dup.analyze_duplicates(df)
    assert r["duplicate_rows"] == 0 and r["hint"] and r["hint"]["columns"] == ["order_id"] and r["hint"]["duplicate_rows"] == 38
    r2 = dup.analyze_duplicates(df, exclude_id_like=True)
    assert r2["duplicate_rows"] == 38 and "order_id" not in r2["columns_used"] and r2["hint"] is None


def test_invalid_columns():
    with pytest.raises(AppError, match="Unknown column"):
        dup.analyze_duplicates(pd.DataFrame({"a": [1]}), ["nope"])
    with pytest.raises(AppError, match="Duplicate column"):
        dup.analyze_duplicates(pd.DataFrame({"a": [1, 1]}), ["a", "a"])


def test_summary_matches_full_analysis():
    df = messy(3)
    s, full = dup.duplicate_summary(df), dup.analyze_duplicates(df)
    assert (s["rows"], s["duplicate_rows"], s["groups"]) == (len(df), full["duplicate_rows"], full["groups"]) and s["pct"] == pytest.approx(full["duplicate_pct"], abs=1e-3)


def test_rows_for_numbers_and_all_duplicate_rows():
    df = pd.DataFrame({"a": ["x", "y", "x", "z", "y", "x"], "b": [1, 2, 1, 3, 2, 1]})
    rows = dup.rows_for_numbers(df, [1, 3, 6])
    assert [r["__row__"] for r in rows] == [1, 3, 6] and all(r["a"] == "x" for r in rows)
    with pytest.raises(AppError, match="out of range"):
        dup.rows_for_numbers(df, [7])
    allrows = dup.all_duplicate_rows(df, None, True, False, False)
    assert allrows["row_number"].tolist() == [1, 3, 6, 2, 5] and allrows["group_id"].tolist() == [1, 1, 1, 2, 2] and allrows["occurrence"].tolist() == [1, 2, 3, 1, 2]


def test_document_paragraph_duplicates():
    text = ("Refund policy\n\nCustomers may request a refund within thirty days.\n\nShipping takes five business days.\n\n"
            "customers  may request a refund within thirty days.\n\nShort\n\nShort\n\nShipping takes five business days.\n\nShipping takes five business days.")
    r = dup.analyze_text_duplicates(text)
    assert r["unit"] == "paragraphs" and r["rows"] == 8 and r["duplicate_rows"] == 3 and r["groups"] == 2     # 'Short' too short to count
    g = {x["count"]: x for x in r["groups_list"]}
    assert g[3]["row_numbers"] == [3, 7, 8] and g[2]["row_numbers"] == [2, 4]      # paragraphs: 1 Refund policy, 2 Customers, 3 Shipping, 4 customers, 5-6 Short, 7-8 Shipping
    assert dup.analyze_text_duplicates(text, ignore_case_space=False)["duplicate_rows"] == 2
    assert dup.text_rows(text, [2])[0]["paragraph"].startswith("Customers may")
