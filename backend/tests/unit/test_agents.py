import pandas as pd

from backend.app.agents.graph import run_workflow
from backend.app.agents.output_agents import verify
from backend.app.agents.planner import plan_question
from backend.app.agents.state import RunContext


def ctx_for(q, df, docs=None):
    c = RunContext(question=q, tables={"sales": df} if df is not None else {}, documents=docs or {})
    return c


def test_planner_routes(sales_df):
    assert plan_question("what is the total revenue by region", ctx_for("", sales_df))["steps"][0] == "sql"
    s = plan_question("find correlations and anomalies", ctx_for("", sales_df))["steps"]
    assert "analytics" in s and "sql" not in s
    s = plan_question("what does the policy say about discounts", ctx_for("", None, {"p": "text"}))["steps"]
    assert s == ["research"]


def test_workflow_runs_all_agents(sales_df):
    st = run_workflow(ctx_for("Analyze trends and anomalies in revenue", sales_df))
    assert st["status"] == "completed"
    done = [t["agent"] for t in st["trace"]]
    assert done[:4] == ["planner", "ingestion", "profiler", "cleaning"] and done[-3:] == ["validation", "story", "report"]
    assert all(t["status"] == "completed" for t in st["trace"])
    assert st["validation"]["total"] > 0 and st["validation"]["passed"] == st["validation"]["total"]
    assert st["report"]["charts"] and st["answer"]


def test_workflow_fails_without_data():
    st = run_workflow(ctx_for("hi", None))
    assert st["status"] == "failed" and "No data sources" in st["answer"]


def test_research_citations_are_verbatim():
    doc = "Discount Policy\n\nSales reps may grant discounts of up to 10% without approval from management.\n\nReturns\n\nElectronics may be returned within 30 days of delivery by customers."
    st = run_workflow(ctx_for("What discount can sales reps grant without approval?", None, {"policy": doc}))
    assert st["research"]["citations"][0]["source"] == "policy"
    assert "10%" in st["research"]["citations"][0]["snippet"]
    assert st["validation"]["passed"] == st["validation"]["total"] >= 1


def test_validation_catches_false_claim(sales_df):
    c = ctx_for("", sales_df)
    ok, _ = verify({"fn": "corr", "a": "units", "b": "revenue", "value": -0.9}, c)
    assert not ok
    ok, _ = verify({"fn": "doc_contains", "source": "x", "snippet": "invented"}, c)
    assert not ok


def test_sql_failure_triggers_retry_and_recovers():
    df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    from backend.app.agents import analysis_agents

    calls = {"n": 0}
    orig = analysis_agents.generate_sql

    def bad(q, t, d, prep=None):
        calls["n"] += 1
        return {"sql": "SELECT nope FROM " + t, "rationale": "bad", "confidence": 0, "source": "test"}

    analysis_agents.generate_sql = bad
    try:
        st = run_workflow(ctx_for("how many rows", df))
    finally:
        analysis_agents.generate_sql = orig
    agents = [t["agent"] for t in st["trace"]]
    assert agents.count("sql") == 2 and agents.count("validation") == 2
    assert st["sql"]["row_count"] == 3 and st["status"] == "completed"
