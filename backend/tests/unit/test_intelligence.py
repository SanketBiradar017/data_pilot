import numpy as np
import pandas as pd
import pytest

from backend.app.agents.graph import run_workflow
from backend.app.agents.intelligence_agents import parse_scenario
from backend.app.agents.planner import plan_question
from backend.app.agents.state import RunContext
from backend.app.analytics import story
from backend.app.analytics.discovery import discover
from backend.app.analytics.executive import run_executive_summary
from backend.app.analytics.facts import FactBook, verify_facts
from backend.app.analytics.roles import detect_roles
from backend.app.analytics.root_cause import parse_question, run_root_cause
from backend.app.analytics.scenario import run_scenarios
from backend.app.analytics.utils import fmtnum
from backend.app.core.exceptions import AppError


def month_rows(month: str, combos: dict, price_cost: float = 0.6) -> pd.DataFrame:
    """combos: {(region, category): (qty_total, price)} spread evenly over every day of the month."""
    days = pd.date_range(f"{month}-01", periods=pd.Period(month).days_in_month)
    rows = []
    for (region, cat), (qty, price) in combos.items():
        for d in days:
            q = qty / len(days)
            rows.append({"order_date": d, "region": region, "category": cat, "quantity": q, "revenue": q * price, "cost": q * price * price_cost})
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def decline():
    june = {("North", "A"): (100, 10), ("North", "B"): (50, 20), ("South", "A"): (100, 10), ("South", "B"): (100, 20)}
    july = {**june, ("South", "B"): (50, 20)}            # only South × B drops: 2000 → 1000
    return pd.concat([month_rows("2025-05", june), month_rows("2025-06", june), month_rows("2025-07", july)], ignore_index=True)


# ---------------- formatting & facts ----------------
def test_fmtnum_modes():
    assert fmtnum(1234567, "standard") == "1,234,567"
    assert fmtnum(1234567, "indian") == "12,34,567"
    assert fmtnum(-250000, "inr") == "-₹2,50,000" and fmtnum(999, "indian") == "999" and fmtnum(100000, "inr") == "₹1,00,000"


def test_fact_verification_detects_tampering():
    df = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
    fb = FactBook("t")
    a = fb.base("sum x", 6.0, "SELECT SUM(x) FROM t")
    b = fb.base("count", 3.0, "SELECT COUNT(*) FROM t")
    r = fb.derived("ratio", "ratio", [a, b])
    assert all(v["verified"] for v in verify_facts(fb.facts, {"t": df}).values())
    fb.get(a)["value"] = 7.0                      # a lie
    v = verify_facts(fb.facts, {"t": df})
    assert not v[a]["verified"] and not v[r]["verified"] and v[b]["verified"]   # dependants fail too
    kept, dropped = story.finalize([story.stmt("claim", [a]), story.stmt("fine", [b])], v)
    assert [s["text"] for s in kept] == ["fine"] and dropped == 1


def test_llm_polish_cannot_add_numbers(monkeypatch):
    monkeypatch.setattr(story, "llm_complete", lambda *a, **k: "Revenue grew 15% and customers rose 99%.")
    assert story.polish("Revenue grew 15%.", []) == "Revenue grew 15%."
    monkeypatch.setattr(story, "llm_complete", lambda *a, **k: "Revenue grew 15%, nicely.")
    assert story.polish("Revenue grew 15%.", []) == "Revenue grew 15%, nicely."


# ---------------- root cause ----------------
def test_parse_question(decline):
    h = parse_question("Why did revenue decrease in July?", decline, detect_roles(decline))
    assert h["metric"] == "revenue" and h["month"] == 7 and h["direction"] == "decrease" and h["grain"] == "month"
    assert parse_question("why did cost rise in Q3 2024", decline, detect_roles(decline))["grain"] == "quarter"


