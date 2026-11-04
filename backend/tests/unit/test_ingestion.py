import json
import sqlite3

import pandas as pd
import pytest

from backend.app.core.exceptions import IngestionError
from backend.app.ingestion.loaders import load_file, load_sql_source, safe_table_name


def test_csv_xlsx_json_parquet(tmp_path):
    df = pd.DataFrame({"a b": [1, 2], "c": ["x", "y"]})
    df.to_csv(tmp_path / "f.csv", index=False)
    df.to_excel(tmp_path / "f.xlsx", index=False)
    df.to_parquet(tmp_path / "f.parquet")
    (tmp_path / "f.json").write_text(json.dumps({"data": df.to_dict("records")}))
    (tmp_path / "f.jsonl").write_text("\n".join(json.dumps(r) for r in df.to_dict("records")))
    for name in ("f.csv", "f.xlsx", "f.parquet", "f.json", "f.jsonl"):
        s = load_file(tmp_path / name)
        assert s.kind == "table" and len(s.df) == 2 and "a_b" in s.df.columns, name


def test_sqlite_and_document(tmp_path):
    con = sqlite3.connect(tmp_path / "x.db")
    con.execute("CREATE TABLE t (a INT, b TEXT)")
    con.executemany("INSERT INTO t VALUES (?,?)", [(1, "x"), (2, "y")])
    con.commit(); con.close()
    assert len(load_file(tmp_path / "x.db").df) == 2
    (tmp_path / "n.txt").write_text("hello policy world")
    assert load_file(tmp_path / "n.txt").kind == "document"
    (tmp_path / "n.md").write_text("# hi\ntext")
    assert load_file(tmp_path / "n.md").text.startswith("# hi")


def test_bad_inputs(tmp_path):
    (tmp_path / "e.csv").write_text("")
    with pytest.raises(IngestionError):
        load_file(tmp_path / "e.csv")
    (tmp_path / "x.exe").write_bytes(b"MZ")
    with pytest.raises(IngestionError, match="Unsupported"):
        load_file(tmp_path / "x.exe")
    (tmp_path / "bad.json").write_text("{not json")
    with pytest.raises(IngestionError):
        load_file(tmp_path / "bad.json")


def test_sql_source_is_read_only(tmp_path):
    con = sqlite3.connect(tmp_path / "s.db")
    con.execute("CREATE TABLE t (a INT)"); con.execute("INSERT INTO t VALUES (1),(2)"); con.commit(); con.close()
    url = f"sqlite:///{tmp_path / 's.db'}"
    assert len(load_sql_source(url, None, "t", 100)) == 2
    assert len(load_sql_source(url, "SELECT a FROM t WHERE a > 1", None, 100)) == 1
    with pytest.raises(Exception):
        load_sql_source(url, "DROP TABLE t", None, 100)
    with pytest.raises(IngestionError):
        load_sql_source(url, None, "t; DROP TABLE t", 100)


def test_safe_table_name():
    assert safe_table_name("2024 Sales (Final).csv") == "t_2024_sales_final"
