import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="datapilot-test-"))
os.environ.update(
    DATABASE_URL=os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_tmp / 'test.db'}", UPLOAD_DIRECTORY=str(_tmp / "up"),
    PROCESSED_DIRECTORY=str(_tmp / "proc"), REPORT_DIRECTORY=str(_tmp / "rep"),
    LLM_PROVIDER="none", SECRET_KEY="test-secret-key-test-secret-key-123", DEBUG="false",
)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.app.main import app  # noqa: E402


def make_sales(n: int = 300) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    d = pd.DataFrame({
        "order_id": np.arange(n),
        "order_date": pd.date_range("2024-01-01", periods=n, freq="D"),
        "region": rng.choice(["North", "South", "East"], n),
        "category": rng.choice(["A", "B"], n),
        "units": rng.integers(1, 10, n),
    })
    d["revenue"] = d["units"] * 10 * (1 + np.arange(n) / n) + rng.normal(0, 2, n)
    d.loc[5, "revenue"] = 99999.0
    return d


@pytest.fixture(scope="session")
def client():
    import backend.app.models  # noqa: F401
    from backend.app.db.base import Base
    from backend.app.db.session import engine

    Base.metadata.drop_all(engine)  # clean slate (matters when TEST_DATABASE_URL points at PostgreSQL)
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def sales_df():
    return make_sales()


def _auth(client, email):
    r = client.post("/api/v1/auth/register", json={"email": email, "password": "password123"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="session")
def auth(client):
    return _auth(client, "owner@test.io")


@pytest.fixture(scope="session")
def other_auth(client):
    return _auth(client, "intruder@test.io")


@pytest.fixture(scope="session")
def sales_dataset(client, auth, sales_df):
    csv = sales_df.to_csv(index=False).encode()
    r = client.post("/api/v1/datasets", headers=auth, files={"file": ("sales.csv", csv, "text/csv")})
    assert r.status_code == 201, r.text
    return r.json()
