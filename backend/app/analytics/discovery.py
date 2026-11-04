"""Automated insight discovery: scan a dataset and surface what matters without being asked.
Detectors: growth/decline, top performers, declining groups, customer behaviour, correlations,
unusual distributions, concentration risk. SQL-verifiable numbers are Facts; statistical ones are re-checked
with a second method. Unverified insights are removed."""
import math

import pandas as pd
from scipy import stats as sps

from backend.app.analytics.facts import FactBook, lit, period_cond, q, verify_facts
from backend.app.analytics.roles import detect_roles
from backend.app.analytics.root_cause import _complete, _periods
from backend.app.analytics.statistics import correlations
from backend.app.analytics.utils import infer_types, jsonable

SEV_W = {"high": 3, "medium": 2, "low": 1, "info": 0.5}


def _grain(df: pd.DataFrame, date: str) -> str:
    span = (df[date].max() - df[date].min()).days
    return "month" if span >= 55 else "week" if span >= 14 else "day"


def _total_sql(fb: FactBook, metric: str, cond: str = "") -> str:
    return f"SELECT COALESCE(SUM({q(metric)}), 0) FROM {fb.table}" + (f" WHERE {cond}" if cond else "")


def _per_sql(fb: FactBook, metric: str, date: str, grain: str, p: pd.Period, extra: str = "") -> str:
    return _total_sql(fb, metric, period_cond(date, grain, str(p.start_time.date())) + extra)


def _ins(kind: str, severity: str, title: str, text: str, facts: list[str], score: float, investigate: dict | None = None, verified: bool | None = None, detail: str = "") -> dict:
    return {"type": kind, "severity": severity, "title": title, "text": text, "facts": facts, "score": score,
            "investigate": investigate, "verified": verified, "verification_detail": detail}


