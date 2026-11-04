import functools
import logging
import time
from collections.abc import Callable

from backend.app.agents.state import AnalystState, RunContext
from backend.app.analytics.utils import plain

log = logging.getLogger("datapilot.agents")


def fmt(v) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, int):
        return f"{v:,}"
    if isinstance(v, float):
        a = abs(v)
        if a >= 1000:
            return f"{v:,.0f}"
        if a >= 100:
            return f"{v:,.1f}"
        return f"{v:,.2f}" if a >= 0.01 or a == 0 else plain(v, 3)
    return str(v)


AGENT_LABELS = {
    "planner": "Planner Agent", "ingestion": "Data Ingestion Agent", "profiler": "Resource Profiler Agent",
    "cleaning": "Data Cleaning Agent", "sql": "SQL Agent", "analytics": "Analytics Agent",
    "research": "Research Agent", "visualization": "Visualization Agent",
    "validation": "Validation Agent", "report": "Report Generation Agent",
    "root_cause": "Root Cause Agent", "scenario": "Scenario Agent", "discovery": "Insight Discovery Agent", "executive": "Executive Summary Agent", "story": "Storytelling Agent", "quality": "Data Quality Agent", "forecast": "Forecast Agent", "business": "Business Insight Agent",
}


def agent(name: str, ctx: RunContext, on_event: Callable[[dict], None] | None = None):
    """Wrap an agent body `fn(state, ctx) -> (updates, summary)` with timing, tracing and error isolation."""

    def deco(fn):
        @functools.wraps(fn)
        def node(state: AnalystState) -> dict:
            t0 = time.perf_counter()
            status, summary, updates = "completed", "", {}
            try:
                updates, summary = fn(state, ctx)
            except Exception as e:  # an agent failing must not kill the whole run
                log.exception("agent %s failed", name)
                status, summary = "failed", f"{type(e).__name__}: {e}"
                updates = {"errors": [f"{AGENT_LABELS[name]}: {e}"]}
            event = {"agent": name, "label": AGENT_LABELS[name], "status": status, "summary": summary,
                     "duration_ms": round((time.perf_counter() - t0) * 1000, 1)}
            out = {**updates, "completed": [name], "trace": [event]}
            return out

        return node

    return deco
