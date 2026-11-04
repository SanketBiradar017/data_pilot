"""Natural language -> SQL. Heuristic generator with optional LLM refinement; every
candidate is validated by the read-only validator and dry-run by the caller."""
import re

import pandas as pd

from backend.app.analytics.llm import llm_complete
from backend.app.analytics.question import (
    _STOP,  # noqa: F401  (re-exported for callers that imported it from here)
    _match_cols,
    _stem,  # noqa: F401
    describe_filters,
    filters_sql,
    measure_cols,
    prepare,
)
from backend.app.analytics.sql_engine import validate_read_query
from backend.app.analytics.utils import categorical_cols, datetime_cols

_METRIC_HINT = ("revenue", "sales", "amount", "price", "total", "profit", "cost", "value", "quantity", "qty", "spend")
_TIME_Q = re.compile(r"over time|trend|monthly|weekly|daily|yearly|quarterly|by (month|week|day|year|quarter)|per (month|week|day|year|quarter)")


def _q(c: str) -> str:
    return '"' + c.replace('"', '""') + '"'


def parse_spec(question: str, df: pd.DataFrame, prep: dict | None = None) -> dict:
    """Read a question as a structured query spec. `explicit` records which parts the user actually said,
    which is what follow-up merging needs."""
    prep = prep or prepare(question, df)
    text, roles = prep["text"], prep["roles"]
    ql = text.lower()
    nums, cats, dts = measure_cols(df), categorical_cols(df), datetime_cols(df)
    all_cols = list(df.columns)
    mentioned = _match_cols(text, all_cols)
    m_num = [c for c in mentioned if c in nums]
    m_cat = [c for c in mentioned if c in cats and c not in m_num]
    m_dt = [c for c in mentioned if c in dts]

    metric_expr = None
    if re.search(r"\bprofits?\b", ql) and not any("profit" in c.lower() for c in all_cols) and roles.get("revenue") and roles.get("cost"):
        metric_expr = {"rev": roles["revenue"], "cost": roles["cost"]}
    metric = "profit" if metric_expr else (m_num[0] if m_num else next((c for h in _METRIC_HINT for c in nums if h in c.lower()), nums[0] if nums else None))
    metric_explicit = bool(m_num) or bool(metric_expr)
    n_match = re.search(r"\b(?:top|bottom|first|best|worst)\s+(\d+)", ql)
    limit = int(n_match.group(1)) if n_match else (10 if re.search(r"\btop|bottom|best|worst|highest|lowest\b", ql) else None)
    desc = not re.search(r"bottom|lowest|worst|least|smallest", ql)

    agg = "SUM"
    if re.search(r"average|avg|mean", ql):
        agg = "AVG"
    elif re.search(r"\bmax|maximum|highest|largest|biggest", ql) and not limit:
        agg = "MAX"
    elif re.search(r"\bmin|minimum|lowest|smallest", ql) and not limit:
        agg = "MIN"
    elif re.search(r"median", ql):
        agg = "MEDIAN"
    count_words = bool(re.search(r"\bhow many\b|\bcount(?:s|ing)?\b|\bnumber of\b", ql))
    by = re.search(r"\b(?:by|per|each|across|for each|grouped by)\s+([a-z0-9_ ]+)", ql)
    distinct = None  # "how many customers" counts distinct customer ids, not rows
    cm = re.search(r"(?:how many|count(?: of)?|number of|total|sum of)\s+(?:the\s+|distinct\s+|unique\s+)*([a-z0-9_]+)", ql[: by.start()] if by else ql)
    if cm:
        hit = _match_cols(cm.group(1), all_cols)
        if hit and hit[0] not in nums and hit[0] not in dts:
            distinct, count_words = hit[0], True
            m_cat = [c for c in m_cat if c != distinct]  # "how many customers" must not group by customer
    agg_explicit = count_words or bool(re.search(r"average|avg|mean|\bmax|maximum|highest|largest|biggest|\bmin|minimum|lowest|smallest|median|\btotal|\bsum\b", ql))
    is_count = count_words or metric is None

    group = None
    if by:
        cand = _match_cols(by.group(1), all_cols)
        # "top 5 X by revenue": a numeric column after "by" is the ranking metric, not a group
        if cand and cand[0] in nums:
            metric, metric_explicit = cand[0], True
            cand = [c for c in cand if c not in nums]
        group = cand[0] if cand else None
    if not group and m_cat:
        group = m_cat[0]
    time_q = _TIME_Q.search(ql)
    grain = t_col = None
    if time_q and dts:
        grain = ("week" if "week" in ql else "day" if re.search(r"daily|day", ql) else "year" if "year" in ql
                 else "quarter" if "quarter" in ql else "month")
        t_col = m_dt[0] if m_dt else dts[0]

    spec = {"agg": agg, "metric": metric, "metric_expr": metric_expr, "group": group, "grain": grain, "time_col": t_col,
            "limit": limit, "desc": desc, "filters": prep["filters"], "distinct": None}
    if grain:
        spec |= {"kind": "trend", "agg": "COUNT" if is_count else agg, "group": None, "distinct": distinct if is_count else None,
                 "rationale": f"{grain}ly trend of {'COUNT(*)' if is_count else agg + '(' + str(metric) + ')'} over {t_col}", "confidence": 0.8}
    elif group and is_count and not m_num:
        spec |= {"kind": "group_count", "agg": "COUNT", "metric": None, "distinct": distinct,
                 "rationale": f"Distinct {distinct} per {group}" if distinct else f"Row count per {group}", "confidence": 0.75}
    elif group and metric:
        spec |= {"kind": "group_agg", "rationale": f"{agg} of {metric} grouped by {group}", "confidence": 0.75}
    elif is_count:
        spec |= {"kind": "count", "agg": "COUNT", "metric": None, "distinct": distinct,
                 "rationale": f"Distinct {distinct}" if distinct else "Total row count", "confidence": 0.7}
    elif limit and metric:
        spec |= {"kind": "rank_rows", "rationale": f"Rows ranked by {metric}", "confidence": 0.65}
    elif metric:
        spec |= {"kind": "agg", "rationale": f"{agg} of {metric}", "confidence": 0.6}
    else:
        spec |= {"kind": "sample", "rationale": "No specific metric found; sampling rows", "confidence": 0.2}
    spec["explicit"] = {"entity": distinct is not None and spec["kind"] in ("count", "group_count", "trend"), "agg": agg_explicit, "metric": metric_explicit, "group": group is not None, "grain": grain is not None,
                        "limit": bool(n_match) or (limit is not None and not grain)}
    return spec


