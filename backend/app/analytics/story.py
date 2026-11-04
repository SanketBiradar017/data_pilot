"""Data storytelling: turn verified facts into business prose. Every sentence lists the facts it uses;
sentences that use any unverified fact are dropped, so no statement can carry an unchecked number."""
import re

from backend.app.analytics.facts import FactBook
from backend.app.analytics.llm import llm_complete


def stmt(text: str, facts: list[str], kind: str = "finding") -> dict:
    return {"text": text, "facts": facts, "kind": kind}


def finalize(statements: list[dict], verification: dict[str, dict], facts: list[dict] | None = None) -> tuple[list[dict], int]:
    """Keep a statement only if every fact it cites verified (and, when facts are given, has a defined value)."""
    by = {f["id"]: f for f in facts or []}
    kept, dropped = [], 0
    for s in statements:
        ok = all(verification.get(f, {}).get("verified") and (f not in by or by[f]["value"] is not None) for f in s["facts"])
        if ok:
            kept.append({**s, "verified": True})
        else:
            dropped += 1
    return kept, dropped


def polish(text: str, facts: list[dict]) -> str:
    """Optional LLM rewrite. Accepted only if it introduces no number that is absent from the verified text."""
    out = llm_complete("You are a business writer. Rewrite the analysis below as a short, clear narrative for a manager. "
                       "Keep every number exactly as given; do not add, round or compute any number. Max 140 words.", text, max_tokens=500)
    if not out:
        return text
    nums = lambda t: set(re.findall(r"\d[\d,]*\.?\d*", t))  # noqa: E731
    return out if nums(out) <= nums(text) else text


def _dir(v: float | None, up: str = "rose", down: str = "fell") -> str:
    return "changed" if v is None else up if v >= 0 else down


