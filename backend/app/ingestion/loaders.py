"""Parsers: file -> LoadedSource (DataFrame for tables, text for documents)."""
import io
import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from backend.app.core.exceptions import IngestionError

TABLE_EXT = {".csv", ".tsv", ".xlsx", ".xls", ".json", ".jsonl", ".parquet", ".sqlite", ".db"}
DOC_EXT = {".pdf", ".docx", ".txt", ".md"}
ALLOWED_EXT = TABLE_EXT | DOC_EXT


@dataclass
class LoadedSource:
    kind: str  # table | document
    source_type: str
    df: pd.DataFrame | None = None
    text: str = ""
    notes: list[str] = field(default_factory=list)


def safe_table_name(name: str) -> str:
    stem = re.sub(r"[^0-9a-zA-Z_]+", "_", Path(name).stem).strip("_").lower() or "data"
    if stem[0].isdigit():
        stem = "t_" + stem
    return stem[:60]


def _read_csv(path: Path, sep: str | None) -> pd.DataFrame:
    last: Exception | None = None
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return pd.read_csv(path, sep=sep, engine="python", encoding=enc)
        except UnicodeDecodeError as e:
            last = e
    raise IngestionError(f"Cannot decode CSV: {last}")


def _read_json(path: Path, lines: bool) -> pd.DataFrame:
    if lines:
        return pd.read_json(path, lines=True)
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(data, dict):
        # {"data":[...]} or {"rows":[...]} or single record / column dict
        for v in data.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                data = v
                break
        else:
            data = [data] if not all(isinstance(v, list) for v in data.values()) else data
    if isinstance(data, dict):
        return pd.DataFrame(data)
    return pd.json_normalize(data)


def _read_sqlite(path: Path) -> pd.DataFrame:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        if not tables:
            raise IngestionError("SQLite file has no tables")
        # Import the largest table.
        counts = {t: con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}
        best = max(counts, key=counts.get)
        df = pd.read_sql_query(f'SELECT * FROM "{best}"', con)
        df.attrs["notes"] = [f"Imported table '{best}' ({counts[best]} rows) of {len(tables)} tables"]
        return df
    finally:
        con.close()


def _read_pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return "\n\n".join(f"[page {i + 1}]\n{(p.extract_text() or '').strip()}" for i, p in enumerate(reader.pages))


def _read_docx(path: Path) -> str:
    import docx

    d = docx.Document(str(path))
    parts = [p.text for p in d.paragraphs if p.text.strip()]
    for t in d.tables:
        for row in t.rows:
            parts.append(" | ".join(c.text.strip() for c in row.cells))
    return "\n".join(parts)


def load_file(path: Path) -> LoadedSource:
    ext = path.suffix.lower()
    if ext not in ALLOWED_EXT:
        raise IngestionError(f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXT))}")
    try:
        if ext == ".csv":
            df = _read_csv(path, None)
        elif ext == ".tsv":
            df = _read_csv(path, "\t")
        elif ext in (".xlsx", ".xls"):
            df = pd.read_excel(path)
        elif ext == ".json":
            df = _read_json(path, False)
        elif ext == ".jsonl":
            df = _read_json(path, True)
        elif ext == ".parquet":
            df = pd.read_parquet(path)
        elif ext in (".sqlite", ".db"):
            df = _read_sqlite(path)
        else:
            text = {".pdf": _read_pdf, ".docx": _read_docx}.get(ext, lambda p: p.read_text(encoding="utf-8", errors="replace"))(path)
            if not text.strip():
                raise IngestionError("No extractable text found in document")
            return LoadedSource("document", ext[1:], text=text)
    except IngestionError:
        raise
    except Exception as e:  # corrupt file, bad encoding, etc.
        raise IngestionError(f"Could not parse {ext} file: {e}") from e
    if df.empty or len(df.columns) == 0:
        raise IngestionError("File contains no rows")
    notes = df.attrs.pop("notes", [])
    return LoadedSource("table", ext[1:], df=_normalize_columns(df), notes=notes)


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    seen: dict[str, int] = {}
    cols = []
    for i, c in enumerate(df.columns):
        name = re.sub(r"\s+", "_", str(c).strip()) or f"column_{i + 1}"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 0
        cols.append(name)
    df = df.copy()
    df.columns = cols
    return df


def load_sql_source(url: str, query: str | None, table: str | None, max_rows: int) -> pd.DataFrame:
    """Import from an external SQL database (read-only query)."""
    from sqlalchemy import create_engine, text

    from backend.app.analytics.sql_engine import validate_read_query

    if not (query or table):
        raise IngestionError("Provide a table name or a SELECT query")
    if url.startswith("sqlite") and ":memory:" in url:
        raise IngestionError("In-memory SQLite is not importable")
    if query:
        sql = validate_read_query(query)
    else:
        if not re.fullmatch(r"[A-Za-z_][\w.]*", table or ""):
            raise IngestionError("Invalid table name")
        sql = f"SELECT * FROM {table}"
    try:
        eng = create_engine(url, connect_args={"connect_timeout": 10} if not url.startswith("sqlite") else {})
        with eng.connect() as con:
            df = pd.read_sql_query(text(f"SELECT * FROM ({sql.rstrip(';')}) AS _q LIMIT {int(max_rows)}"), con)
        eng.dispose()
    except Exception as e:
        raise IngestionError(f"Database import failed: {str(e).splitlines()[0][:300]}") from e
    if df.empty:
        raise IngestionError("Query returned no rows")
    return _normalize_columns(df)


def df_to_bytes_preview(df: pd.DataFrame, n: int = 100) -> list[dict]:
    return json.loads(df.head(n).to_json(orient="records", date_format="iso", default_handler=str))


__all__ = ["load_file", "load_sql_source", "safe_table_name", "ALLOWED_EXT", "io"]
