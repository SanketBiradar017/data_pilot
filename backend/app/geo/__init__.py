"""Geographic reference data (boundaries, name index) and name resolution."""
import gzip
import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).parent / "data"
_ISO3 = re.compile(r"^[A-Z0-9]{3}$")

# Spellings that Natural Earth does not carry but business data uses all the time.
_EXTRA_COUNTRY_ALIASES = {
    "USA": ["us", "u s", "u s a", "usa", "united states of america", "america", "united states"],
    "GBR": ["uk", "u k", "great britain", "britain", "england", "scotland", "wales", "northern ireland", "united kingdom of great britain and northern ireland"],
    "ARE": ["uae", "u a e", "emirates"],
    "RUS": ["russia", "russian federation"],
    "KOR": ["south korea", "korea republic of", "republic of korea", "korea south", "korea"],
    "PRK": ["north korea", "korea dpr", "democratic peoples republic of korea"],
    "CZE": ["czechia", "czech republic"],
    "CIV": ["ivory coast", "cote d ivoire"],
    "MMR": ["burma", "myanmar"],
    "VNM": ["vietnam", "viet nam"],
    "NLD": ["holland", "the netherlands", "netherlands"],
    "TUR": ["turkey", "turkiye"],
    "IRN": ["iran", "islamic republic of iran"],
    "SYR": ["syria"],
    "TZA": ["tanzania", "united republic of tanzania"],
    "COD": ["drc", "dr congo", "democratic republic of the congo", "congo kinshasa"],
    "COG": ["congo brazzaville", "republic of the congo"],
    "BOL": ["bolivia"],
    "VEN": ["venezuela"],
    "LAO": ["laos"],
    "MKD": ["north macedonia", "macedonia"],
    "SWZ": ["eswatini", "swaziland"],
    "TLS": ["east timor", "timor leste"],
    "CHN": ["prc", "peoples republic of china", "mainland china"],
    "HKG": ["hong kong sar", "hong kong"],
    "SRB": ["serbia"],
    "BRN": ["brunei"],
}


def norm(s: object) -> str:
    """Accent-, case- and punctuation-insensitive key."""
    t = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    t = t.replace("&", " and ")
    t = re.sub(r"[^a-z0-9]+", " ", t).strip()
    return re.sub(r"^the ", "", t)


def valid_iso3(code: str) -> bool:
    return bool(_ISO3.match(code or ""))


@lru_cache(maxsize=1)
def country_index() -> dict:
    """{'by_name': norm-name -> iso3, 'names': iso3 -> display name, 'iso2': iso3 -> iso2}."""
    rows = json.loads((DATA / "countries.json").read_text(encoding="utf-8"))
    by_name: dict[str, str] = {}
    names, iso2 = {}, {}
    for r in rows:
        names[r["iso3"]] = r["name"]
        iso2[r["iso3"]] = r["iso2"]
        keys = [r["iso3"], r["iso2"], r["name"], *r["aliases"]]
        for k in keys:
            if k:
                by_name.setdefault(norm(k), r["iso3"])
    for iso3, extra in _EXTRA_COUNTRY_ALIASES.items():
        if iso3 in names:
            for k in extra:
                by_name[norm(k)] = iso3
    return {"by_name": by_name, "names": names, "iso2": iso2}


def resolve_country(value: object, default: str | None = None) -> str | None:
    if value is None:
        return default
    return country_index()["by_name"].get(norm(value), default)


@lru_cache(maxsize=300)
def states(iso3: str) -> dict:
    """{'by_name': norm key -> canonical state name, 'names': [canonical names]} (empty when no admin-1 data)."""
    f = DATA / "admin1" / f"{iso3}.geojson"
    if not valid_iso3(iso3) or not f.exists():
        return {"by_name": {}, "names": []}
    feats = json.loads(f.read_text(encoding="utf-8"))["features"]
    by: dict[str, str] = {}
    names = []
    for ft in feats:  # canonical names first so an alias never shadows another state's real name
        p = ft["properties"]
        names.append(p["name"])
        by[norm(p["name"])] = p["name"]
    for ft in feats:
        p = ft["properties"]
        for k in [*p.get("aliases", []), p.get("postal"), p.get("code")]:
            if k and len(norm(k)) >= 2:
                by.setdefault(norm(k), p["name"])
    return {"by_name": by, "names": names}


def resolve_state(iso3: str, value: object) -> str | None:
    if value is None:
        return None
    return states(iso3)["by_name"].get(norm(value))


@lru_cache(maxsize=300)
def cities(iso3: str) -> list[dict]:
    f = DATA / "cities" / f"{iso3}.json"
    if not valid_iso3(iso3) or not f.exists():
        return []
    return json.loads(f.read_text(encoding="utf-8"))


@lru_cache(maxsize=300)
def boundary_bytes(kind: str, iso3: str = "") -> bytes | None:
    """Gzipped GeoJSON for `world` or a country's `states`; None when unavailable."""
    if kind == "world":
        f = DATA / "world.geojson"
    elif kind == "states" and valid_iso3(iso3):
        f = DATA / "admin1" / f"{iso3}.geojson"
    else:
        return None
    return gzip.compress(f.read_bytes(), 6) if f.exists() else None
