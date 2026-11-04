"""Question suggestions generated from the actual data (columns, values, latest period, quality), never from a fixed list.
Every template is phrased so the planner routes it to an agent that can answer it; tests run each one end to end."""
import re

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer

from backend.app.analytics.discovery import _grain
from backend.app.analytics.roles import detect_roles
from backend.app.analytics.root_cause import _complete, _periods
from backend.app.analytics.utils import infer_types

CATEGORY_ORDER = ["Explore", "Trend", "Why", "What-if", "Summary", "Customers", "Quality", "Documents"]


def _s(col: str) -> str:
    return col.replace("_", " ")


def _plural(word: str) -> str:
    w = _s(re.sub(r"[_ ]?id$", "", word, flags=re.I) or word)
    return w if w.endswith("s") else w[:-1] + "ies" if w.endswith("y") and w[-2:-1] not in "aeiou" else w + "s"


def _item(question: str, category: str, reason: str) -> dict:
    return {"question": question, "category": category, "reason": reason}


def _latest_change(d: pd.DataFrame, date: str, metric: str) -> dict | None:
    """Direction of the latest complete period vs the one before it (so 'Why did X increase/decrease in <period>?' is true)."""
    grain = _grain(d, date)
    if grain == "day":
        return None
    per = _periods(d, date, grain)
    avail = sorted(per.unique())
    if len(avail) < 2:
        return None
    cur = avail[-1] if _complete(d, date, grain, avail[-1]) or len(avail) < 3 else avail[-2]
    prev = cur - 1
    if prev not in set(avail):
        return None
    t = d.groupby(per)[metric].sum()
    a, b = float(t.get(cur, 0.0)), float(t.get(prev, 0.0))
    if b == 0 or a == b:
        return None
    word = "increase" if a > b else "decrease"
    label = f"in {cur.start_time.strftime('%B %Y')}" if grain == "month" else "last week"
    return {"word": word, "label": label, "pct": (a - b) / abs(b) * 100, "grain": grain}


def _top_terms(text: str, k: int = 3) -> list[str]:
    paras = [p for p in re.split(r"\n\s*\n", text) if len(p.strip()) > 30] or [text]
    try:
        vec = TfidfVectorizer(stop_words="english", max_features=200, token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z]{3,}\b")
        m = vec.fit_transform(paras)
    except ValueError:
        return []
    scores = m.sum(axis=0).A1
    terms = vec.get_feature_names_out()
    return [terms[i] for i in scores.argsort()[::-1][:k]]


