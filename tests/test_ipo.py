from datetime import date

from app.adapters.ipo.nse_ipo import merge_ipos, parse_issues

CURRENT = [{
    "symbol": "ACME", "companyName": "Acme Industries Limited", "series": "EQ",
    "issueStartDate": "10-Nov-2026", "issueEndDate": "12-Nov-2026", "status": "Active",
    "issueSize": "12000000", "issuePrice": "Rs.270 to Rs.285", "noOfTime": "3.41", "lotSize": "52",
}]
UPCOMING = {"data": [
    {"symbol": "SMEX", "companyName": "Smex Ltd", "series": "SME", "issueStartDate": "20-11-2026",
     "issueEndDate": "22-11-2026", "issuePrice": "60-62", "status": "Forthcoming"},
    {"symbol": "ACME", "companyName": "dup", "issuePrice": "1"},
    {"companyName": "no symbol"},
]}


def test_parse_nse_issues():
    ipos = merge_ipos(parse_issues(CURRENT, "open"), parse_issues(UPCOMING, "upcoming"))
    assert [i.symbol for i in ipos] == ["ACME", "SMEX"]
    acme, smex = ipos
    assert (acme.price_low, acme.price_high, acme.lot_size, acme.subscription_times) == (270, 285, 52, 3.41)
    assert acme.status == "open" and acme.category == "Mainboard" and acme.issue_start == date(2026, 11, 10)
    assert acme.min_investment == 285 * 52
    assert smex.category == "SME" and smex.status == "upcoming" and smex.issue_end == date(2026, 11, 22)
    assert parse_issues({"unexpected": True}, "open") == []


def test_ipo_list_and_ai_review_clamps_lots(env):
    c = env.client()
    c.put("/api/wallet", json={"deployable": 30_000})  # DEMOTECH lot = 285*52 = 14,820
    env.llm.ipo = {"overview": "busy month", "assessments": [
        {"symbol": "DEMOTECH", "verdict": "APPLY", "rationale": "solid", "risks": "pricey", "suggested_lots": 5},
        {"symbol": "TINYSME", "verdict": "AVOID", "rationale": "risky", "risks": "liquidity", "suggested_lots": 2},
        {"symbol": "UNKNOWN", "verdict": "APPLY", "rationale": "", "risks": "", "suggested_lots": 1},
    ]}
    assert len(c.get("/api/ipos").json()) == 3
    review = c.post("/api/ipos/review").json()
    by = {a["symbol"]: a for a in review["assessments"]}
    assert set(by) == {"DEMOTECH", "TINYSME"}
    assert by["DEMOTECH"]["suggested_lots"] == 2 and by["TINYSME"]["suggested_lots"] == 0
    assert review["overview"] == "busy month"
    assert "IPO" in env.llm.calls[-1][0]


def test_rules_advisor_cannot_review_ipos(env):
    c = env.client()
    c.put("/api/settings", json={"advisor_id": "rules"})
    review = c.post("/api/ipos/review").json()
    assert review["assessments"] == [] and "Rules advisor" in review["overview"]