def describe_spec(spec: dict) -> str:
    """One plain sentence saying how the question was read, shown to the user above the answer."""
    agg, m = spec.get("agg"), "profit (revenue − cost)" if spec.get("metric_expr") else spec.get("metric")
    names = {"SUM": "Total", "AVG": "Average", "MAX": "Maximum", "MIN": "Minimum", "MEDIAN": "Median"}
    kind = spec["kind"]
    if kind == "sample":
        return "No measure found in the question, so this is a sample of rows."
    if kind in ("count", "group_count") or agg == "COUNT":
        s = f"Number of distinct {spec['distinct']}" if spec.get("distinct") else "Number of rows"
    elif kind == "rank_rows":
        s = f"Rows with the {'highest' if spec.get('desc', True) else 'lowest'} {m}"
    else:
        s = f"{names[agg]} {m}"
    if spec.get("grain"):
        s += f" by {spec['grain']} ({spec['time_col']})"
    elif spec.get("group"):
        s += f" by {spec['group']}"
    if spec.get("limit") and kind not in ("agg", "trend", "rank_rows"):
        s += f", {'top' if spec.get('desc', True) else 'bottom'} {spec['limit']}"
    if spec.get("filters"):
        s += f", only where {describe_filters(spec['filters'])}"
    return s


