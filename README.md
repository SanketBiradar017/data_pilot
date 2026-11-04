# DataPilot AI

Multi-agent **data analyst**: upload data, ask questions in plain English, get answers that are
backed by SQL, statistics and charts — and **verified** before you see them.

- **Backend:** Python 3.11, FastAPI, SQLAlchemy, **PostgreSQL** (SQLite for quick local dev), DuckDB, pandas/SciPy
- **Agents:** LangGraph (`planner → ingestion → profiler → cleaning → sql | analytics | research | visualization → validation → report`)
- **Frontend:** React 18, Vite, Tailwind CSS, Recharts, TanStack Query

## Features

| Area | What works |
|---|---|
| Ingestion | CSV, TSV, Excel, JSON/JSONL, Parquet, SQLite files, **external SQL databases** (table or SELECT), PDF, DOCX, TXT, Markdown |
| Profiling & quality | Per-column profile + histograms, 0–100 quality score (completeness/uniqueness/validity/consistency), concrete fixable issues |
| Cleaning | Logged one-click ops: type inference, trim, case standardisation, dedupe, imputation, outlier clipping, auto-clean |
| Analysis | Descriptive stats, Spearman correlations, robust (MAD) anomaly detection, Theil–Sen trends + 3-period projection, ANOVA/Welch group tests |
| SQL | Natural-language → SQL (heuristic, optional LLM), read-only DuckDB editor, cross-dataset joins, saved queries, auto charts |
| Pivot tables | Drag-and-drop rows / columns / values / filters, SUM·COUNT·AVG·MIN·MAX, multi-field grouping, totals, chart view, CSV and Excel export |
| Regression | Simple & multiple OLS (statsmodels): coefficients, p-values, confidence intervals, R²/adj. R², F-test, holdout validation, backward feature selection, residual & influence diagnostics, VIF |
| Hypothesis tests | Independent / Welch / paired t-test, ANOVA, chi-square, with CI, effect size, assumption checks and plain-English interpretation |
| Pareto & ABC | 80/20 analysis, cumulative %, configurable A/B/C classes, Pareto chart, CSV export |
| Variance | Actual vs target (column or fixed total), current vs previous period (week/month/quarter/year), revenue / cost / profit with correct favourable direction, tolerance band |
| Root cause analysis | "Why did revenue decrease in July?" → what happened, dimension / 2-way-cell contributions, volume · mix · price decomposition (reconciles exactly), seasonality check, ranked factors, SQL evidence, actions |
| Insight discovery | Scans a dataset unprompted: growth/decline, high performers, declining groups, customer behaviour (churn risk, whales), correlations, skewed distributions, concentration risk |
| Storytelling | Business prose where **every sentence cites verified calculations** (numbered footnotes with SQL / formula); unverified sentences are dropped |
| Executive summary | KPIs vs previous period, performance narrative, risks, opportunities, prioritised recommendations, evidence table; PDF / Excel export |
| Scenarios | "What if prices rise 10%?" with price, volume, elasticity, cost, fixed-cost share and segment assumptions; multi-scenario comparison; sensitivity curve; **estimates are always labelled and kept separate from observed data** |
| Documents | TF-IDF retrieval with verbatim, cited passages |
| Grounding | Every numeric claim is **re-computed independently** from raw data; unsupported claims are dropped; failed SQL is retried once |
| Reports | PDF (charts, tables, citations) and Excel (summary, result, SQL, chart data, quality) downloads |
| Autonomous Data Analyst | **Analyse my data** (button on every table): quality checks, statistics and anomalies, insight discovery, business questions (top region, loss-making products, profit by category, most valuable customers, discounts vs profit), root cause and an executive summary, with charts and recommended actions. Every number is re-computed with SQL |
| Chat | Ask in plain language. Filters (“in North”, “March 2024”, “revenue above 1000”), follow-ups (“what about South?”), forecasts, root-cause and what-if. Every answer shows how the question was understood, the SQL, evidence and an agent trace. Numbers are re-computed in pandas; a column or value the data lacks gets a clear “can't answer”, never a substitute |
| Platform | JWT auth, per-user data isolation, audit log, request logging, upload validation, read-only SQL sandbox |

## Quick start (local)

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), Node 20+.

```bash
cp .env.example .env            # defaults use SQLite; see "Configuration" for PostgreSQL
make install                    # uv sync + npm install
make seed                       # optional: regenerate demo data in data/samples
make run                        # API  → http://127.0.0.1:8000  (docs at /docs)
make web                        # UI   → http://localhost:5173  (second terminal)
```

Open the UI, **create an account** (the first account becomes admin), then *Data sources → Load demo dataset*
(or upload your own file) and go to **Analysis workspace** or **Ask your data**.

### Production build (single process)

```bash
make build                      # frontend/dist
uv run uvicorn backend.app.main:app --host 0.0.0.0 --port 8000   # serves API + UI
```

### Docker (PostgreSQL included)

```bash
echo "SECRET_KEY=$(openssl rand -hex 32)" >> .env
docker compose up --build       # → http://localhost:8000
```

## Configuration (`.env`)

| Variable | Default | Notes |
|---|---|---|
| `SECRET_KEY` | dev value | **Required in production** (`APP_ENV=production` refuses to start otherwise) |
| `DATABASE_URL` | SQLite file | PostgreSQL: `postgresql+psycopg://user:pw@host:5432/db` |
| `CORS_ORIGINS` | localhost:5173 | comma-separated or JSON list |
| `ALLOW_REGISTRATION` | `true` | set `false` after creating your accounts |
| `ACCESS_TOKEN_MINUTES` | `720` | JWT lifetime |
| `UPLOAD_DIRECTORY`, `PROCESSED_DIRECTORY`, `REPORT_DIRECTORY` | `./data/...`, `./storage/reports` | |
| `MAX_UPLOAD_MB` / `MAX_QUERY_ROWS` / `QUERY_TIMEOUT_SECONDS` | `100` / `10000` / `30` | |
| `LLM_PROVIDER` | `none` | `none`, `anthropic` or `google`; with `none` everything runs deterministically |
| `LLM_MODEL`, `LLM_TEMPERATURE`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY` | — | LLM is optional and only assists routing, SQL drafting and answer wording |
| `TEST_DATABASE_URL` | SQLite temp | tests only; point at PostgreSQL to run the suite there |

## Tests

```bash
make test                                                      # 50 tests: unit, integration, end-to-end (SQLite)
TEST_DATABASE_URL=postgresql+psycopg://… uv run pytest -q      # same suite on PostgreSQL
```

## Project layout

```
backend/app/
  agents/        LangGraph state, planner, data/analysis/output agents, graph (routing + retry)
  analytics/     profiling, quality, cleaning, statistics, nl2sql, sql_engine (safe DuckDB), charts, llm
  ingestion/     file/DB loaders
  services/      datasets, analysis runner, report rendering
  api/v1/        auth, datasets, sql, analyses, chat, reports, dashboard, settings, health
frontend/src/    pages/, components/ (ChartRenderer, AgentTimeline, AnalysisResult…), api client
backend/tests/   unit/ integration/ e2e/
docs/            architecture, API, security, deployment
```

## Known limitations

See [docs/architecture.md](docs/architecture.md#limitations). Notably: without an LLM key, natural-language
understanding is rule-based (it handles aggregations, top-N, group-by, trends and counts, not arbitrary
multi-step questions); analyses run in-process (no job queue); uploads are limited by memory (pandas).
