"""Safe, read-only SQL execution over uploaded datasets using DuckDB."""
import re
import threading
import time

import duckdb
import pandas as pd

from backend.app.analytics.utils import frame_records
from backend.app.core.exceptions import UnsafeQuery

_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|create|alter|truncate|attach|detach|copy|pragma|install|load|"
    r"export|import|call|set|reset|grant|revoke|vacuum|checkpoint|replace\s+into|merge)\b",
    re.I,
)
_FORBIDDEN_FUNCS = re.compile(
    r"\b(read_csv\w*|read_parquet|read_json\w*|read_text|read_blob|glob|parquet_scan|csv_scan|"
    r"sqlite_scan|postgres_scan|duckdb_\w+|query_table|getenv|current_setting)\s*\(",
    re.I,
)


def _strip(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    sql = re.sub(r"--[^\n]*", " ", sql)
    return sql.strip()


def validate_read_query(sql: str) -> str:
    clean = _strip(sql or "")
    if not clean:
        raise UnsafeQuery("Query is empty")
    body = clean.rstrip(";").strip()
    # Reject multiple statements (ignore semicolons inside string literals).
    no_str = re.sub(r"'(?:[^']|'')*'", "''", body)
    if ";" in no_str:
        raise UnsafeQuery("Only a single statement is allowed")
    if not re.match(r"^(select|with)\b", body, re.I):
        raise UnsafeQuery("Only SELECT queries are allowed")
    if _FORBIDDEN.search(no_str):
        raise UnsafeQuery("Query contains a forbidden keyword; only read-only SELECT is allowed")
    if _FORBIDDEN_FUNCS.search(no_str):
        raise UnsafeQuery("Query uses a forbidden function")
    return body


def run_query(
    tables: dict[str, pd.DataFrame], sql: str, max_rows: int = 10_000, timeout: int = 30
) -> dict:
    safe = validate_read_query(sql)
    limit = max(1, min(int(max_rows), 10_000))
    con = duckdb.connect(":memory:", config={"enable_external_access": False})
    try:
        for name, df in tables.items():
            con.register(name, df)
        timer = threading.Timer(timeout, con.interrupt)
        timer.start()
        start = time.perf_counter()
        try:
            res = con.execute(f"SELECT * FROM ({safe}) AS _r LIMIT {limit + 1}").fetchdf()
        except duckdb.InterruptException:
            raise UnsafeQuery(f"Query exceeded {timeout}s timeout")
        except duckdb.Error as e:
            raise UnsafeQuery(f"SQL error: {str(e).splitlines()[0]}")
        finally:
            timer.cancel()
        truncated = len(res) > limit
        res = res.head(limit)
        return {
            "sql": safe,
            "columns": list(res.columns),
            "rows": frame_records(res),
            "row_count": len(res),
            "truncated": truncated,
            "elapsed_ms": round((time.perf_counter() - start) * 1000, 1),
            "dataframe": res,
        }
    finally:
        con.close()


def scalars(tables: dict[str, pd.DataFrame], sqls: list[str], timeout: int = 30) -> list[float | None]:
    """Run many single-value read-only queries on one connection (used to verify facts). Each returns first cell or None."""
    con = duckdb.connect(":memory:", config={"enable_external_access": False})
    out: list[float | None] = []
    try:
        for name, df in tables.items():
            con.register(name, df)
        timer = threading.Timer(timeout, con.interrupt)
        timer.start()
        try:
            for sql in sqls:
                safe = validate_read_query(sql)
                try:
                    row = con.execute(safe).fetchone()
                except duckdb.Error as e:
                    raise UnsafeQuery(f"SQL error: {str(e).splitlines()[0]}")
                v = row[0] if row else None
                out.append(None if v is None else float(v))
        finally:
            timer.cancel()
        return out
    finally:
        con.close()
