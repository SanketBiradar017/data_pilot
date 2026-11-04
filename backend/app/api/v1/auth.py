from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.core.security import (
    create_access_token,
    get_current_user,
    get_db,
    hash_password,
    verify_password,
)
from backend.app.models import User
from backend.app.schemas.api import LoginIn, RegisterIn
from backend.app.services.datasets import audit

router = APIRouter()


def user_out(u: User) -> dict:
    return {"id": u.id, "email": u.email, "name": u.name, "role": u.role, "preferences": u.preferences or {}}


@router.post("/register", status_code=201)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    if not settings.allow_registration:
        raise HTTPException(403, "Registration is disabled")
    email = body.email.lower()
    if db.scalar(select(User).where(func.lower(User.email) == email)):
        raise HTTPException(409, "Email already registered")
    first = db.scalar(select(func.count(User.id))) == 0
    u = User(email=email, name=body.name or email.split("@")[0], password_hash=hash_password(body.password),
             role="admin" if first else "analyst", preferences={})
    db.add(u)
    db.commit()
    audit(db, u, "auth.register")
    return {"token": create_access_token(u.id), "user": user_out(u)}


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    u = db.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    if not u or not verify_password(body.password, u.password_hash):
        raise HTTPException(401, "Invalid email or password")
    audit(db, u, "auth.login")
    return {"token": create_access_token(u.id), "user": user_out(u)}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return user_out(user)
