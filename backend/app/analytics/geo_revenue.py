"""Global Revenue Intelligence: detect geo/financial columns and aggregate revenue & loss by World > Country > State > City."""
import re
from collections import OrderedDict
from functools import lru_cache

import numpy as np
import pandas as pd

from backend.app import geo
from backend.app.analytics.utils import infer_types, is_text, jsonable
from backend.app.core.exceptions import AppError

ROLES = ("country", "state", "city", "revenue", "expense", "loss", "profit", "date")
GEO_ROLES = ("country", "state", "city")
MEASURE_ROLES = ("revenue", "expense", "loss", "profit")

_NAME_HINTS = {
    "country": re.compile(r"country|nation|cntry|ctry|iso.?3|iso.?2|country.?code", re.I),
    "state": re.compile(r"state|province|prov\b|region|territory|county|division|emirate|prefecture", re.I),
    "city": re.compile(r"city|town|municipal|metro|locality|district", re.I),
    "revenue": re.compile(r"revenue|sales|turnover|income|gross|amount|total|receipts|net.?sales", re.I),
    "expense": re.compile(r"expense|cost|cogs|spend|expenditure|outflow", re.I),
    "loss": re.compile(r"loss|writeoff|write.?off|shrink|deficit", re.I),
    "profit": re.compile(r"profit|margin.?amount|net.?income|earnings|ebit|pnl|p.?l\b", re.I),
    "date": re.compile(r"date|time|day|month|period|created|ordered|invoice|txn", re.I),
}
_NOT_MEASURE = re.compile(r"price|rate|ratio|pct|percent|discount|score|avg|average|\bid\b|_id$|^id$|qty|quantity|units|count|zip|postal|phone|lat|lon", re.I)
_NUM_CLEAN = re.compile(r"[^0-9eE+\-.]")
_MAX_LEVEL_CITIES = 500


def _numeric(s: pd.Series) -> pd.Series:
    """Coerce a column to float; strings like '$1,200.50' or '(300)' are parsed."""
    if pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s):
        return s.astype(float)
    t = s.astype("string")
    neg = t.str.match(r"^\s*\(.*\)\s*$").fillna(False)
    v = pd.to_numeric(t.str.replace(_NUM_CLEAN, "", regex=True), errors="coerce").astype(float)
    return v.where(~neg, -v.abs())


def _numeric_ok(s: pd.Series) -> float:
    """Share of non-null values that parse as numbers."""
    nn = s.notna().sum()
    if nn == 0:
        return 0.0
    return float(_numeric(s).notna().sum() / nn)


def _geo_hit_rate(s: pd.Series, role: str, sample: int = 400) -> float:
    vals = s.dropna().astype(str).unique()[:sample]
    if len(vals) == 0:
        return 0.0
    if role == "country":
        return float(np.mean([geo.resolve_country(v) is not None for v in vals]))
    if role == "state":
        known, codes = _known_state_names()
        return float(np.mean([(geo.norm(v) in known) or (geo.norm(v) in codes) for v in vals]))
    if role == "city":
        known = _known_city_names()
        return float(np.mean([geo.norm(v) in known for v in vals]))
    return 0.0


# Countries probed when no country column exists; also the set of countries used to validate state columns.
_STATE_PROBE = ("USA", "IND", "CAN", "AUS", "BRA", "CHN", "GBR", "DEU", "FRA", "MEX", "ITA", "ESP", "JPN", "RUS", "IDN", "ZAF", "NGA", "ARE", "ARG", "PAK")
_city_cache: set[str] | None = None
# sales-territory words that happen to be an alias of some state somewhere; they must not make "Region = East/West" look geographic
_GENERIC = {"east", "west", "north", "south", "central", "northeast", "northwest", "southeast", "southwest", "eastern", "western", "northern",
            "southern", "mid west", "midwest", "capital", "metro", "other", "unknown", "all", "total", "national", "international", "domestic", "global"}
