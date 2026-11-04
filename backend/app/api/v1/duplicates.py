import io

import pandas as pd
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from backend.app.analytics import duplicates as dup
from backend.app.core.security import get_current_user, get_db
from backend.app.models import User
from backend.app.schemas.api import DupExportIn, DupOptionsIn, DupRowsIn
from backend.app.services import datasets as ds_svc

router = APIRouter()


def _run(db: Session, user: User, dataset_id: int, o: DupOptionsIn):
    ds = ds_svc.get_dataset(db, user, dataset_id)
    if ds.kind == "document":
        return ds, None, dup.analyze_text_duplicates(ds_svc.load_text(ds), True, o.limit)
    df = ds_svc.load_df(ds)
    return ds, df, dup.analyze_duplicates(df, o.columns, o.blank_as_missing, o.ignore_case_space, o.exclude_id_like, o.limit)


@router.post("/{dataset_id}/duplicates")
def analyze(dataset_id: int, body: DupOptionsIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _, _, res = _run(db, user, dataset_id, body)
    return res


@router.post("/{dataset_id}/duplicates/rows")
def inspect_rows(dataset_id: int, body: DupRowsIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """The original records behind a duplicate group (by 1-based row / paragraph number)."""
    ds = ds_svc.get_dataset(db, user, dataset_id)
    if ds.kind == "document":
        return {"columns": ["paragraph"], "rows": dup.text_rows(ds_svc.load_text(ds), body.row_numbers)}
    df = ds_svc.load_df(ds)
    return {"columns": list(df.columns), "rows": dup.rows_for_numbers(df, body.row_numbers)}


@router.post("/{dataset_id}/duplicates/export")
def export(dataset_id: int, body: DupExportIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ds, df, res = _run(db, user, dataset_id, body)
    cols = res["columns_used"]
    groups = pd.DataFrame([{"group_id": g["id"], "occurrences": g["count"], "extra_copies": g["extra"], "first_row": g["first_row"],
                            "row_numbers": ", ".join(map(str, g["row_numbers"])) + (" …" if g["count"] > len(g["row_numbers"]) else ""), **g["values"]} for g in res["groups_list"]])
    if body.scope == "rows":
        if df is None:
            paras = dup.text_rows(ds_svc.load_text(ds), sorted({r for g in res["groups_list"] for r in g["row_numbers"]}))
            frame = pd.DataFrame(paras).rename(columns={"__row__": "paragraph_number"})
        else:
            frame = dup.all_duplicate_rows(df, body.columns, body.blank_as_missing, body.ignore_case_space, body.exclude_id_like)
    else:
        frame = groups
    ds_svc.audit(db, user, "dataset.duplicates.export", f"id={dataset_id} scope={body.scope} fmt={body.format}")
    base = f"duplicates_{ds.table_name}_{body.scope}"[:70]
    if body.format == "csv":
        return StreamingResponse(iter([frame.to_csv(index=False)]), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{base}.csv"'})
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as xw:
        summary = pd.DataFrame({"Metric": ["Dataset", "Unit", "Total", "Duplicate (extra) copies", "Duplicate %", "Duplicate groups", "Rows involved", "Columns compared", "Blank cells treated as missing"],
                                "Value": [ds.name, res["unit"], res["rows"], res["duplicate_rows"], f"{res['duplicate_pct']:.4f}%", res["groups"], res["rows_involved"], ", ".join(cols), res["blank_cells_treated_as_missing"]]})
        summary.to_excel(xw, sheet_name="Summary", index=False)
        groups.to_excel(xw, sheet_name="Groups", index=False)
        if body.scope == "rows":
            frame.to_excel(xw, sheet_name="Duplicate rows", index=False)
        head = xw.book.add_format({"bold": True, "bg_color": "#B8864A", "font_color": "white"})
        for name, f in (("Summary", summary), ("Groups", groups)) + ((("Duplicate rows", frame),) if body.scope == "rows" else ()):
            ws = xw.sheets[name]
            for i, c in enumerate(f.columns):
                ws.write(0, i, c, head)
                ws.set_column(i, i, min(40, max(12, len(str(c)) + 4)))
    return StreamingResponse(iter([buf.getvalue()]), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f'attachment; filename="{base}.xlsx"'})
