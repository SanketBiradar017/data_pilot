"""Understanding a chat question against the dataset schema. Deterministic, so a question always means
the same thing and the meaning can be checked.

  prepare          - pulls row filters out of the question ("in North", "in March 2024", "revenue above 1000"),
                     repairs typos in column names and reports terms that match no column
  clarification    - the honest answer when the question names something the data does not have
  apply_filters    - the same filters as pandas / SQL, used for execution and for independent verification
  resolve_followup - "what about South?" is merged into the meaning of the previous question
  verify_spec      - recomputes a generated query's result in pandas, independently of DuckDB
"""
import difflib
import re

import numpy as np
import pandas as pd

from backend.app.analytics.roles import detect_roles
from backend.app.analytics.utils import datetime_cols, is_id_like, numeric_cols

_STOP = {"the", "a", "an", "of", "by", "per", "for", "in", "on", "to", "and", "is", "are", "what", "which",
         "show", "me", "give", "list", "how", "much", "many", "total", "average", "avg", "mean", "sum",
         "top", "bottom", "highest", "lowest", "each", "every", "all", "with", "from", "over", "time",
         "number", "count", "most", "least", "best", "worst", "trend", "monthly", "weekly", "daily", "yearly"}

MONTHS = {m: i + 1 for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july",
                                          "august", "september", "october", "november", "december"])}
MONTHS |= {k[:3]: v for k, v in list(MONTHS.items())} | {"sept": 9}
_MONTH_RX = "|".join(sorted(MONTHS, key=len, reverse=True))
MONTH_NAMES = [m.capitalize() for m in list(MONTHS)[:12]]

TIME_WORDS = {"day", "days", "daily", "week", "weeks", "weekly", "month", "months", "monthly", "quarter", "quarters",
              "quarterly", "year", "years", "yearly", "annual", "annually", "time", "date", "dates", "period", "hour"}
_LEAD = {"highest", "lowest", "largest", "smallest", "biggest", "best", "worst", "top", "bottom", "most", "least",
         "total", "average", "mean", "sum", "median", "max", "min", "maximum", "minimum", "count", "number", "overall"}
_EXEMPT = {"number", "count", "rows", "row", "records", "record", "entries", "entry", "items", "data", "value",
           "values", "figure", "figures", "result", "results", "everything", "anything", "it", "that", "this",
           "them", "these", "those", "next", "future", "coming", "upcoming", "following", "last", "previous",
           "current", "total", "overall", "our", "my", "their", "its", "any", "some", "also", "then", "plus", "only", "just",
           "versus", "vs", "between", "where", "when", "if", "how", "what", "why", "who", "please", "both", "either"}
_VOCAB = _STOP | _EXEMPT | TIME_WORDS | {
    "where", "above", "below", "greater", "less", "than", "between", "maximum", "minimum", "median", "forecast",
    "predict", "compare", "change", "changes", "drop", "increase", "decrease", "growth", "profit", "margin", "sales",
    "revenue", "cost", "costs", "price", "quantity", "region", "category", "product", "customer", "customers", "date",
    "show", "display", "tell", "give", "please", "would", "could", "should", "there", "their", "about", "which",
    "being", "between", "during", "within", "since", "while", "whose", "least", "years", "months", "weeks", "unusual",
    "anomalies", "outliers", "correlation", "distribution", "average", "highest", "lowest", "breakdown", "summary"}

# business words that name a column role when the dataset uses another word
_SYN = {"revenue": {"revenue", "revenues", "sales", "income", "turnover", "amount", "receipts", "earnings"},
        "cost": {"cost", "costs", "expense", "expenses", "spend", "spending", "expenditure"},
        "quantity": {"quantity", "qty", "units", "volume", "volumes"},
        "price": {"price", "prices", "rate"}}
_PROFIT = {"profit", "profits", "earnings", "net"}


_ID_NAME = re.compile(r"(?:^|_|\b)(?:id|uuid|guid|key|code|no|num|number|sku)$|^(?:id|uuid)(?:_|$)", re.I)


def is_identifier(name: str, s: pd.Series) -> bool:
    """Codes and keys (order_id, customer_no) are labels, never measures: summing them is meaningless."""
    return bool(_ID_NAME.search(name)) or is_id_like(s)