_state_cache: tuple[set[str], set[str]] | None = None


def _known_state_names() -> tuple[set[str], set[str]]:
    """(names+aliases across every country, short codes of the probe countries). A column may mix states of many countries."""
    global _state_cache
    if _state_cache is None:
        names: set[str] = set()
        for f in (geo.DATA / "admin1").glob("*.geojson"):
            names |= {k for k in geo.states(f.stem)["by_name"] if len(k) >= 3 and k not in _GENERIC}
        codes: set[str] = set()
        for iso3 in _STATE_PROBE:
            codes |= {k for k in geo.states(iso3)["by_name"] if len(k) == 2}
        _state_cache = (names, codes)
    return _state_cache


def _known_city_names() -> set[str]:
    global _city_cache
    if _city_cache is None:
        _city_cache = {geo.norm(c["name"]) for f in (geo.DATA / "cities").glob("*.json") for c in geo.cities(f.stem)}
        _city_cache |= {geo.norm(c["ascii"]) for f in (geo.DATA / "cities").glob("*.json") for c in geo.cities(f.stem)}
    return _city_cache


def detect_columns(df: pd.DataFrame) -> dict:
    """Score every column for every role. Returns the best pick per role with a confidence in [0, 1]."""
    cols = [str(c) for c in df.columns]
    text_cols = [c for c in cols if is_text(df[c])]
    cand: dict[str, list[dict]] = {r: [] for r in ROLES}

    for role in GEO_ROLES:
        for c in text_cols:
            if df[c].nunique(dropna=True) < 1:
                continue
            named = bool(_NAME_HINTS[role].search(c))
            rate = _geo_hit_rate(df[c], role)
            # content matters more than the header: "Region" holding US states is a state column, "Region" holding East/West is not
            conf = 0.0 if rate < 0.3 and not (named and role == "city") else min(1.0, 0.75 * rate + (0.25 if named else 0.0))
            if role == "city" and df[c].nunique() > 0.9 * max(len(df), 1) and not named:
                conf *= 0.5
            if conf > 0:
                cand[role].append({"column": c, "confidence": round(conf, 2), "match_rate": round(rate, 2)})

    dts = [c for c in cols if pd.api.types.is_datetime64_any_dtype(df[c])]
    for c in cols:
        if c in dts:
            cand["date"].append({"column": c, "confidence": 0.95, "match_rate": 1.0})
        elif is_text(df[c]) and _NAME_HINTS["date"].search(c):
            parsed = pd.to_datetime(df[c].dropna().head(200), errors="coerce", format="mixed")
            if len(parsed) and parsed.notna().mean() > 0.8:
                cand["date"].append({"column": c, "confidence": 0.8, "match_rate": round(float(parsed.notna().mean()), 2)})

    for c in cols:
        if _NOT_MEASURE.search(c) or c in dts:
            continue
        ok = _numeric_ok(df[c]) if not pd.api.types.is_numeric_dtype(df[c]) else 1.0
        if ok < 0.8 or pd.api.types.is_bool_dtype(df[c]):
            continue
        for role in MEASURE_ROLES:
            if _NAME_HINTS[role].search(c):
                # "net_income"/"gross_profit" belong to profit, not revenue; "cost" never counts as revenue
                if role == "revenue" and (_NAME_HINTS["profit"].search(c) or _NAME_HINTS["expense"].search(c) or _NAME_HINTS["loss"].search(c)):
                    continue
                exact = bool(re.fullmatch(role + r"s?|total_?" + role, c.strip().lower()))
                cand[role].append({"column": c, "confidence": 0.95 if exact else 0.8, "match_rate": round(ok, 2)})

    best, alts = {}, {}
    used: set[str] = set()
    for role in ROLES:
        ranked = sorted(cand[role], key=lambda x: -x["confidence"])
        pick = next((x for x in ranked if x["column"] not in used or role == "date"), None)
        best[role] = pick
        if pick:
            used.add(pick["column"])
        alts[role] = [x["column"] for x in ranked]

    # no country column but states match one country strongly -> assume it
    assumed = None
    if not best["country"] and best["state"]:
        assumed = _infer_country(df[best["state"]["column"]])
    detected = {r: (best[r]["column"] if best[r] else None) for r in ROLES}
    conf = {r: (best[r]["confidence"] if best[r] else 0.0) for r in ROLES}
    issues = []
    if not any(detected[r] for r in GEO_ROLES):
        issues.append("No location column (country, state or city) could be detected.")
    if not detected["country"] and not assumed and (detected["state"] or detected["city"]):
        issues.append("No country column found; states and cities cannot be placed on the world map without a country.")
    if not any(detected[r] for r in ("revenue", "profit", "loss")):
        issues.append("No revenue, profit or loss column could be detected.")
    uncertain = [r for r in ("country", "state", "city", "revenue") if detected[r] and conf[r] < 0.6]
    for r in uncertain:
        issues.append(f"Low confidence for {r}: “{detected[r]}”. Please confirm the mapping.")
    return {"mapping": detected, "confidence": conf, "alternatives": alts, "assumed_country": assumed,
            "needs_mapping": bool(issues), "issues": issues, "columns": cols}


