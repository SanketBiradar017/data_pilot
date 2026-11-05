import logging

import httpx
import pytest
from sqlalchemy import select, text

from backend.app.analytics import llm
from backend.app.config import settings
from backend.app.core import secrets
from backend.app.db.session import SessionLocal
from backend.app.models import ApiKey, ApiKeyEvent, AuditLog, User
from backend.app.services import ai_config

API = "/api/v1/admin/ai-keys"
KEY1 = "AIzaSyTESTKEYONE_0123456789abcdefghijk"   # fake
KEY2 = "AIzaSyTESTKEYTWO_0123456789abcdefghijk"   # fake
BAD = "AIzaSyBADBADBADBAD_0123456789abcdefghij"   # fake


@pytest.fixture(scope="module")
def root(client, auth):
    r = client.post("/api/v1/auth/register", json={"email": "keyadmin@test.io", "password": "password123", "name": "ka"})
    assert r.status_code == 201, r.text
    uid = r.json()["user"]["id"]
    with SessionLocal() as db:
        db.get(User, uid).role = "super_admin"
        db.commit()
    yield {"Authorization": f"Bearer {r.json()['token']}"}
    with SessionLocal() as db:  # the shared test DB must not keep an extra super admin (other modules count them)
        db.get(User, uid).role = "admin"
        db.commit()


@pytest.fixture(autouse=True)
def fake_google(monkeypatch):
    """Provider stub: BAD keys are rejected, unknown model -> 404; records the key of each generate call."""
    calls = {"generate": []}

    def get(url, headers=None, timeout=None):
        key = headers.get("x-goog-api-key", "")
        if key == BAD:
            return httpx.Response(403, json={"error": {"message": f"API key {key} not valid"}})
        if "nonexistent" in url:
            return httpx.Response(404, json={})
        return httpx.Response(200, json={"name": "models/x"})

    def post(url, headers=None, json=None, timeout=None):
        calls["generate"].append((headers.get("x-goog-api-key"), url))
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "hi"}]}}], "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 2}},
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "get", get)
    monkeypatch.setattr(httpx, "post", post)
    ai_config.invalidate()
    return calls


def test_requires_super_admin(client, auth, root):
    assert client.get(API).status_code == 401
    assert client.get(API, headers=auth).status_code == 403
    assert client.post(API, headers=auth, json={"api_key": KEY1}).status_code == 403
    assert client.get(API + "/history", headers=auth).status_code == 403


def test_env_fallback_then_admin_key_takes_priority(client, root, fake_google, monkeypatch):
    monkeypatch.setattr(settings, "google_api_key", "AIzaENVKEY_0123456789abcdefghijklmnop")
    monkeypatch.setattr(settings, "llm_provider", "google")
    ai_config.invalidate()
    o = client.get(API, headers=root).json()
    assert o["effective"]["key_source"] == "env" and o["effective"]["enabled"] and o["env"]["google"]["masked"].endswith("mnop")
    assert llm.llm_complete("s", "p") == "hi" and fake_google["generate"][-1][0].startswith("AIzaENV")

    r = client.post(API, headers=root, json={"provider": "google", "label": "prod", "api_key": KEY1, "activate": True})
    assert r.status_code == 201, r.text
    k = r.json()
    assert k["is_active"] and k["status"] == "valid" and k["masked"] == "•" * 12 + KEY1[-4:]
    # takes effect immediately, no restart
    assert llm.llm_complete("s", "p") == "hi" and fake_google["generate"][-1][0] == KEY1
    assert client.get(API, headers=root).json()["effective"]["key_source"] == "admin"

    # rotate: second key replaces the first as the single active key
    k2 = client.post(API, headers=root, json={"label": "next", "api_key": KEY2}).json()
    assert not k2["is_active"]
    assert client.post(f"{API}/{k2['id']}/activate", headers=root).json()["is_active"]
    llm.llm_complete("s", "p")
    assert fake_google["generate"][-1][0] == KEY2
    keys = {x["id"]: x for x in client.get(API, headers=root).json()["keys"]}
    assert keys[k["id"]]["is_active"] is False and keys[k2["id"]]["is_active"] is True
    assert keys[k2["id"]]["usage"]["calls"] >= 1 and keys[k2["id"]]["usage"]["input_tokens"] >= 3

    # deactivate -> back to env key
    d = client.post(f"{API}/{k2['id']}/deactivate", headers=root).json()
    assert "environment" in d["message"]
    llm.llm_complete("s", "p")
    assert fake_google["generate"][-1][0].startswith("AIzaENV")


