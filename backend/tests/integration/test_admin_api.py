import pytest
from sqlalchemy import select

from backend.app.db.session import SessionLocal
from backend.app.models import ApiRequestLog, User

API = "/api/v1/admin"


def _register(client, email):
    r = client.post("/api/v1/auth/register", json={"email": email, "password": "password123", "name": email.split("@")[0]})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}, r.json()["user"]["id"]


@pytest.fixture(scope="module")
def root(client, auth):  # `auth` registers first -> ensures a regular "admin" role user exists
    h, uid = _register(client, "root@test.io")
    with SessionLocal() as db:
        db.get(User, uid).role = "super_admin"
        db.commit()
    return h, uid


GET_PATHS = ["/overview", "/users", "/users/1", "/users/export.csv", "/datasets", "/activity", "/usage/tokens", "/usage/api", "/system"]


def test_anonymous_and_non_super_admin_blocked(client, auth, other_auth):
    for p in GET_PATHS:
        assert client.get(API + p).status_code == 401, p
        assert client.get(API + p, headers=auth).status_code == 403, p        # role "admin" is NOT enough
        assert client.get(API + p, headers=other_auth).status_code == 403, p  # analyst
    assert client.post(f"{API}/users/1/suspend", headers=other_auth).status_code == 403
    assert client.post(f"{API}/users/1/delete", headers=other_auth, json={"confirm_email": "x"}).status_code == 403
    assert client.delete(f"{API}/datasets/1", headers=other_auth).status_code == 403


def test_overview_and_read_endpoints(client, root, sales_dataset):
    h, _ = root
    o = client.get(f"{API}/overview", headers=h).json()
    assert o["total_users"] >= 3 and o["datasets"] >= 1 and len(o["signups_by_day"]) == 30
    for p in GET_PATHS:
        assert client.get(API + p, headers=h).status_code == 200, p
    assert client.get(f"{API}/system", headers=h).json()["checks"][0]["name"] == "Database"


def test_user_list_search_filter_detail(client, root):
    h, _ = root
    r = client.get(f"{API}/users", headers=h, params={"q": "INTRUDER"}).json()
    assert [u["email"] for u in r["items"]] == ["intruder@test.io"]
    assert client.get(f"{API}/users", headers=h, params={"q": "%"}).json()["total"] == 0  # LIKE wildcard escaped
    assert client.get(f"{API}/users", headers=h, params={"role": "super_admin"}).json()["total"] == 1
    u = client.get(f"{API}/users/{r['items'][0]['id']}", headers=h).json()
    assert u["email"] == "intruder@test.io" and "password_hash" not in u
    assert client.get(f"{API}/users/999999", headers=h).status_code == 404


def test_csv_export_neutralises_formulas(client, root):
    h, _ = root
    _register(client, "=cmd@evil.io")
    r = client.get(f"{API}/users/export.csv", headers=h)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    assert "'=cmd@evil.io" in r.text and ",=cmd@evil.io" not in r.text
    assert "password" not in r.text.lower().split("\n")[0]


def test_suspend_blocks_login_and_token_then_reactivate(client, root):
    h, rid = root
    uh, uid = _register(client, "victim@test.io")
    assert client.get("/api/v1/auth/me", headers=uh).status_code == 200
    assert client.post(f"{API}/users/{uid}/suspend", headers=h).json()["status"] == "suspended"
    assert client.get("/api/v1/auth/me", headers=uh).status_code == 403  # existing token dies immediately
    assert client.post("/api/v1/auth/login", json={"email": "victim@test.io", "password": "password123"}).status_code == 403
    client.post(f"{API}/users/{uid}/reactivate", headers=h)
    r = client.post("/api/v1/auth/login", json={"email": "victim@test.io", "password": "password123"})
    assert r.status_code == 200
    assert client.get(f"{API}/users/{uid}", headers=h).json()["last_login_at"]


def test_guards_self_and_super_admin(client, root):
    h, rid = root
    assert client.post(f"{API}/users/{rid}/suspend", headers=h).status_code == 400
    assert client.post(f"{API}/users/{rid}/delete", headers=h, json={"confirm_email": "root@test.io"}).status_code == 400
    _, other_root = _register(client, "root2@test.io")
    with SessionLocal() as db:
        db.get(User, other_root).role = "super_admin"
        db.commit()
    assert client.post(f"{API}/users/{other_root}/suspend", headers=h).status_code == 403


def test_delete_user_requires_matching_email_and_cascades(client, root):
    h, _ = root
    dh, did = _register(client, "doomed@test.io")
    csv = b"a,b\n1,2\n3,4\n"
    assert client.post("/api/v1/datasets", headers=dh, files={"file": ("d.csv", csv, "text/csv")}).status_code == 201
    assert client.post(f"{API}/users/{did}/delete", headers=h, json={"confirm_email": "nope@x.io"}).status_code == 400
    assert client.post(f"{API}/users/{did}/delete", headers=h, json={"confirm_email": "DOOMED@test.io"}).status_code == 200
    assert client.get(f"{API}/users/{did}", headers=h).status_code == 404
    assert client.get("/api/v1/auth/me", headers=dh).status_code == 401
    acts = client.get(f"{API}/activity", headers=h, params={"q": "admin.user.delete"}).json()["items"]
    assert acts and "doomed@test.io" in acts[0]["detail"]


def test_dataset_admin_and_api_usage_logged(client, root, sales_dataset):
    h, _ = root
    ds = client.get(f"{API}/datasets", headers=h, params={"q": "owner@"}).json()
    assert ds["total"] >= 1 and ds["items"][0]["owner_email"] == "owner@test.io"
    assert client.delete(f"{API}/datasets/999999", headers=h).status_code == 404
    with SessionLocal() as db:
        routes = set(db.scalars(select(ApiRequestLog.route)))
    assert "/api/v1/datasets" in routes and not any("eyJ" in r or "?" in r for r in routes)
    u = client.get(f"{API}/usage/api", headers=h).json()
    assert u["totals"]["requests"] > 0 and u["top_routes"]
