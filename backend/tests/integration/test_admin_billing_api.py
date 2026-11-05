
import pytest

from backend.app.db.session import SessionLocal
from backend.app.models import User
from backend.app.services import appconfig

A = "/api/v1/admin"
API = "/api/v1"


def _reg(client, email):
    r = client.post(f"{API}/auth/register", json={"email": email, "password": "password123"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}, r.json()["user"]["id"]


@pytest.fixture(scope="module")
def root(client, auth):
    h, uid = _reg(client, "billing-root@test.io")
    with SessionLocal() as db:
        db.get(User, uid).role = "super_admin"
        db.commit()
    return h


@pytest.fixture(autouse=True)
def _reset_settings(client):
    yield
    with SessionLocal() as db:
        from backend.app.models import AppSetting
        db.query(AppSetting).delete()
        db.commit()
    appconfig._cache.clear()


def _plan(**kw):
    return {"slug": "pro", "name": "Pro", "monthly_price_cents": 1900, "yearly_price_cents": 19000, "trial_days": 7, **kw}


CSV = b"a,b\n1,2\n3,4\n"


def test_new_admin_routes_are_super_admin_only(client, other_auth):
    gets = ["/plans", "/promos", "/transactions", "/settings/ai", "/settings/platform", "/analytics", "/ai/summary", "/users/1/billing"]
    for p in gets:
        assert client.get(A + p).status_code == 401, p
        assert client.get(A + p, headers=other_auth).status_code == 403, p
    assert client.post(f"{A}/plans", json=_plan(), headers=other_auth).status_code == 403
    assert client.put(f"{A}/settings/platform", json={"app_name": "x"}, headers=other_auth).status_code == 403
    assert client.post(f"{A}/users/1/role", json={"role": "super_admin"}, headers=other_auth).status_code == 403


def test_role_change_guards(client, root):
    _, uid = _reg(client, "promotee@test.io")
    assert client.post(f"{A}/users/{uid}/role", json={"role": "admin"}, headers=root).json()["role"] == "admin"
    assert client.post(f"{A}/users/{uid}/role", json={"role": "root"}, headers=root).status_code == 422
    me = client.get(f"{API}/auth/me", headers=root).json()["id"]
    assert client.post(f"{A}/users/{me}/role", json={"role": "analyst"}, headers=root).status_code == 400


def test_plan_crud_validation(client, root):
    assert client.post(f"{A}/plans", json=_plan(features={"nope": True}), headers=root).status_code == 422
    assert client.post(f"{A}/plans", json=_plan(limits={"max_datasets": -1}), headers=root).status_code == 422
    assert client.post(f"{A}/plans", json=_plan(monthly_price_cents=-5), headers=root).status_code == 422
    r = client.post(f"{A}/plans", json=_plan(limits={"max_datasets": 1}), headers=root)
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    assert client.post(f"{A}/plans", json=_plan(), headers=root).status_code == 409
    assert client.put(f"{A}/plans/{pid}", json=_plan(name="Pro+"), headers=root).json()["name"] == "Pro+"
    free = next(p for p in client.get(f"{A}/plans", headers=root).json()["items"] if p["slug"] == "free")
    assert client.delete(f"{A}/plans/{free['id']}", headers=root).status_code == 400
    assert client.delete(f"{A}/plans/{pid}", headers=root).status_code == 204


def test_plan_limits_and_features_enforced(client, root):
    h, uid = _reg(client, "limited@test.io")
    r = client.post(f"{A}/plans", json=_plan(slug="tiny", name="Tiny", monthly_price_cents=0, yearly_price_cents=0, trial_days=0,
                                             limits={"max_datasets": 1, "max_file_mb": 1}, features={"ai_chat": False, "pdf_reports": False}), headers=root)
    pid = r.json()["id"]
    assert client.post(f"{A}/users/{uid}/subscription", json={"plan_id": pid}, headers=root).status_code == 200
    up = lambda n: client.post(f"{API}/datasets", headers=h, files={"file": (n, CSV, "text/csv")})  # noqa: E731
    assert up("one.csv").status_code == 201
    big = client.post(f"{API}/datasets", headers=h, files={"file": ("big.csv", b"a\n" + b"1\n" * 700_000, "text/csv")})
    assert big.status_code in (402, 413)
    two = client.post(f"{API}/datasets", headers=h, files={"file": ("two.csv", b"x,y\n9,8\n", "text/csv")})
    assert two.status_code == 402 and "Tiny" in two.json()["detail"]
    assert client.get(f"{API}/chat/conversations", headers=h).status_code == 403  # feature off for plan
    me = client.get(f"{API}/billing/me", headers=h).json()
    assert me["plan"]["slug"] == "tiny" and me["features"]["ai_chat"] is False and me["usage"]["max_datasets"] == 1


def test_global_feature_toggle_and_super_admin_exempt(client, root, auth):
    assert client.get(f"{API}/sql/schema", headers=auth).status_code == 200
    assert client.put(f"{A}/settings/features", json={"sql_analysis": False}, headers=root).status_code == 200
    r = client.get(f"{API}/sql/schema", headers=auth)
    assert r.status_code == 403 and "disabled" in r.json()["detail"]
    assert client.get(f"{API}/billing/me", headers=auth).json()["features"]["sql_analysis"] is False


def test_upload_settings_enforced(client, root, auth):
    assert client.put(f"{A}/settings/uploads", json={"allowed_formats": [".exe"]}, headers=root).status_code == 422
    assert client.put(f"{A}/settings/uploads", json={"allowed_formats": [".json"]}, headers=root).status_code == 200
    r = client.post(f"{API}/datasets", headers=auth, files={"file": ("new.csv", b"q,w\n5,6\n", "text/csv")})
    assert r.status_code in (400, 422) and "Unsupported" in r.text


def test_promo_rules_and_revenue(client, root):
    plan = client.post(f"{A}/plans", json=_plan(slug="promoplan", name="PP", trial_days=0), headers=root).json()
    h, uid = _reg(client, "buyer@test.io")
    bad = {"code": "x", "discount_type": "percent", "value": 10}
    assert client.post(f"{A}/promos", json=bad, headers=root).status_code == 422
    assert client.post(f"{A}/promos", json={**bad, "code": "BIG", "value": 150}, headers=root).status_code == 422
    c = client.post(f"{A}/promos", json={"code": "launch20", "discount_type": "percent", "value": 20, "max_uses": 1, "plan_ids": [plan["id"]],
                                         "first_time_only": True}, headers=root)
    assert c.status_code == 201 and c.json()["code"] == "LAUNCH20"
    v = client.post(f"{API}/billing/promo/validate", headers=h, json={"code": "launch20", "plan_id": plan["id"]}).json()
    assert v["discount_cents"] == 380 and v["total_cents"] == 1520
    other = client.post(f"{A}/plans", json=_plan(slug="other", name="Other"), headers=root).json()
    assert client.post(f"{API}/billing/promo/validate", headers=h, json={"code": "LAUNCH20", "plan_id": other["id"]}).status_code == 400
    assert client.post(f"{API}/billing/promo/validate", headers=h, json={"code": "nope", "plan_id": plan["id"]}).status_code == 400

    t = client.post(f"{A}/transactions", headers=root, json={"user_id": uid, "plan_id": plan["id"], "promo_code": "LAUNCH20"})
    assert t.status_code == 201 and t.json()["amount_cents"] == 1520 and t.json()["discount_cents"] == 380
    assert client.get(f"{API}/billing/me", headers=h).json()["plan"]["slug"] == "promoplan"  # activated
    # max_uses=1 reached
    h2, uid2 = _reg(client, "buyer2@test.io")
    assert client.post(f"{A}/transactions", headers=root, json={"user_id": uid2, "plan_id": plan["id"], "promo_code": "LAUNCH20"}).status_code == 400
    promo = next(p for p in client.get(f"{A}/promos", headers=root).json()["items"] if p["code"] == "LAUNCH20")
    assert promo["uses"] == 1 and promo["discount_given_cents"] == 380 and promo["revenue_cents"] == 1520
    assert client.delete(f"{A}/promos/{promo['id']}", headers=root).status_code == 409  # redeemed -> keep history

    an = client.get(f"{A}/analytics", headers=root).json()
    assert an["mrr_cents"] >= 1900 and an["paying_subscribers"] >= 1

    ref = client.post(f"{A}/transactions/{t.json()['id']}/refund", headers=root, json={"note": "dup"})
    assert ref.status_code == 200 and ref.json()["amount_cents"] == -1520
    assert client.post(f"{A}/transactions/{t.json()['id']}/refund", headers=root, json={}).status_code == 400
    s = client.get(f"{A}/transactions", headers=root).json()["summary"]
    assert s["refunded_cents"] >= 1520


def test_trial_and_plan_change_rules(client, root):
    p = client.post(f"{A}/plans", json=_plan(slug="trialy", name="Trialy", trial_days=14), headers=root).json()
    h, _ = _reg(client, "trialer@test.io")
    r = client.post(f"{API}/billing/change-plan", headers=h, json={"plan_id": p["id"]})
    assert r.status_code == 200 and r.json()["subscription"]["status"] == "trialing"
    free = next(x for x in client.get(f"{API}/billing/plans", headers=h).json() if x["slug"] == "free")
    assert client.post(f"{API}/billing/change-plan", headers=h, json={"plan_id": free["id"]}).status_code == 200  # downgrade ok
    again = client.post(f"{API}/billing/change-plan", headers=h, json={"plan_id": p["id"]})
    assert again.status_code == 409  # trial used; paid needs gateway


def test_platform_settings_maintenance_registration_verification(client, root, auth):
    pub = client.get(f"{API}/platform").json()
    assert pub["app_name"] and "smtp_password" not in str(pub)
    assert client.put(f"{A}/settings/platform", json={"primary_color": "red"}, headers=root).status_code == 422
    assert client.put(f"{A}/settings/platform", json={"logo_url": "javascript:alert(1)"}, headers=root).status_code == 422
    assert client.put(f"{A}/settings/platform", json={"bogus": 1}, headers=root).status_code == 422
    assert client.put(f"{A}/settings/platform", json={"email_verification": True}, headers=root).status_code == 400  # no SMTP

    client.put(f"{A}/settings/platform", json={"registration_open": False}, headers=root)
    assert client.post(f"{API}/auth/register", json={"email": "late@test.io", "password": "password123"}).status_code == 403
    client.put(f"{A}/settings/platform", json={"registration_open": True}, headers=root)

    client.put(f"{A}/settings/platform", json={"maintenance_mode": True, "maintenance_message": "Back soon"}, headers=root)
    m = client.get(f"{API}/datasets", headers=auth)
    assert m.status_code == 503 and m.json()["maintenance"] is True
    assert client.get(f"{A}/overview", headers=root).status_code == 200  # admin stays reachable
    assert client.get(f"{API}/platform").json()["maintenance_mode"] is True
    client.put(f"{A}/settings/platform", json={"maintenance_mode": False}, headers=root)
    assert client.get(f"{API}/datasets", headers=auth).status_code == 200


def test_email_verification_flow(client, root, monkeypatch):
    sent = []
    monkeypatch.setattr("backend.app.services.mailer.send_mail", lambda to, s, b: (sent.append((to, b)) or (True, "")))
    client.put(f"{A}/settings/smtp", json={"host": "smtp.test", "from_email": "no-reply@test.io"}, headers=root)
    assert client.put(f"{A}/settings/platform", json={"email_verification": True}, headers=root).status_code == 200
    r = client.post(f"{API}/auth/register", json={"email": "verifyme@test.io", "password": "password123"})
    assert r.status_code == 201 and r.json()["verification_required"] is True and "token" not in r.json()
    assert client.post(f"{API}/auth/login", json={"email": "verifyme@test.io", "password": "password123"}).status_code == 403
    link = next(b for to, b in sent if to == "verifyme@test.io")
    token = link.split("token=")[1].split()[0]
    assert client.post(f"{API}/auth/verify", json={"token": "junk"}).status_code == 400
    assert client.post(f"{API}/auth/verify", json={"token": token}).status_code == 200
    assert client.post(f"{API}/auth/login", json={"email": "verifyme@test.io", "password": "password123"}).status_code == 200
    # an access token must not work as a verification token
    access = client.post(f"{API}/auth/login", json={"email": "verifyme@test.io", "password": "password123"}).json()["token"]
    assert client.post(f"{API}/auth/verify", json={"token": access}).status_code == 400


def test_ai_settings_validation_and_caps(client, root, monkeypatch):
    assert client.put(f"{A}/settings/ai", json={"temperature": 5}, headers=root).status_code == 422
    assert client.put(f"{A}/settings/ai", json={"provider": "openai"}, headers=root).status_code == 422
    r = client.put(f"{A}/settings/ai", json={"temperature": 0.3, "system_prompt": "Be brief.", "monthly_token_cap": 100,
                                             "prices": {"m1": {"input_per_m": 3, "output_per_m": 15}}}, headers=root)
    assert r.status_code == 200 and r.json()["values"]["prices"]["m1"]["output_per_m"] == 15
    got = client.get(f"{A}/settings/ai", headers=root).json()
    assert "key" not in str(got["values"]).lower() and "anthropic_key_set" in got["secrets"]
    client.put(f"{A}/settings/ai", json={"monthly_token_cap": None}, headers=root)  # null clears
    assert client.get(f"{A}/settings/ai", headers=root).json()["values"]["monthly_token_cap"] is None

    from backend.app.analytics import llm
    from backend.app.models import LlmUsage
    monkeypatch.setattr(llm.settings, "anthropic_api_key", "k")
    monkeypatch.setattr(llm.settings, "llm_provider", "anthropic")
    calls = []
    monkeypatch.setattr(llm, "_call", lambda *a: calls.append(a) or "ok")
    with SessionLocal() as db:
        db.add(LlmUsage(provider="anthropic", model="m1", input_tokens=80, output_tokens=40, ok=True))
        db.commit()
    client.put(f"{A}/settings/ai", json={"monthly_token_cap": 100, "system_prompt": "Be brief."}, headers=root)
    assert llm.llm_complete("sys", "hi") is None and not calls  # cap reached -> deterministic fallback
    client.put(f"{A}/settings/ai", json={"monthly_token_cap": None}, headers=root)
    assert llm.llm_complete("sys", "hi") == "ok" and "Be brief." in calls[-1][2]
    s = client.get(f"{A}/ai/summary", headers=root).json()
    assert s["month_tokens"] >= 120 and any(m["model"] == "m1" and m["cost_usd"] > 0 for m in s["by_model"]) or s["unpriced_models"]