def test_root_cause_hand_computed(decline):
    r = run_root_cause(decline, "sales", month=7, year=2025)
    t = r["totals"]
    assert (r["current"], r["previous"]) == ("2025-07", "2025-06") and r["direction"] == "decreased"
    assert t["previous"] == pytest.approx(5000) and t["current"] == pytest.approx(4000) and t["change"] == pytest.approx(-1000) and t["change_pct"] == pytest.approx(-20)
    dims = {d["dimension"]: d for d in r["dimensions"]}
    assert dims["region"]["top"][0]["group"] == "South" and dims["region"]["top"][0]["share_of_change_pct"] == pytest.approx(100)
    assert dims["category"]["top"][0]["group"] == "B"
    cell = r["cells"][0]
    assert {cell["value1"], cell["value2"]} == {"South", "B"} and cell["change"] == pytest.approx(-1000)
    d = r["drivers"]                                   # volume: (300-350) × (5000/350)
    assert d["volume_effect"] == pytest.approx(-50 * 5000 / 350) and d["volume_effect"] + d["price_mix_effect"] == pytest.approx(-1000)
    assert d["quantity_change_pct"] == pytest.approx(-50 / 350 * 100)
    assert d["mix_effect"] + d["like_for_like_price_effect"] == pytest.approx(d["price_mix_effect"])
    assert all(c["passed"] for c in r["reconciliation"]) and r["seasonality"] is None
    assert all(v["verified"] for v in r["verification"].values())


def test_root_cause_story_cites_verified_facts(decline):
    r = run_root_cause(decline, "sales", month=7, year=2025, mode="inr")
    s = story.root_cause_story(r)
    text = " ".join(x["text"] for x in s["statements"])
    assert "decreased by ₹1,000 (-20.0%)" in text and "South" in text and "“B”" in text
    assert s["dropped"] == 0 and all(x["verified"] and x["facts"] for x in s["statements"])
    assert any("South" in rec for rec in s["recommendations"])


def test_root_cause_seasonality_flag():
    base = {("N", "A"): (100, 10), ("S", "A"): (100, 10)}
    drop = {("N", "A"): (60, 10), ("S", "A"): (60, 10)}
    df = pd.concat([month_rows("2024-06", base), month_rows("2024-07", drop), month_rows("2025-06", base), month_rows("2025-07", drop)], ignore_index=True)
    r = run_root_cause(df, "t", month=7, year=2025)
    assert r["seasonality"]["same_direction"] and r["seasonality"]["likely_seasonal"]
    assert "seasonal" in " ".join(x["text"] for x in story.root_cause_story(r)["statements"])


def test_root_cause_errors(decline):
    with pytest.raises(AppError, match="No data for that month"):
        run_root_cause(decline, "sales", month=12, year=2025)
    with pytest.raises(AppError, match="date column"):
        run_root_cause(decline.drop(columns="order_date"), "sales")
    with pytest.raises(AppError, match="previous"):
        run_root_cause(decline[decline.order_date >= "2025-07-01"], "sales", month=7)


# ---------------- discovery ----------------
@pytest.fixture(scope="module")
def business():
    rng = np.random.default_rng(5)
    frames = []
    for m, (e, f, o) in {"2025-04": (700, 200, 100), "2025-05": (720, 190, 90), "2025-06": (900, 120, 60)}.items():
        days = pd.date_range(f"{m}-01", periods=pd.Period(m).days_in_month)
        for prod, tot in (("Electronics", e), ("Furniture", f), ("Office", o)):
            for d in days:
                frames.append({"order_date": d, "product": prod, "customer_id": int(rng.integers(1, 40)), "amount": tot / len(days)})
    return pd.concat([pd.DataFrame(frames)], ignore_index=True)


def test_discovery_finds_and_verifies(business):
    r = discover(business, "biz")
    types = {i["type"] for i in r["insights"]}
    assert {"growth", "concentration", "declining", "performer"} <= types
    assert r["dropped_unverified"] == 0 and all(i["verified"] for i in r["insights"])
    conc = next(i for i in r["insights"] if i["type"] == "concentration")
    assert "Electronics" in conc["title"] and conc["severity"] == "high"
    dec = next(i for i in r["insights"] if i["type"] == "declining")
    assert "Furniture" in dec["title"] or "Office" in dec["title"]
    assert all(v["verified"] for v in r["verification"].values())


def test_discovery_drops_unverifiable_insight(business, monkeypatch):
    import backend.app.analytics.discovery as disc

    real = disc.verify_facts
    monkeypatch.setattr(disc, "verify_facts", lambda facts, tables, only_key=True: {k: {**v, "verified": False} for k, v in real(facts, tables, only_key).items()})
    r = discover(business, "biz")
    assert r["dropped_unverified"] > 0 and not any(i["facts"] for i in r["insights"])


