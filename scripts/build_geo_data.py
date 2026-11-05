"""Build the lazy-loaded boundary files used by Global Revenue Intelligence.

Input: Natural Earth GeoJSON (public domain) downloaded to a directory.
Output (backend/app/geo/data): world.geojson, countries.json (name index), admin1/<ISO3>.geojson, cities/<ISO3>.json
Usage: uv run python scripts/build_geo_data.py <dir-with-natural-earth-geojson>
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "backend" / "app" / "geo" / "data"


def _round_ring(ring, nd):
    out, last = [], None
    for x, y in ring:
        p = (round(x, nd), round(y, nd))
        if p != last:
            out.append(list(p))
        last = p
    return out if len(out) >= 4 else None


def _geom(g, nd):
    if g["type"] == "Polygon":
        rings = [r for r in (_round_ring(r, nd) for r in g["coordinates"]) if r]
        return {"type": "Polygon", "coordinates": rings} if rings else None
    polys = []
    for poly in g["coordinates"]:
        rings = [r for r in (_round_ring(r, nd) for r in poly) if r]
        if rings:
            polys.append(rings)
    return {"type": "MultiPolygon", "coordinates": polys} if polys else None


def _dump(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")


def main(src: Path):
    countries = json.loads((src / "ne_50m_admin_0_countries.geojson").read_text(encoding="utf-8"))
    feats, index = [], []
    for f in countries["features"]:
        p = f["properties"]
        iso3 = p["ADM0_A3"]
        g = _geom(f["geometry"], 2)
        if not g:
            continue
        iso2 = p["ISO_A2_EH"] if p.get("ISO_A2_EH") not in (None, "-99") else (p["ISO_A2"] if p["ISO_A2"] != "-99" else "")
        names = {p.get(k) for k in ("NAME", "NAME_LONG", "ADMIN", "FORMAL_EN", "NAME_EN", "ABBREV", "BRK_NAME", "NAME_SORT")} - {None}
        feats.append({"type": "Feature", "properties": {"iso3": iso3, "iso2": iso2, "name": p["NAME"]}, "geometry": g})
        index.append({"iso3": iso3, "iso2": iso2, "name": p["NAME"], "aliases": sorted(names)})
    _dump(OUT / "world.geojson", {"type": "FeatureCollection", "features": feats})
    _dump(OUT / "countries.json", index)

    by_c = defaultdict(list)
    adm = json.loads((src / "ne_10m_admin_1_states_provinces.geojson").read_text(encoding="utf-8"))
    for f in adm["features"]:
        p = f["properties"]
        g = _geom(f["geometry"], 2)
        if not g:
            continue
        alts = [a.strip() for a in (p.get("name_alt") or "").split("|") if a.strip()]
        alts += [p[k] for k in ("name_en", "name_local", "gn_name") if p.get(k)]
        by_c[p["adm0_a3"]].append({"type": "Feature", "geometry": g, "properties": {
            "name": p["name"], "aliases": sorted(set(alts)), "postal": p.get("postal") or "", "code": (p.get("iso_3166_2") or "").split("-")[-1],
            "type": p.get("type_en") or "", "lat": p.get("latitude"), "lon": p.get("longitude")}})
    for iso3, fs in by_c.items():
        _dump(OUT / "admin1" / f"{iso3}.geojson", {"type": "FeatureCollection", "features": fs})

    cities = defaultdict(list)
    pl = json.loads((src / "ne_10m_populated_places_simple.geojson").read_text(encoding="utf-8"))
    for f in pl["features"]:
        p = f["properties"]
        cities[p["adm0_a3"]].append({"name": p["name"], "ascii": p.get("nameascii") or p["name"], "state": p.get("adm1name") or "",
                                     "lat": round(p["latitude"], 3), "lon": round(p["longitude"], 3), "pop": p.get("pop_max") or 0})
    for iso3, cs in cities.items():
        _dump(OUT / "cities" / f"{iso3}.json", cs)
    print(f"world={len(feats)} admin1 countries={len(by_c)} city countries={len(cities)}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
