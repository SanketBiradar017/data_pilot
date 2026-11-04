import re

from backend.app.agents.state import AnalystState, RunContext
from backend.app.analytics.llm import llm_complete
from backend.app.analytics.question import clarification, prepare

ANALYSIS_STEPS = ["sql", "analytics", "root_cause", "scenario", "forecast", "discovery", "executive", "business", "quality", "research", "visualization"]
AUTOPILOT = ["quality", "analytics", "discovery", "business", "root_cause", "executive", "visualization"]
SPECIAL = ("root_cause", "scenario", "forecast", "discovery", "executive", "quality")

_RULES = [
    ("autopilot", r"analy[sz]e (?:my|the|this|our) (?:data|dataset|file)|autonomous|full (?:analysis|investigation)|auto(?:matic)? analysis|investigate (?:my|the|this) (?:data|dataset)|analy[sz]e everything"),
    ("scenario", r"what if|what happens|scenario|simulate|suppose|assuming|if (?:we |our |the )?(?:product |selling )?(?:prices?|costs?|volume|demand|sales)"),
    ("forecast", r"forecast|predict|projection|project(?:ed|ion)s?\b|next (?:\d+ )?(?:day|week|month|quarter|year)s?\b|\bfuture\b|outlook|\d+ (?:day|week|month|quarter|year)s? (?:ahead|from now)"),
    ("executive", r"executive summary|management summary|board summary|summari[sz]e (?:the )?(?:business|performance)|how is (?:the )?business|overall performance"),
    ("root_cause", r"\bwhy\b|root cause|what (?:caused|drove|led to|explains)|reason (?:for|behind)|how come"),
    ("quality", r"data quality|quality of|missing (?:values?|data)|duplicate|null values|how clean|dirty data|messy data"),
    ("discovery", r"discover|interesting|anything (?:unusual|notable|important)|what should i know|key insights?|surpris|find patterns|hidden"),
        ("profile", r"profile|describe|overview|schema|structure|columns|summar"),
    ("analytics", r"correlat|relationship|anomal|outlier|trend|forecast|predict|driver|insight|statistic|signific|"
                  r"analy[sz]e|why|pattern|compare|comparison|differ|growth|decline|seasonal"),
    ("visualization", r"chart|plot|graph|visual|distribution|histogram|heatmap|dashboard"),
    ("research", r"document|policy|pdf|according to|contract|report says|text|mention|said|handbook"),
    ("sql", r"how many|count|total|sum|average|avg|mean|top \d*|bottom|highest|lowest|max|min|per |by |each|"
            r"list|show|median|most|least|which|what is"),
]


def plan_question(question: str, ctx: RunContext) -> dict:
    q = question.lower()
    intents = [name for name, rx in _RULES if re.search(rx, q)]
    has_tables, has_docs = bool(ctx.tables), bool(ctx.documents)
    steps: list[str] = []

    if has_tables and "autopilot" in intents:
        from backend.app.analytics.roles import detect_roles

        r = detect_roles(ctx.tables[ctx.primary])
        steps = [s for s in AUTOPILOT if s != "root_cause" or (r["date"] and r["revenue"])]
        return {"intents": intents, "steps": steps, "rationale": "Autonomous analysis: quality, statistics, insights, business questions, root cause, executive summary."}
    special = [x for x in SPECIAL if x in intents] if has_tables else []
    if "root_cause" in special and "scenario" in special:
        special.remove("root_cause")
    if "forecast" in special and ("scenario" in special or "root_cause" in special):
        special.remove("forecast")  # "what if prices rise next year" is a scenario; "why did it fall" explains the past
    if special:
        steps = list(special)
    elif has_tables and ("sql" in intents or not intents):
        steps.append("sql")
    if has_tables and "analytics" in intents and not special:
        steps.append("analytics")
    if has_docs and ("research" in intents or not has_tables):
        steps.append("research")
    if has_tables and ("visualization" in intents or "analytics" in intents or "sql" in steps or special):
        steps.append("visualization")
    if has_tables and not any(s in steps for s in ("sql", "analytics", *SPECIAL)):
        steps = ["analytics", "visualization"]  # open-ended request -> full EDA
    rationale = f"Detected intents: {', '.join(intents) or 'general exploration'}."

    out = llm_complete(
        "You route analytics questions. Reply with a comma-separated subset of: sql, analytics, research, "
        "visualization. No other text.",
        f"Question: {question}\nTables: {list(ctx.tables)}\nDocuments: {list(ctx.documents)}",
        max_tokens=30,
    )
    if out and not special:
        picked = [s.strip() for s in out.lower().split(",") if s.strip() in ANALYSIS_STEPS]
        picked = [s for s in picked if (s != "research" or has_docs) and (s in ("research",) or has_tables)]
        if picked:
            steps, rationale = [s for s in ANALYSIS_STEPS if s in picked], rationale + " (LLM-refined routing)"
    return {"intents": intents, "steps": steps, "rationale": rationale}


def planner_node(state: AnalystState, ctx: RunContext):
    plan = plan_question(state["question"], ctx)
    out: dict = {"plan": plan}
    note = ""
    if ctx.primary and "research" not in plan["steps"]:
        df = ctx.tables[ctx.primary]
        others = [c for t, d in ctx.tables.items() if t != ctx.primary for c in d.columns]
        prep = prepare(state["question"], df, others)
        ctx.extra["prep"] = prep
        out["notes"] = prep["notes"]
        if prep["missing"] or prep["unknown_values"]:  # never answer a different question than the one asked
            out["clarification"] = clarification(prep, df)
            plan["steps"] = []
            note = " Stopped: " + ", ".join(prep["missing"] + prep["unknown_values"]) + " not found in the data."
    plan["pipeline"] = ["planner", "ingestion", "profiler", "cleaning", *plan["steps"], "validation", "story", "report"]
    return out, f"Plan: {' → '.join(plan['steps']) or 'none'}. {plan['rationale']}{note}"
