"""Tools read the data pack. Exact facts come from here, never from the model.

The data files live in data/. Paths are built from this file's location so they work
the same on your laptop and on Vercel.
"""
from functools import lru_cache
import json

from langchain_core.tools import tool

from agent.data import load_all


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
        out[row["batch_no"]] = {**skus.get(code, {}), **row, "sku_code": code}
    return out


def batch_record(batch_no: str) -> dict:
    """Plain function: easy to test without a model."""
    row = _batches().get(batch_no.strip().upper())
    if row is None:
        return {"found": False, "batch_no": batch_no, "reason": "No such batch in the batch master"}
    return {"found": True, **row}


@lru_cache(maxsize=1)
def _claims() -> list[dict]:
    """Return cleaned claim rows in JSON-safe form for exact claim-number searches."""
    claims = load_all()["claims"].drop(columns="src_row")
    return json.loads(claims.to_json(orient="records", date_format="iso"))


def claim_records(claim_no: str) -> dict:
    """Find one or more cleaned claim records by exact normalized claim number."""
    normalized = claim_no.strip().upper().replace(" ", "-")
    rows = [row for row in _claims() if row["claim_no"] == normalized]
    return {"found": bool(rows), "claim_no": normalized, "records": rows}


@tool
def lookup_batch(batch_no: str) -> dict:
    """Look up one batch in the batch master. Returns the SKU, product, manufacturing date,
    expiry date and price to stockist, or found=False if the batch does not exist.
    Use it whenever a question mentions a batch number."""
    return batch_record(batch_no)


@tool
def search_claims(claim_no: str) -> dict:
    """Find a claim by its claim number. Use this for a claim status or credit-note question."""
    return claim_records(claim_no)


TOOLS = [lookup_batch, search_claims]