def table_suggestions(df: pd.DataFrame, name: str, quality_score: float | None = None) -> list[dict]:
    df = infer_types(df)
    r = detect_roles(df)
    out: list[dict] = []
    rev = r["revenue"]
    measures = [c for c in r["additive"] if c != r["customer"]]
    metric = rev or (measures[0] if measures else None)
    others = [c for c in measures if c != metric][:2]
    dims = list(dict.fromkeys([d for d in ([r["product"]] if r["product"] else []) + r["dimensions"] if d]))
    date, cost, qty, cust = r["date"], r["cost"], r["quantity"], r["customer"]
    m = _s(metric) if metric else None
    d0 = df.dropna(subset=[date]) if date else None
    span = (d0[date].max() - d0[date].min()).days if date and len(d0) else 0
    grain = _grain(d0, date) if date and len(d0) else None

    # ---- Explore: rankings, lows, averages, per-dimension breakdowns
    if metric:
        for i, dim in enumerate(dims[:3]):
            if i == 0:
                out.append(_item(f"What is the total {m} by {_s(dim)}?", "Explore", f"{metric} grouped by {dim}"))
                out.append(_item(f"Top 5 {_plural(dim)} by {m}", "Explore", f"ranking of {dim}"))
            out.append(_item(f"Which {_s(dim)} has the highest {m}?", "Explore", f"best {dim} by {metric}"))
            out.append(_item(f"Which {_s(dim)} has the lowest {m}?", "Explore", f"weakest {dim} by {metric}"))
            out.append(_item(f"What is the average {m} by {_s(dim)}?", "Explore", f"{metric} grouped by {dim}"))
            out.append(_item(f"How many records are there by {_s(dim)}?", "Explore", f"row count per {dim}"))
        if not dims:
            out.append(_item(f"What is the total {m}?", "Explore", f"sum of {metric}"))
        out.append(_item(f"What is the average {m}?", "Explore", f"mean of {metric}"))
        out.append(_item(f"What is the maximum {m}?", "Explore", f"largest single {metric}"))
        out.append(_item(f"Show the distribution of {m}", "Explore", "histogram and summary statistics"))
        for o in others:
            out.append(_item(f"What is the total {_s(o)}?", "Explore", f"sum of {o}"))
            if dims:
                out.append(_item(f"What is the average {_s(o)} by {_s(dims[0])}?", "Explore", f"{o} grouped by {dims[0]}"))
    else:
        out.append(_item(f"How many rows are in {name}?", "Explore", "row count"))
        for dim in dims[:2]:
            out.append(_item(f"How many records are there by {_s(dim)}?", "Explore", f"count grouped by {dim}"))
        if r["measures"]:
            out.append(_item(f"Show the distribution of {_s(r['measures'][0])}", "Explore", "histogram and summary statistics"))

    # ---- Trend
    if metric and date and grain:
        label = {"month": "monthly", "week": "weekly"}.get(grain)
        out.append(_item(f"Show the {label} {m} trend" if label else f"Show the {m} trend over time", "Trend", f"{metric} over {date}"))
        if span >= 28 and grain == "month":
            out.append(_item(f"Show the weekly {m} trend", "Trend", f"{metric} by week"))
        if span >= 2 * 365:
            out.append(_item(f"Show the yearly {m} trend", "Trend", f"{metric} by year"))
        out.append(_item(f"Is there a growth trend in {m}?", "Trend", "trend significance test"))
        for o in others[:1]:
            out.append(_item(f"Show the {label or 'daily'} {_s(o)} trend", "Trend", f"{o} over {date}"))

    # ---- Why: latest and previous period, for each main measure
    if date and grain in ("month", "week"):
        whys = [(metric, m)] if metric else []
        if cost and cost != metric:
            whys.append((cost, _s(cost)))
        if qty and qty not in (metric, cost):
            whys.append((qty, _s(qty)))
        if rev and cost:
            whys.append(("profit", "profit"))
        for col, shown in whys[:4]:
            tmp = d0.assign(profit=d0[rev] - d0[cost]) if col == "profit" else d0
            ch = _latest_change(tmp, date, col)
            if ch:
                out.append(_item(f"Why did {shown} {ch['word']} {ch['label']}?", "Why", f"{col} moved {ch['pct']:+.1f}% in the latest period"))
        if metric:
            ch2 = _latest_change(d0[d0[date] < _latest_period_start(d0, date, grain)], date, metric) if len(d0) else None
            if ch2 and grain == "month":
                out.append(_item(f"Why did {m} {ch2['word']} {ch2['label']}?", "Why", f"{metric} moved {ch2['pct']:+.1f}% the period before"))

    # ---- What-if
    if rev:
        target = "profit" if cost else m
        out.append(_item(f"What happens to {target} if prices increase by 10%?", "What-if", "10% price increase"))
        out.append(_item(f"What happens to {target} if prices decrease by 5%?", "What-if", "5% price cut"))
        out.append(_item("What if demand drops 10%?", "What-if", "10% volume decline"))
        out.append(_item("Simulate a 15% price cut with elasticity of -1.5", "What-if", "price cut with a demand response"))
        if cost:
            out.append(_item("What happens to profit if costs rise 5%?", "What-if", "5% cost inflation"))
        for dim in dims[:2]:
            vals = df[dim].dropna().astype(str).value_counts()
            seg = next((v for v in vals.index if len(v.strip()) >= 3 and re.fullmatch(r"[\w &-]+", v)), None)
            if seg:
                out.append(_item(f"What if costs rise 5% and prices rise 8% for {seg}?" if cost else f"What happens to {m} if prices increase by 8% for {seg}?", "What-if", f"segment scenario for {dim} = {seg}"))

    # ---- Summary
    if metric:
        out.append(_item("Give me an executive summary", "Summary", "KPIs, risks, opportunities and actions"))
    if len(r["measures"]) >= 2 or (metric and date):
        out.append(_item("Discover anything interesting in this data", "Summary", "automatic insight scan"))
    if len(r["additive"]) >= 2 or date:
        out.append(_item("Analyze trends, correlations and anomalies", "Summary", f"{len(r['measures'])} numeric columns" + (f" and a date column ({date})" if date else "")))
    if len(measures) >= 2:
        out.append(_item("Are there any strong correlations between my numeric columns?", "Summary", f"{len(measures)} numeric columns to compare"))
    for col in [c for c in measures if df[c].nunique() > 20][:2]:
        out.append(_item(f"Find outliers and anomalies in {_s(col)}", "Summary", "robust anomaly scan"))

    # ---- Customers
    if cust and metric:
        out.append(_item(f"Top 10 {_plural(cust)} by {m}", "Customers", f"largest {cust} values by {metric}"))
        out.append(_item(f"Bottom 10 {_plural(cust)} by {m}", "Customers", f"smallest {cust} values by {metric}"))

    # ---- Quality
    nulls = int(df.isna().any(axis=1).sum())
    if (quality_score is not None and quality_score < 95) or nulls:
        out.append(_item("Give me an overview of data quality", "Quality", f"quality score {quality_score:.0f}/100" if quality_score is not None else f"{nulls} rows have missing values"))
    if nulls:
        out.append(_item("How many missing values and duplicate rows are there?", "Quality", f"{nulls} of {len(df)} rows have a missing value"))
    return out


