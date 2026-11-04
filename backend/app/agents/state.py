import operator
from dataclasses import dataclass, field
from typing import Annotated, Any, TypedDict

import pandas as pd


def _merge(a: dict | None, b: dict | None) -> dict:
    return {**(a or {}), **(b or {})}


class AnalystState(TypedDict, total=False):
    question: str
    plan: dict                       # {"steps": [...], "intents": [...], "rationale": str}
    completed: Annotated[list[str], operator.add]
    trace: Annotated[list[dict], operator.add]   # live agent events
    errors: Annotated[list[str], operator.add]
    retries: int
    profile: dict
    quality: dict
    cleaning: dict
    sql: dict                        # {sql, rationale, columns, rows, row_count, source, error}
    analytics: dict                  # EDA results
    research: dict                   # {citations: [...]}
    charts: list[dict]
    insights: list[dict]             # each carries evidence + (after validation) verified flag
    validation: dict
    answer: str
    report: dict                     # structured report payload
    status: str
    # intelligence agents
    facts: Annotated[list[dict], operator.add]          # verified-number registry shared by all agents
    statements: Annotated[list[dict], operator.add]     # story sentences, each citing fact ids
    verification: Annotated[dict, _merge]               # fact id -> {verified, detail}; merged across agents
    root_cause: dict
    scenario: dict
    discovery: dict
    executive: dict
    story: dict
    quality_report: dict
    forecast: dict
    business: dict
    clarification: dict              # set when the question names something the data does not have
    notes: list[str]                 # how the question was read (typos repaired, synonyms, ignored phrases)
    interpretation: str              # one sentence: what was actually computed


@dataclass
class RunContext:
    """Heavy, non-serialisable data shared by agents (kept out of graph state)."""

    question: str
    tables: dict[str, pd.DataFrame] = field(default_factory=dict)
    table_labels: dict[str, str] = field(default_factory=dict)  # table_name -> dataset display name
    documents: dict[str, str] = field(default_factory=dict)     # dataset name -> text
    cleaned: dict[str, pd.DataFrame] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def primary(self) -> str | None:
        return next(iter(self.tables), None)