def test_discovery_without_date_or_measure():
    r = discover(pd.DataFrame({"a": list("abcdef"), "b": list("uvwxyz")}), "t")
    assert r["insights"] == [] and r["skipped"]


# ---------------- scenario ----------------
@pytest.fixture(scope="module")
def june_only():
    return month_rows("2025-06", {("North", "A"): (100, 10), ("North", "B"): (50, 20), ("South", "A"): (100, 10), ("South", "B"): (100, 20)}, 0.6)


def val(res, fid):
    return next(f for f in res["facts"] if f["id"] == fid)["value"]


def test_scenario_price_increase_hand_computed(june_only):
    r = run_scenarios(june_only, "t", [{"price_change_pct": 10}], cost="cost")
    R, C = 5000.0, 3000.0
    obs, s = r["observed"], r["scenarios"][0]["facts"]
    assert val(r, obs["revenue"]) == pytest.approx(R) and val(r, obs["profit"]) == pytest.approx(R - C)
    assert val(r, s["revenue"]) == pytest.approx(R * 1.1) and val(r, s["cost"]) == pytest.approx(C)    # no volume response
    assert val(r, s["profit"]) == pytest.approx(R * 1.1 - C) and val(r, s["profit_change_pct"]) == pytest.approx(25.0)
    assert r["kind"] == "scenario_estimate" and "ESTIMATES" in r["disclaimer"]
    assert any("elasticity" in n for n in r["scenarios"][0]["notes"])
    assert all(v["verified"] for v in r["verification"].values())
    est = [f for f in r["facts"] if f["id"] in s.values()]
    assert est and all(f["estimate"] for f in est) and not any(f.get("estimate") for f in r["facts"] if f["id"] in obs.values())


def test_scenario_elasticity_fixed_cost_and_segment(june_only):
    sc = {"price_change_pct": 10, "elasticity": -1.0, "cost_change_pct": 5, "fixed_cost_pct": 50}
    r = run_scenarios(june_only, "t", [sc], cost="cost")
    f = r["scenarios"][0]["facts"]
    vol = 1.1 * 0 + (1 + 0) * (1 - 0.1)                                          # (1+v)(1+e·p) = 0.9
    assert val(r, f["revenue"]) == pytest.approx(5000 * 1.1 * vol)
    assert val(r, f["cost"]) == pytest.approx(3000 * (0.5 * vol + 0.5) * 1.05)
    assert val(r, f["quantity"]) == pytest.approx(350 * vol)
    # segment: only category A is repriced
    r = run_scenarios(june_only, "t", [{"price_change_pct": 10, "segment": {"column": "category", "values": ["A"]}}], cost="cost")
    f = r["scenarios"][0]["facts"]
    assert val(r, f["revenue"]) == pytest.approx(2000 * 1.1 + 3000) and r["scenarios"][0]["segment"] == "category in A"


def test_scenario_compare_breakdown_sensitivity_and_limits(june_only):
    r = run_scenarios(june_only, "t", [{"name": "up", "price_change_pct": 10}, {"name": "down", "price_change_pct": -10}], cost="cost", group_by="region")
    assert [s["name"] for s in r["scenarios"]] == ["up", "down"] and len(r["scenarios"][0]["breakdown"]) == 2
    sens = r["sensitivity"]
    assert sens[0]["price_change_pct"] == -20 and sens[-1]["price_change_pct"] == 20 and sens[-1]["profit"] > sens[0]["profit"]
    with pytest.raises(AppError, match="out of range"):
        run_scenarios(june_only, "t", [{"price_change_pct": 900}], cost="cost")
    with pytest.raises(AppError, match="At most 5"):
        run_scenarios(june_only, "t", [{"price_change_pct": 1}] * 6, cost="cost")
    r = run_scenarios(june_only.drop(columns="cost"), "t", [{"price_change_pct": 5}])
    assert "profit" not in r["scenarios"][0]["facts"] and any("No cost column" in n for n in r["scenarios"][0]["notes"])


def test_scenario_latest_baseline(decline):
    r = run_scenarios(decline, "t", [{"price_change_pct": 10}], cost="cost", baseline_scope="latest")
    assert "2025-07" in r["baseline_scope"] and val(r, r["observed"]["revenue"]) == pytest.approx(4000)
    assert all(v["verified"] for v in r["verification"].values())