def measure_cols(df: pd.DataFrame) -> list[str]:
    return [c for c in numeric_cols(df) if not is_identifier(c, df[c])]


def _stem(w: str) -> str:
    w = w.lower()
    if len(w) > 3 and w.endswith("ies"):
        return w[:-3] + "y"
    return w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w


def _match_cols(question: str, cols: list[str]) -> list[str]:
    words = [_stem(w) for w in re.findall(r"[A-Za-z0-9]+", question) if w.lower() not in _STOP]
    scored = []
    for c in cols:
        parts = [_stem(p) for p in re.split(r"[_\W]+", c) if p]
        s = sum(1 for p in parts if p in words) + (2 if _stem(c) in words else 0)
        if s:
            scored.append((s, question.lower().find(parts[0]) if parts else 0, c))
    return [c for _, _, c in sorted(scored, key=lambda t: (-t[0], t[1]))]


# ---------------------------------------------------------------- filters
_CMP = {"above": ">", "over": ">", "greater than": ">", "more than": ">", "exceeding": ">", "exceeds": ">",
        "higher than": ">", "bigger than": ">", "larger than": ">", "at least": ">=", "below": "<", "under": "<",
        "less than": "<", "lower than": "<", "fewer than": "<", "smaller than": "<", "at most": "<=",
        ">": ">", "<": "<", ">=": ">=", "<=": "<="}
_NUMRX = re.compile(
    r"(?P<before>(?:[a-z_][a-z_0-9]*\s+){0,3})(?P<op>above|over|greater than|more than|exceeding|exceeds|higher than|"
    r"bigger than|larger than|at least|below|under|less than|lower than|fewer than|smaller than|at most|>=|<=|>|<)\s*"
    r"(?P<num>-?\d[\d,]*(?:\.\d+)?)(?!\s*%)\s*(?P<suf>thousand|million|lakhs?|crores?|mn|cr|k|m)?\b", re.I)
_SUFFIX = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6, "lakh": 1e5, "lakhs": 1e5,
           "cr": 1e7, "crore": 1e7, "crores": 1e7}
_RELATIVE = re.compile(r"\b(?:last|this|previous|past|current|latest)\s+(?:month|year|quarter|week)\b|\byesterday\b|\btoday\b|\bytd\b", re.I)
_VALUE_STOP = _STOP | {"all", "na", "n/a", "none", "null", "nan", "no", "yes", "other", "unknown"}
_PREP_BEFORE = re.compile(r"(?:\b(?:in|for|from|at|of|only|just|within|where|with|excluding|except|is|equals?|=)\s*)$", re.I)


def _lit(v) -> str:
    return "'" + str(v).replace("'", "''") + "'"


def _q(c: str) -> str:
    return '"' + c.replace('"', '""') + '"'


def filters_sql(filters: list[dict]) -> str:
    out = []
    for f in filters:
        c, op, v = _q(f["col"]), f["op"], f["value"]
        if op == "in":
            out.append(f"{c} IN ({', '.join(_lit(x) for x in v)})")
        elif op in ("year", "month", "quarter"):
            out.append(f"EXTRACT({op} FROM {c}) IN ({', '.join(str(int(x)) for x in v)})")
        else:
            out.append(f"{c} {op} {float(v):.10g}")
    return " AND ".join(out)


def apply_filters(df: pd.DataFrame, filters: list[dict]) -> pd.DataFrame:
    mask = pd.Series(True, index=df.index)
    for f in filters:
        s, op, v = df[f["col"]], f["op"], f["value"]
        if op == "in":
            m = s.isin(v)
        elif op in ("year", "month", "quarter"):
            m = getattr(s.dt, op).isin(v)
        else:
            m = {">": s > v, ">=": s >= v, "<": s < v, "<=": s <= v}[op]
        mask &= m.fillna(False)
    return df[mask]


