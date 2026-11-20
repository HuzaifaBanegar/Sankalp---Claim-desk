"""Tests for deterministic CSV cleaning."""
from agent.data import CLEAN_LOG, load_all


def test_load_all_returns_all_seven_cleaned_extracts():
    cleaned = load_all()
    assert set(cleaned) == {"sku", "batch", "stockist", "sales", "claims", "stock", "emails"}
    assert set(CLEAN_LOG) == {
        "sku_master", "batch_master", "stockist_master", "primary_sales",
        "expiry_claims", "cnf_stock_snapshot", "claim_emails",
    }


def test_loader_normalizes_keys_and_converts_known_types():
    cleaned = load_all()
    assert cleaned["batch"]["batch_no"].str.fullmatch(r"[A-Z0-9]+", na=False).all()
    assert str(cleaned["sales"]["invoice_date"].dtype).startswith("datetime64")
    assert str(cleaned["claims"]["qty_claimed"].dtype).startswith(("int", "float"))


def test_clean_log_keeps_reproducible_counts():
    load_all()
    assert CLEAN_LOG["primary_sales"]["raw_rows"] >= 1
    assert "exact_duplicates_removed" in CLEAN_LOG["expiry_claims"]
    assert "unparsed_dates" in CLEAN_LOG["batch_master"]