def discover(df: pd.DataFrame, table: str, mode: str = "standard", max_insights: int = 14, prefix: str = "D") -> dict:
    df = infer_types(df)
    roles = detect_roles(df)
    fb = FactBook(table, mode, prefix)
    metric = roles["revenue"] or (roles["measures"][0] if roles["measures"] else None)
    date = roles["date"]
    out: list[dict] = []
    skipped: list[str] = []
    if not metric:
        skipped.append("No numeric measure found: growth, performer and concentration checks skipped")

    cur = prev = grain = None
    if metric and date:
        d = df.dropna(subset=[date])
        grain = _grain(d, date)
        per = _periods(d, date, grain)
        avail = sorted(per.unique())
        if len(avail) >= 2:
            cur = avail[-1]
            if not _complete(d, date, grain, cur) and len(avail) >= 3:
                cur = avail[-2]
            prev = cur - 1
            if prev not in set(avail):
                cur = prev = None
    elif metric:
        skipped.append("No date column: period-over-period checks skipped")

    # ---- (a) growth / decline
    if metric and cur is not None:
        r1 = fb.base(f"{metric} in {cur}", float(df.loc[_periods(df.dropna(subset=[date]), date, grain) == cur, metric].sum()), _per_sql(fb, metric, date, grain, cur), "currency")
        r0 = fb.base(f"{metric} in {prev}", float(df.loc[_periods(df.dropna(subset=[date]), date, grain) == prev, metric].sum()), _per_sql(fb, metric, date, grain, prev), "currency")
        dl = fb.derived(f"Change in {metric}", "diff", [r1, r0], "currency")
        pc = fb.derived(f"% change in {metric}", "pct_change", [r1, r0], "pct")
        v = fb.value(pc)
        if v is not None and abs(v) >= 3:
            up = v > 0
            sev = "high" if abs(v) >= 25 else "medium" if abs(v) >= 10 else "low"
            out.append(_ins("growth" if up else "decline", sev if not up else ("medium" if sev == "high" else sev),
                            f"{metric.capitalize()} {'grew' if up else 'declined'} {abs(v):.1f}% in {cur}",
                            f"{metric.capitalize()} {'rose' if up else 'fell'} by {fb.absolute(dl)} ({fb.text(pc, True)}) from {prev} ({fb.text(r0)}) to {cur} ({fb.text(r1)}).",
                            [r0, r1, dl, pc], abs(v) * (1.2 if not up else 1.0),
                            {"tool": "root_cause", "metric": metric, "current": str(cur), "grain": grain}))

    # ---- (b)(c)(g) per-dimension analysis
    if metric:
        total_f = fb.base(f"Total {metric}", float(df[metric].sum()), _total_sql(fb, metric), "currency")
        dims = ([roles["product"]] if roles["product"] else []) + [x for x in roles["dimensions"] if x != roles["product"]]
        if roles["customer"]:
            dims_for_conc = dims[:4] + [roles["customer"]]
        else:
            dims_for_conc = dims[:4]
        for dim in dims_for_conc:
            g = df.groupby(dim, observed=True)[metric].sum().sort_values(ascending=False)
            g = g[g > 0]
            if len(g) < 2 or g.sum() <= 0:
                continue
            n = len(g)
            tops = []
            for name in g.index[:3]:
                tops.append(fb.base(f"{metric}, {dim} = {name}", float(g[name]), _total_sql(fb, metric, f"{q(dim)} = {lit(name)}"), "currency"))
            sh1 = fb.derived(f"Share of {metric} from {dim} = {g.index[0]}", "share", [tops[0], total_f], "pct")
            top3 = fb.derived(f"Top-3 {dim} {metric}", "sum", tops, "currency")
            sh3 = fb.derived(f"Top-3 {dim} share of {metric}", "share", [top3, total_f], "pct")
            s1, s3 = fb.value(sh1), fb.value(sh3)
            is_customer = dim == roles["customer"]
            if n >= 3 and (s1 >= 35 or (s3 >= 70 and n > 5)):
                sev = "high" if s1 >= 50 else "medium"
                what = f"{dim} “{g.index[0]}”" if not is_customer else f"customer {g.index[0]}"
                out.append(_ins("concentration", sev, f"Concentration risk: {what} drives {s1:.0f}% of {metric}",
                                f"{what[0].upper() + what[1:]} accounts for {fb.text(sh1)} of total {metric}, and the top 3 {dim} values together for {fb.text(sh3)} (of {n} {dim} values). Losing {('them' if is_customer else 'it')} would hit results hard.",
                                [sh1, sh3], s1 * 0.9, {"tool": "pareto", "category": dim, "value": metric}))
            if cur is not None and not is_customer and n <= 60:
                dd = df.dropna(subset=[date])
                pp = _periods(dd, date, grain)
                gcur = dd[pp == cur].groupby(dim, observed=True)[metric].sum()
                gprev = dd[pp == prev].groupby(dim, observed=True)[metric].sum()
                nprev = dd[pp == prev].groupby(dim, observed=True)[metric].count()       # rows behind each number
                rows = []
                for name in g.index[:12]:
                    a0, a1 = float(gprev.get(name, 0.0)), float(gcur.get(name, 0.0))
                    if a0 > 0 and a0 / max(1e-9, float(gprev.sum())) >= 0.03 and int(nprev.get(name, 0)) >= 5:   # ignore groups backed by <5 rows
                        rows.append((name, a0, a1, (a1 - a0) / a0 * 100))
                if rows:
                    best = max(rows, key=lambda r: r[3])
                    worst = min(rows, key=lambda r: r[3])
                    for kind, rw in (("performer", best), ("declining", worst)):
                        name, a0, a1, pct = rw
                        if (kind == "performer" and pct < 10) or (kind == "declining" and pct > -10):
                            continue
                        f1 = fb.base(f"{metric} in {cur}, {dim} = {name}", a1, _per_sql(fb, metric, date, grain, cur, f" AND {q(dim)} = {lit(name)}"), "currency")
                        f0 = fb.base(f"{metric} in {prev}, {dim} = {name}", a0, _per_sql(fb, metric, date, grain, prev, f" AND {q(dim)} = {lit(name)}"), "currency")
                        fp = fb.derived(f"% change, {dim} = {name}", "pct_change", [f1, f0], "pct")
                        sev = "medium" if abs(pct) >= 25 else "low"
                        if kind == "performer":
                            out.append(_ins("performer", sev, f"High performer: {dim} “{name}” grew {pct:.0f}%",
                                            f"{dim[0].upper() + dim[1:]} “{name}” grew {fb.absolute(fp)} in {cur} ({fb.text(f0)} → {fb.text(f1)}), the strongest growth among the main {dim} groups.",
                                            [f0, f1, fp], abs(pct) * 0.8, {"tool": "root_cause", "metric": metric, "current": str(cur), "grain": grain}))
                        else:
                            out.append(_ins("declining", "high" if pct <= -25 else "medium", f"Declining: {dim} “{name}” fell {abs(pct):.0f}%",
                                            f"{dim[0].upper() + dim[1:]} “{name}” fell {fb.absolute(fp)} in {cur} ({fb.text(f0)} → {fb.text(f1)}), the sharpest drop among the main {dim} groups.",
                                            [f0, f1, fp], abs(pct) * 1.1, {"tool": "root_cause", "metric": metric, "current": str(cur), "grain": grain}))
            if is_customer and cur is not None:  # churn risk: big customers who went quiet
                dd = df.dropna(subset=[date])
                pp = _periods(dd, date, grain)
                tot = dd.groupby(dim, observed=True)[metric].sum()
                big = tot[tot >= tot.quantile(0.8)].index
                c_prev = dd[pp == prev].groupby(dim, observed=True)[metric].sum()
                c_cur = dd[pp == cur].groupby(dim, observed=True)[metric].sum()
                lost = [c for c in big if c_prev.get(c, 0) > 0 and c_cur.get(c, 0) <= 0.4 * c_prev.get(c, 0)]
                if lost:
                    c = max(lost, key=lambda x: c_prev.get(x, 0))
                    f1 = fb.base(f"{metric} in {cur}, {dim} = {c}", float(c_cur.get(c, 0.0)), _per_sql(fb, metric, date, grain, cur, f" AND {q(dim)} = {lit(c)}"), "currency")
                    f0 = fb.base(f"{metric} in {prev}, {dim} = {c}", float(c_prev.get(c, 0.0)), _per_sql(fb, metric, date, grain, prev, f" AND {q(dim)} = {lit(c)}"), "currency")
                    fp = fb.derived(f"% change, {dim} = {c}", "pct_change", [f1, f0], "pct")
                    out.append(_ins("customer", "medium", f"{len(lost)} high-value customer(s) sharply reduced spend",
                                    f"{len(lost)} of the top-20% customers spent far less in {cur} than in {prev}. The biggest drop: customer {c} went from {fb.text(f0)} to {fb.text(f1)} ({fb.text(fp, True)}).",
                                    [f0, f1, fp], 45 + len(lost), {"tool": "pareto", "category": dim, "value": metric}))
            if is_customer:  # unusually large customers (Tukey fence)
                q1, q3 = g.quantile(0.25), g.quantile(0.75)
                fence = q3 + 3 * (q3 - q1)
                big = g[g > fence]
                if len(big) and (q3 - q1) > 0:
                    out.append(_ins("customer", "info", f"{len(big)} unusually large customer(s)",
                                    f"{len(big)} customers spend far more than typical (beyond 3×IQR above the upper quartile); the largest is customer {big.index[0]}, with {fb.text(tops[0])} in total {metric}.",
                                    [tops[0]], 20 + len(big), {"tool": "pareto", "category": dim, "value": metric}))

    # ---- (e) correlations (verified via rank-correlation recomputation)
    corr = correlations(df, 0.7)
    for p in corr["pairs"][:3]:
        pair = df[[p["a"], p["b"]]].dropna()
        r2 = float(pair[p["a"]].rank().corr(pair[p["b"]].rank()))
        ok = abs(r2 - p["r"]) < 1e-6
        out.append(_ins("correlation", "info", f"{p['a']} and {p['b']} move together (r = {p['r']:.2f})",
                        f"{p['a']} and {p['b']} show a {p['strength']} {p['direction']} rank correlation (r = {p['r']:.2f}, n = {p['n']}); changes in one tend to accompany changes in the other, which does not by itself prove cause.",
                        [], abs(p["r"]) * 30, None, ok, f"re-computed from ranks: r = {r2:.3f}"))

    # ---- (f) unusual distributions
    for col in roles["measures"][:6]:
        s = df[col].dropna()
        if len(s) < 30 or s.std() == 0:
            continue
        sk = float(sps.skew(s))
        k = max(1, math.ceil(len(s) * 0.01))
        top_sum = fb.base(f"Sum of top 1% of {col}", float(s.nlargest(k).sum()), f"SELECT COALESCE(SUM(x), 0) FROM (SELECT {q(col)} AS x FROM {table} WHERE {q(col)} IS NOT NULL ORDER BY {q(col)} DESC LIMIT {k})", "number")
        tot_c = fb.base(f"Sum of {col}", float(s.sum()), _total_sql(fb, col), "number")
        sh = fb.derived(f"Share of {col} held by the top 1% of rows", "share", [top_sum, tot_c], "pct")
        if abs(sk) >= 2 and s.sum() > 0 and (fb.value(sh) or 0) >= 8:
            out.append(_ins("distribution", "medium" if fb.value(sh) >= 20 else "low", f"{col} is heavily skewed by a few extreme rows",
                            f"The top 1% of rows ({k}) hold {fb.text(sh)} of all {col} (skewness {sk:.1f}); averages for {col} are pulled up by a few extreme values, so prefer medians.",
                            [sh], 18 + (fb.value(sh) or 0) / 2, None))

    # ---- (h) label hygiene: spelling variants split one group into several (silently skews every breakdown)
    worst = None
    for dim in roles["dimensions"] + ([roles["customer"]] if roles["customer"] else []):
        if pd.api.types.is_numeric_dtype(df[dim]):
            continue
        raw = df[dim].dropna().astype(str)
        norm = raw.str.strip().str.replace(r"\s+", " ", regex=True).str.lower()
        groups: dict[str, list[str]] = {}
        for r_, n_ in zip(raw.unique(), norm.reindex(raw.drop_duplicates().index)):
            groups.setdefault(n_, []).append(r_)
        counts = raw.value_counts()
        variants = {n_: sorted(v, key=lambda x: -counts[x]) for n_, v in groups.items() if len(v) > 1}
        if not variants:
            continue
        noncanon = [x for v in variants.values() for x in v[1:]]
        n_rows = int(counts[noncanon].sum())
        if worst is None or n_rows > worst[1]:
            worst = (dim, n_rows, noncanon, variants)
    if worst:
        dim, n_rows, noncanon, variants = worst
        vals = ", ".join(lit(x) for x in noncanon[:20])
        nn = fb.base(f"Rows in {dim} using a variant spelling", float(n_rows), f"SELECT COUNT(*) FROM {table} WHERE {q(dim)} IN ({vals})", "count")
        nt = fb.base(f"Rows with a {dim} value", float(df[dim].notna().sum()), f"SELECT COUNT(*) FROM {table} WHERE {q(dim)} IS NOT NULL", "count")
        sh = fb.derived(f"Share of {dim} rows with a variant spelling", "share", [nn, nt], "pct")
        ex = "; ".join(f"“{v[1]}” vs “{v[0]}”" for v in list(variants.values())[:3])
        out.append(_ins("data_quality", "medium" if (fb.value(sh) or 0) >= 1 else "low", f"{dim} has labels that differ only by spacing or capitalisation",
                        f"{fb.text(nn)} rows ({fb.text(sh)} of {dim} values) use spelling variants of another label, e.g. {ex}. Totals by {dim} split the same group across labels until the column is cleaned.",
                        [nn, sh], 40 + (fb.value(sh) or 0), {"tool": "clean"}))

    # ---- verify and finalise
    ver = verify_facts(fb.facts, {table: df}, only_key=False)
    final = []
    dropped = 0
    for i in out:
        if i["verified"] is None:
            ok = all(ver.get(f, {}).get("verified") for f in i["facts"])
            i["verified"] = ok
            i["verification_detail"] = "; ".join(ver[f]["detail"] for f in i["facts"][:2]) if i["facts"] else "no numeric claim"
        if i["verified"]:
            final.append(i)
        else:
            dropped += 1
    # diversity: at most 3 per type, ranked by severity weight × score
    final.sort(key=lambda i: -(SEV_W[i["severity"]] * 100 + i["score"]))
    per: dict[str, int] = {}
    picked = []
    for i in final:
        if per.get(i["type"], 0) < 3:
            picked.append(i)
            per[i["type"]] = per.get(i["type"], 0) + 1
    picked = picked[:max_insights]
    for n, i in enumerate(picked, 1):
        i["id"] = f"I{n}"
    used = {f for i in picked for f in i["facts"]}
    facts = [f for f in fb.facts if f["id"] in used or f["id"] in {x for ff in fb.facts if ff["id"] in used for x in ff["inputs"]}]
    return jsonable({"insights": picked, "facts": facts, "verification": {k: v for k, v in ver.items() if k in {f["id"] for f in facts}},
                     "dropped_unverified": dropped, "skipped": skipped, "metric": metric, "grain": grain,
                     "period": {"current": str(cur) if cur is not None else None, "previous": str(prev) if prev is not None else None},
                     "summary": {t: sum(1 for i in picked if i["type"] == t) for t in sorted({i["type"] for i in picked})}, "roles": {k: v for k, v in roles.items() if k != "measures"}})
