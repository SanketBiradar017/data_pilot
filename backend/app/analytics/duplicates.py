"""Duplicate analysis for tables (identical rows) and documents (repeated paragraphs).

Definitions
* Two rows are duplicates when they are equal in every compared column. Missing values (NaN / None / NaT) are equal to each
  other. Blank text ('' or only spaces) is treated as missing by default (`blank_as_missing`), so "" and NULL match.
* Text is compared exactly (case and spacing matter) unless `ignore_case_space` is on.
* "Duplicate rows" = extra copies: a record that appears 3 times contributes 2. This is exactly what removing duplicates
  (keep first) would delete, so the percentage is the share of the table that is redundant.
"""
import re

import numpy as np
import pandas as pd

from backend.app.analytics.utils import is_id_like, is_text, jsonable
from backend.app.core.exceptions import AppError

BUCKETS = [(2, 2, "2×"), (3, 3, "3×"), (4, 4, "4×"), (5, 9, "5–9×"), (10, 10**12, "10×+")]


def _normalise(df: pd.DataFrame, cols: list[str], blank_as_missing: bool, ignore_case_space: bool) -> tuple[pd.DataFrame, int]:
    """Comparison copy of the chosen columns plus the number of blank cells that were treated as missing."""
    work = pd.DataFrame(index=df.index)
    blanks = 0
    for c in cols:
        s = df[c]
        if is_text(s):
            o = s.astype(object)
            blank = o.map(lambda v: isinstance(v, str) and v.strip() == "")
            if blank_as_missing:
                blanks += int(blank.sum())
                o = o.where(~blank, None)
            if ignore_case_space:
                o = o.map(lambda v: re.sub(r"\s+", " ", v.strip()).lower() if isinstance(v, str) else v)
            o = o.where(o.notna(), None)                # None and NaN are one and the same "missing"
            work[c] = o
        else:
            work[c] = s
    return work, blanks


def _group_ids(work: pd.DataFrame) -> np.ndarray:
    return work.groupby(list(work.columns), dropna=False, sort=False).ngroup().to_numpy()


def _resolve_columns(df: pd.DataFrame, columns: list[str] | None, exclude_id_like: bool) -> list[str]:
    cols = list(columns) if columns else list(df.columns)
    bad = [c for c in cols if c not in df.columns]
    if bad:
        raise AppError(f"Unknown column(s): {', '.join(bad)}")
    if len(set(cols)) != len(cols):
        raise AppError("Duplicate column names in the selection")
    if exclude_id_like and not columns:
        cols = [c for c in cols if not is_id_like(df[c])] or cols
    return cols


def _clean_value(v):
    return jsonable(v) if not (isinstance(v, str) and v == "") else ""


def _core(df: pd.DataFrame, cols: list[str], blank_as_missing: bool, ignore_case_space: bool):
    work, blanks = _normalise(df, cols, blank_as_missing, ignore_case_space)
    gid = _group_ids(work)
    sizes = np.bincount(gid) if len(gid) else np.array([], dtype=int)
    return gid, sizes, blanks


def duplicate_summary(df: pd.DataFrame) -> dict:
    """Cheap counts for upload time (exact duplicates over all columns, default rules)."""
    n = len(df)
    if n == 0 or len(df.columns) == 0:
        return {"rows": n, "duplicate_rows": 0, "groups": 0, "pct": 0.0, "blank_cells": 0}
    gid, sizes, blanks = _core(df, list(df.columns), True, False)
    dup = sizes[sizes > 1]
    extra = int((dup - 1).sum())
    return {"rows": n, "duplicate_rows": extra, "groups": int(len(dup)), "pct": round(extra / n * 100, 4), "blank_cells": blanks}