def describe_filters(filters: list[dict]) -> str:
    out = []
    for f in filters:
        if f["op"] == "in":
            out.append(f"{f['col']} = {' or '.join(map(str, f['value']))}")
        elif f["op"] == "month":
            out.append("month = " + " or ".join(MONTH_NAMES[int(m) - 1] for m in f["value"]))
        elif f["op"] in ("year", "quarter"):
            out.append(f"{f['op']} = " + " or ".join((f"Q{int(m)}" if f["op"] == "quarter" else str(int(m))) for m in f["value"]))
        else:
            out.append(f"{f['col']} {f['op']} {f['value']:,.10g}")
    return ", ".join(out)


def filters_phrase(filters: list[dict]) -> str:
    """Canonical wording that `prepare` reads back as the same filters."""
    out = []
    for f in filters:
        if f["op"] == "in":
            out.append("in " + " and ".join(map(str, f["value"])))
        elif f["op"] == "month":
            out.append("in " + " and ".join(MONTH_NAMES[int(m) - 1] for m in f["value"]))
        elif f["op"] == "year":
            out.append("in " + " and ".join(str(int(m)) for m in f["value"]))
        elif f["op"] == "quarter":
            out.append("in " + " and ".join(f"Q{int(m)}" for m in f["value"]))
        else:
            word = {">": "above", ">=": "at least", "<": "below", "<=": "at most"}[f["op"]]
            out.append(f"where {f['col']} {word} {f['value']:.10g}")
    return " ".join(out)


def _blank(text: str, a: int, b: int) -> str:
    return text[:a] + " " * (b - a) + text[b:]


def _value_filters(text: str, df: pd.DataFrame, cols_words: set[str]) -> tuple[list[dict], str]:
    """Categorical values named in the question ('in North') become `col IN (...)` filters."""
    ql = text.lower()
    found: list[tuple[int, int, str, str]] = []
    for c in df.columns:
        s = df[c]
        if pd.api.types.is_numeric_dtype(s) or pd.api.types.is_datetime64_any_dtype(s) or is_id_like(s):
            continue
        uniq = s.dropna().astype(str).unique()
        if len(uniq) > 2000:
            continue
        for v in uniq:
            lv = v.strip().lower()
            if len(lv) < 2 or lv in _VALUE_STOP or lv not in ql:
                continue
            for m in re.finditer(rf"(?<![a-z0-9]){re.escape(lv)}(?![a-z0-9])", ql):
                found.append((m.start(), m.end(), c, v))
    taken: list[tuple[int, int]] = []
    hits: dict[str, list[str]] = {}
    for a, b, c, v in sorted(found, key=lambda t: (-(t[1] - t[0]), t[0])):
        if any(a < y and x < b for x, y in taken):
            continue
        stems = {_stem(w) for w in re.findall(r"[a-z0-9]+", ql[a:b])}
        if stems <= cols_words and not _PREP_BEFORE.search(ql[:a]):
            continue  # "total sales" must not filter department = Sales
        taken.append((a, b))
        hits.setdefault(c, [])
        if v not in hits[c]:
            hits[c].append(v)
        text = _blank(text, a, b)
    return [{"col": c, "op": "in", "value": vs} for c, vs in hits.items()], text


def _date_filters(text: str, dts: list[str], named: str | None) -> tuple[list[dict], str]:
    if not dts:
        return [], text
    col = named or dts[0]
    out: list[dict] = []
    years = []
    for m in list(re.finditer(r"\b((?:19|20)\d{2})\b", text)):
        years.append(int(m.group(1)))
        text = _blank(text, m.start(), m.end())
    if years:
        out.append({"col": col, "op": "year", "value": sorted(set(years))})
    qs = []
    for m in list(re.finditer(r"\bq([1-4])\b", text, re.I)):
        qs.append(int(m.group(1)))
        text = _blank(text, m.start(), m.end())
    if qs:
        out.append({"col": col, "op": "quarter", "value": sorted(set(qs))})
    months = []
    for m in list(re.finditer(rf"\b(?:in|during|for|of|from|since)\s+({_MONTH_RX})\b", text, re.I)):
        months.append(MONTHS[m.group(1).lower()])
        text = _blank(text, m.start(1), m.end(1))
    for m in list(re.finditer(r"\b(january|february|april|june|july|august|september|october|november|december)\b", text, re.I)):
        months.append(MONTHS[m.group(1).lower()])
        text = _blank(text, m.start(), m.end())
    if months:
        out.append({"col": col, "op": "month", "value": sorted(set(months))})
    return out, text