def _infer_country(s: pd.Series) -> str | None:
    vals = s.dropna().astype(str).unique()[:300]
    if len(vals) == 0:
        return None
    best, rate = None, 0.0
    for iso3 in _STATE_PROBE:
        r = float(np.mean([geo.resolve_state(iso3, v) is not None for v in vals]))
        if r > rate:
            best, rate = iso3, r
    return best if rate >= 0.6 else None


# ---------- prepared frame ----------

_FRAMES: "OrderedDict[tuple, pd.DataFrame]" = OrderedDict()
_MAX_FRAMES = 6


def _validate(df: pd.DataFrame, mapping: dict) -> dict:
    m = {r: (mapping.get(r) or None) for r in ROLES}
    for r, c in m.items():
        if c is not None and c not in df.columns:
            raise AppError(f"Mapped column “{c}” ({r}) does not exist in this dataset")
    if not any(m[r] for r in GEO_ROLES):
        raise AppError("Map at least one location column (country, state or city)")
    if not any(m[r] for r in ("revenue", "profit", "loss")):
        raise AppError("Map a revenue, profit or loss column")
    for r in MEASURE_ROLES:
        if m[r] and _numeric_ok(df[m[r]]) < 0.5:
            raise AppError(f"Column “{m[r]}” is not numeric, so it cannot be used as {r}")
    return m


def prepare(df: pd.DataFrame, mapping: dict, assumed_country: str | None = None) -> pd.DataFrame:
    """Row-level frame with resolved geography and financial measures (loss/profit derived when not given)."""
    df = infer_types(df)
    m = _validate(df, mapping)
    out = pd.DataFrame(index=df.index)
    n = len(df)

    # country
    if m["country"]:
        raw = df[m["country"]].astype("string")
        uniq = raw.dropna().unique()
        lut = {u: geo.resolve_country(u) for u in uniq}
        out["_c"] = raw.map(lut).astype(object)
    else:
        out["_c"] = assumed_country
        out["_c"] = out["_c"].astype(object)
    # state (resolved inside its country)
    out["_s"] = None
    if m["state"]:
        raw = df[m["state"]].astype("string")
        pairs = pd.DataFrame({"c": out["_c"], "s": raw}).dropna().drop_duplicates()
        lut = {(c, s): geo.resolve_state(c, s) for c, s in zip(pairs["c"], pairs["s"], strict=True)}
        out["_s"] = [lut.get((c, s)) if c is not None and s is not pd.NA and s is not None else None for c, s in zip(out["_c"], raw, strict=True)]
    # city (kept as typed, matched to coordinates later)
    if m["city"]:
        out["_city"] = df[m["city"]].astype("string").str.strip()
    else:
        out["_city"] = pd.Series([None] * n, index=df.index, dtype="string")

    rev = _numeric(df[m["revenue"]]) if m["revenue"] else None
    exp = _numeric(df[m["expense"]]) if m["expense"] else None
    los = _numeric(df[m["loss"]]).abs() if m["loss"] else None
    pro = _numeric(df[m["profit"]]) if m["profit"] else None

    out["revenue"] = rev if rev is not None else np.nan
    if pro is not None:
        profit = pro
    elif rev is not None and exp is not None:
        profit = rev - exp
    elif rev is not None and los is not None:
        profit = rev - los
    else:
        profit = None
    if los is not None:
        loss, basis = los, "loss_column"
    elif profit is not None:
        loss, basis = (-profit).clip(lower=0), "negative_profit"
    else:
        loss, basis = None, "none"
    out["loss"] = loss if loss is not None else np.nan
    out["profit"] = profit if profit is not None else np.nan
    out["date"] = _to_date(df[m["date"]]) if m["date"] else pd.NaT
    out.attrs.update(basis=basis, has_revenue=rev is not None or pro is not None, has_loss=loss is not None,
                     has_profit=profit is not None, mapping=m, assumed_country=assumed_country)
    return out


