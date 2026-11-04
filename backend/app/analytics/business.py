"""Business findings for the Autonomous Data Analyst: the questions a manager asks of a sales dataset
(who earns the most, what loses money, who matters, do discounts hurt). Each number is a Fact, re-computed with SQL
by `verify_facts`; a statement that cites an unverified fact is dropped by `finalize`."""
import re

import pandas as pd

from backend.app.analytics.charts import spec
from backend.app.analytics.facts import FactBook, eq_cond, labels, q, verify_facts
from backend.app.analytics.roles import detect_roles
from backend.app.analytics.story import finalize, stmt
from backend.app.analytics.utils import infer_types, jsonable

MAX_MEMBERS = 2000
_REGION = r"region|state|country|market|city|area|zone|territory"
_CATEGORY = r"categor|segment|department|type|class|group|brand"
_PRODUCT = r"product|item|sku|sub_?categor"


def _pick(cols: list[str], rx: str, exclude: set[str] = frozenset()) -> str | None:
    return next((c for c in cols if c not in exclude and re.search(rx, c, re.I)), None)


def _ok(df: pd.DataFrame, dim: str) -> bool:
    return 2 <= df[dim].nunique(dropna=False) <= MAX_MEMBERS


def _sum_sql(fb: FactBook, expr: str, cond: str = "") -> str:
    return f"SELECT COALESCE(SUM({expr}), 0) FROM {fb.table}" + (f" WHERE {cond}" if cond else "")


def _by(values: pd.Series, dim: pd.Series) -> pd.Series:
    return values.groupby(labels(dim)).sum(min_count=1).dropna()