def _numeric_filters(text: str, nums: list[str]) -> tuple[list[dict], str]:
    out: list[dict] = []
    for m in list(_NUMRX.finditer(text)):
        words = list(re.finditer(r"[a-z_][a-z_0-9]*", m.group("before"), re.I))
        col, start = None, None
        for k in range(1, len(words) + 1):  # nearest words first: "order value above 100"
            win = " ".join(w.group(0) for w in words[len(words) - k:])
            hit = [c for c in _match_cols(win, nums)]
            if hit:
                col, start = hit[0], m.start("before") + words[len(words) - k].start()
                break
        if not col:
            continue
        n = float(m.group("num").replace(",", "")) * _SUFFIX.get((m.group("suf") or "").lower(), 1)
        out.append({"col": col, "op": _CMP[m.group("op").lower()], "value": n})
        text = _blank(text, start, m.end())
    return out, text


# ---------------------------------------------------------------- grounding
def _role_col(roles: dict, word: str) -> str | None:
    for role, words in _SYN.items():
        if word in words and roles.get(role):
            return roles[role]
    return None


def _resolve_term(words: list[str], cols: list[str], roles: dict, measures: list[str] | None = None, entity_ok: bool = True) -> tuple[str, str | None]:
    """-> ("ok"|"synonym"|"profit"|"missing", column). With `measures`, the term must name a numeric measure
    (or, when entity_ok, an identifier/text column that will be counted)."""
    phrase = " ".join(words[:2])
    if _match_cols(phrase, measures if measures is not None else cols):
        return "ok", None
    if measures is not None and entity_ok and _match_cols(words[0], cols):
        return "ok", None
    w = _stem(words[0])
    for cand in (words[0], w):
        col = _role_col(roles, cand)
        if col:
            return "synonym", col
        if cand in _PROFIT and roles.get("revenue") and roles.get("cost"):
            return "profit", None
    return "missing", None


_P1 = re.compile(r"\b(?P<lead>total|sum(?:\s+of)?|average|avg|mean|median)\s+(?:the\s+|our\s+)?(?P<w1>[a-z][a-z_]*)(?:\s+(?!(?:and|or|in|for|where|with|of|on|at|from|to|over|during|only|between)\b)(?P<w2>[a-z][a-z_]*))?", re.I)
_P2 = re.compile(r"\b(?:by|per|for each|each|across|grouped by|group by|split by|broken down by|breakdown by)\s+(?:the\s+)?(?P<w1>[a-z][a-z_]*)(?:\s+(?!(?:and|or|in|for|where|with|of|on|at|from|to|over|during|only|between)\b)(?P<w2>[a-z][a-z_]*))?", re.I)
_P3 = re.compile(r"\b(?:forecast|predict|projection of|project)\s+(?:the\s+|our\s+|future\s+)*(?P<w1>[a-z][a-z_]*)(?:\s+(?!(?:and|or|in|for|where|with|of|on|at|from|to|over|during|only|between)\b)(?P<w2>[a-z][a-z_]*))?", re.I)


def _terms(text: str, cols: list[str], roles: dict, has_date: bool, measures: list[str]) -> tuple[list[str], list[str], dict]:
    """-> (unresolved terms, notes, replacements word->column)"""
    missing: list[str] = []
    notes: list[str] = []
    repl: dict[str, str] = {}
    for rx, kind in ((_P1, "measure"), (_P2, "group"), (_P3, "forecast")):
        for m in rx.finditer(text):
            lead = (m.groupdict().get("lead") or "").lower()
            items = [[w.lower() for w in (m.group("w1"), m.group("w2")) if w]]
            pos = m.end()
            while e := _AND.match(text, pos):  # "total revenue and headcount", "by region and shift"
                items.append([e.group(1).lower()])
                pos = e.end()
            for words in items:
                _check(words, kind, lead, cols, roles, has_date, measures, missing, notes, repl)
    return list(dict.fromkeys(missing)), list(dict.fromkeys(notes)), repl


_AND = re.compile(r"\s*(?:,|and\b|&)\s*(?:the\s+|our\s+)?([a-z][a-z_]*)", re.I)


