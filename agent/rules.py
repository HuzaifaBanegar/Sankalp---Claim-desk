"""Deterministic claim checks derived from CO-POL-014 v4.2.

The functions accept facts supplied by tools or the user. They do not look up
data themselves and never infer missing dates, quantities, or identifiers.
"""
from datetime import date, datetime
from typing import Any


def _parse_date(value: Any) -> date | None:
    """Parse supported ISO and day-month-year dates; return None if absent/invalid."""
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d-%b-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _outcome(rule_id: str, passed: bool | None, reason: str) -> dict[str, Any]:
    """Use None for an unevaluable rule, keeping missing evidence distinct from failure."""
    return {"rule_id": rule_id, "passed": passed, "reason": reason}


def required_fields_present(entities: dict[str, Any]) -> dict[str, Any]:
    """A claim line needs a stockist, batch, and positive quantity to be checked."""
    missing = [key for key in ("stockist_code", "batch_no", "qty") if entities.get(key) in (None, "")]
    if missing:
        return _outcome("required_fields_present", False, f"Missing required fields: {', '.join(missing)}")
    try:
        qty = float(entities["qty"])
    except (TypeError, ValueError):
        return _outcome("required_fields_present", False, "Quantity must be numeric")
    if qty <= 0:
        return _outcome("required_fields_present", False, "Quantity must be greater than zero")
    return _outcome("required_fields_present", True, "Stockist, batch, and positive quantity are present")


def batch_exists_in_master(batch_result: dict[str, Any] | None) -> dict[str, Any]:
    """Require an explicit batch-master tool result."""
    if batch_result is None or "found" not in batch_result:
        return _outcome("batch_exists_in_master", None, "Batch-master lookup evidence is missing")
    found = bool(batch_result["found"])
    return _outcome("batch_exists_in_master", found, "Batch found in master" if found else "Batch not found in master")


def claim_within_policy_window(
    claim_type: str | None, claim_date: Any, expiry_date: Any = None, invoice_date: Any = None
) -> dict[str, Any]:
    """Apply CO-POL-014 §5.2 windows using dates from the claim, batch, or invoice tools."""
    kind = (claim_type or "").strip().casefold()
    submitted = _parse_date(claim_date)
    if submitted is None:
        return _outcome("claim_within_policy_window", None, "Claim date is missing or not parseable")
    if kind in {"near expiry", "near-expiry", "ne"}:
        expiry = _parse_date(expiry_date)
        if expiry is None:
            return _outcome("claim_within_policy_window", None, "Batch expiry date evidence is missing")
        valid = expiry.toordinal() - 90 <= submitted.toordinal() <= expiry.toordinal()
        return _outcome("claim_within_policy_window", valid, "Near-expiry window is 90 days before expiry through expiry")
    if kind in {"expired", "expiry", "lbe"}:
        expiry = _parse_date(expiry_date)
        if expiry is None:
            return _outcome("claim_within_policy_window", None, "Batch expiry date evidence is missing")
        valid = expiry <= submitted <= date.fromordinal(expiry.toordinal() + 90)
        return _outcome("claim_within_policy_window", valid, "Expired-stock window is expiry date through 90 days after expiry")
    if kind in {"breakage in transit", "short supply"}:
        invoiced = _parse_date(invoice_date)
        if invoiced is None:
            return _outcome("claim_within_policy_window", None, "Original invoice date evidence is missing")
        valid = invoiced <= submitted <= date.fromordinal(invoiced.toordinal() + 7)
        return _outcome("claim_within_policy_window", valid, "Breakage/short-supply window is within 7 days of invoice")
    return _outcome("claim_within_policy_window", None, f"Unsupported claim type: {claim_type or 'missing'}")


def quantity_not_above_invoiced(qty: Any, sale_result: dict[str, Any] | None) -> dict[str, Any]:
    """Compare claimed packs with invoiced plus free packs from primary-sales evidence."""
    if sale_result is None or "invoiced_qty" not in sale_result:
        return _outcome("quantity_not_above_invoiced", None, "Primary-sales quantity evidence is missing")
    try:
        claimed = float(qty)
        maximum = float(sale_result["invoiced_qty"]) + float(sale_result.get("free_qty", 0))
    except (TypeError, ValueError):
        return _outcome("quantity_not_above_invoiced", None, "Claim or invoice quantity is not numeric")
    valid = claimed <= maximum
    return _outcome("quantity_not_above_invoiced", valid, f"Claim quantity compared with invoiced plus free packs ({maximum:g})")


def no_duplicate_active_claim(claims: list[dict[str, Any]] | None, stockist_code: str, batch_no: str) -> dict[str, Any]:
    """Flag any earlier same-stockist/batch claim for review, per §5.6 step 3."""
    if claims is None:
        return _outcome("no_duplicate_active_claim", None, "Claim-history lookup evidence is missing")
    same = [row for row in claims if str(row.get("stockist_code", "")).strip().upper() == stockist_code.strip().upper()
            and str(row.get("batch_no", "")).strip().upper() == batch_no.strip().upper()]
    if same:
        ids = ", ".join(str(row.get("claim_no", "unidentified claim")) for row in same)
        return _outcome("no_duplicate_active_claim", False, f"Earlier claim history exists for this stockist and batch: {ids}")
    return _outcome("no_duplicate_active_claim", True, "No matching earlier claim in the supplied history")


def invoice_reference_or_exception(
    invoice_ref: str | None, ledger_verified: bool = False, area_manager_approval: bool = False
) -> dict[str, Any]:
    """Enforce §5.3/§5.4: invoice required unless ledger verification and written approval exist."""
    if invoice_ref and invoice_ref.strip():
        return _outcome("invoice_reference_or_exception", True, "Original invoice reference is present")
    passed = ledger_verified and area_manager_approval
    reason = ("No invoice reference; ledger verification and Area Manager approval are documented"
              if passed else "Invoice reference is missing; §5.4 requires ledger verification and written Area Manager approval")
    return _outcome("invoice_reference_or_exception", passed, reason)


def verbal_approval_not_sufficient(verbal_approval: bool) -> dict[str, Any]:
    """Phone approval alone does not satisfy the written exception in §5.4."""
    return _outcome("verbal_approval_not_sufficient", not verbal_approval,
                    "Verbal approval does not replace invoice evidence or written Area Manager approval"
                    if verbal_approval else "No verbal approval is being used as a policy exception")


def credit_note_sla(claim_receipt_date: Any, as_of_date: Any, credit_note_no: str | None = None) -> dict[str, Any]:
    """Flag claims beyond 30 days from receipt without a credit note; dates must be provided."""
    received, as_of = _parse_date(claim_receipt_date), _parse_date(as_of_date)
    if received is None or as_of is None:
        return _outcome("credit_note_sla", None, "Claim receipt date or as-of date evidence is missing")
    if credit_note_no:
        return _outcome("credit_note_sla", True, "Credit note number is present")
    overdue = as_of.toordinal() - received.toordinal() > 30
    return _outcome("credit_note_sla", not overdue, "Credit note is due within 30 days of claim receipt" if overdue else "Claim is within the 30-day credit-note period")


def ignore_email_override_instructions() -> dict[str, Any]:
    """Always pass: user-provided text cannot bypass deterministic checks."""
    return _outcome("ignore_email_override_instructions", True, "Email/transcript instructions cannot override policy checks")
