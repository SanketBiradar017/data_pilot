import io

import pandas as pd
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from backend.app.analytics import hypothesis, pareto, pivot, regression, variance
from backend.app.analytics.utils import categorical_cols, datetime_cols, infer_types, jsonable, numeric_cols
from backend.app.core.exceptions import AppError
from backend.app.core.security import get_current_user, get_db
from backend.app.models import User
from backend.app.schemas.api import HypothesisIn, ParetoIn, PivotExportIn, PivotIn, RegressionIn, VarianceIn
from backend.app.services import datasets as ds_svc

router = APIRouter()


def _frame(db: Session, user: User, dataset_id: int) -> tuple[pd.DataFrame, str]:
    ds = ds_svc.get_dataset(db, user, dataset_id)
    if ds.kind != "table":
        raise AppError("This tool needs a tabular dataset")
    return ds_svc.load_df(ds), ds.name


@router.get("/fields/{dataset_id}")
def fields(dataset_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Columns with their role plus distinct values (for filter pickers)."""
    df, _ = _frame(db, user, dataset_id)
    nums, dts, cats = set(numeric_cols(df)), set(datetime_cols(df)), set(categorical_cols(df, 200))
    out = []
    for c in df.columns:
        kind = "numeric" if c in nums else "datetime" if c in dts else "category" if c in cats else "text"
        item = {"name": c, "kind": kind, "unique": int(df[c].nunique(dropna=True))}
        if kind == "category":
            item["values"] = [str(v) for v in df[c].dropna().astype(str).value_counts().head(100).index]
        elif kind in ("numeric", "datetime"):
            item["min"], item["max"] = jsonable(df[c].min()), jsonable(df[c].max())
        out.append(item)
    # integer ID-like columns are numeric dtype but not measures; flag them so the UI can hide them from "values"
    for item in out:
        item["measure"] = item["name"] in nums
    return {"columns": out, "rows": len(df)}


@router.post("/pivot")
def pivot_run(body: PivotIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    df, _ = _frame(db, user, body.dataset_id)
    res = pivot.pivot(df, body.rows, body.columns, [v.model_dump() for v in body.values], [f.model_dump() for f in body.filters], body.totals)
    ds_svc.audit(db, user, "analytics.pivot", f"dataset={body.dataset_id}")
    return {**res, "chart": pivot.pivot_chart(res)}


@router.post("/pivot/export")
def pivot_export(body: PivotExportIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    df, name = _frame(db, user, body.dataset_id)
    res = pivot.pivot(df, body.rows, body.columns, [v.model_dump() for v in body.values], [f.model_dump() for f in body.filters], body.totals)
    frame = pivot.pivot_to_frame(res)
    ds_svc.audit(db, user, "analytics.pivot.export", f"dataset={body.dataset_id} fmt={body.format}")
    base = f"pivot_{name}"[:60]
    if body.format == "csv":
        return StreamingResponse(iter([frame.to_csv(index=False)]), media_type="text/csv",
                                 headers={"Content-Disposition": f'attachment; filename="{base}.csv"'})
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as xw:
        frame.to_excel(xw, sheet_name="Pivot", index=False)
        wb, ws = xw.book, xw.sheets["Pivot"]
        head = wb.add_format({"bold": True, "bg_color": "#92623A", "font_color": "white", "border": 1})
        num = wb.add_format({"num_format": "#,##0.00"})
        bold = wb.add_format({"bold": True, "num_format": "#,##0.00", "top": 1})
        for i, c in enumerate(frame.columns):
            ws.write(0, i, c, head)
            ws.set_column(i, i, max(14, min(40, len(str(c)) + 4)), num if i >= len(res["row_fields"]) else None)
        if res["has_totals"]:
            for i in range(len(frame.columns)):
                v = frame.iloc[-1, i]
                ws.write(len(frame), i, None if pd.isna(v) else v, bold)
        ws.freeze_panes(1, len(res["row_fields"]))
        pd.DataFrame({"Setting": ["Dataset", "Rows", "Columns", "Values", "Filters", "Source rows"],
                      "Value": [name, ", ".join(body.rows), ", ".join(body.columns), ", ".join(res["value_labels"]),
                                "; ".join(f"{f.column} {f.op} {f.value}" for f in body.filters) or "none", res["source_rows"]]}).to_excel(xw, sheet_name="Definition", index=False)
    return StreamingResponse(iter([buf.getvalue()]), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f'attachment; filename="{base}.xlsx"'})


@router.post("/regression")
def regression_run(body: RegressionIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    df, _ = _frame(db, user, body.dataset_id)
    res = regression.run_regression(df, body.target, body.features, body.auto_select, body.alpha)
    ds_svc.audit(db, user, "analytics.regression", f"dataset={body.dataset_id} target={body.target}")
    return res


@router.post("/hypothesis")
def hypothesis_run(body: HypothesisIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    df, _ = _frame(db, user, body.dataset_id)
    res = hypothesis.run_test(df, body.test, body.value, body.group, body.groups, body.value2, body.alpha)
    ds_svc.audit(db, user, "analytics.hypothesis", f"dataset={body.dataset_id} test={body.test}")
    return res


@router.post("/pareto")
def pareto_run(body: ParetoIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    df, _ = _frame(db, user, body.dataset_id)
    res = pareto.run_pareto(df, body.category, body.value, body.a_cut, body.b_cut)
    ds_svc.audit(db, user, "analytics.pareto", f"dataset={body.dataset_id}")
    return res


@router.post("/variance")
def variance_run(body: VarianceIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    df, _ = _frame(db, user, body.dataset_id)
    metrics = [m.model_dump() for m in body.metrics]
    if body.mode == "target":
        res = variance.actual_vs_target(df, metrics, body.group_by, body.tolerance_pct, body.derive_profit)
    else:
        if not body.date_column:
            raise AppError("Choose a date column for period comparison")
        df = infer_types(df)
        res = variance.period_over_period(df, body.date_column, metrics, body.period, body.group_by, body.tolerance_pct, body.current, body.previous)
    ds_svc.audit(db, user, "analytics.variance", f"dataset={body.dataset_id} mode={body.mode}")
    return res