def test_invalid_key_cannot_be_activated_and_active_key_not_replaced_by_bad(client, root):
    r = client.post(API, headers=root, json={"api_key": BAD, "activate": True})
    assert r.status_code == 422 and BAD not in r.text and "rejected" in r.text
    row = next(x for x in client.get(API, headers=root).json()["keys"] if x["status"] == "invalid")
    assert not row["is_active"]
    good = client.post(API, headers=root, json={"api_key": KEY1, "activate": True}).json()
    r = client.put(f"{API}/{good['id']}", headers=root, json={"api_key": BAD})
    assert r.status_code == 422 and BAD not in r.text
    still = next(x for x in client.get(API, headers=root).json()["keys"] if x["id"] == good["id"])
    assert still["is_active"] and still["masked"].endswith(KEY1[-4:])
    assert client.delete(f"{API}/{good['id']}", headers=root).status_code == 409   # active keys cannot be deleted
    client.post(f"{API}/{good['id']}/deactivate", headers=root)
    assert client.delete(f"{API}/{good['id']}", headers=root).status_code == 204


def test_validation_never_echoes_secret(client, root):
    r = client.post(API, headers=root, json={"api_key": "short secret with spaces"})
    assert r.status_code == 422 and "short secret" not in r.text
    r = client.post(API, headers=root, json={"api_key": 12345})          # pydantic type error path
    assert r.status_code == 422 and "12345" not in r.text and "input" not in r.text
    r = client.post(API, headers=root, json={"api_key": KEY1, "bogus": KEY2})  # extra field
    assert r.status_code == 422 and KEY2 not in r.text
    assert client.post(API, headers=root, json={"api_key": KEY1, "provider": "nope"}).status_code == 422


def test_encrypted_at_rest_and_never_in_responses_history_or_logs(client, root, caplog):
    caplog.set_level(logging.DEBUG)
    r = client.post(API, headers=root, json={"label": "secret-test", "api_key": KEY2, "activate": True})
    assert r.status_code == 201
    kid = r.json()["id"]
    client.post(f"{API}/{kid}/test", headers=root)
    bodies = [client.get(API, headers=root).text, client.get(API + "/history", headers=root).text, r.text]
    with SessionLocal() as db:
        row = db.get(ApiKey, kid)
        assert KEY2 not in row.ciphertext and secrets.decrypt(row.ciphertext) == KEY2
        raw = db.execute(text("select ciphertext from api_keys where id=:i"), {"i": kid}).scalar()
        assert KEY2 not in raw
        dump = " ".join(f"{a.action} {a.detail}" for a in db.scalars(select(AuditLog))) + " ".join(e.detail for e in db.scalars(select(ApiKeyEvent)))
    assert all(KEY2 not in b and "ciphertext" not in b for b in bodies) and KEY2 not in dump
    assert KEY2 not in caplog.text
    # redaction safety net
    logging.getLogger("t").warning("boom x-goog-api-key: %s", KEY2)
    assert KEY2 not in secrets.redact(f"x-goog-api-key: {KEY2} and {KEY1}")


def test_history_and_audit_trail(client, root):
    h = client.get(API + "/history", headers=root).json()
    acts = {e["action"] for e in h}
    assert {"create", "activate", "deactivate", "delete"} <= acts and all(e["actor"] == "keyadmin@test.io" for e in h)
    with SessionLocal() as db:
        assert db.scalar(select(AuditLog).where(AuditLog.action == "admin.apikey.activate")) is not None


