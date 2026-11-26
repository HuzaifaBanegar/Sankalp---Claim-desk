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
    assert "expiry date (YYYY-MM-DD, DD-MM-YYYY, DD/MM/YYYY, or Mon-YY)" in intake["missing"]


def test_date_is_extracted_even_when_labeled_as_expiry():
    text = (
        "Near expiry claim: STK0117, L2400579, Qty: 38 strips, "
        "Expiry: 31/10/2026, Invoice: INV/S01/2507/044588"
    )
    intake = inspect_request(text)
    assert intake["entities"]["claim_date"] == "2026-10-31"
    assert "expiry date (YYYY-MM-DD, DD-MM-YYYY, DD/MM/YYYY, or Mon-YY)" not in intake["missing"]


def test_submission_date_accepts_day_month_year_formats():
    for value in ("31/10/2026", "31-10-2026"):
        intake = inspect_request(
            f"Near expiry claim: STK0117, L2400579, Qty: 38 strips, "
            f"submission date: {value}, Invoice: INV/S01/2507/044588"
        )
        assert intake["entities"]["claim_date"] == "2026-10-31"


def test_month_year_date_uses_first_day_of_month():
    intake = inspect_request(
        "Near expiry claim: STK0117, L2400579, Qty: 38 strips, "
        "Expiry: Oct-26, Invoice: INV/S01/2507/044588"
    )
    assert intake["entities"]["claim_date"] == "2026-10-01"


def test_claim_search_returns_tool_backed_facts():
    result = claim_records("CLM-2607-02627")
    assert result["found"] is True
    assert result["records"][0]["status"] == "Pending"
