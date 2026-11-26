"""Deterministic intake checks for user-entered claim requests.

This module reads only the user's text. It extracts identifiers that have clear
formats and asks for missing information before a model or data tool is called.
"""
from __future__ import annotations

import re
from typing import Any, Callable

from agent.normalize import (
 normalize_batch_no,
 normalize_claim_no,
 normalize_invoice_ref,
 normalize_stockist_code,
)
from agent.rules import _parse_date

CLAIM_NUMBER = re.compile(r"\bCLM[-\s]?(\d{4})[-\s]?(\d{5})\b", re.IGNORECASE)
STOCKIST_CODE = re.compile(r"\bSTK[-\s]?(\d{4})\b", re.IGNORECASE)
BATCH_NUMBER = re.compile(r"\b([A-Z][\s-]?\d{6,8})\b", re.IGNORECASE)
INVOICE_REFERENCE = re.compile(
 r"\b("
 r"INV(?:/[A-Z0-9]+){3,}"
 r"|INV(?:-[A-Z0-9]+){3,}"
 r")\b",
 re.IGNORECASE,
)
QUANTITY = re.compile(
 r"\b(\d+(?:\.\d+)?)\s*(?:packs?|strips?|units?|bottles?|pcs?)\b",
 re.IGNORECASE,
)
# Also "Qty: 38" / "Quantity: 38 strips"
QUANTITY_LABELED = re.compile(
 r"\b(?:qty|quantity)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(?:packs?|strips?|units?|bottles?|pcs?)?\b",
 re.IGNORECASE,
)

CLAIM_DATE_PATTERNS: list[tuple[re.Pattern[str], int]] = [
 (
 re.compile(
 r"\b(?:claim date|submitted on|submission date|as on|dated)\s*[:=]?\s*"
 r"(\d{4}-\d{2}-\d{2})\b",
 re.IGNORECASE,
 ),
 1,
 ),
 (
 re.compile(
 r"\b(?:claim date|submitted on|submission date|as on|dated)\s*[:=]?\s*"
 r"(\d{1,2}[-/]\d{1,2}[-/]\d{4})\b",
 re.IGNORECASE,
 ),
 1,
 ),
 (
 re.compile(
 r"\b(?:claim date|submitted on|submission date|as on|dated)\s*[:=]?\s*"
 r"(\d{1,2}-[A-Za-z]{3}-\d{4})\b",
 re.IGNORECASE,
 ),
 1,
 ),
]
ANY_DATE_PATTERNS = [
    re.compile(r"\b\d{4}-\d{1,2}-\d{1,2}\b"),
    re.compile(r"\b\d{1,2}[-/]\d{1,2}[-/]\d{4}\b"),
    re.compile(r"\b\d{1,2}-[A-Za-z]{3}-\d{4}\b", re.IGNORECASE),
    re.compile(r"\b[A-Za-z]{3,9}[- ]\d{2,4}\b", re.IGNORECASE),
]

CLAIM_TYPES: list[tuple[str, str]] = [
 ("near-expiry", "Near expiry"),
 ("near expiry", "Near expiry"),
 ("near expiry return", "Near expiry"),
 ("expired", "Expired"),
 ("expiry return", "Expired"),
 ("breakage in transit", "Breakage in transit"),
 ("breakage", "Breakage in transit"),
 ("short supply", "Short supply"),
]

def _match(pattern: re.Pattern[str], text: str, format_value: Callable) -> str | None:
    """Return the first normalized regex match, or None when text has no match."""
    found = pattern.search(text)
    return format_value(found) if found else None


def _extract_claim_date(text: str) -> str | None:
    """Parse the first recognizable date in the request and store it as ISO."""
    for pattern, group in CLAIM_DATE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        parsed = _parse_date(match.group(group))
        if parsed:
            return parsed.isoformat()

    candidates = [match for pattern in ANY_DATE_PATTERNS for match in pattern.finditer(text)]
    for match in sorted(candidates, key=lambda item: item.start()):
        parsed = _parse_date(match.group(0))
        if parsed:
            return parsed.isoformat()
    return None


def _extract_claim_type(text: str) -> str | None:
    lower = text.lower()
    for phrase, value in CLAIM_TYPES:
        if phrase in lower:
            return value
    return None


def _extract_quantity(text: str) -> str | None:
    quantity = _match(QUANTITY, text, lambda match: match.group(1))
    if quantity:
        return quantity
    return _match(QUANTITY_LABELED, text, lambda match: match.group(1))


def _invoice_exception_documented(text: str) -> bool:
    lower = text.lower()
    ledger_match = (
        "ledger" in lower or "purchase-ledger" in lower
    ) and "area manager" in lower
    verbal = any(
        phrase in lower
        for phrase in ("approved on phone", "am bhai said ok", "phone approval", "on phone")
    )
    # A written exception still needs explicit ledger verification and AM approval.
    return ledger_match and "written" in lower and not verbal


def _clean_entities(entities: dict[str, Any]) -> dict[str, Any]:
    out = dict(entities)
    if out.get("claim_no"):
        out["claim_no"] = normalize_claim_no(out["claim_no"])
    if out.get("stockist_code"):
        out["stockist_code"] = normalize_stockist_code(out["stockist_code"])
    if out.get("batch_no"):
        out["batch_no"] = normalize_batch_no(out["batch_no"])
    if out.get("invoice_ref"):
        out["invoice_ref"] = normalize_invoice_ref(out["invoice_ref"])
    return out


