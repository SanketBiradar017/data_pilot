from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from backend.app import geo
from backend.app.analytics import geo_revenue as gr
from backend.app.core.exceptions import AppError, NotFound
from backend.app.core.security import get_current_user, get_db
from backend.app.models import GeoMapping, User
from backend.app.schemas.api import GeoMappingIn, GeoSummaryIn
from backend.app.services import datasets as ds_svc

router = APIRouter()


def _assume(ds, state_col: str) -> str | None:
    df = ds_svc.load_df(ds)
    return gr._infer_country(df[state_col]) if state_col in df.columns else None


def _table(db: Session, user: User, dataset_id: int):
    ds = ds_svc.get_dataset(db, user, dataset_id)  # enforces ownership
    if ds.kind != "table":
        raise AppError("Global Revenue Intelligence needs a tabular dataset")
    return ds


def _geojson(data: bytes | None) -> Response:
    if data is None:
        raise NotFound("No boundary data for this region")
    return Response(data, media_type="application/geo+json", headers={"Content-Encoding": "gzip", "Cache-Control": "private, max-age=86400"})


@router.get("/boundaries/world")
def world_boundaries(user: User = Depends(get_current_user)):
    return _geojson(geo.boundary_bytes("world"))


@router.get("/boundaries/{iso3}/states")
def state_boundaries(iso3: str, user: User = Depends(get_current_user)):
    return _geojson(geo.boundary_bytes("states", iso3.upper()))


@router.get("/boundaries/{iso3}/cities")
def city_points(iso3: str, user: User = Depends(get_current_user)):
    iso3 = iso3.upper()
    return {"country": iso3, "cities": geo.cities(iso3)}


@router.get("/mapping/{dataset_id}")
def get_mapping(dataset_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Detected columns plus the saved mapping (if the user confirmed one)."""
    ds = _table(db, user, dataset_id)
    det = gr.detect_columns(ds_svc.load_df(ds))
    saved = db.get(GeoMapping, ds.id)
    return {**det, "saved": saved.mapping if saved else None}


@router.put("/mapping/{dataset_id}")
def save_mapping(dataset_id: int, body: GeoMappingIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ds = _table(db, user, dataset_id)
    df = ds_svc.load_df(ds)
    m = body.model_dump()
    gr._validate(df, m)
    if not m["country"] and not m["assumed_country"] and m["state"]:
        m["assumed_country"] = gr._infer_country(df[m["state"]])  # raises a readable error for bad columns
    row = db.get(GeoMapping, ds.id) or GeoMapping(dataset_id=ds.id)
    row.mapping = m
    db.add(row)
    db.commit()
    ds_svc.audit(db, user, "geo.mapping", f"dataset={ds.id}")
    return {"saved": m}


@router.delete("/mapping/{dataset_id}", status_code=204)
def reset_mapping(dataset_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ds = _table(db, user, dataset_id)
    row = db.get(GeoMapping, ds.id)
    if row:
        db.delete(row)
        db.commit()


@router.post("/summary")
def summary(body: GeoSummaryIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ds = _table(db, user, body.dataset_id)
    saved = db.get(GeoMapping, ds.id)
    chosen = body.mapping.model_dump() if body.mapping else (saved.mapping if saved else None)
    if chosen is None:
        det = gr.detect_columns(ds_svc.load_df(ds))
        chosen = {**det["mapping"], "assumed_country": det["assumed_country"]}
    elif not chosen.get("country") and not chosen.get("assumed_country") and chosen.get("state"):
        chosen = {**chosen, "assumed_country": _assume(ds, chosen["state"])}
    assumed = chosen.get("assumed_country")
    chosen = {k: v for k, v in chosen.items() if k != "assumed_country"}
    frame = gr.get_frame((ds.id, ds.updated_at.isoformat()), lambda: ds_svc.load_df(ds), chosen, assumed)
    if body.level != "world" and not body.country:
        raise AppError("country is required below world level")
    return gr.summarize(frame, body.level, body.country, body.state, body.date_from, body.date_to)