def _check(words, kind, lead, cols, roles, has_date, measures, missing, notes, repl) -> None:
    """Does one measure / group term in the question exist in the data? Records what is missing or was mapped."""
    while words and words[0] in _LEAD:
        words.pop(0)
    if not words:
        return
    w1 = words[0]
    if w1 in TIME_WORDS:
        if kind == "group" and not has_date and w1 not in ("time", "period"):
            missing.append("a date column")
        return
    if w1 in _STOP or w1 in _EXEMPT or not w1.isalpha() and "_" not in w1:
        return
    words = [w1] + ([words[1]] if len(words) > 1 and words[1] not in _STOP | TIME_WORDS | _EXEMPT else [])
    status, col = _resolve_term(words, cols, roles, measures if kind != "group" else None,
                                entity_ok=kind == "forecast" or lead.startswith(("total", "sum")))
    if status == "missing":
        missing.append(" ".join(words))
    elif status == "synonym" and col:
        repl[w1] = col
        notes.append(f"Treating “{w1}” as column “{col}”.")
    elif status == "profit":
        notes.append("There is no profit column; profit is calculated as revenue − cost on rows that have both.")


def _repair_typos(text: str, cols: list[str], known: set[str]) -> tuple[str, list[str]]:
    vocab = {p for c in cols for p in re.split(r"[_\W]+", c.lower()) if len(p) >= 4} | {c.lower() for c in cols}
    stems = {_stem(v) for v in vocab}
    notes = []
    for m in sorted(set(re.findall(r"[A-Za-z]{5,}", text)), key=len):
        w = m.lower()
        if w in _VOCAB or w in known or w in vocab or _stem(w) in stems:
            continue
        close = difflib.get_close_matches(w, vocab, n=1, cutoff=0.86)
        if close:
            text = re.sub(rf"\b{re.escape(m)}\b", close[0], text)
            notes.append(f"Reading “{m}” as column “{close[0]}”.")
    return text, notes


_ENT = re.compile(r"\b(?:for|in|of|from|at|only|just)\s+(?:the\s+)?([A-Z][A-Za-z0-9&'-]+(?:\s+[A-Z][A-Za-z0-9&'-]+)*)")


def _unknown_entities(text: str, df: pd.DataFrame, cols: list[str]) -> tuple[list[str], dict]:
    """Capitalised names after 'for/in/of' that are neither a value nor a column ("for Electronics" when there is no
    such category). Dropping them silently would answer a different question."""
    known = {w for c in cols for w in re.split(r"[_\W]+", c.lower()) if w} | {_stem(w) for c in cols for w in re.split(r"[_\W]+", c.lower()) if w}
    out, sugg = [], {}
    pool = None
    for m in _ENT.finditer(text):
        phrase = m.group(1)
        words = [w.lower() for w in re.findall(r"[A-Za-z0-9]+", phrase)]
        if all(w in _VOCAB or w in known or _stem(w) in known or w in MONTHS for w in words):
            continue
        out.append(phrase)
        if pool is None:
            pool = {str(v).lower(): str(v) for c in df.columns if not pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_datetime64_any_dtype(df[c])
                    and df[c].nunique() <= 2000 for v in df[c].dropna().unique()}
        sugg[phrase] = [pool[k] for k in difflib.get_close_matches(phrase.lower(), list(pool), n=3, cutoff=0.7)]
    return out, sugg


def _roles(df: pd.DataFrame) -> dict:
    """detect_roles re-infers types over every row, so remember the answer on the frame (keyed by its shape and dtypes)."""
    key = (tuple(df.columns), len(df), tuple(map(str, df.dtypes)))
    hit = df.attrs.get("_roles")
    if hit and hit[0] == key:
        return hit[1]
    roles = detect_roles(df)
    df.attrs["_roles"] = (key, roles)
    return roles