def merge_structured_entities(entities: dict[str, Any] | None) -> dict[str, Any]:
    """Use when the API/form sends pre-filled fields; still normalize."""
    base = {
        "claim_no": None,
        "stockist_code": None,
        "batch_no": None,
        "invoice_ref": None,
        "qty": None,
        "claim_type": None,
        "claim_date": None,
        "invoice_exception_documented": False,
        "verbal_approval": False,
    }
    if entities:
        base.update({key: value for key, value in entities.items() if value not in (None, "")})
    return _clean_entities(base)

def inspect_request(text: str, structured: dict[str, Any] | None = None) -> dict[str, Any]:
    """Classify a request and return extracted facts plus missing mandatory fields."""
    from_form = structured is not None
    text = text or ""

    claim_no = _match(CLAIM_NUMBER, text, lambda match: f"CLM-{match.group(1)}-{match.group(2)}")
    stockist_code = _match(STOCKIST_CODE, text, lambda match: f"STK{match.group(1)}")
    batch_raw = _match(BATCH_NUMBER, text, lambda match: re.sub(r"[\s-]", "", match.group(1).upper()))
    invoice_ref = _match(INVOICE_REFERENCE, text, lambda match: normalize_invoice_ref(match.group(1)))
    quantity = _extract_quantity(text)
    claim_date = _extract_claim_date(text)
    claim_type = _extract_claim_type(text)
    exception = _invoice_exception_documented(text)
    verbal = any(
        phrase in text.lower()
        for phrase in ("approved on phone", "am bhai said ok", "phone approval", "over the phone")
    )

    structured_values = structured or {}
    entities = merge_structured_entities(
        {
            **structured_values,
            "claim_no": structured_values.get("claim_no") or claim_no,
            "stockist_code": structured_values.get("stockist_code") or stockist_code,
            "batch_no": structured_values.get("batch_no") or batch_raw,
            "invoice_ref": structured_values.get("invoice_ref") or invoice_ref,
            "qty": structured_values.get("qty") or quantity,
            "claim_type": structured_values.get("claim_type") or claim_type,
            "claim_date": structured_values.get("claim_date") or claim_date,
            "invoice_exception_documented": structured_values.get("invoice_exception_documented") or exception,
            "verbal_approval": structured_values.get("verbal_approval", False) or verbal,
        }
    )

    if entities.get("claim_no"):
        return {
            "intent": "claim_status",
            "ready": True,
            "entities": entities,
            "missing": [],
        }

    claim_words = (
        "claim", "return", "near expiry", "near-expiry", "expired", "expiry",
        "breakage", "short supply", "credit note",
    )
    lower = text.lower()
    looks_like_claim = from_form or any(word in lower for word in claim_words)

    if looks_like_claim:
        missing: list[str] = []
        if not entities.get("stockist_code"):
            missing.append("stockist code")
        if not entities.get("batch_no"):
            missing.append("batch number")
        if not entities.get("qty"):
            missing.append("quantity with unit (for example, 20 strips)")
        if not entities.get("claim_type"):
            missing.append("claim type (Near expiry, Expired, Breakage in transit, or Short supply)")
        if not entities.get("claim_date"):
            missing.append("expiry date (YYYY-MM-DD, DD-MM-YYYY, DD/MM/YYYY, or Mon-YY)")
        if not entities.get("invoice_ref") and not entities.get("invoice_exception_documented"):
            missing.append(
                "original invoice reference, or documented purchase-ledger verification "
                "and written Area Manager approval"
            )
        return {
            "intent": "claim_triage",
            "ready": not missing,
            "entities": entities,
            "missing": missing,
        }

    if entities.get("batch_no"):
        return {
            "intent": "batch_lookup",
            "ready": True,
            "entities": entities,
            "missing": [],
        }

    return {
        "intent": "general",
        "ready": True,
        "entities": entities,
        "missing": [],
    }


def inspect_structured_claim_triage(payload: dict[str, Any]) -> dict[str, Any]:
    """Raise-claim form: skip free-text regex; validate normalized fields only."""
    entities = merge_structured_entities(payload)
    missing: list[str] = []
    if not entities.get("stockist_code"):
        missing.append("stockist code")
    if not entities.get("batch_no"):
        missing.append("batch number")
    if not entities.get("qty"):
        missing.append("quantity")
    if not entities.get("claim_type"):
        missing.append("claim type")
    if not entities.get("claim_date"):
        missing.append("expiry date")
    if not entities.get("invoice_ref") and not entities.get("invoice_exception_documented"):
        missing.append(
            "original invoice reference, or documented purchase-ledger verification "
            "and written Area Manager approval"
        )
    return {
        "intent": "claim_triage",
        "ready": not missing,
        "entities": entities,
        "missing": missing,
    }


def inspect_structured_claim_status(claim_no: str) -> dict[str, Any]:
    entities = merge_structured_entities({"claim_no": claim_no})
    return {
        "intent": "claim_status",
        "ready": bool(entities.get("claim_no")),
        "entities": entities,
        "missing": [] if entities.get("claim_no") else ["claim number"],
    }


def missing_fields_message(intake: dict[str, Any]) -> str:
    """Create a clear deterministic response when a claim cannot yet be assessed."""
    if not intake.get("missing"):
        return "The request is missing required information."
    bullet = "\n".join(f"• {item}" for item in intake["missing"])
    return (
        "I need the following before I can assess this claim:\n"
        f"{bullet}\n\n"
        "Tip: include the product expiry date (for example, “31/10/2026” or “Oct-26”), "
        "along with stockist code, batch, quantity with unit, claim type, and invoice reference."
    )
