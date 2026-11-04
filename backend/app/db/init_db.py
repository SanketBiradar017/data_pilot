from backend.app.config import settings
from backend.app.db.base import Base
from backend.app.db.session import engine


def init_db() -> None:
    import backend.app.models  # noqa: F401  (register tables)

    settings.ensure_dirs()
    Base.metadata.create_all(bind=engine)
