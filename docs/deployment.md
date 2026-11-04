# Deployment

1. Provision PostgreSQL 14+ and set `DATABASE_URL=postgresql+psycopg://…`.
2. Set `APP_ENV=production`, a random `SECRET_KEY`, `CORS_ORIGINS` (if the UI is on another origin), `ALLOW_REGISTRATION=false` after onboarding.
3. `docker compose up --build` (bundles Postgres) or build the image and run it with your own database.
4. Persist `data/` (uploads + processed parquet) and `storage/` (reports) on a volume.
5. Put a TLS-terminating reverse proxy in front; `GET /api/v1/health` is the health probe.
6. Run a single app process per volume, or move `data/` to shared storage before scaling horizontally.