def prepare(question: str, df: pd.DataFrame, extra_cols: list[str] | None = None) -> dict:
    """Split a question into row filters and the rest; report terms the data cannot answer."""
    nums, dts = measure_cols(df), datetime_cols(df)
    cols = list(df.columns)
    roles = _roles(df)
    cw = {_stem(p) for c in cols for p in re.split(r"[_\W]+", c.lower()) if p}
    text = question
    notes: list[str] = []
    f_num, text = _numeric_filters(text, nums)
    f_val, text = _value_filters(text, df, cw)
    named = (_match_cols(question, dts) or [None])[0]
    f_date, text = _date_filters(text, dts, named)
    if _RELATIVE.search(question):
        notes.append("Relative dates such as “last month” are not interpreted, so every period is included. Name a month or year to narrow it.")
    text, n2 = _repair_typos(text, cols, set())
    missing, n3, repl = _terms(text, cols + list(extra_cols or []), roles, bool(dts), nums)
    for w, col in repl.items():
        text = re.sub(rf"\b{re.escape(w)}\b", col, text, flags=re.I)
    unknown, sugg = _unknown_entities(text, df, cols)
    return {"text": text, "filters": f_val + f_date + f_num, "notes": notes + n2 + n3, "missing": missing, "unknown_values": unknown,
            "value_suggestions": sugg, "roles": roles}


def clarification(prep: dict, df: pd.DataFrame) -> dict:
    cols = [str(c) for c in df.columns]
    low = {c.lower(): c for c in cols}
    missing, unknown = prep["missing"], prep.get("unknown_values", [])
    sugg: dict[str, list[str]] = dict(prep.get("value_suggestions", {}))
    for t in missing:
        close = difflib.get_close_matches(t.lower(), list(low), n=3, cutoff=0.5)
        sugg[t] = [low[c] for c in close]
    bits = []
    if missing:
        bits.append("no column matches " + ", ".join(f"“{t}”" for t in missing))
    if unknown:
        bits.append("no value or column matches " + ", ".join(f"“{t}”" for t in unknown))
    msg = f"I can't answer that from this dataset: {' and '.join(bits)}. I won't guess a substitute, because that would give you a wrong number."
    hint = [f"Did you mean {', '.join(v)}?" for v in sugg.values() if v]
    return {"message": msg + (" " + " ".join(hint) if hint else "") + " Available columns: " + ", ".join(cols[:30]) + (" …" if len(cols) > 30 else "") + ".",
            "missing": missing + unknown, "suggestions": sugg, "columns": cols}


# ---------------------------------------------------------------- follow-ups
_CUE = re.compile(r"^\s*(?:and|also|now|then|so|ok(?:ay)?|what about|how about|what of|same|but|only|just|instead|exclude|excluding|"
                  r"without|except|filter|break (?:it|that|this) down|split (?:it|that|this)|show (?:it|that|this|them)|"
                  r"what if (?:we )?(?:look|filter|show)|and why)\b", re.I)
_PRONOUN = re.compile(r"\b(?:it|that|those|these|them|same|previous|above|earlier)\b|\bthis(?!\s+(?:month|year|quarter|week))\b", re.I)
_RESET = re.compile(r"\b(?:remove|clear|drop|ignore|without)\s+(?:the\s+|all\s+)?filters?\b|\boverall\b|\bacross all\b|\ball (?:data|rows|periods|regions)\b|\bno filter", re.I)
_NONSQL = re.compile(r"\bwhy\b|forecast|predict|project|next (?:\d+ )?(?:day|week|month|quarter|year)|what drove|root cause|what caused|explain", re.I)
AGG_WORD = {"SUM": "total", "AVG": "average", "MAX": "maximum", "MIN": "minimum", "MEDIAN": "median", "COUNT": "count of"}


def render_question(spec: dict) -> str:
    """Canonical wording of a spec; `parse_spec(render_question(s))` gives s back (checked by tests)."""
    agg, metric = spec.get("agg") or "SUM", "profit" if spec.get("metric_expr") else spec.get("metric")
    group, grain, limit = spec.get("group"), spec.get("grain"), spec.get("limit")
    word = AGG_WORD[agg] if agg != "COUNT" else "count of"
    mtxt = f"{word} {metric}" if metric and agg != "COUNT" else (f"number of {spec['distinct']}" if spec.get("distinct") else "count of records")
    if limit and group:
        s = f"{'top' if spec.get('desc', True) else 'bottom'} {limit} {group}" + (f" by {mtxt}" if metric and agg != "COUNT" else "")
    elif limit and metric:
        s = f"{'top' if spec.get('desc', True) else 'bottom'} {limit} rows by {metric}"
    elif grain:
        s = f"{mtxt} by {grain}"
    elif group:
        s = f"{mtxt} by {group}"
    else:
        s = mtxt
    f = filters_phrase(spec.get("filters") or [])
    return (s + " " + f).strip()