def _latest_period_start(d: pd.DataFrame, date: str, grain: str):
    per = _periods(d, date, grain)
    avail = sorted(per.unique())
    cur = avail[-1] if _complete(d, date, grain, avail[-1]) or len(avail) < 3 else avail[-2]
    return cur.start_time


def document_suggestions(name: str, text: str) -> list[dict]:
    terms = _top_terms(text, 4)
    out = [_item(f"What does the document {name} say about {t}?", "Documents", f"“{t}” is a prominent topic in the text") for t in terms]
    out.append(_item(f"What are the key points in the document {name}?", "Documents", "most relevant passages"))
    return out


def build_suggestions(tables: list[tuple[str, pd.DataFrame, float | None]], docs: list[tuple[str, str]], limit: int = 48) -> list[dict]:
    """A ranked pool. The first few entries span different categories (so the default view is varied); the rest follow."""
    items: list[dict] = []
    for name, df, q in tables[:1]:           # the primary table drives the questions; the rest are documents / joins
        items += table_suggestions(df, name, q)
    for name, text in docs[:2]:
        items += document_suggestions(name, text)
    seen, by_cat = set(), {c: [] for c in CATEGORY_ORDER}
    for it in items:
        k = it["question"].lower()
        if k not in seen:
            seen.add(k)
            by_cat[it["category"]].append(it)
    out: list[dict] = []
    queues = [by_cat[c] for c in CATEGORY_ORDER if by_cat[c]]
    while any(queues) and len(out) < limit:                  # round-robin across categories
        for qd in queues:
            if qd and len(out) < limit:
                out.append(qd.pop(0))
    quality = [i for i in out if i["category"] == "Quality"][:1]
    if quality and quality[0] not in out[:8]:                # a real data problem always shows up early
        out.remove(quality[0])
        out.insert(min(6, len(out)), quality[0])
    return out
