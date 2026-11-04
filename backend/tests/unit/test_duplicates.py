"""Duplicate analysis vs an independent brute-force oracle (plain dict counting), on data with NaN, blanks and case/space variants."""
import math
import re
from collections import defaultdict

import numpy as np
import pandas as pd
import pytest

from backend.app.analytics import duplicates as dup
from backend.app.core.exceptions import AppError

MISSING = object()


def make_messy(seed: int, n: int = 400) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    names = rng.choice(["Ann", "ann ", " Ann", "Bob", "BOB", "Cy", "", "   ", None], n, p=[.2, .08, .05, .2, .05, .15, .1, .05, .12]).astype(object)
    df = pd.DataFrame({
        "name": names, "city": rng.choice(["Pune", "pune", "Delhi", None, ""], n).astype(object),
        "age": np.where(rng.random(n) < .15, np.nan, rng.integers(20, 24, n)).astype(float),
        "flag": rng.random(n) < .5, "joined": pd.to_datetime("2024-01-01") + pd.to_timedelta(rng.integers(0, 3, n), unit="D"),
        "row_id": np.arange(n),
    })
    df.loc[rng.random(n) < .1, "joined"] = pd.NaT
    return pd.concat([df, df.sample(40, random_state=seed)], ignore_index=True)     # planted exact duplicates (same row_id)


def oracle(df, cols, blank_as_missing=True, ignore_case_space=False):
    groups = defaultdict(list)
    for i, rec in enumerate(df[cols].to_dict("records")):
        key = []
        for c in cols:
            v = rec[c]
            if v is None or (isinstance(v, float) and math.isnan(v)) or v is pd.NaT:
                key.append(MISSING)
                continue
            if isinstance(v, str):
                if blank_as_missing and v.strip() == "":
                    key.append(MISSING)
                    continue
                if ignore_case_space:
                    v = re.sub(r"\s+", " ", v.strip()).lower()
            key.append(v)
        groups[tuple(key)].append(i)
    dups = {k: v for k, v in groups.items() if len(v) > 1}
    return {"extra": sum(len(v) - 1 for v in dups.values()), "groups": len(dups), "involved": sum(len(v) for v in dups.values()),
            "sizes": sorted((len(v) for v in dups.values()), reverse=True), "firsts": sorted(v[0] + 1 for v in dups.values()), "all": groups}


@pytest.mark.parametrize("seed", range(8))
@pytest.mark.parametrize("opts", [(True, False), (False, False), (True, True), (False, True)])
def test_matches_bruteforce_for_every_rule_combination(seed, opts):
    blank, ics = opts
    df = make_messy(seed)
    cols = list(df.columns)
    exp = oracle(df, cols, blank, ics)
    r = dup.analyze_duplicates(df, None, blank, ics, False, 500)
    assert (r["duplicate_rows"], r["groups"], r["rows_involved"]) == (exp["extra"], exp["groups"], exp["involved"])
    assert sorted((g["count"] for g in r["groups_list"]), reverse=True) == exp["sizes"]
    assert sorted(g["first_row"] for g in r["groups_list"]) == exp["firsts"]
    assert r["duplicate_pct"] == pytest.approx(exp["extra"] / len(df) * 100)
    assert r["unique_rows"] + r["groups"] + r["duplicate_rows"] == len(df)
    assert sum(c["value"] for c in r["composition"]) == len(df)
    assert sum(b["groups"] for b in r["distribution"]) == r["groups"] and sum(b["extra_rows"] for b in r["distribution"]) == r["duplicate_rows"]


@pytest.mark.parametrize("seed", range(6))
def test_subset_of_columns_and_ranking(seed):
    df = make_messy(seed + 20)
    cols = ["name", "city", "age"]
    exp = oracle(df, cols, True, True)
    r = dup.analyze_duplicates(df, cols, True, True, False, 500)
    assert (r["duplicate_rows"], r["groups"]) == (exp["extra"], exp["groups"]) and r["columns_used"] == cols and not r["all_columns"]
    counts = [g["count"] for g in r["groups_list"]]
    assert counts == sorted(counts, reverse=True)                                    # largest first
    for g in r["groups_list"][:10]:                                                   # every listed row number really belongs to the group
        key = [k for k, v in exp["all"].items() if v[0] + 1 == g["first_row"]][0]
        assert [i + 1 for i in exp["all"][key]][:50] == g["row_numbers"]


def test_missing_and_blank_semantics():
    df = pd.DataFrame({"a": ["x", "x", None, None, "", "  ", np.nan, "y"], "b": [1.0, 1.0, np.nan, np.nan, np.nan, np.nan, np.nan, 2.0]})
    r = dup.analyze_duplicates(df)                                                   # "", "  ", None, NaN are all "missing" -> rows 3-7 are one group
    assert r["groups"] == 2 and r["duplicate_rows"] == 1 + 4 and r["blank_cells_treated_as_missing"] == 2
    strict = dup.analyze_duplicates(df, blank_as_missing=False)                     # blank strings are real values; None and NaN still match
    assert strict["groups"] == 2 and strict["duplicate_rows"] == 1 + 2 and strict["blank_cells_treated_as_missing"] == 0
    assert dup.analyze_duplicates(pd.DataFrame({"a": [None, None, np.nan, pd.NaT]}))["duplicate_rows"] == 3


