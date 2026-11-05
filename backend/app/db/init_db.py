import logging

from sqlalchemy import inspect, text

from backend.app.config import settings
from backend.app.db.base import Base
from backend.app.db.session import engine

log = logging.getLogger("datapilot")

# create_all never alters existing tables, so columns added after first release are patched in here.
_ADDED_COLUMNS = {
    "users": [
        ("status", "VARCHAR(20) NOT NULL DEFAULT 'active'"),
        ("last_login_at", "TIMESTAMP"),
        ("email_verified", "BOOLEAN NOT NULL DEFAULT TRUE"),
    ],
    "llm_usage": [("api_key_id", "INTEGER")],
}


def _migrate() -> None:
    insp = inspect(engine)
    for table, cols in _ADDED_COLUMNS.items():
        if not insp.has_table(table):
            continue
        have = {c["name"] for c in insp.get_columns(table)}
        for name, ddl in cols:
            if name not in have:
                with engine.begin() as c:
                    c.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                log.info("migrated: %s.%s added", table, name)


def init_db() -> None:
    import backend.app.models  # noqa: F401  (register tables)

    settings.ensure_dirs()
    Base.metadata.create_all(bind=engine)
    _migrate()
