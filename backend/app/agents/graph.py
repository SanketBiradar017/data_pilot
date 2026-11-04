"""LangGraph multi-agent workflow.

planner → ingestion → profiler → cleaning → {sql | analytics | research | visualization}* → validation → report
Conditional edges: skip unplanned agents, abort on missing data, retry SQL once if validation fails.
"""
from collections.abc import Callable

from langgraph.graph import END, START, StateGraph

from backend.app.agents.analysis_agents import (
    analytics_node,
    research_node,
    sql_node,
    visualization_node,
)
from backend.app.agents.common import agent
from backend.app.agents.data_agents import cleaning_node, ingestion_node, profiler_node
from backend.app.agents.intelligence_agents import (
    business_node,
    discovery_node,
    executive_node,
    forecast_node,
    quality_node,
    root_cause_node,
    scenario_node,
    story_node,
)
from backend.app.agents.output_agents import report_node, validation_node
from backend.app.agents.planner import ANALYSIS_STEPS, planner_node
from backend.app.agents.state import AnalystState, RunContext

NODES = {"planner": planner_node, "ingestion": ingestion_node, "profiler": profiler_node,
         "cleaning": cleaning_node, "sql": sql_node, "analytics": analytics_node, "research": research_node,
         "visualization": visualization_node, "validation": validation_node, "report": report_node,
         "root_cause": root_cause_node, "scenario": scenario_node, "discovery": discovery_node, "executive": executive_node, "quality": quality_node, "forecast": forecast_node, "business": business_node, "story": story_node}


def next_analysis_step(state: AnalystState) -> str:
    done = set(state.get("completed", []))
    for step in ANALYSIS_STEPS:
        if step in state.get("plan", {}).get("steps", []) and step not in done:
            return step
    return "validation"


def build_graph(ctx: RunContext):
    g = StateGraph(AnalystState)
    for name, fn in NODES.items():
        g.add_node(name, agent(name, ctx)(fn))

    g.add_edge(START, "planner")
    g.add_edge("planner", "ingestion")
    g.add_conditional_edges(
        "ingestion", lambda s: "abort" if s.get("errors") else "profiler", {"profiler": "profiler", "abort": "report"})
    g.add_edge("profiler", "cleaning")
    targets = {s: s for s in ANALYSIS_STEPS} | {"validation": "validation"}
    for src in ("cleaning", *ANALYSIS_STEPS):
        g.add_conditional_edges(src, next_analysis_step, targets)

    def after_validation(s: AnalystState) -> str:
        return "sql" if s.get("validation", {}).get("retry") else "story"

    g.add_conditional_edges("validation", after_validation, {"sql": "sql", "story": "story"})
    g.add_edge("story", "report")
    g.add_edge("report", END)
    return g.compile()


def run_workflow(ctx: RunContext, on_event: Callable[[dict, dict], None] | None = None) -> dict:
    """Execute the graph, streaming per-agent events; returns the final merged state."""
    graph = build_graph(ctx)
    state: AnalystState = {"question": ctx.question, "completed": [], "trace": [], "errors": [], "retries": 0,
                           "insights": [], "facts": [], "statements": [], "verification": {}}
    for update in graph.stream(state, stream_mode="updates", config={"recursion_limit": 40}):
        for node, out in update.items():
            for k, v in out.items():
                if k in ("completed", "trace", "errors", "facts", "statements"):
                    state[k] = state.get(k, []) + v
                elif k == "verification":
                    state[k] = {**state.get(k, {}), **v}
                else:
                    state[k] = v
            if on_event:
                on_event(out.get("trace", [{}])[0], state)
    state["status"] = "failed" if "ingestion" not in state["completed"] or any(
        t["status"] == "failed" and t["agent"] in ("ingestion", "report") for t in state["trace"]) else "completed"
    return state