def _mcol(spec: dict) -> str:
    mx = spec.get("metric_expr")
    return f"({_q(mx['rev'])} - {_q(mx['cost'])})" if mx else _q(spec["metric"])


def _agg(spec: dict, agg: str) -> tuple[str, str]:
    alias = "profit" if spec.get("metric_expr") else spec["metric"][:40]
    return f"{agg}({_mcol(spec)})", f"{agg.lower()}_{alias}"


def _count(spec: dict) -> str:
    return f"COUNT(DISTINCT {_q(spec['distinct'])})" if spec.get("distinct") else "COUNT(*)"


def spec_sql(spec: dict, table: str) -> str:
    w = filters_sql(spec.get("filters") or [])
    frm = f"FROM {table}" + (f"\nWHERE {w}" if w else "")
    kind, agg = spec["kind"], spec.get("agg") or "SUM"
    order = "DESC" if spec.get("desc", True) else "ASC"
    lim = f"\nLIMIT {spec['limit']}" if spec.get("limit") else ""
    if kind == "trend":
        expr = _count(spec) if agg == "COUNT" else _agg(spec, agg)[0]
        return (f"SELECT DATE_TRUNC('{spec['grain']}', {_q(spec['time_col'])}) AS period, {expr} AS value\n{frm}\n"
                f"GROUP BY 1\nORDER BY 1")
    if kind == "group_count":
        return f"SELECT {_q(spec['group'])}, {_count(spec)} AS count\n{frm}\nGROUP BY 1\nORDER BY 2 {order}{lim}"
    if kind == "group_agg":
        expr, alias = _agg(spec, agg)
        return f"SELECT {_q(spec['group'])}, {expr} AS {alias}\n{frm}\nGROUP BY 1\nORDER BY 2 {order}{lim}"
    if kind == "count":
        return f"SELECT {_count(spec)} AS {'unique_' + spec['distinct'][:40] if spec.get('distinct') else 'row_count'} {frm}"
    if kind == "rank_rows":
        return f"SELECT *\n{frm}\nORDER BY {_mcol(spec)} {order}\nLIMIT {spec['limit']}"
    if kind == "agg":
        expr, alias = _agg(spec, agg)
        return f"SELECT {expr} AS {alias}, COUNT(*) AS rows\n{frm}"
    return f"SELECT * {frm} LIMIT 100"


def heuristic_sql(question: str, table: str, df: pd.DataFrame, prep: dict | None = None) -> dict:
    spec = parse_spec(question, df, prep)
    return {"sql": spec_sql(spec, table), "rationale": spec["rationale"], "confidence": spec["confidence"],
            "spec": spec, "interpretation": describe_spec(spec)}


def schema_text(table: str, df: pd.DataFrame) -> str:
    cols = ", ".join(f"{c} ({df[c].dtype})" for c in df.columns)
    return f"Table {table}: {cols}"


def generate_sql(question: str, table: str, df: pd.DataFrame, prep: dict | None = None) -> dict:
    base = heuristic_sql(question, table, df, prep)
    out = llm_complete(
        "You write DuckDB SQL. Return ONLY one read-only SELECT statement, no markdown, no explanation. "
        "Quote identifiers with double quotes. Use only the given table and columns.",
        f"{schema_text(table, df)}\nSample rows:\n{df.head(3).to_csv(index=False)}\nQuestion: {question}",
        max_tokens=500,
    )
    if out:
        cand = re.sub(r"^```(?:sql)?|```$", "", out.strip(), flags=re.M).strip()
        try:
            validate_read_query(cand)
            return {"sql": cand, "rationale": "Generated by LLM and validated read-only", "confidence": 0.85, "source": "llm",
                    "interpretation": "SQL written by the language model from your question and the schema; its numbers are checked by re-running the query."}
        except Exception:
            pass
    return {**base, "source": "heuristic"}


__all__ = ["describe_spec", "generate_sql", "heuristic_sql", "parse_spec", "spec_sql"]