def test_case_and_spacing_only_when_asked():
    df = pd.DataFrame({"n": ["Ann", "ann", " ANN ", "A  nn", "Ann"], "v": 1})
    assert dup.analyze_duplicates(df)["duplicate_rows"] == 1                         # exact: only the two "Ann"
    r = dup.analyze_duplicates(df, ignore_case_space=True)
    assert r["duplicate_rows"] == 3 and r["groups"] == 1 and r["groups_list"][0]["count"] == 4


def test_types_are_not_confused():
    df = pd.DataFrame({"a": [1, 1.0, True, "1", 1], "b": 0})
    r = dup.analyze_duplicates(df)
    assert r["groups"] == 1 and r["groups_list"][0]["count"] >= 2                    # 1 / 1.0 / True collapse in pandas; "1" stays distinct
    assert not any(g["values"]["a"] == "1" for g in r["groups_list"])


def test_id_like_hint_and_exclusion():
    df = pd.DataFrame({"order_id": range(10), "who": ["a", "a", "b", "c", "c", "c", "d", "e", "f", "g"], "amt": [1, 1, 2, 3, 3, 3, 4, 5, 6, 7]})
    r = dup.analyze_duplicates(df)
    assert r["duplicate_rows"] == 0 and r["hint"] and r["hint"]["columns"] == ["order_id"] and r["hint"]["duplicate_rows"] == 3
    r2 = dup.analyze_duplicates(df, exclude_id_like=True)
    assert r2["duplicate_rows"] == 3 and r2["groups"] == 2 and "order_id" not in r2["columns_used"] and r2["hint"] is None
    assert dup.analyze_duplicates(df.drop(columns="order_id"))["hint"] is None


def test_edge_cases_and_errors():
    assert dup.analyze_duplicates(pd.DataFrame({"a": []}))["duplicate_rows"] == 0
    one = dup.analyze_duplicates(pd.DataFrame({"a": [1]}))
    assert one["duplicate_rows"] == 0 and one["unique_rows"] == 1
    same = dup.analyze_duplicates(pd.DataFrame({"a": [5] * 6, "b": ["x"] * 6}))
    assert same["duplicate_rows"] == 5 and same["duplicate_pct"] == pytest.approx(5 / 6 * 100) and same["groups_list"][0]["count"] == 6
    assert same["distribution"][3]["label"] == "5–9×" and same["distribution"][3]["groups"] == 1
    with pytest.raises(AppError, match="Unknown column"):
        dup.analyze_duplicates(pd.DataFrame({"a": [1]}), ["zzz"])
    with pytest.raises(AppError, match="out of range"):
        dup.rows_for_numbers(pd.DataFrame({"a": [1, 2]}), [3])


def test_limit_only_truncates_the_listing_not_the_counts():
    df = pd.DataFrame({"a": np.repeat(np.arange(30), 2)})
    r = dup.analyze_duplicates(df, limit=5)
    assert r["groups"] == 30 and r["duplicate_rows"] == 30 and r["groups_returned"] == 5 and len(r["groups_list"]) == 5


def test_summary_matches_full_analysis_and_does_not_mutate_input():
    df = make_messy(3)
    before = df.copy(deep=True)
    s = dup.duplicate_summary(df)
    r = dup.analyze_duplicates(df)
    assert (s["duplicate_rows"], s["groups"], s["rows"], s["blank_cells"]) == (r["duplicate_rows"], r["groups"], r["rows"], r["blank_cells_treated_as_missing"])
    pd.testing.assert_frame_equal(df, before)


def test_row_inspection_and_export_frame():
    df = pd.DataFrame({"k": ["a", "b", "a", None, None], "v": [1, 2, 1, np.nan, np.nan]})
    r = dup.analyze_duplicates(df)
    g = r["groups_list"][0]
    rows = dup.rows_for_numbers(df, g["row_numbers"])
    assert [x["__row__"] for x in rows] == g["row_numbers"] and all(x["k"] == g["values"]["k"] for x in rows[:2] if g["values"]["k"])
    allrows = dup.all_duplicate_rows(df, None, True, False, False)
    assert allrows["row_number"].tolist() == [1, 3, 4, 5] and allrows["group_id"].tolist() == [1, 1, 2, 2] and allrows["occurrence"].tolist() == [1, 2, 1, 2]


def test_document_duplicates():
    text = ("Refund policy applies to all purchases within thirty days.\n\nShipping takes five business days.\n\n"
            "refund   POLICY applies to all purchases within thirty days.\n\nShort.\n\nShort.\n\nShipping takes five business days.\n\nShipping takes five business days.")
    r = dup.analyze_text_duplicates(text)
    assert r["unit"] == "paragraphs" and r["rows"] == 7
    assert r["groups"] == 2 and r["duplicate_rows"] == 1 + 2                         # refund x2 (case/space-insensitive), shipping x3; "Short." ignored (<20 chars)
    assert r["groups_list"][0]["count"] == 3 and r["groups_list"][0]["row_numbers"] == [2, 6, 7]
    assert dup.text_rows(text, [2, 6])[0]["paragraph"].startswith("Shipping")
    assert dup.analyze_text_duplicates("Only one paragraph here, nothing repeats.")["duplicate_rows"] == 0
