from contextvars import ContextVar
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.db.session import SessionLocal
from backend.app.models import User

_bearer = HTTPBearer(auto_error=False)
ALGORITHM = "HS256"
SUPER_ADMIN = "super_admin"

# Who is making the current request / background job (for usage attribution).
current_user_id: ContextVar[int | None] = ContextVar("current_user_id", default=None)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode()[:72], hashed.encode())
    except ValueError:
        return False


def create_access_token(user_id: int) -> str:
    exp = datetime.now(UTC) + timedelta(minutes=settings.access_token_minutes)
    return jwt.encode({"sub": str(user_id), "exp": exp}, settings.secret_key, algorithm=ALGORITHM)


def create_purpose_token(user_id: int, purpose: str, hours: int = 48) -> str:
    exp = datetime.now(UTC) + timedelta(hours=hours)
    return jwt.encode({"sub": str(user_id), "exp": exp, "purpose": purpose}, settings.secret_key, algorithm=ALGORITHM)


def decode_purpose_token(token: str, purpose: str) -> int | None:
    try:
        p = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        return int(p["sub"]) if p.get("purpose") == purpose else None
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED, "Not authenticated", headers={"WWW-Authenticate": "Bearer"}
    )
    if creds is None:
        raise unauthorized
    try:
        payload = jwt.decode(creds.credentials, settings.secret_key, algorithms=[ALGORITHM])
        if payload.get("purpose"):
            raise unauthorized
        user = db.get(User, int(payload["sub"]))
    except (jwt.PyJWTError, KeyError, ValueError):
        raise unauthorized
    if user is None:
        raise unauthorized
    if user.status != "active":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account suspended")
    request.state.user_id = user.id
    current_user_id.set(user.id)
    return user


def require_super_admin(user: User = Depends(get_current_user)) -> User:
    """Role is read from the database on every request (never trusted from the token),
    so demotion/suspension takes effect immediately."""
    if user.role != SUPER_ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Super admin access required")
    return user
