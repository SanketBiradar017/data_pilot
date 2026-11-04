"""Fact book: every number shown to the user is a fact that is either re-computed with SQL
or derived from other verified facts with a named, independently re-evaluated operation."""
from typing import Any

import pandas as pd

from backend.app.analytics.sql_engine import scalars
from backend.app.analytics.utils import fmtnum, jsonable


def q(col: str) -> str:
    return '"' + col.replace('"', '""') + '"'


def lit(v: Any) -> str:
    return "'" + str(v).replace("'", "''") + "'"


BLANK = "(blank)"


def eq_cond(col: str, value: Any) -> str:
    """SQL equality that treats the '(blank)' label as NULL."""
    return f"{q(col)} IS NULL" if value == BLANK else f"{q(col)} = {lit(value)}"


def labels(series: pd.Series) -> pd.Series:
    """Group labels as text with missing values shown as '(blank)' (so no row silently disappears from a breakdown)."""
    return series.astype(object).where(series.notna(), BLANK).astype(str)


def period_cond(date_col: str, grain: str, start: str) -> str:
    unit = {"week": "week", "month": "month", "quarter": "quarter", "year": "year", "day": "day"}[grain]
    return f"CAST(DATE_TRUNC('{unit}', {q(date_col)}) AS DATE) = DATE '{start}'"


OPS = {
    "diff": lambda a, b: a - b,
    "pct_change": lambda cur, prev: (cur - prev) / abs(prev) * 100 if prev else None,
    "share": lambda part, total: part / total * 100 if total else None,
    "ratio": lambda a, b: a / b if b else None,
    "sum": lambda *xs: sum(xs),
    "volume_effect": lambda r0, q0, q1: (q1 - q0) * r0 / q0 if q0 else None,
    "price_effect": lambda r0, q0, r1, q1: r1 - q1 * r0 / q0 if q0 else None,
    "scale": lambda a, k: a * k,
    # scenario ESTIMATES (assumption-driven, never observed data); p, v, c, phi in percent, e = elasticity
    "scn_revenue": lambda rm, ro, p, v, e: rm * (1 + p / 100) * max(0.0, (1 + v / 100) * (1 + e * p / 100)) + ro,
    "scn_quantity": lambda qm, qo, p, v, e: qm * max(0.0, (1 + v / 100) * (1 + e * p / 100)) + qo,
    "scn_cost": lambda cm, co, p, v, e, c, phi: cm * ((1 - phi / 100) * max(0.0, (1 + v / 100) * (1 + e * p / 100)) + phi / 100) * (1 + c / 100) + co,
}


class FactBook:
    def __init__(self, table: str, mode: str = "standard", prefix: str = "F"):
        self.table, self.mode, self.prefix = table, mode, prefix
        self.facts: list[dict] = []
        self.exprs: dict[str, str] = {}      # derived metrics, e.g. {"profit": '("revenue" - "cost")'}

    def col(self, name: str) -> str:
        return self.exprs.get(name) or q(name)

    @classmethod
    def from_list(cls, table: str, mode: str, facts: list[dict]) -> "FactBook":
        fb = cls(table, mode)
        fb.facts = facts
        return fb

    def _add(self, **f) -> str:
        fid = f"{self.prefix}{len(self.facts) + 1}"
        self.facts.append({"id": fid, **f})
        return fid

    def base(self, label: str, value: float | None, sql: str, unit: str = "number", key: bool = True) -> str:
        return self._add(label=label, value=value, unit=unit, sql=sql, op=None, inputs=[], key=key)

    def derived(self, label: str, op: str, inputs: list[str], unit: str = "number", key: bool = True, extra: list[float] | None = None, estimate: bool = False) -> str:
        vals = [self.value(i) for i in inputs] + (extra or [])
        v = None if any(x is None for x in vals) else OPS[op](*vals)
        return self._add(label=label, value=v, unit=unit, sql=None, op=op, inputs=inputs, extra=extra or [], key=key, estimate=estimate)

    def get(self, fid: str) -> dict:
        return next(f for f in self.facts if f["id"] == fid)

    def value(self, fid: str):
        return self.get(fid)["value"]

    def text(self, fid: str, signed: bool = False) -> str:
        f = self.get(fid)
        v = f["value"]
        if v is None:
            return "n/a"
        if f["unit"] == "pct":
            return f"{v:+.1f}%" if signed else f"{v:.1f}%"
        grouping = "indian" if self.mode in ("indian", "inr") else "standard"
        digits = 0 if f["unit"] == "count" or abs(v) >= 1000 or abs(v - round(v)) < 0.005 else 2   # never round 4.56 to "5"
        body = fmtnum(abs(v), "inr" if (self.mode == "inr" and f["unit"] == "currency") else grouping, digits)
        sign = ("+" if v >= 0 else "-") if signed else ("-" if v < 0 else "")
        return f"{sign}{body}"

    def absolute(self, fid: str) -> str:
        f = self.get(fid)
        if f["value"] is None:
            return "n/a"
        if f["unit"] == "pct":
            return f"{abs(f['value']):.1f}%"
        return self.text(fid).lstrip("-")


def _close(a: float | None, b: float | None, tol: float = 1e-6) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def verify_facts(facts: list[dict], tables: dict[str, pd.DataFrame], only_key: bool = True) -> dict[str, dict]:
    """Return {fact_id: {"verified": bool, "detail": str}}. SQL facts are re-executed; derived facts are re-evaluated from
    their (verified) inputs. Only key facts and their dependencies are checked unless only_key is False."""
    by = {f["id"]: f for f in facts}
    need: set[str] = set()

    def mark(fid: str):
        if fid in need:
            return
        need.add(fid)
        for i in by[fid]["inputs"]:
            mark(i)

    for f in facts:
        if f["key"] or not only_key:
            mark(f["id"])
    base_ids = [i for i in need if by[i]["sql"]]
    res: dict[str, dict] = {}
    if base_ids:
        try:
            got = scalars(tables, [by[i]["sql"] for i in base_ids])
        except Exception as e:
            got = [None] * len(base_ids)
            for i in base_ids:
                res[i] = {"verified": False, "detail": f"SQL error: {e}"}
        for i, v in zip(base_ids, got):
            if i not in res:
                ok = _close(v, by[i]["value"], 1e-6)
                res[i] = {"verified": ok, "detail": f"SQL re-executed → {v:,.6g}" if v is not None else "SQL returned no value"}
    for f in facts:  # facts are created in dependency order
        if f["id"] not in need or f["sql"]:
            continue
        ins = [by[i] for i in f["inputs"]]
        if not all(res.get(i["id"], {}).get("verified") for i in ins):
            res[f["id"]] = {"verified": False, "detail": "an input fact failed verification"}
            continue
        try:
            vals = [i["value"] for i in ins]
            v = None if any(x is None for x in vals) else OPS[f["op"]](*vals, *f.get("extra", []))   # undefined in, undefined out
        except Exception as e:
            res[f["id"]] = {"verified": False, "detail": f"recompute error: {e}"}
            continue
        res[f["id"]] = {"verified": _close(v, f["value"]), "detail": f"{f['op']} re-evaluated from {', '.join(f['inputs'])} → {v:,.6g}" if v is not None else f"{f['op']}: undefined (an input is zero or undefined)"}
    return jsonable(res)
