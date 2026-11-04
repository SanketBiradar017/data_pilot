# Architecture

```
React (Vite) ──/api/v1──▶ FastAPI ──▶ PostgreSQL / SQLite   users, datasets, analyses, reports, chat, audit
                            │
                            ├──▶ parquet files (data/processed)   cleaned tabular data
                            ├──▶ DuckDB (in-memory, per query)    read-only SQL over registered DataFrames
                            └──▶ LangGraph agent workflow
```

## Agent workflow (`backend/app/agents`)

State is a typed dict (`AnalystState`); heavy data (DataFrames, document text) lives in a `RunContext`
captured by the nodes, so the graph state stays JSON-serialisable and is persisted after every agent.

| Agent | Responsibility |
|---|---|
| Planner (+ conditional routing = orchestrator) | Classifies intent (rules, optionally refined by an LLM) and decides which analysis agents run |
| Data Ingestion | Verifies selected sources are loaded; aborts the run with a clear error if none |
| Resource Profiler | Column-level profiling of every table |
| Data Cleaning | Quality inspection; applies only value-preserving fixes (trim/case) in memory — destructive fixes are reported, never silent |
| SQL | NL → SQL, executes through the read-only sandbox |
| Analytics | EDA: trends, correlations, anomalies, group tests → insights, each with a machine-checkable claim |
| Research | TF-IDF retrieval over documents → verbatim citations |
| Visualization | Chart specs built from computed data only |
| Validation | Re-computes each claim from raw data by a different method; removes failures; requests one SQL retry on error/empty |
| Root Cause | Explains a metric change between two periods; exact decompositions; every number is a fact |
| Scenario | Parses "what if…" assumptions, simulates, labels results as ESTIMATES next to the verified observed baseline |
| Insight Discovery | Detects growth, decline, performers, customer behaviour, correlations, distributions, concentration |
| Executive Summary | Management KPIs, risks, opportunities, recommendations |
| Storytelling | Assembles cited, verified statements into the final narrative (optional LLM polish cannot add numbers) |
| Report | Final answer, KPIs, recommendations, evidence list |

Routing: `planner → ingestion →(abort→report) profiler → cleaning → [sql|analytics|root_cause|scenario|discovery|executive|research|visualization]* → validation →(retry→sql) story → report`.
An agent that raises is isolated: the trace marks it `failed` and the run continues with the remaining evidence.

Live status: the analysis runner (`services/analysis.py`) streams graph updates and writes the trace to the
`analyses` row after each agent; the UI polls `GET /analyses/{id}` and renders the timeline.

## Fact layer (`analytics/facts.py`)
Every number shown by the intelligence agents is a **fact**: a *base* fact carries the SQL that produces it and is re-executed in a sandboxed DuckDB; a *derived* fact names an operation (`diff`, `pct_change`, `share`, `volume_effect`, …) and is re-evaluated from its verified inputs. A statement is shown only if all facts it cites verified. Scenario outputs are derived facts flagged `estimate` and are never mixed with observed values.

## Grounding rules
* Insights are produced only from computed values; each carries `evidence.check`.
* `validation` recomputes: correlations via rank-correlation, group means/shares via groupby, trends via Spearman,
  SQL by re-execution, document snippets by verbatim search.
* Robust statistics are used (MAD, Theil–Sen, Spearman) so a single bad value cannot create or hide a finding.

## Limitations
* Without an LLM, NL→SQL is heuristic: single table, one aggregate, optional group-by / top-N / time grain.
  Use the SQL editor for anything more complex (joins across sources are supported there).
* Analyses run in a FastAPI background task, not a distributed queue; a server restart loses in-flight runs.
* Datasets are loaded fully in memory (pandas); designed for files up to a few hundred MB.
* Embedded-vector retrieval is TF-IDF, not neural embeddings.
* External-database import copies a snapshot (up to 100k rows); it is not a live connection.
* PDF reports render charts with matplotlib (static); interactive charts are in the web UI.
* Schema is created with `create_all` on startup; there are no Alembic migrations yet.
