"""PDF and Excel report rendering from a completed analysis."""
import io
from datetime import UTC, datetime

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.models import Analysis, Report, User

INDIGO = colors.HexColor("#4f46e5")


def _chart_png(spec: dict) -> bytes | None:
    data = pd.DataFrame(spec.get("data", []))
    if data.empty or spec["type"] == "heatmap":
        return None
    fig, ax = plt.subplots(figsize=(7, 3.2), dpi=130)
    x, ys = spec["x"], [y for y in spec["y"] if y in data.columns]
    try:
        if spec["type"] == "pie":
            ax.pie(data[ys[0]], labels=data[x], autopct="%1.0f%%", textprops={"fontsize": 7})
        elif spec["type"] in ("line",):
            for y in ys:
                ax.plot(data[x], data[y], marker="o", ms=3, ls="--" if y == "forecast" else "-", label=y)
            ax.legend(fontsize=7)
            ax.set_xticks(ax.get_xticks()[:: max(1, len(data) // 8)])
        elif spec["type"] == "scatter":
            ax.scatter(data[x], data[ys[0]], s=8, alpha=.6)
            ax.set_xlabel(x)
            ax.set_ylabel(ys[0])
        else:
            ax.bar(data[x].astype(str), data[ys[0]], color="#4f46e5")
        ax.set_title(spec["title"], fontsize=9)
        ax.tick_params(labelsize=7)
        plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
        fig.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format="png")
        return buf.getvalue()
    except Exception:
        return None
    finally:
        plt.close(fig)


def render_pdf(path, report: dict) -> None:
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], textColor=INDIGO, fontSize=20, alignment=0)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=colors.HexColor("#111827"), spaceBefore=12)
    body = ParagraphStyle("b", parent=ss["BodyText"], leading=14)
    esc = lambda s: str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm,
                            title=report["title"], author="DataPilot AI")
    s = [Paragraph(esc(report["title"]), h1),
         Paragraph(f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC · Sources: {esc(', '.join(report.get('datasets', [])))}", ss["Italic"]),
         Spacer(1, 10), Paragraph("Executive summary", h2)]
    for line in str(report["answer"]).split("\n"):
        s.append(Paragraph(esc(line), body))
    if report.get("kpis"):
        t = Table([[k["label"] for k in report["kpis"]], [f"{k['value']:,}" if isinstance(k["value"], int) else str(k["value"]) for k in report["kpis"]]])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), INDIGO), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                               ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("GRID", (0, 0), (-1, -1), .4, colors.lightgrey),
                               ("FONTSIZE", (0, 0), (-1, -1), 9)]))
        s += [Spacer(1, 8), t]
    if report.get("insights"):
        s.append(Paragraph("Key findings (evidence-verified)", h2))
        for i in report["insights"]:
            mark = "✔" if i.get("verified") else "•"
            s.append(Paragraph(f"{mark} {esc(i['text'])}", body))
    if report.get("recommendations"):
        s.append(Paragraph("Recommendations", h2))
        for r in report["recommendations"]:
            s.append(Paragraph(f"→ {esc(r)}", body))
    for c in report.get("charts", [])[:5]:
        png = _chart_png(c)
        if png:
            s += [Spacer(1, 8), Image(io.BytesIO(png), width=15 * cm, height=6.8 * cm)]
    if report.get("sql"):
        s.append(Paragraph("Query used", h2))
        s.append(Paragraph(esc(report["sql"]).replace("\n", "<br/>"), ParagraphStyle("code", parent=body, fontName="Courier", fontSize=8)))
        cols, rows = report.get("result_columns") or [], report.get("result_rows") or []
        if cols and rows:
            data = [cols] + [[str(r.get(c, ""))[:24] for c in cols] for r in rows[:15]]
            t = Table(data, repeatRows=1)
            t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2ff")), ("GRID", (0, 0), (-1, -1), .3, colors.lightgrey),
                                   ("FONTSIZE", (0, 0), (-1, -1), 7)]))
            s += [Spacer(1, 6), t]
    if report.get("citations"):
        s.append(Paragraph("Document citations", h2))
        for c in report["citations"]:
            s.append(Paragraph(f"[{esc(c['source'])} · chunk {c['chunk']}] {esc(c['snippet'][:300])}", body))
    v = report.get("validation") or {}
    if v.get("total"):
        s.append(Paragraph("Validation", h2))
        s.append(Paragraph(f"{v['passed']} of {v['total']} numeric claims independently re-computed and confirmed.", body))
    doc.build(s)


