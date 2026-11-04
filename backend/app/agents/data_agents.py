
from backend.app.agents.state import AnalystState, RunContext
from backend.app.analytics.profiling import profile_dataframe
from backend.app.analytics.quality import quality_report


def ingestion_node(state: AnalystState, ctx: RunContext):
    if not ctx.tables and not ctx.documents:
        raise ValueError("No data sources available. Upload or select a dataset first.")
    rows = sum(len(d) for d in ctx.tables.values())
    return {}, (f"Loaded {len(ctx.tables)} table(s) ({rows:,} rows) and {len(ctx.documents)} document(s) "
                f"from storage; schemas verified")


def profiler_node(state: AnalystState, ctx: RunContext):
    profiles = {n: profile_dataframe(df) for n, df in ctx.tables.items()}
    primary = profiles.get(ctx.primary, {})
    summary = "No tabular data to profile"
    if primary:
        summary = (f"{ctx.primary}: {primary['rows']:,} rows × {primary['columns']} cols; "
                   f"{len(primary['numeric_columns'])} numeric, {len(primary['categorical_columns'])} categorical, "
                   f"{len(primary['datetime_columns'])} datetime")
    return {"profile": {"tables": profiles}}, summary


def cleaning_node(state: AnalystState, ctx: RunContext):
    """Inspects data quality and REPORTS issues. It never changes the data, so every number and SQL statement
    in an answer can be reproduced on the stored dataset (fix issues explicitly on the Data sources page)."""
    reports = {name: quality_report(df) for name, df in ctx.tables.items()}
    primary = reports.get(ctx.primary, {})
    issues = primary.get("issues", [])
    summary = (f"Quality score {primary.get('score', 'n/a')} ({len(issues)} issue(s) flagged; data analysed as stored, nothing altered)"
               if primary else "Nothing to clean")
    return {"quality": {"tables": reports}, "cleaning": {"applied": [], "flagged": [i["message"] for i in issues[:5]]}}, summary