def test_parse_scenario_phrases(june_only):
    p = lambda q: parse_scenario(q, june_only)  # noqa: E731
    assert p("What happens to profit if product prices increase by 10%?")["price_change_pct"] == 10
    gad = june_only.assign(category=june_only.category.map({"A": "Gadgets", "B": "Tools"}))
    s = parse_scenario("What if costs rise 5% and prices rise 8% for Gadgets?", gad)
    assert (s["cost_change_pct"], s["price_change_pct"], s["segment"]) == (5, 8, {"column": "category", "values": ["Gadgets"]})
    s = p("Simulate a 15% price cut with elasticity of -1.5")
    assert s["price_change_pct"] == -15 and s["elasticity"] == -1.5
    assert p("what if demand drops 12%")["volume_change_pct"] == -12


# ---------------- executive summary ----------------
def test_executive_summary(decline):
    r = run_executive_summary(decline, "sales", "demo", "indian", 92.0)
    by = {k["label"]: k for k in r["kpis"]}
    assert by["revenue"]["value"] == pytest.approx(5000 + 5000 + 4000) and by["revenue"]["period_value"] == pytest.approx(4000) and by["revenue"]["change_pct"] == pytest.approx(-20)
    assert by["profit"]["value"] == pytest.approx(14000 * 0.4) and all(k["verified"] for k in r["kpis"])
    assert r["performance"] and all(s["verified"] for s in r["performance"])
    assert any("down 20.0%" in s["text"] for s in r["performance"])
    assert r["recommendations"] and r["evidence"] and all(e["verified"] for e in r["evidence"])


# ---------------- planner & graph ----------------
@pytest.mark.parametrize("q,step", [
    ("Why did revenue decrease in July?", "root_cause"), ("What happens to profit if prices increase by 10%?", "scenario"),
    ("Give me an executive summary", "executive"), ("Discover anything interesting", "discovery"), ("Give me an overview of data quality", "quality"),
])
def test_planner_routes_new_intents(decline, q, step):
    ctx = RunContext(question=q, tables={"sales": decline})
    plan = plan_question(q, ctx)
    assert plan["steps"][0] == step and "sql" not in plan["steps"]


def test_existing_routing_unchanged(decline):
    assert plan_question("What is total revenue by region?", RunContext(question="", tables={"sales": decline}))["steps"][0] == "sql"


def test_graph_root_cause_end_to_end(decline):
    st = run_workflow(RunContext(question="Why did revenue decrease in July?", tables={"sales": decline}, table_labels={"sales": "demo"}, extra={"number_mode": "inr"}))
    assert st["status"] == "completed" and [t["agent"] for t in st["trace"]][-4:] == ["visualization", "validation", "story", "report"]
    assert all(t["status"] == "completed" for t in st["trace"])
    assert "₹1,000" in st["answer"] and st["report"]["root_cause"]["metric"] == "revenue"
    assert st["story"]["footnotes"] and all(f["verified"] for f in st["story"]["footnotes"])
    assert st["validation"]["status"] == "passed" and st["report"]["charts"]


def test_graph_scenario_labels_estimate_and_observed(june_only):
    st = run_workflow(RunContext(question="What happens to profit if prices increase by 10%?", tables={"t": june_only}, table_labels={"t": "x"}))
    assert st["status"] == "completed"
    assert "OBSERVED baseline" in st["answer"] and "ESTIMATE (not observed data)" in st["answer"]
    kinds = {s["kind"] for s in st["story"]["statements"]}
    assert kinds == {"observed", "estimate"} and any(f["estimate"] for f in st["story"]["footnotes"])


def test_graph_scenario_without_assumption_fails_gracefully(june_only):
    st = run_workflow(RunContext(question="what if things change?", tables={"t": june_only}))
    assert any("could not find an assumption" in e for e in st["errors"]) and "could not complete" in st["answer"].lower()


def test_root_cause_flags_wrong_premise(decline):
    r = run_root_cause(decline, "sales", month=7, year=2025, question="Why did revenue increase in July?")
    s = story.root_cause_story(r)
    assert s["statements"][0]["kind"] == "context" and "you asked about an increase" in s["statements"][0]["text"] and "actually decreased" in s["statements"][0]["text"]
    assert s["headline"].startswith("Revenue decreased")
