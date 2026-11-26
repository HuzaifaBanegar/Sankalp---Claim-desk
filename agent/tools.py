"""Tools read the data pack. Exact facts come from here, never from the model.

The data files live in data/. Paths are built from this file's location so they work
the same on your laptop and on Vercel.
"""
from functools import lru_cache
import json

from langchain_core.tools import tool

from agent.data import load_all

from agent.normalize import (
    normalize_batch_no,
    normalize_claim_no,
    normalize_invoice_ref,
    normalize_stockist_code)


@lru_cache(maxsize=1)
def _batches() -> dict:
    """Join the cleaned batch and SKU masters, keyed by normalized batch number."""
    cleaned = load_all()
    skus = cleaned["sku"].drop(columns="src_row").set_index("sku_code").to_dict("index")
    out = {}
    for row in cleaned["batch"].drop(columns="src_row").to_dict("records"):
        code = row["sku_code"]
        for field in ("mfg_date", "expiry_date"):
            if hasattr(row[field], "strftime"):
                row[field] = row[field].strftime("%d-%m-%Y")
        out[normalize_batch_no(row["batch_no"])] = {**skus.get(code, {}), **row, "sku_code": code}
    return out


def batch_record(batch_no: str) -> dict:
    """Plain function: easy to test without a model."""
    row = _batches().get(normalize_batch_no(batch_no))
    if row is None:
        return {"found": False, "batch_no": batch_no, "reason": "No such batch in the batch master"}
    return {"found": True, **row}


@lru_cache(maxsize=1)
def _claims() -> list[dict]:
    """Return cleaned claim rows in JSON-safe form for exact claim-number searches."""
    claims = load_all()["claims"].drop(columns="src_row")
    return json.loads(claims.to_json(orient="records", date_format="iso"))


def claim_records(
    claim_no: str | None = None,
    batch_no: str | None = None,
    stockist_code: str | None = None,
) -> dict:
    """Find claims by claim number or by the stockist/batch pair used for duplicate checks."""
    rows = _claims()
    query: dict[str, str] = {}
    if claim_no:
        query["claim_no"] = normalize_claim_no(claim_no)
    if batch_no:
        query["batch_no"] = normalize_batch_no(batch_no)
    if stockist_code:
        query["stockist_code"] = normalize_stockist_code(stockist_code)
    rows = [row for row in rows if all(str(row.get(key, "")).strip().upper() == value for key, value in query.items())]
    return {"found": bool(rows), **query, "records": rows}


@lru_cache(maxsize=1)
def _sales() -> list[dict]:
    """Return cleaned primary-sales rows in JSON-safe form."""
    sales = load_all()["sales"].drop(columns="src_row")
    return json.loads(sales.to_json(orient="records", date_format="iso"))


def primary_sale_records(invoice_ref: str, batch_no: str, stockist_code: str) -> dict:
    """Match invoice, batch, and stockist against cleaned primary-sales rows."""
    invoice = normalize_invoice_ref(invoice_ref)
    batch = normalize_batch_no(batch_no)
    stockist = normalize_stockist_code(stockist_code)
    rows = [
        row for row in _sales()
        if row["invoice_no"] == invoice
        and str(row.get("batch_no") or "") == batch
        and row["stockist_code"] == stockist
    ]
    return {"found": bool(rows), "invoice_ref": invoice, "batch_no": batch, "stockist_code": stockist, "records": rows}


@tool
def lookup_batch(batch_no: str) -> dict:
    """Look up one batch in the batch master. Returns the SKU, product, manufacturing date,
    expiry date and price to stockist, or found=False if the batch does not exist.
    Use it whenever a question mentions a batch number."""
    return batch_record(batch_no)


@tool
def search_claims(claim_no: str = "", batch_no: str = "", stockist_code: str = "") -> dict:
    """Search by claim number for status, or by batch_no plus stockist_code for earlier claim history."""
    return claim_records(claim_no or None, batch_no or None, stockist_code or None)


@tool
def match_primary_sale(invoice_ref: str, batch_no: str, stockist_code: str) -> dict:
    """Match invoice, batch, and stockist to validate the claimed quantity against sales."""
    return primary_sale_records(invoice_ref, batch_no, stockist_code)


TOOLS = [lookup_batch, search_claims, match_primary_sale]
