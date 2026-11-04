"""Create all database tables (also done automatically on API startup)."""
from backend.app.db.init_db import init_db

if __name__ == "__main__":
    init_db()
    print("Database initialised")
