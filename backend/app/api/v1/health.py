from fastapi import APIRouter
from sqlalchemy import text

from backend.app.db.session import engine

router = APIRouter()


@router.get("")
def health():
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
        db = "ok"
    except Exception as e:
        db = f"error: {type(e).__name__}"
    return {"status": "ok" if db == "ok" else "degraded", "database": db}
