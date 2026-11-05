"""Promote (or demote with --revoke) an existing account to super_admin.

    uv run python -m scripts.make_super_admin you@example.com
"""
import sys

from sqlalchemy import func, select

from backend.app.db.init_db import init_db
from backend.app.db.session import SessionLocal
from backend.app.models import User

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        sys.exit(__doc__)
    init_db()
    with SessionLocal() as db:
        u = db.scalar(select(User).where(func.lower(User.email) == args[0].lower()))
        if not u:
            sys.exit(f"No user with email {args[0]}")
        u.role = "analyst" if "--revoke" in sys.argv else "super_admin"
        db.commit()
        print(f"{u.email} is now {u.role}")
