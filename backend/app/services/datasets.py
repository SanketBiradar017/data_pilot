"""Dataset lifecycle: ingest -> clean -> profile -> persist."""
import hashlib
import logging
import re
import shutil
import uuid
from pathlib import Path

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.analytics.cleaning import apply_operation
from backend.app.analytics.duplicates import analyze_text_duplicates, duplicate_summary
from backend.app.analytics.profiling import profile_dataframe
from backend.app.analytics.quality import quality_report
from backend.app.analytics.utils import frame_records, infer_types, jsonable
from backend.app.config import ROOT, settings
from backend.app.core.exceptions import AppError, IngestionError, NotFound
from backend.app.ingestion.loaders import ALLOWED_EXT, DOC_EXT, load_file, load_sql_source, safe_table_name
from backend.app.models import AuditLog, Dataset, User
from backend.app.services import appconfig
from backend.app.services import entitlements as ent

log = logging.getLogger(__name__)


def audit(db: Session, user: User | None, action: str, detail: str = "") -> None:
    db.add(AuditLog(user_id=user.id if user else None, action=action, detail=detail[:2000]))
    db.commit()


def _unique_table(db: Session, owner_id: int, base: str) -> str:
    existing = set(db.scalars(select(Dataset.table_name).where(Dataset.owner_id == owner_id)))
    name, i = base, 2
    while name in existing:
        name, i = f"{base}_{i}", i + 1
    return name


def get_dataset(db: Session, user: User, dataset_id: int) -> Dataset:
    ds = db.get(Dataset, dataset_id)
    if ds is None or ds.owner_id != user.id:
        raise NotFound("Dataset not found")
    return ds


def resolve_path(stored: str) -> Path | None:
    """Find a stored file. Older records hold paths relative to the launch directory, so look in the usual places."""
    p = Path(stored)
    if p.is_absolute():
        return p if p.exists() else None
    for base in (ROOT, ROOT / "backend", Path.cwd()):
        if (base / p).exists():
            return (base / p).resolve()
    return None


def _data_file(ds: Dataset) -> Path:
    f = resolve_path(ds.data_path)
    if f is None:
        raise AppError(f"The stored data file for '{ds.name}' is missing on disk. Delete this data source and upload the file again.", 410)
    return f


def load_df(ds: Dataset) -> pd.DataFrame:
    if ds.kind != "table":
        raise AppError("Dataset is a document, not a table")
    return pd.read_parquet(_data_file(ds))


def load_text(ds: Dataset) -> str:
    return _data_file(ds).read_text(encoding="utf-8")


def heal_paths(db: Session) -> int:
    """Startup repair: copy files saved under a different working directory into the canonical folder and store absolute paths."""
    fixed = 0
    for ds in db.scalars(select(Dataset)).all():
        stored = Path(ds.data_path)
        found = resolve_path(ds.data_path)
        if found is None:
            log.warning("dataset %s (%s): data file missing (%s)", ds.id, ds.name, ds.data_path)
            continue
        target = settings.processed_directory / f"{ds.id}{found.suffix}"
        if found != target and not stored.is_absolute():
            settings.processed_directory.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                shutil.copy2(found, target)
            ds.data_path = str(target)
            fixed += 1
        elif not stored.is_absolute():
            ds.data_path = str(found)
            fixed += 1
    if fixed:
        db.commit()
        log.info("repaired storage paths for %d dataset(s)", fixed)
    return fixed


def _refresh_stats(ds: Dataset, df: pd.DataFrame) -> None:
    df.to_parquet(ds.data_path, index=False)
    ds.row_count, ds.column_count = len(df), len(df.columns)
    ds.profile = {**profile_dataframe(df), "duplicates": duplicate_summary(df)}
    ds.quality = quality_report(df)
    ds.size_bytes = Path(ds.data_path).stat().st_size


def _persist_table(db: Session, user: User, df: pd.DataFrame, *, name: str, source_type: str,
                   original: str, checksum: str, notes: list[str] | None = None) -> Dataset:
    df = infer_types(df)
    ds = Dataset(owner_id=user.id, name=name, kind="table", source_type=source_type,
                 original_filename=original, checksum=checksum,
                 table_name=_unique_table(db, user.id, safe_table_name(name)))
    db.add(ds)
    db.flush()
    ds.data_path = str(settings.processed_directory / f"{ds.id}.parquet")
    try:
        _refresh_stats(ds, df)
    except Exception as e:
        db.rollback()
        raise IngestionError(f"Could not store dataset: {e}") from e
    ds.cleaning_log = [{"op": "ingest", "message": m} for m in (notes or [])]
    db.commit()
    audit(db, user, "dataset.create", f"id={ds.id} name={name} rows={ds.row_count}")
    return ds


