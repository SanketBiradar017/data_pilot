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

## Admin-managed API keys
- Super Admin > **API Keys** stores provider keys in the `api_keys` table as Fernet ciphertext. The master key is `API_KEY_ENCRYPTION_KEY` (environment only; required in production, shared by all instances, comma-separated for rotation).
- Responses only ever carry a masked value (last 4 characters). Key material is never written to logs (a redaction filter is a second line of defence), audit entries, history rows, error messages or validation errors (the 422 handler strips echoed input).
- Resolution order: active admin key → `GOOGLE_API_KEY` / `ANTHROPIC_API_KEY` from the environment. Keys are tested against the provider before activation; a failing replacement never displaces the live key. Only one key per provider can be active (database-enforced).
- Every request resolves the key fresh (5-second per-instance cache); a change made on any instance reaches the others within that window without a restart. Changes are recorded in `api_key_events` and `audit_logs`.
