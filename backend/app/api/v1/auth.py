from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.core.security import (
    create_access_token,
    create_purpose_token,
    decode_purpose_token,
    get_current_user,
    get_db,
    hash_password,
    verify_password,
)
from backend.app.models import User
from backend.app.schemas.api import LoginIn, RegisterIn
from backend.app.services import appconfig, mailer
from backend.app.services.datasets import audit

router = APIRouter()


def _notify(kind: str, u: User, **extra) -> None:
    """Templated email from admin-configured notification messages (best effort)."""
    plat, tpl = appconfig.get("platform"), appconfig.get("notifications")
    ctx = {"name": u.name or u.email, "app": plat["app_name"], "url": plat["public_url"], "support": plat["support_email"] or "support", **extra}
    mailer.send_mail(u.email, mailer.render(tpl[f"{kind}_subject"], **ctx), mailer.render(tpl[f"{kind}_body"], **ctx))


def user_out(u: User) -> dict:
    return {"id": u.id, "email": u.email, "name": u.name, "role": u.role, "preferences": u.preferences or {}}


@router.post("/register", status_code=201)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    if not settings.allow_registration or not appconfig.get("platform")["registration_open"]:
        raise HTTPException(403, "Registration is currently closed")
    email = body.email.lower()
    if db.scalar(select(User).where(func.lower(User.email) == email)):
        raise HTTPException(409, "Email already registered")
    first = db.scalar(select(func.count(User.id))) == 0
    u = User(email=email, name=body.name or email.split("@")[0], password_hash=hash_password(body.password),
             role="admin" if first else "analyst", preferences={})
    needs_verify = appconfig.get("platform")["email_verification"] and not first
    u.email_verified = not needs_verify
    db.add(u)
    db.commit()
    audit(db, u, "auth.register")
    if needs_verify:
        link = f'{appconfig.get("platform")["public_url"].rstrip("/")}/verify?token={create_purpose_token(u.id, "verify")}'
        _notify("verification", u, link=link)
        return {"verification_required": True, "email": u.email}
    _notify("welcome", u)
    return {"token": create_access_token(u.id), "user": user_out(u)}


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    u = db.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    if not u or not verify_password(body.password, u.password_hash):
        raise HTTPException(401, "Invalid email or password")
    if u.status != "active":
        raise HTTPException(403, "Account suspended")
    if not u.email_verified:
        raise HTTPException(403, "Please verify your email address first. Check your inbox for the link.")
    u.last_login_at = datetime.now(UTC)
    db.commit()
    audit(db, u, "auth.login")
    return {"token": create_access_token(u.id), "user": user_out(u)}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return user_out(user)


@router.post("/verify")
def verify_email(body: dict, db: Session = Depends(get_db)):
    uid = decode_purpose_token(str(body.get("token", "")), "verify")
    u = db.get(User, uid) if uid else None
    if not u:
        raise HTTPException(400, "Invalid or expired verification link")
    if not u.email_verified:
        u.email_verified = True
        db.commit()
        audit(db, u, "auth.verify_email")
    return {"verified": True}


@router.post("/resend-verification")
def resend_verification(body: LoginIn, db: Session = Depends(get_db)):
    """Requires the password so it can't be used to spam arbitrary addresses."""
    u = db.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    if u and not u.email_verified and verify_password(body.password, u.password_hash):
        link = f'{appconfig.get("platform")["public_url"].rstrip("/")}/verify?token={create_purpose_token(u.id, "verify")}'
        _notify("verification", u, link=link)
    return {"sent": True}