def ingest_upload(db: Session, user: User, filename: str, content: bytes) -> Dataset:
    settings.ensure_dirs()
    safe_name = Path(filename or "upload").name
    ext = Path(safe_name).suffix.lower()
    cfg = appconfig.get("uploads", db)
    allowed = {e for e in cfg["allowed_formats"] if e in ALLOWED_EXT}
    if ext not in allowed:
        raise IngestionError(f"Unsupported file type '{ext or '(none)'}'. Allowed: {', '.join(sorted(allowed))}")
    if not content:
        raise IngestionError("File is empty")
    max_mb = ent.effective_upload_limit_mb(db, user)
    if len(content) > max_mb * 1024 * 1024:
        raise IngestionError(f"File exceeds {max_mb} MB limit", 413)
    if ext in DOC_EXT:
        ent.check_feature(db, user, "document_research")
    ent.check_limit(db, user, "max_datasets")
    ent.check_limit(db, user, "storage_mb", len(content) / 1048576)
    if cfg.get("storage_limit_gb"):
        total = db.scalar(select(func.coalesce(func.sum(Dataset.size_bytes), 0))) or 0
        if total + len(content) > cfg["storage_limit_gb"] * 1024**3:
            raise IngestionError("Platform storage limit reached. Contact the administrator.", 507)
    checksum = hashlib.sha256(content).hexdigest()
    dup = db.scalar(select(Dataset).where(Dataset.owner_id == user.id, Dataset.checksum == checksum))
    if dup:
        raise AppError(f"This file was already uploaded as '{dup.name}' (id {dup.id})", 409)

    path = settings.upload_directory / f"{uuid.uuid4().hex}{ext}"
    path.write_bytes(content)
    try:
        src = load_file(path)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    name = Path(safe_name).stem
    if src.kind == "table":
        ds = _persist_table(db, user, src.df, name=name, source_type=src.source_type,
                            original=safe_name, checksum=checksum, notes=src.notes)
        return ds
    ds = Dataset(owner_id=user.id, name=name, kind="document", source_type=src.source_type,
                 original_filename=safe_name, checksum=checksum,
                 table_name=_unique_table(db, user.id, safe_table_name(name)))
    db.add(ds)
    db.flush()
    ds.data_path = str(settings.processed_directory / f"{ds.id}.txt")
    Path(ds.data_path).write_text(src.text, encoding="utf-8")
    ds.row_count = len([p for p in re.split(r"\n\s*\n", src.text) if p.strip()])
    ds.size_bytes = len(content)
    ds.profile = {"characters": len(src.text), "words": len(src.text.split()), "paragraphs": ds.row_count,
                  "preview": src.text[:1500]}
    _d = analyze_text_duplicates(src.text, True, 1)
    ds.profile = {**ds.profile, "duplicates": {"rows": _d["rows"], "duplicate_rows": _d["duplicate_rows"], "groups": _d["groups"], "pct": round(_d["duplicate_pct"], 4), "blank_cells": 0}}
    db.commit()
    audit(db, user, "dataset.create", f"id={ds.id} document={name}")
    return ds


def ingest_sql(db: Session, user: User, url: str, query: str | None, table: str | None, name: str) -> Dataset:
    ent.check_limit(db, user, "max_datasets")
    df = load_sql_source(url, query, table, settings.max_query_rows * 10)
    ds = _persist_table(db, user, df, name=name, source_type="sql", original=table or "query",
                        checksum="", notes=[f"Imported from external SQL database ({url.split('@')[-1].split('?')[0]})"])
    return ds


def clean(db: Session, user: User, ds: Dataset, op: str, column: str | None, strategy: str | None) -> dict:
    df = load_df(ds)
    new_df, msg = apply_operation(df, op, column, strategy)
    before_q = (ds.quality or {}).get("score")
    _refresh_stats(ds, new_df)
    ds.cleaning_log = [*(ds.cleaning_log or []), {"op": op, "column": column, "message": msg,
                                                   "rows_after": len(new_df)}]
    db.commit()
    audit(db, user, "dataset.clean", f"id={ds.id} op={op} column={column}")
    return {"message": msg, "quality_before": before_q, "quality_after": ds.quality.get("score")}


def preview(ds: Dataset, limit: int, offset: int) -> dict:
    df = load_df(ds)
    page = df.iloc[offset: offset + limit]
    return {"columns": [{"name": c, "dtype": str(df[c].dtype)} for c in df.columns],
            "rows": frame_records(page), "total": len(df), "offset": offset, "limit": limit}


def delete(db: Session, user: User, ds: Dataset) -> None:
    f = resolve_path(ds.data_path)
    if f:
        f.unlink(missing_ok=True)
    db.delete(ds)
    db.commit()
    audit(db, user, "dataset.delete", f"id={ds.id}")


def serialize(ds: Dataset, detail: bool = False) -> dict:
    d = {"id": ds.id, "name": ds.name, "kind": ds.kind, "source_type": ds.source_type,
         "table_name": ds.table_name, "original_filename": ds.original_filename, "status": ds.status,
         "row_count": ds.row_count, "column_count": ds.column_count, "size_bytes": ds.size_bytes,
         "quality_score": (ds.quality or {}).get("score"), "created_at": ds.created_at.isoformat(),
         "updated_at": ds.updated_at.isoformat()}
    if detail:
        d.update(profile=jsonable(ds.profile), quality=jsonable(ds.quality), cleaning_log=ds.cleaning_log or [])
    return d