def merge_specs(prev: dict, new: dict, question: str) -> dict:
    ex = new.get("explicit", {})
    out = {k: (list(v) if isinstance(v, list) else v) for k, v in prev.items() if k != "explicit"}
    if ex.get("agg"):
        out["agg"] = new["agg"]
    if ex.get("entity"):
        out["distinct"], out["agg"] = new["distinct"], "COUNT"
    if ex.get("metric"):
        out["metric"], out["metric_expr"], out["distinct"] = new["metric"], new.get("metric_expr"), None
    if ex.get("group"):
        out["group"], out["grain"] = new["group"], None
    if ex.get("grain"):
        out["grain"], out["group"], out["time_col"] = new["grain"], None, new.get("time_col")
    if ex.get("limit"):
        out["limit"], out["desc"] = new["limit"], new["desc"]
    if _RESET.search(question):
        out["filters"] = []
    keep = [f for f in out.get("filters", []) if not any(n["col"] == f["col"] and n["op"] == f["op"] for n in new.get("filters", []))]
    out["filters"] = keep + list(new.get("filters", []))
    if not out.get("metric") and not out.get("metric_expr"):
        out["agg"] = out.get("agg") or "COUNT"
    return out


def resolve_followup(question: str, df: pd.DataFrame, prev_question: str | None) -> dict:
    """Make a follow-up question self-contained. Returns {question, followup, note}."""
    from backend.app.analytics.nl2sql import parse_spec  # local import: nl2sql imports this module

    plain = {"question": question, "followup": False, "note": None}
    if not prev_question:
        return plain
    new = parse_spec(question, df)
    ex = new["explicit"]
    words = len(question.split())
    modifier = bool(re.match(r"^\s*(?:by|per|across|for each|in|for|during|from|within)\b", question, re.I)) and words <= 6
    bare = modifier or not any(ex.values()) and not new["filters"] and words <= 6 and not _NONSQL.search(question)
    asks_more = bool(_CUE.search(question) or (_PRONOUN.search(question) and words <= 14) or bare or (new["filters"] and words <= 6 and not ex["metric"]))
    if not asks_more:
        return plain
    prev = parse_spec(prev_question, df)
    mname = "profit" if prev.get("metric_expr") else prev.get("metric")
    if _NONSQL.search(question):
        if ex["metric"] or not mname:
            return plain
        ctx = f"{mname} {filters_phrase(prev['filters'])}".strip()
        text = f"{question.rstrip('? .')} regarding {ctx}"
        return {"question": text, "followup": True, "note": f"Follow-up on “{prev_question}”: using {ctx}."}
    if not (prev.get("metric") or prev.get("metric_expr") or prev.get("agg") == "COUNT" or prev.get("kind") in ("count", "group_count")):
        return plain
    merged = merge_specs(prev, new, question)
    text = render_question(merged)
    return {"question": text, "followup": True, "note": f"Follow-up on “{prev_question}”. Understood as: “{text}”."}


# ---------------------------------------------------------------- independent verification
def _close(a, b, tol: float = 1e-6) -> bool:
    if a is None or b is None:
        return a is None and b is None
    a, b = float(a), float(b)
    return abs(a - b) <= tol * max(abs(a), abs(b), 1.0)


def _key(v):
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return None
    if isinstance(v, (pd.Timestamp, np.datetime64)) or hasattr(v, "isoformat"):
        return str(pd.Timestamp(v))[:10]
    return str(v.item() if hasattr(v, "item") else v)


_PF = {"SUM": lambda s: s.sum(min_count=1), "AVG": lambda s: s.mean(), "MEDIAN": lambda s: s.median(), "MAX": lambda s: s.max(), "MIN": lambda s: s.min()}
FREQ = {"day": "D", "week": "W", "month": "M", "quarter": "Q", "year": "Y"}