def render_xlsx(path, report: dict) -> None:
    with pd.ExcelWriter(path, engine="xlsxwriter") as xw:
        wb = xw.book
        bold = wb.add_format({"bold": True, "bg_color": "#4f46e5", "font_color": "white"})
        wrap = wb.add_format({"text_wrap": True, "valign": "top"})
        ws = wb.add_worksheet("Summary")
        xw.sheets["Summary"] = ws
        ws.set_column(0, 0, 28)
        ws.set_column(1, 1, 100, wrap)
        ws.write(0, 0, report["title"], wb.add_format({"bold": True, "font_size": 14}))
        r = 2
        for label, val in [("Question", report["question"]), ("Answer", report["answer"]),
                           *[(k["label"], k["value"]) for k in report.get("kpis", [])]]:
            ws.write(r, 0, label, bold)
            ws.write(r, 1, val if not isinstance(val, float) else round(val, 3), wrap)
            r += 1
        r += 1
        for title, items in (("Insights", [i["text"] for i in report.get("insights", [])]),
                             ("Recommendations", report.get("recommendations", []))):
            ws.write(r, 0, title, bold)
            r += 1
            for it in items:
                ws.write(r, 1, it, wrap)
                r += 1
            r += 1
        cols, rows = report.get("result_columns") or [], report.get("result_rows") or []
        if cols:
            pd.DataFrame(rows, columns=cols).to_excel(xw, sheet_name="Query result", index=False)
            xw.sheets["Query result"].set_column(0, len(cols), 18)
        if report.get("sql"):
            pd.DataFrame({"sql": [report["sql"]]}).to_excel(xw, sheet_name="SQL", index=False)
        for n, c in enumerate(report.get("charts", [])[:6]):
            sheet = f"Chart data {n + 1}"
            pd.DataFrame(c["data"]).to_excel(xw, sheet_name=sheet, index=False)
        cit = report.get("citations") or []
        if cit:
            pd.DataFrame(cit).to_excel(xw, sheet_name="Citations", index=False)
        q = report.get("quality", {}).get("issues")
        if q:
            pd.DataFrame(q).to_excel(xw, sheet_name="Data quality", index=False)


def create_report(db: Session, user: User, analysis: Analysis, fmt: str, title: str | None) -> Report:
    report = (analysis.result or {}).get("report")
    if not report:
        from backend.app.core.exceptions import AppError

        raise AppError("Analysis has no completed report yet", 409)
    settings.ensure_dirs()
    rec = Report(owner_id=user.id, analysis_id=analysis.id, title=title or report["title"], format=fmt, file_path="")
    db.add(rec)
    db.flush()
    path = settings.report_directory / f"report_{rec.id}.{fmt}"
    (render_pdf if fmt == "pdf" else render_xlsx)(path, {**report, "title": rec.title})
    rec.file_path, rec.size_bytes = str(path), path.stat().st_size
    db.commit()
    return rec


def create_report_from_payload(db: Session, user: User, payload: dict, fmt: str, title: str | None = None) -> Report:
    """Render a ready report dict (e.g. executive summary) without an analysis run."""
    settings.ensure_dirs()
    rec = Report(owner_id=user.id, analysis_id=None, title=title or payload["title"], format=fmt, file_path="")
    db.add(rec)
    db.flush()
    path = settings.report_directory / f"report_{rec.id}.{fmt}"
    (render_pdf if fmt == "pdf" else render_xlsx)(path, {**payload, "title": rec.title})
    rec.file_path, rec.size_bytes = str(path), path.stat().st_size
    db.commit()
    return rec


def executive_to_report(res: dict, dataset_name: str) -> dict:
    """Map an executive summary into the generic report structure used by the PDF / Excel renderers."""
    unit_fmt = lambda k: (f"{k['value']:,.0f}" if k["value"] is not None else "n/a")  # noqa: E731
    ins = ([{"text": "Risk: " + i["text"], "verified": i["verified"]} for i in res["risks"]]
           + [{"text": "Opportunity: " + i["text"], "verified": i["verified"]} for i in res["opportunities"]]
           + [{"text": "Finding: " + i["text"], "verified": i["verified"]} for i in res["findings"] if i not in res["risks"] and i not in res["opportunities"]])
    ver = res["verification"]
    ok = sum(bool(v["verified"]) for v in ver.values())
    return {"title": res["title"], "question": f"Management summary, {res['period']}", "answer": "\n".join(s["text"] for s in res["performance"]),
            "kpis": [{"label": k["label"].capitalize() + (f" ({k['change_pct']:+.1f}%)" if k.get("change_pct") is not None else ""), "value": unit_fmt(k)} for k in res["kpis"]],
            "insights": ins, "recommendations": [r["text"] for r in res["recommendations"]], "charts": res["charts"], "sql": None, "result_columns": [], "result_rows": [],
            "citations": [], "quality": {}, "validation": {"passed": ok, "total": len(ver)}, "datasets": [dataset_name]}
