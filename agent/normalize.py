"""Single place for stockist/batch/claim/invoice normalization before lookups."""
import re


# OCR-style: letter O only in digit-heavy batch strings (use carefully)
_BATCH_OCR = str.maketrans({"O": "0", "o": "0"})


def normalize_stockist_code(value: str | None) -> str:
    if not value or not str(value).strip():
        return ""
    return str(value).strip().upper()


def normalize_batch_no(value: str | None, *, try_ocr: bool = True) -> str:
    if not value or not str(value).strip():
        return ""

    s = str(value).strip().upper().replace(" ", "").replace("-", "")
    if try_ocr and re.fullmatch(r"[A-Z0-9]{6,12}", s) and "O" in s:
        s = s.translate(_BATCH_OCR)
    return s


def normalize_claim_no(value: str | None) -> str:
    if not value or not str(value).strip():
        return ""

    s = str(value).strip().upper().replace(" ", "-")
    # CLM260702627 -> CLM-2607-02627
    match = re.fullmatch(r"CLM-?(\d{4})-?(\d{5})", s.replace("--", "-"))
    if match:
        return f"CLM-{match.group(1)}-{match.group(2)}"
    return s


def normalize_invoice_ref(value: str | None) -> str:
    if not value or not str(value).strip():
        return ""

    s = str(value).strip().upper()
    # INV-S02-2510-053444 -> INV/S02/2510/053444
    if s.startswith("INV-"):
        parts = s.split("-")
        if len(parts) >= 4 and parts[0] == "INV":
            return "/".join([parts[0], *parts[1:]])

    # Collapse duplicate slashes and unify case.
    s = re.sub(r"/+", "/", s)
    return s


def normalize_sku_code(value: str | None) -> str:
    if not value or not str(value).strip():
        return ""
    return str(value).strip().upper().replace("-", "")