def business_findings(df: pd.DataFrame, table: str, mode: str = "standard") -> dict:
    df = infer_types(df)
    roles = detect_roles(df)
    rev, cost, dims, nums = roles["revenue"], roles["cost"], roles["dimensions"], roles["measures"]
    profit_col = next((c for c in nums if re.search(r"profit|net_income", c, re.I)), None)
    fb = FactBook(table, mode, "B")
    profit = None
    if profit_col:
        pexpr, profit = q(profit_col), df[profit_col]
    elif rev and cost:
        pexpr, profit = f"({q(rev)} - {q(cost)})", df[rev] - df[cost]
    sts, findings, charts, recs = [], [], [], []

    def add(kind: str, severity: str, title: str, text: str, ids: list[str]) -> None:
        sts.append(stmt(text, ids, "finding"))
        findings.append({"kind": kind, "severity": severity, "title": title, "text": text, "facts": ids})

    def member_fact(label: str, expr: str, dim: str, member: str, value: float, unit: str = "currency") -> str:
        return fb.base(label, float(value), _sum_sql(fb, expr, eq_cond(dim, member)), unit)

    # 1. who earns the most / least ------------------------------------------------------------
    if rev:
        total = fb.base(f"Total {rev}", float(df[rev].sum()), _sum_sql(fb, q(rev)), "currency")
        seen = set()
        for dim in [d for d in (_pick(dims, _REGION), _pick(dims, _CATEGORY), *dims[:1]) if d][:2]:
            if dim in seen or not _ok(df, dim):
                continue
            seen.add(dim)
            g = _by(df[rev], df[dim]).sort_values(ascending=False)
            if len(g) < 2 or total is None or fb.value(total) == 0:
                continue
            top = member_fact(f"{rev} in {g.index[0]}", q(rev), dim, g.index[0], g.iloc[0])
            share = fb.derived(f"Share of {rev} from {g.index[0]}", "share", [top, total], "pct")
            ids = [top, share, total]
            text = f"{g.index[0]} is the largest {dim} by {rev}: {fb.text(top)}, {fb.text(share)} of the total."
            if len(g) >= 3:
                low = member_fact(f"{rev} in {g.index[-1]}", q(rev), dim, g.index[-1], g.iloc[-1])
                text += f" The smallest is {g.index[-1]} at {fb.text(low)}."
                ids.append(low)
            add("performer", "info", f"Top {dim} by {rev}", text, ids)
            charts.append(spec("bar", f"{rev} by {dim}", [{dim: k, rev: float(v)} for k, v in g.head(12).items()], dim, [rev]))

    if profit is not None:
        # 2. what loses money -------------------------------------------------------------------
        cand = [d for d in (_pick(dims, _PRODUCT), *dims) if d]
        for dim in dict.fromkeys(cand):
            if not _ok(df, dim):
                continue
            g = _by(profit, df[dim]).sort_values()
            losers = g[g < 0]
            if losers.empty:
                continue
            n_all = fb.base(f"Number of {dim} values", float(len(g)), f"SELECT COUNT(*) FROM (SELECT 1 FROM {table} GROUP BY {q(dim)})", "count")
            n_loss = fb.base(f"{dim} values with a total loss", float(len(losers)),
                             f"SELECT COUNT(*) FROM (SELECT 1 FROM {table} GROUP BY {q(dim)} HAVING SUM({pexpr}) < 0)", "count")
            worst = [member_fact(f"Profit of {m}", pexpr, dim, m, v) for m, v in losers.head(3).items()]
            names = ", ".join(f"{m} ({fb.text(i)})" for (m, _), i in zip(losers.head(3).items(), worst, strict=True))
            add("loss", "high", f"Loss-making {dim} values",
                f"{fb.text(n_loss)} of {fb.text(n_all)} {dim} values lose money overall. The biggest losses: {names}.", [n_loss, n_all, *worst])
            charts.append(spec("bar", f"Loss-making {dim} values (profit)", [{dim: m, "profit": float(v)} for m, v in losers.head(10).items()], dim, ["profit"]))
            recs.append(f"Review pricing, discounts and costs for the loss-making {dim} values (starting with {losers.index[0]}), or stop selling them.")
            break

        # 3. who contributes most to profit -----------------------------------------------------
        dim = _pick(dims, _CATEGORY) or (dims[0] if dims else None)
        if dim and _ok(df, dim):
            g = _by(profit, df[dim]).sort_values(ascending=False)
            tot = fb.base("Total profit", float(profit.sum()), _sum_sql(fb, pexpr), "currency")
            if len(g) >= 2 and fb.value(tot) and fb.value(tot) > 0:
                ids, bits = [tot], []
                for m, v in g.head(3).items():
                    f = member_fact(f"Profit of {m}", pexpr, dim, m, v)
                    sh = fb.derived(f"Share of profit from {m}", "share", [f, tot], "pct")
                    ids += [f, sh]
                    bits.append(f"{m} {fb.text(f)} ({fb.text(sh)})")
                add("contribution", "info", f"Profit by {dim}", f"Profit by {dim}: " + "; ".join(bits) + f", out of {fb.text(tot)} in total.", ids)
                charts.append(spec("bar", f"Profit by {dim}", [{dim: k, "profit": float(v)} for k, v in g.head(12).items()], dim, ["profit"]))

    # 4. most valuable customers --------------------------------------------------------------
    cust = roles["customer"]
    value = df[rev] if rev else profit
    vexpr = q(rev) if rev else (pexpr if profit is not None else None)
    if cust and value is not None and vexpr and df[cust].nunique() >= 10:
        g = _by(value, df[cust]).sort_values(ascending=False)
        tot = fb.base("Total value", float(value.sum()), _sum_sql(fb, vexpr), "currency")
        if len(g) >= 10 and fb.value(tot) and fb.value(tot) > 0:
            top5 = [member_fact(f"{'Revenue' if rev else 'Profit'} from {m}", vexpr, cust, m, v) for m, v in g.head(5).items()]
            s5 = fb.derived("Top 5 customers combined", "sum", top5, "currency")
            sh = fb.derived("Share from the top 5 customers", "share", [s5, tot], "pct")
            what = "revenue" if rev else "profit"
            add("customer", "info", "Most valuable customers",
                f"The 5 most valuable customers ({', '.join(map(str, g.head(5).index))}) bring in {fb.text(s5)}, {fb.text(sh)} of all {what}.", [s5, sh, tot])
            recs.append("Protect your best customers: assign an account owner and track their repeat-purchase rate.")
            if fb.value(sh) >= 30:
                recs.append(f"The top 5 customers are {fb.text(sh)} of {what}, which is a concentration risk; build the next tier of customers.")

    # 5. do discounts hurt profitability? -----------------------------------------------------
    disc = _pick(nums, r"discount")
    target = profit if profit is not None else (df[rev] if rev else None)
    texpr = pexpr if profit is not None else (q(rev) if rev else None)
    if disc and target is not None:
        d = df[disc]
        pos = d[d > 0]
        if len(pos) >= 30 and (d.fillna(0) == 0).sum() >= 30:
            thr = float(pos.median())
            what = "profit" if profit is not None else "revenue"
            sets = [("without a discount", f"COALESCE({q(disc)}, 0) = 0", target[d.fillna(0) == 0]),
                    (f"with a discount up to {thr:g}", f"{q(disc)} > 0 AND {q(disc)} <= {thr!r}", target[(d > 0) & (d <= thr)]),
                    (f"with a discount above {thr:g}", f"{q(disc)} > {thr!r}", target[d > thr])]
            ids = []
            for label, cond, sub in sets:
                ids.append(fb.base(f"Average {what} per row {label}", float(sub.mean()),
                                   f"SELECT AVG({texpr}) FROM {table} WHERE {cond}", "currency"))
            none_, low, high = ids
            vals = [fb.value(i) for i in ids]
            if all(v is not None for v in vals):
                hurt = vals[2] < vals[1] < vals[0]
                gap = fb.derived(f"Change in average {what}, high discount vs none", "diff", [high, none_], "currency")
                text = (f"Discounts and {what} move in opposite directions: the average per row is {fb.text(none_)} without a discount, "
                        f"{fb.text(low)} with a discount up to {thr:g} and {fb.text(high)} above {thr:g} ({fb.text(gap, True)} versus no discount)."
                        if hurt else
                        f"Average {what} per row is {fb.text(none_)} without a discount, {fb.text(low)} with a discount up to {thr:g} and "
                        f"{fb.text(high)} above {thr:g}; there is no steady pattern of discounts lowering {what}.")
                add("discount", "high" if hurt and vals[2] < 0 else "medium" if hurt else "info", "Discounts and profitability", text, [*ids, gap])
                charts.append(spec("bar", f"Average {what} per row by discount level", [{"discount": "none", what: vals[0]}, {"discount": f"up to {thr:g}", what: vals[1]}, {"discount": f"above {thr:g}", what: vals[2]}], "discount", [what]))
                if hurt:
                    recs.append(f"Set a ceiling on discounts: rows discounted above {thr:g} earn {fb.text(high)} on average, against {fb.text(none_)} at full price.")

    ver = verify_facts(fb.facts, {table: df}, only_key=False)
    kept, dropped = finalize(sts, ver, fb.facts)
    kept_text = {s["text"] for s in kept}
    findings = [f for f in findings if f["text"] in kept_text]
    return jsonable({"findings": findings, "statements": kept, "facts": fb.facts, "verification": ver, "charts": charts if findings else [],
                     "recommendations": recs if findings else [], "dropped_unverified": dropped,
                     "coverage": {"revenue": rev, "cost": cost, "profit": profit_col or ("revenue − cost" if profit is not None else None),
                                  "customer": cust, "discount": disc, "dimensions": dims[:6]}})