def _to_date(s: pd.Series) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(s):
        d = s
    else:
        d = pd.to_datetime(s, errors="coerce", format="mixed")
    return d.dt.tz_localize(None) if getattr(d.dt, "tz", None) is not None else d


def get_frame(key: tuple, df_loader, mapping: dict, assumed_country: str | None) -> pd.DataFrame:
    full = key + (repr(sorted(mapping.items())), assumed_country)
    if full in _FRAMES:
        _FRAMES.move_to_end(full)
        return _FRAMES[full]
    frame = prepare(df_loader(), mapping, assumed_country)
    _FRAMES[full] = frame
    while len(_FRAMES) > _MAX_FRAMES:
        _FRAMES.popitem(last=False)
    return frame


# ---------- aggregation ----------

def _fast_agg(d: pd.DataFrame, key: str) -> pd.DataFrame:
    """groupby with vectorised sums (min_count so all-null groups stay null)."""
    g = d.groupby(key, sort=False, dropna=True)
    return pd.DataFrame({"revenue": g["revenue"].sum(min_count=1), "loss": g["loss"].sum(min_count=1),
                         "profit": g["profit"].sum(min_count=1), "transactions": g.size()})


def _totals(d: pd.DataFrame, attrs: dict) -> dict:
    def s(c, ok=True):
        return float(d[c].sum()) if ok and len(d) and d[c].notna().any() else None
    return {"revenue": s("revenue", attrs["has_revenue"]), "loss": s("loss", attrs["has_loss"]),
            "profit": s("profit", attrs["has_profit"]), "transactions": int(len(d))}


def _region(key, name, row, **extra) -> dict:
    return jsonable({"key": key, "name": name, "revenue": row["revenue"], "loss": row["loss"], "profit": row["profit"],
                     "transactions": int(row["transactions"]), **extra})


