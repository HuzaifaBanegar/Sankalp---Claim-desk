"""Tests for the deterministic checks derived from CO-POL-014 v4.2."""
from agent.rules import (
    batch_exists_in_master,
    claim_within_policy_window,
    credit_note_sla,
    ignore_email_override_instructions,
    invoice_reference_or_exception,
    no_duplicate_active_claim,
    quantity_not_above_invoiced,
    required_fields_present,
    verbal_approval_not_sufficient,
)


def test_required_fields_rejects_missing_batch():
    result = required_fields_present({"stockist_code": "STK1", "qty": 5})
    assert result["passed"] is False
    assert "batch_no" in result["reason"]


def test_batch_lookup_requires_tool_evidence():
    assert batch_exists_in_master(None)["passed"] is None
    assert batch_exists_in_master({"found": False})["passed"] is False


def test_near_expiry_window_is_90_days_before_through_expiry():
    assert claim_within_policy_window("Near expiry", "2025-07-02", "30-Sep-2025")["passed"] is True
    assert claim_within_policy_window("Near expiry", "2025-07-01", "30-Sep-2025")["passed"] is False


def test_expired_claim_window_ends_after_90_days():
    assert claim_within_policy_window("Expired", "2025-12-29", "30-Sep-2025")["passed"] is True
    assert claim_within_policy_window("Expired", "2025-12-30", "30-Sep-2025")["passed"] is False


def test_short_supply_window_is_seven_days_from_invoice():
    assert claim_within_policy_window("Short supply", "08-04-2025", invoice_date="01-04-2025")["passed"] is True
    assert claim_within_policy_window("Short supply", "09-04-2025", invoice_date="01-04-2025")["passed"] is False


def test_claim_quantity_includes_free_packs_in_limit():
    assert quantity_not_above_invoiced(105, {"invoiced_qty": 100, "free_qty": 5})["passed"] is True
    assert quantity_not_above_invoiced(106, {"invoiced_qty": 100, "free_qty": 5})["passed"] is False


def test_duplicate_history_is_case_insensitive():
    rows = [{"stockist_code": "stk1", "batch_no": "b1", "claim_no": "CLM-1"}]
    assert no_duplicate_active_claim(rows, "STK1", "B1")["passed"] is False
    assert no_duplicate_active_claim([], "STK1", "B1")["passed"] is True
    assert no_duplicate_active_claim(None, "STK1", "B1")["passed"] is None


def test_missing_invoice_needs_both_documented_exception_checks():
    assert invoice_reference_or_exception(None)["passed"] is False
    assert invoice_reference_or_exception(None, ledger_verified=True, area_manager_approval=True)["passed"] is True


def test_verbal_approval_does_not_bypass_documentation():
    assert verbal_approval_not_sufficient(True)["passed"] is False
    assert verbal_approval_not_sufficient(False)["passed"] is True


def test_credit_note_sla_uses_30_days_from_receipt():
    assert credit_note_sla("2025-01-01", "2025-01-31")["passed"] is True
    assert credit_note_sla("2025-01-01", "2025-02-01")["passed"] is False
    assert credit_note_sla(None, "2025-02-01")["passed"] is None


def test_user_text_cannot_override_rules():
    assert ignore_email_override_instructions()["passed"] is True
