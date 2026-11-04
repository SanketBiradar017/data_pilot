# API (`/api/v1`, interactive docs at `/docs`)

All endpoints except `health` and `auth/*` require `Authorization: Bearer <token>`.

| Method & path | Purpose |
|---|---|
| `POST /auth/register`, `POST /auth/login`, `GET /auth/me` | Accounts / JWT |
| `POST /datasets` (multipart `file`) | Ingest file → profile + quality |
| `POST /datasets/from-sql` | Import table/SELECT from an external SQL DB |
| `POST /datasets/load-sample` | Import the bundled demo dataset |
| `GET /datasets`, `GET /datasets/{id}`, `GET /datasets/{id}/preview?limit&offset`, `GET /datasets/{id}/download`, `DELETE /datasets/{id}` | Manage sources |
| `POST /datasets/{id}/clean` `{op, column?, strategy?}` | Cleaning ops: `infer_types trim_whitespace standardize_case drop_duplicates fill_missing drop_missing_rows drop_column clip_outliers auto_clean` |
| `GET /sql/schema`, `POST /sql/query`, `POST /sql/generate` | SQL editor backend (read-only) |
| `GET/POST/DELETE /sql/saved` | Saved queries |
| `POST /analyses` `{question, dataset_ids}` → 202 | Start agent run (poll `GET /analyses/{id}`) |
| `GET /analyses`, `GET /analyses/{id}`, `DELETE /analyses/{id}` | History, trace, result |
| `GET/POST/DELETE /chat/conversations…`, `POST /chat/conversations/{id}/messages` | Chat (runs the workflow synchronously) |
| `POST /reports` `{analysis_id, format: pdf|xlsx}`, `GET /reports`, `GET /reports/{id}/download`, `DELETE` | Exports |
| `GET /advanced/fields/{dataset_id}` | Column roles + distinct values for the pickers |
| `POST /advanced/pivot`, `POST /advanced/pivot/export` `{format: csv|xlsx}` | Pivot engine and file export |
| `POST /advanced/regression` | OLS fit, metrics, diagnostics, chart data |
| `POST /advanced/hypothesis` `{test: t_independent|t_welch|t_paired|anova|chi_square}` | Statistical tests |
| `POST /advanced/pareto` | Pareto / ABC classification |
| `POST /advanced/variance` `{mode: target|period}` | Variance analysis |
| `GET /intelligence/roles/{dataset_id}` | Detected revenue / cost / quantity / date / customer columns |
| `POST /intelligence/root-cause` `{question?, metric?, grain, current?, previous?}` | Root cause with story, facts and verification |
| `GET /intelligence/discover/{dataset_id}` | Automated insights (cached per dataset version; `?refresh=true`) |
| `POST /intelligence/executive-summary`, `POST /intelligence/executive-summary/export` | Management summary and PDF / Excel export |
| `POST /intelligence/scenario` `{scenarios[], revenue?, cost?, quantity?, baseline_scope}` | What-if simulation (estimates) |
| `GET /dashboard/overview` | KPIs for the overview page |
| `GET/PUT /settings` | Preferences and system info |

Errors are `{"detail": "..."}` with 400/401/404/409/413/422 as appropriate.