def analyze_duplicates(df: pd.DataFrame, columns: list[str] | None = None, blank_as_missing: bool = True,
                       ignore_case_space: bool = False, exclude_id_like: bool = False, limit: int = 100) -> dict:
    n = len(df)
    cols = _resolve_columns(df, columns, exclude_id_like)
    if n == 0 or not cols:
        return jsonable(_empty(n, cols))
    gid, sizes, blanks = _core(df, cols, blank_as_missing, ignore_case_space)
    dup_gids = np.flatnonzero(sizes > 1)
    extra = int((sizes[dup_gids] - 1).sum())
    involved = int(sizes[dup_gids].sum())

    # positions of every row of each group, without a per-group scan of the whole table
    order = np.argsort(gid, kind="stable")
    starts = np.concatenate([[0], np.cumsum(sizes)])
    first_pos = {int(g): int(order[starts[g]]) for g in dup_gids}
    ranked = sorted(dup_gids.tolist(), key=lambda g: (-int(sizes[g]), first_pos[g]))

    groups = []
    for k, g in enumerate(ranked[:limit]):
        pos = order[starts[g]:starts[g + 1]]
        first = df.iloc[int(pos[0])]
        groups.append({"id": k + 1, "count": int(sizes[g]), "extra": int(sizes[g]) - 1, "first_row": int(pos[0]) + 1,
                       "row_numbers": (pos[:50] + 1).tolist(), "values": {c: _clean_value(first[c]) for c in cols},
                       "share_of_duplicates_pct": (int(sizes[g]) - 1) / extra * 100 if extra else 0.0})

    dist = []
    for lo, hi, label in BUCKETS:
        sel = sizes[(sizes >= lo) & (sizes <= hi)]
        dist.append({"label": label, "groups": int(len(sel)), "extra_rows": int((sel - 1).sum()), "rows": int(sel.sum())})
    singles = int((sizes == 1).sum())
    result = {
        "unit": "rows", "rows": n, "columns_used": cols, "all_columns": len(cols) == len(df.columns),
        "duplicate_rows": extra, "duplicate_pct": extra / n * 100, "groups": int(len(dup_gids)), "rows_involved": involved,
        "rows_involved_pct": involved / n * 100, "unique_rows": singles, "unique_records": int(len(sizes)),
        "largest_group": int(sizes.max()) if len(sizes) else 0, "blank_cells_treated_as_missing": blanks if blank_as_missing else 0,
        "options": {"blank_as_missing": blank_as_missing, "ignore_case_space": ignore_case_space, "exclude_id_like": exclude_id_like},
        "groups_list": groups, "groups_returned": len(groups), "distribution": dist,
        "top": [{"label": _label(g["values"]), "count": g["count"], "id": g["id"]} for g in groups[:10]],
        "composition": [{"label": "Unique rows", "value": singles}, {"label": "First copies (kept)", "value": len(dup_gids)}, {"label": "Extra copies (redundant)", "value": extra}],
        "hint": None,
    }
    if extra == 0 and not columns and not exclude_id_like:   # rows that differ only by an auto-number look unique but are not
        ids = [c for c in cols if is_id_like(df[c])]
        if ids and len(ids) < len(cols):
            alt = analyze_duplicates(df, None, blank_as_missing, ignore_case_space, True, 1)
            if alt["duplicate_rows"] > 0:
                result["hint"] = {"columns": ids, "duplicate_rows": alt["duplicate_rows"], "groups": alt["groups"],
                                  "message": f"No exact duplicates, but {alt['duplicate_rows']:,} row(s) are identical apart from {', '.join(ids)}. Try ignoring ID-like columns."}
    return jsonable(result)


def _label(values: dict, max_cols: int = 3, width: int = 22) -> str:
    parts = []
    for c, v in list(values.items())[:max_cols]:
        t = "∅" if v is None else "(blank)" if v == "" else str(v)
        parts.append(t if len(t) <= width else t[: width - 1] + "…")
    return " · ".join(parts) + (" …" if len(values) > max_cols else "")


def _empty(n: int, cols: list[str]) -> dict:
    return {"unit": "rows", "rows": n, "columns_used": cols, "all_columns": True, "duplicate_rows": 0, "duplicate_pct": 0.0, "groups": 0, "rows_involved": 0,
            "rows_involved_pct": 0.0, "unique_rows": n, "unique_records": n, "largest_group": 1 if n else 0, "blank_cells_treated_as_missing": 0,
            "options": {}, "groups_list": [], "groups_returned": 0, "distribution": [{"label": b[2], "groups": 0, "extra_rows": 0, "rows": 0} for b in BUCKETS],
            "top": [], "composition": [{"label": "Unique rows", "value": n}, {"label": "First copies (kept)", "value": 0}, {"label": "Extra copies (redundant)", "value": 0}], "hint": None}


def rows_for_numbers(df: pd.DataFrame, row_numbers: list[int]) -> list[dict]:
    """Original rows by 1-based row number (for inspection)."""
    bad = [r for r in row_numbers if r < 1 or r > len(df)]
    if bad:
        raise AppError(f"Row number(s) out of range: {bad[:5]}")
    sub = df.iloc[[r - 1 for r in row_numbers]]
    out = []
    for r, (_, row) in zip(row_numbers, sub.iterrows()):
        out.append({"__row__": r, **{c: _clean_value(row[c]) for c in df.columns}})
    return out


