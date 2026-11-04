import pandas as pd
import pytest

from backend.app.analytics.sql_engine import run_query, validate_read_query
from backend.app.core.exceptions import UnsafeQuery

BAD = ["DROP TABLE t", "DELETE FROM t", "SELECT 1; DROP TABLE t", "INSERT INTO t VALUES (1)",
       "COPY t TO '/tmp/x.csv'", "SELECT * FROM read_csv('/etc/passwd')", "ATTACH 'x.db'", "", "PRAGMA version",
       "WITH x AS (SELECT 1) DELETE FROM t", "SELECT * FROM read_parquet('a.parquet')", "/*c*/ UPDATE t SET a=1"]


@pytest.mark.parametrize("sql", BAD)
def test_rejects_unsafe(sql):
    with pytest.raises(UnsafeQuery):
        validate_read_query(sql)


def test_allows_select_and_cte():
    assert validate_read_query("SELECT 1;") == "SELECT 1"
    validate_read_query("WITH a AS (SELECT 1 x) SELECT * FROM a")
    validate_read_query("SELECT 'a;b' AS s")


def test_run_query_and_limits():
    df = pd.DataFrame({"a": range(50)})
    r = run_query({"t": df}, "SELECT SUM(a) AS s FROM t", 10, 5)
    assert r["rows"][0]["s"] == sum(range(50))
    r = run_query({"t": df}, "SELECT * FROM t", 10, 5)
    assert r["row_count"] == 10 and r["truncated"]


def test_external_access_blocked():
    with pytest.raises(UnsafeQuery):
        run_query({}, "SELECT * FROM read_text('/etc/passwd')", 10, 5)


def test_sql_error_is_reported():
    with pytest.raises(UnsafeQuery, match="SQL error"):
        run_query({"t": pd.DataFrame({"a": [1]})}, "SELECT nope FROM t", 10, 5)
