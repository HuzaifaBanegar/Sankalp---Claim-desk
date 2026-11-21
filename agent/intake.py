"""Deterministic intake checks for user-entered claim requests.

This module reads only the user's text. It extracts identifiers that have clear
formats and asks for missing information before a model or data tool is called.
"""
import re
from typing import Any


CLAIM_NUMBER = re.compile(r"\bCLM[-\s]?(\d{4})[-\s]?(\d{5})\b", re.IGNORECASE)
STOCKIST_CODE = re.compile(r"\bSTK[-\s]?(\d{4})\b", re.IGNORECASE)
BATCH_NUMBER = re.compile(r"\b([A-Z]\d{6,8})\b", re.IGNORECASE)
INVOICE_REFERENCE = re.compile(r"\bINV(?:/[A-Z0-9]+){3,}\b", re.IGNORECASE)
QUANTITY = re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:packs?|strips?|units?|bottles?|pcs?)\b", re.IGNORECASE)
CLAIM_DATE = re.compile(r"\bclaim date\s*[:=]?\s*(\d{4}-\d{2}-\d{2})\b", re.IGNORECASE)

CLAIM_TYPES = {
    "near expiry": "Near expiry",
    "expired": "Expired",
    "breakage": "Breakage in transit",
    "short supply": "Short supply",
}


def _match(pattern: re.Pattern[str], text: str, format_value) -> str | None:
    """Return the first normalized regex match, or None when text has no match."""
    found = pattern.search(text)
    return format_value(found) if found else None


def inspect_request(text: str) -> dict[str, Any]:
    """Classify a request and return extracted facts plus missing mandatory fields."""
    normalized = text.upper()
    claim_no = _match(CLAIM_NUMBER, text, lambda m: f"CLM-{m.group(1)}-{m.group(2)}")
    stockist_code = _match(STOCKIST_CODE, text, lambda m: f"STK{m.group(1)}")
    batch_no = _match(BATCH_NUMBER, text, lambda m: m.group(1).upper())
    invoice_ref = _match(INVOICE_REFERENCE, text, lambda m: m.group(0).upper())
    quantity = _match(QUANTITY, text, lambda m: m.group(1))
    claim_date = _match(CLAIM_DATE, text, lambda m: m.group(1))
    claim_type = next((value for phrase, value in CLAIM_TYPES.items() if phrase in normalized.lower()), None)
    exception = "ledger" in normalized.lower() and "written" in normalized.lower() and "area manager" in normalized.lower()

    entities = {
        "claim_no": claim_no,
        "stockist_code": stockist_code,
        "batch_no": batch_no,
        "invoice_ref": invoice_ref,
        "qty": quantity,
        "claim_type": claim_type,
        "claim_date": claim_date,
        "invoice_exception_documented": exception,
    }
    if claim_no:
        return {"intent": "claim_status", "ready": True, "entities": entities, "missing": []}

    claim_words = ("claim", "return", "near expiry", "expired", "breakage", "short supply")
    if any(word in normalized.lower() for word in claim_words):
        missing = [name for name, value in {
            "stockist code": stockist_code,
            "batch number": batch_no,
            "quantity with unit (for example, 20 strips)": quantity,
            "claim type": claim_type,
            "claim date (YYYY-MM-DD)": claim_date,
        }.items() if not value]
        if not invoice_ref and not exception:
            missing.append("original invoice reference, or documented purchase-ledger verification and written Area Manager approval")
        return {"intent": "claim_triage", "ready": not missing, "entities": entities, "missing": missing}

    if batch_no:
        return {"intent": "batch_lookup", "ready": True, "entities": entities, "missing": []}
    return {"intent": "general", "ready": True, "entities": entities, "missing": []}


def missing_fields_message(intake: dict[str, Any]) -> str:
    """Create a clear deterministic response when a claim cannot yet be assessed."""
    fields = "; ".join(intake["missing"])
    return f"I need the following before I can assess this claim: {fields}."
