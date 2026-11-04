# Security

* **Auth:** bcrypt password hashes, HS256 JWTs. Production refuses the default `SECRET_KEY`.
* **Isolation:** every dataset, analysis, conversation, report and saved query is scoped to its owner
  (cross-tenant access returns 404; covered by tests).
* **SQL sandbox:** single statement, `SELECT`/`WITH` only, keyword and function deny-list (no file/network readers),
  DuckDB `enable_external_access=false`, row cap and wall-clock timeout. External-DB imports use the same validator.
  LLM-generated SQL passes through the same checks.
* **Uploads:** extension allow-list, size cap, filename sanitised, files stored under random names, parse failures
  surface as 422 (never a 500), duplicates detected by SHA-256.
* **HTTP:** CORS allow-list, `nosniff` / `X-Frame-Options`, request-id logging, internal errors are logged and returned generically.
* **Audit:** login, upload/delete/clean, SQL runs, analyses and reports are written to `audit_logs`.
* **Not included (add before exposing publicly):** rate limiting, password reset / email verification, TLS termination
  (use a reverse proxy), secret rotation, malware scanning of uploads.
* **External DB URLs** typed in the UI contain credentials and are not stored — only the imported snapshot is.
