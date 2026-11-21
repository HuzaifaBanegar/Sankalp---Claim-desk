from agent.intake import inspect_request, missing_fields_message
from agent.tools import claim_records


def test_claim_status_needs_only_a_claim_number():
    intake = inspect_request("What is the status of CLM 2607 02627?")
    assert intake["intent"] == "claim_status"
    assert intake["ready"] is True
    assert intake["entities"]["claim_no"] == "CLM-2607-02627"


def test_claim_triage_lists_the_missing_fields():
    intake = inspect_request("Please process an expiry claim for STK0143.")
    assert intake["intent"] == "claim_triage"
    assert intake["ready"] is False
    assert "batch number" in intake["missing"]
    assert "I need the following" in missing_fields_message(intake)


def test_complete_claim_triage_has_all_required_fields():
    text = "Near expiry claim: STK0143, K2440124, 689 strips, claim date 2026-11-21, invoice INV/S02/2503/033678."
    intake = inspect_request(text)
    assert intake["intent"] == "claim_triage"
    assert intake["ready"] is True
    assert intake["entities"]["claim_date"] == "2026-11-21"


def test_claim_triage_requires_a_claim_date_for_policy_window_check():
    intake = inspect_request("Near expiry claim: STK0143, K2440124, 689 strips, invoice INV/S02/2503/033678.")
    assert "claim date (YYYY-MM-DD)" in intake["missing"]


def test_claim_search_returns_tool_backed_facts():
    result = claim_records("CLM-2607-02627")
    assert result["found"] is True
    assert result["records"][0]["status"] == "Pending"