def summarize(frame: pd.DataFrame, level: str, country: str | None = None, state: str | None = None,
              date_from: str | None = None, date_to: str | None = None) -> dict:
    attrs = frame.attrs
    d = frame
    date_range = None
    if d["date"].notna().any():
        date_range = {"min": d["date"].min().date().isoformat(), "max": d["date"].max().date().isoformat()}
        if date_from or date_to:
            lo = pd.to_datetime(date_from) if date_from else pd.Timestamp.min
            hi = (pd.to_datetime(date_to) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)) if date_to else pd.Timestamp.max
            d = d[(d["date"] >= lo) & (d["date"] <= hi)]
    elif date_from or date_to:
        raise AppError("This dataset has no date column mapped, so a date range cannot be applied")

    names = geo.country_index()["names"]
    unmapped: dict | None = None
    scope_note = None
    regions: list[dict] = []
    child_level = {"world": "country", "country": "state", "state": "city", "city": None}[level]
    has_state = bool(attrs["mapping"].get("state"))
    has_city = bool(attrs["mapping"].get("city"))
    has_country = bool(attrs["mapping"].get("country") or attrs.get("assumed_country"))

    if level == "world":
        if not has_country:
            scope_note = "No country column mapped: showing totals only."
        sub = d
        if has_country:
            ok = sub[sub["_c"].notna()]
            agg = _fast_agg(ok, "_c")
            regions = [_region(c, names.get(c, c), r, iso3=c) for c, r in agg.iterrows()]
            bad = sub[sub["_c"].isna()]
            if len(bad):
                unmapped = _totals(bad, attrs)
    else:
        if not country or not geo.valid_iso3(country):
            raise AppError("A valid country code is required")
        sub = d[d["_c"] == country]
        if level == "country":
            if has_state:
                agg = _fast_agg(sub[sub["_s"].notna()], "_s")
                regions = [_region(s, s, r) for s, r in agg.iterrows()]
                bad = sub[sub["_s"].isna()]
                if len(bad):
                    unmapped = _totals(bad, attrs)
            elif has_city:
                child_level = "city"
                regions = _city_regions(sub, country, None)
            else:
                child_level = None
                scope_note = "This dataset has no state/province column, so only country totals are available."
        else:  # state or city: city regions inside a state
            if level == "state":
                sub = sub[sub["_s"] == state] if state else sub
            if not has_city:
                child_level = None
                scope_note = "This dataset has no city column, so state totals are the deepest level."
            else:
                regions = _city_regions(sub, country, state)

    regions.sort(key=lambda r: -(r["revenue"] if r["revenue"] is not None else -(r["loss"] or 0)))
    tot = _totals(sub, attrs)
    for r in regions:
        base = tot["revenue"]
        r["share"] = (r["revenue"] / base) if base and r["revenue"] is not None else None
    rev_ranked = [r for r in regions if r["revenue"] is not None]
    return jsonable({
        "level": level, "child_level": child_level, "country": country, "state": state,
        "totals": tot, "regions": regions, "unmapped": unmapped, "scope_note": scope_note, "date_range": date_range,
        "top": rev_ranked[:5], "bottom": [r for r in reversed(rev_ranked[-5:]) if r not in rev_ranked[:5]],
        "highest_loss": sorted([r for r in regions if r["loss"]], key=lambda r: -r["loss"])[:5],
        "loss_basis": attrs["basis"], "capabilities": {"revenue": attrs["has_revenue"], "loss": attrs["has_loss"], "profit": attrs["has_profit"]},
    })


def _city_regions(sub: pd.DataFrame, country: str, state: str | None) -> list[dict]:
    sub = sub[sub["_city"].notna() & (sub["_city"].str.len() > 0)]
    if sub.empty:
        return []
    k = sub["_city"].map(geo.norm)
    work = sub.assign(_k=k.values)
    agg = _fast_agg(work, "_k")
    label = work.groupby("_k", sort=False)["_city"].agg(lambda x: x.mode().iat[0])
    places = _city_lookup(country)
    state_n = geo.norm(state) if state else None
    out = []
    for key, row in agg.sort_values("revenue", ascending=False, na_position="last").head(_MAX_LEVEL_CITIES).iterrows():
        hit = places.get(key)
        if hit and state_n:  # prefer a same-named place inside the selected state
            hit = [c for c in hit if geo.norm(c["state"]) == state_n] or hit
        p = max(hit, key=lambda c: c["pop"]) if hit else None
        out.append(_region(key, label[key], row, lat=p["lat"] if p else None, lon=p["lon"] if p else None,
                           state=p["state"] if p else None))
    return out


@lru_cache(maxsize=64)
def _city_lookup(iso3: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for c in geo.cities(iso3):
        for k in {geo.norm(c["name"]), geo.norm(c["ascii"])}:
            out.setdefault(k, []).append(c)
    return out