def root_cause_story(res: dict) -> dict:
    fb = FactBook.from_list("", res["mode"], res["facts"])
    m, cur, prev = res["metric"], res["current"], res["previous"]
    t = res["totals"]
    r0, r1, delta, pct = t["facts"]
    st = [stmt(f"{m.capitalize()} {res['direction']} by {fb.absolute(delta)} ({fb.text(pct, True)}) from {prev} ({fb.text(r0)}) to {cur} ({fb.text(r1)}).", [r0, r1, delta, pct], "what")]
    is_cost = any(h in m.lower() for h in ("cost", "expense", "cogs", "spend"))
    bad = (t["change"] > 0) if is_cost else (t["change"] < 0)      # for costs, an increase is the adverse direction
    recs: list[str] = []
    asked = res.get("asked_direction")
    if asked and ((asked == "decrease") != (t["change"] < 0)) and t["change"] != 0:
        st.insert(0, stmt(f"Note: you asked about {'an' if asked == 'increase' else 'a'} {asked}, but {m} actually {res['direction']} in {cur} ({fb.text(pct, True)} vs {prev}). The analysis below explains the actual change.", [pct], "context"))
    dims = res["dimensions"]
    top = None
    for dr in dims:
        tp = dr["top"][0] if dr["top"] else None
        if tp and (tp["share_of_change_pct"] or 0) >= 15:
            top = (dr["dimension"], tp)
            break
    if top:
        dim, tp = top
        a0, a1, dd, sh = tp["facts"]
        over = " (more than the whole change, because other groups moved the opposite way)" if (tp["share_of_change_pct"] or 0) > 100 else ""
        st.append(stmt(f"The change was driven mainly by {dim} “{tp['group']}”: {m} {_dir(tp['change'])} by {fb.absolute(dd)} there, {fb.text(sh)} of the total change{over}.", [dd, sh], "why"))
        if res["cells"]:
            c = res["cells"][0]
            if (c["share_of_change_pct"] or 0) >= 25:
                f0, f1, fd, fs = c["facts"]
                st.append(stmt(f"The strongest pocket was {c['dim1']} “{c['value1']}” × {c['dim2']} “{c['value2']}”, which {_dir(c['change'], 'added', 'lost')} {fb.absolute(fd)} ({fb.text(fs)} of the total change).", [fd, fs], "why"))
                recs.append(f"Focus on {c['dim1']} “{c['value1']}” in {c['dim2']} “{c['value2']}”: it accounts for {fb.text(fs)} of the change, so a targeted action is more efficient than a broad one.")
        recs.append(f"Investigate {dim} “{tp['group']}”: check pricing, availability, competition and campaign performance there." if bad and not is_cost
                     else f"Investigate why {m} rose in {dim} “{tp['group']}”: check supplier prices, waste, volumes and one-off items there." if bad
                     else f"Understand what worked in {dim} “{tp['group']}” and replicate it in other {dim} groups.")
    dr = res["drivers"]
    if dr and dr["kind"] == "volume_price":
        f_q0, f_q1, f_qp, f_vol, f_pr, f_p0, f_p1, f_pp = dr["facts"]
        st.append(stmt(f"Quantity {_dir(dr['quantity_change_pct'])} {fb.absolute(f_qp)} (volume effect {fb.text(f_vol, True)}), while average {m} per {dr['quantity']} {_dir(dr['unit_value_change_pct'], 'rose', 'fell')} {fb.absolute(f_pp)} (price and mix effect {fb.text(f_pr, True)}).",
                       [f_qp, f_vol, f_pp, f_pr], "why"))
        major = "volume" if abs(dr["volume_effect"]) >= abs(dr["price_mix_effect"]) else "price/mix"
        if major == "volume":
            recs.append("Volume is the main driver: review demand generation, stock availability and customer retention." if bad and not is_cost else "Volume growth is the main driver: make sure supply and service capacity can sustain it." if not is_cost else "Higher activity volume is driving the cost: check it is matched by revenue." if bad else "Lower volume is reducing the cost: check it is not caused by lost business.")
        else:
            recs.append("Price/mix is the main driver: review discounting and the product mix being sold." if bad and not is_cost else "Higher price/mix is the main driver: confirm it is sustainable and not hurting volume." if not is_cost else "Higher unit cost is the main driver: renegotiate supplier prices or review the product mix." if bad else "Lower unit cost is the main driver: confirm it is sustainable and not a quality trade-off.")
        if abs(dr.get("unattributed") or 0) > 0.01 * abs(t["change"] or 1) and dr.get("unattributed_fact"):
            uf = dr["unattributed_fact"]
            st.append(stmt(f"{fb.absolute(uf)} of the change comes from rows without a {dr['quantity']} value, so it cannot be split into volume and price.", [uf], "why"))
    elif dr:
        f_n0, f_n1, f_np, f_vol, f_pr = dr["facts"]
        st.append(stmt(f"The number of records {_dir(dr['quantity_change_pct'])} {fb.absolute(f_np)} (effect {fb.text(f_vol, True)}), and the average value per record contributed {fb.text(f_pr, True)}.", [f_np, f_vol, f_pr], "why"))
    if res["offsets"]:
        o = res["offsets"][0]
        st.append(stmt(f"This was partly offset by {_dir(o['change'], 'growth', 'a decline')} in “{o['group']}” ({fb.text(o['facts'][2], True)}).", [o["facts"][2]], "why"))
    se = res["seasonality"]
    if se:
        sp = se["facts"][2]
        if se["likely_seasonal"]:
            st.append(stmt(f"The same period a year earlier ({se['prior_previous']} → {se['prior_period']}) moved {fb.text(sp, True)}, so part of this change looks seasonal.", [sp], "context"))
            recs.append("Compare with last year's pattern before reacting: this movement is likely seasonal.")
        else:
            st.append(stmt(f"A year earlier ({se['prior_previous']} → {se['prior_period']}) the metric moved {fb.text(sp, True)}, so this is unlikely to be purely seasonal.", [sp], "context"))
    if len(dims) and all(abs(d["top"][0]["share_of_change_pct"] or 0) < 40 for d in dims if d["top"]):
        recs.append("The change is spread across many groups: look for market-wide or operational causes rather than a single segment.")
    if not res["complete_current_period"]:
        recs.append(f"Note: {cur} contains fewer days of data than a full period, so the comparison may be understated.")
    kept, dropped = finalize(st, res["verification"], res["facts"])
    main = [x for x in kept if x["kind"] == "what"]
    headline = (main[0]["text"] if main else kept[0]["text"]) if kept else f"{m} {res['direction']}"
    return {"headline": headline, "statements": kept, "dropped": dropped, "recommendations": recs[:6]}