def all_duplicate_rows(df: pd.DataFrame, columns: list[str] | None, blank_as_missing: bool, ignore_case_space: bool, exclude_id_like: bool, cap: int = 100_000) -> pd.DataFrame:
    """Every row that belongs to a duplicate group, with group id, occurrence number and row number (for export)."""
    cols = _resolve_columns(df, columns, exclude_id_like)
    if len(df) == 0 or not cols:
        return pd.DataFrame(columns=["group_id", "occurrence", "row_number", *df.columns])
    gid, sizes, _ = _core(df, cols, blank_as_missing, ignore_case_space)
    pos = np.flatnonzero(sizes[gid] > 1)
    first = {}
    for p in pos:
        first.setdefault(int(gid[p]), int(p))
    ranked = sorted(first, key=lambda g: (-int(sizes[g]), first[g]))
    rank = {g: i + 1 for i, g in enumerate(ranked)}
    out = df.iloc[pos].copy()
    out.insert(0, "row_number", pos + 1)
    out.insert(0, "group_id", [rank[int(gid[p])] for p in pos])
    out = out.sort_values(["group_id", "row_number"], kind="stable")
    out.insert(1, "occurrence", out.groupby("group_id").cumcount() + 1)
    return out.head(cap)


# ---------------------------------------------------------------------------------- documents
def analyze_text_duplicates(text: str, ignore_case_space: bool = True, limit: int = 100, min_chars: int = 20) -> dict:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    keyed = []
    for i, p in enumerate(paras):
        k = re.sub(r"\s+", " ", p).lower() if ignore_case_space else p
        keyed.append((i, p, k if len(p) >= min_chars else None))
    n = len(paras)
    buckets: dict[str, list[int]] = {}
    for i, _, k in keyed:
        if k is not None:
            buckets.setdefault(k, []).append(i)
    dups = {k: v for k, v in buckets.items() if len(v) > 1}
    extra = sum(len(v) - 1 for v in dups.values())
    ranked = sorted(dups.values(), key=lambda v: (-len(v), v[0]))
    groups = [{"id": k + 1, "count": len(v), "extra": len(v) - 1, "first_row": v[0] + 1, "row_numbers": [i + 1 for i in v[:50]],
               "values": {"paragraph": paras[v[0]][:300]}, "share_of_duplicates_pct": (len(v) - 1) / extra * 100 if extra else 0.0}
              for k, v in enumerate(ranked[:limit])]
    sizes = np.array([len(v) for v in dups.values()], dtype=int)
    dist = []
    for lo, hi, label in BUCKETS:
        sel = sizes[(sizes >= lo) & (sizes <= hi)] if len(sizes) else sizes
        dist.append({"label": label, "groups": int(len(sel)), "extra_rows": int((sel - 1).sum()) if len(sel) else 0, "rows": int(sel.sum()) if len(sel) else 0})
    involved = int(sizes.sum()) if len(sizes) else 0
    return jsonable({
        "unit": "paragraphs", "rows": n, "columns_used": ["paragraph"], "all_columns": True, "duplicate_rows": extra, "duplicate_pct": extra / n * 100 if n else 0.0,
        "groups": len(dups), "rows_involved": involved, "rows_involved_pct": involved / n * 100 if n else 0.0, "unique_rows": n - involved,
        "unique_records": n - extra, "largest_group": int(sizes.max()) if len(sizes) else (1 if n else 0), "blank_cells_treated_as_missing": 0,
        "options": {"ignore_case_space": ignore_case_space}, "groups_list": groups, "groups_returned": len(groups), "distribution": dist,
        "top": [{"label": g["values"]["paragraph"][:40] + ("…" if len(g["values"]["paragraph"]) > 40 else ""), "count": g["count"], "id": g["id"]} for g in groups[:10]],
        "composition": [{"label": "Unique paragraphs", "value": n - involved}, {"label": "First copies (kept)", "value": len(dups)}, {"label": "Extra copies (redundant)", "value": extra}],
        "hint": None,
    })


def text_rows(text: str, row_numbers: list[int]) -> list[dict]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    bad = [r for r in row_numbers if r < 1 or r > len(paras)]
    if bad:
        raise AppError(f"Paragraph number(s) out of range: {bad[:5]}")
    return [{"__row__": r, "paragraph": paras[r - 1]} for r in row_numbers]