def metric_series(d: pd.DataFrame, spec: dict) -> pd.Series:
    mx = spec.get("metric_expr")
    return d[mx["rev"]] - d[mx["cost"]] if mx else d[spec["metric"]]


def verify_spec(df: pd.DataFrame, spec: dict, res: pd.DataFrame) -> tuple[bool, str]:
    """Recompute the query result with pandas (a different engine than DuckDB) and compare every number."""
    kind = spec["kind"]
    if kind == "sample":
        return True, "plain row sample; no calculation to check"
    d = apply_filters(df, spec.get("filters") or [])
    agg = spec.get("agg") or "SUM"
    dist = spec.get("distinct")
    if kind == "count":
        n = int(d[dist].nunique()) if dist else len(d)
        return _close(res.iloc[0, 0], n), f"recounted {n:,} {'distinct ' + dist if dist else 'row'}(s) in pandas"
    if kind == "agg":
        exp = _PF[agg](metric_series(d, spec)) if len(d) else None
        exp = None if exp is None or pd.isna(exp) else float(exp)
        got = res.iloc[0, 0]
        got = None if got is None or pd.isna(got) else float(got)
        ok = _close(got, exp) and int(res.iloc[0, 1]) == len(d)
        return ok, f"recomputed {agg.lower()} = {exp!r} over {len(d):,} row(s)"
    if kind == "rank_rows":
        vals = metric_series(d, spec).dropna().sort_values(ascending=not spec.get("desc", True)).head(int(spec["limit"]))
        got = pd.to_numeric(res[spec["metric"]], errors="coerce").dropna().tolist() if spec.get("metric") in res.columns else []
        ok = len(vals) == len(got) and all(_close(a, b) for a, b in zip(sorted(vals), sorted(got), strict=False))
        return ok, f"top {len(vals)} value(s) recomputed"
    # grouped results
    if kind == "trend":
        t = d.dropna(subset=[spec["time_col"]])
        keys = t[spec["time_col"]].dt.to_period(FREQ[spec["grain"]]).dt.start_time
        sub = t
    else:
        keys, sub = d[spec["group"]], d
    if kind == "group_count" or (kind == "trend" and agg == "COUNT"):
        exp = sub.groupby(keys, dropna=False)[dist].nunique() if dist else sub.groupby(keys, dropna=False).size()
    else:
        exp = metric_series(sub, spec).groupby(keys, dropna=False).agg(lambda s: _PF[agg](s))
    exp_map = {_key(k): (None if pd.isna(v) else float(v)) for k, v in exp.items()}
    vcol = res.columns[1]
    got_map = {_key(k): (None if pd.isna(v) else float(v)) for k, v in zip(res.iloc[:, 0], res[vcol], strict=False)}
    limit = spec.get("limit")
    if limit:
        top = sorted((v for v in exp_map.values() if v is not None), reverse=spec.get("desc", True))[: int(limit)]
        ok = (len(got_map) == len(top) and all(k in exp_map and _close(exp_map[k], v) for k, v in got_map.items())
              and all(_close(a, b) for a, b in zip(sorted(top), sorted(v for v in got_map.values() if v is not None), strict=False)))
    else:
        ok = set(got_map) == set(exp_map) and all(_close(exp_map[k], v) for k, v in got_map.items())
    return ok, f"recomputed {len(exp_map)} group value(s) in pandas; {len(got_map)} returned"


def explain_empty(df: pd.DataFrame, filters: list[dict]) -> str:
    """Why a filtered question matched nothing, from the data itself."""
    for f in filters:
        if len(apply_filters(df, [f])) == 0:
            s = df[f["col"]]
            if f["op"] in ("year", "month", "quarter"):
                return (f"No rows have {describe_filters([f])}. “{f['col']}” covers {s.min():%Y-%m-%d} to {s.max():%Y-%m-%d}.")
            if f["op"] == "in":
                vals = ", ".join(map(str, s.dropna().astype(str).unique()[:8]))
                return f"No rows have {describe_filters([f])}. Values in “{f['col']}” include: {vals}."
            return f"No rows have {describe_filters([f])}. “{f['col']}” ranges from {s.min():,.10g} to {s.max():,.10g}."
    return f"No rows satisfy all of these together: {describe_filters(filters)}."