def test_model_change_applies_live_and_is_validated(client, root, fake_google, monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "google")
    client.post(API, headers=root, json={"api_key": KEY1, "activate": True})
    assert client.put(API + "/model", headers=root, json={"model": "gemini-2.5-pro"}).status_code == 200
    llm.llm_complete("s", "p")
    assert fake_google["generate"][-1][1].endswith("/models/gemini-2.5-pro:generateContent")
    assert client.get(API, headers=root).json()["effective"]["model"] == "gemini-2.5-pro"
    r = client.put(API + "/model", headers=root, json={"model": "nonexistent-model"})
    assert r.status_code == 422 and "not found" in r.text
    assert client.put(API + "/model", headers=root, json={"model": "bad model/../x"}).status_code == 422
    assert client.get(API, headers=root).json()["effective"]["model"] == "gemini-2.5-pro"   # unchanged after failures
    assert any(e["action"] == "model_changed" for e in client.get(API + "/history", headers=root).json())
    client.put(API + "/model", headers=root, json={"model": "gemini-2.0-flash"})


def test_cross_instance_pickup_and_db_enforced_single_active(client, root):
    """A second 'instance' has its own cache: it sees a DB change once its short TTL expires."""
    k = client.post(API, headers=root, json={"api_key": KEY1, "activate": True}).json()
    ai_config.invalidate()
    assert ai_config.resolve("google").key_id == k["id"]
    # simulate another instance deactivating the key directly in the DB
    with SessionLocal() as db:
        db.get(ApiKey, k["id"]).is_active = False
        db.commit()
    assert ai_config.resolve("google").key_id == k["id"]          # still cached locally ...
    ai_config._cache["google"] = (ai_config._cache["google"][0] - ai_config._TTL - 1, ai_config._cache["google"][1])   # ... until the TTL passes
    assert ai_config.resolve("google").key_id is None
    # the DB itself refuses two active keys for one provider
    k2 = client.post(API, headers=root, json={"api_key": KEY2}).json()
    with SessionLocal() as db:
        db.get(ApiKey, k["id"]).is_active = True
        db.get(ApiKey, k2["id"]).is_active = True
        with pytest.raises(Exception):  # noqa: B017
            db.commit()
        db.rollback()


def test_unreadable_admin_key_falls_back_to_env(client, root, monkeypatch):
    monkeypatch.setattr(settings, "google_api_key", "AIzaFALLBACK_0123456789abcdefghijklmnop")
    k = client.post(API, headers=root, json={"api_key": KEY1, "activate": True}).json()
    with SessionLocal() as db:
        db.get(ApiKey, k["id"]).ciphertext = "garbage"
        db.commit()
    ai_config.invalidate()
    r = ai_config.resolve("google")
    assert r.source == "env" and r.key.startswith("AIzaFALLBACK")
    assert "garbage" not in client.get(API, headers=root).text


def test_encryption_master_key(monkeypatch):
    from cryptography.fernet import Fernet

    k1, k2 = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "api_key_encryption_key", k1)
    tok = secrets.encrypt("hello-secret-value-123")
    monkeypatch.setattr(settings, "api_key_encryption_key", f"{k2},{k1}")   # rotation: new key first, old still decrypts
    assert secrets.decrypt(tok) == "hello-secret-value-123"
    monkeypatch.setattr(settings, "api_key_encryption_key", k2)
    with pytest.raises(secrets.SecretsError):
        secrets.decrypt(tok)
    monkeypatch.setattr(settings, "api_key_encryption_key", "not-a-fernet-key")
    with pytest.raises(secrets.SecretsError) as e:
        secrets.encrypt("x")
    assert "not-a-fernet-key" not in str(e.value)
    monkeypatch.setattr(settings, "api_key_encryption_key", "")
    monkeypatch.setattr(settings, "app_env", "production")
    with pytest.raises(secrets.SecretsError):
        secrets.encrypt("x")


def test_key_pasted_into_model_setting_is_never_used_or_shown(client, root, monkeypatch, caplog):
    leaked = "AQ.Ab8RN6Jz5mxFAKEFAKEFAKEFAKE_0123456789abcdef"
    monkeypatch.setattr(settings, "llm_provider", "google")
    monkeypatch.setattr(settings, "llm_model", leaked)
    from backend.app.services import appconfig
    appconfig._cache.clear()
    with SessionLocal() as db:
        appconfig.put(db, "ai", {"model": "", "provider": ""})
    rt = llm.ai_runtime()
    assert rt["model"] == "gemini-2.0-flash"
    assert leaked not in client.get(API, headers=root).text and leaked not in caplog.text
    r = client.put(API + "/model", headers=root, json={"model": leaked, "verify": False})
    assert r.status_code == 422 and leaked not in r.text
