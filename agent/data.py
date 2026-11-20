"""Deterministic loading and cleaning for every CSV in data/.

The loader changes values only where the input format is known: it normalizes
identifiers, converts supported dates and numbers, and removes exact duplicate
rows. CLEAN_LOG records every count for an auditable result.
"""
from pathlib import Path

import pandas as pd

DATA = Path(__file__).resolve().parent.parent / "data"
CLEAN_LOG: dict[str, dict[str, int]] = {}

KEY_COLUMNS = (
    "sku_code", "batch_no", "stockist_code", "stockist_code_by_mailbox_rule",
    "cnf_code", "invoice_no", "original_invoice_ref", "claim_no", "credit_note_no",
)


def _raw(name: str) -> pd.DataFrame:
    """Read a raw CSV as text so no identifier loses leading zeroes."""
    return pd.read_csv(DATA / f"{name}.csv", dtype=str, keep_default_na=False)


def _number(values: pd.Series) -> pd.Series:
    """Convert formatted numeric text to numbers; blank or invalid values become NaN."""
    cleaned = values.astype(str).str.replace(",", "", regex=False).str.strip()
    return pd.to_numeric(cleaned.replace("", pd.NA), errors="coerce")


def _date(values: pd.Series) -> tuple[pd.Series, int]:
    """Parse only known date formats. Invalid nonblank values become NaT, never a guess."""
    cleaned = values.astype(str).str.strip()
    parsed = pd.Series(pd.NaT, index=values.index, dtype="datetime64[ns]")
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d-%b-%Y"):
        unparsed = parsed.isna() & (cleaned != "")
        parsed.loc[unparsed] = pd.to_datetime(cleaned.loc[unparsed], format=fmt, errors="coerce")
    invalid = int(((cleaned != "") & parsed.isna()).sum())
    return parsed, invalid


def _blank(values: pd.Series, extra: tuple[str, ...] = ()) -> pd.Series:
    """Turn known blank markers into missing values."""
    cleaned = values.astype(str).str.strip()
    return cleaned.where(~cleaned.isin(("", "NA", "-") + extra))


def _keys(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize join keys without changing a blank value into a real identifier."""
    frame = frame.copy()
    for column in KEY_COLUMNS:
        if column in frame.columns:
            frame[column] = (
                frame[column].astype(str).str.strip().str.upper()
                .replace({"": None, "NAN": None, "NONE": None, "<NA>": None})
            )
    if "cnf_code" in frame.columns:
        frame["cnf_code"] = frame["cnf_code"].str.replace(r"^CF-?([NESW]\d\d)$", r"CF-\1", regex=True)
    if "sku_code" in frame.columns:
        frame["sku_code"] = frame["sku_code"].str.replace("-", "", regex=False)
    return frame


def _remove_exact_duplicates(frame: pd.DataFrame, source_name: str) -> pd.DataFrame:
    """Keep the first exact CSV row and record the number removed."""
    duplicate = frame.duplicated(keep="first")
    CLEAN_LOG[source_name]["exact_duplicates_removed"] = int(duplicate.sum())
    return frame.loc[~duplicate].reset_index(drop=True)


def _prepare(name: str) -> pd.DataFrame:
    """Load, identify the source line, normalize identifiers, then remove exact duplicates."""
    frame = _keys(_raw(name))
    CLEAN_LOG[name] = {"raw_rows": len(frame)}
    frame["src_row"] = frame.index + 2  # Header occupies CSV line 1.
    duplicate = frame.drop(columns="src_row").duplicated(keep="first")
    CLEAN_LOG[name]["exact_duplicates_removed"] = int(duplicate.sum())
    return frame.loc[~duplicate].reset_index(drop=True)


def load_all() -> dict[str, pd.DataFrame]:
    """Return cleaned versions of all seven extracts and refresh CLEAN_LOG."""
    CLEAN_LOG.clear()

    sku = _prepare("sku_master")
    for column in ("shelf_life_months", "pts_inr", "mrp_inr"):
        sku[column] = _number(sku[column])

    batch = _prepare("batch_master")
    batch["mfg_date"], bad_mfg = _date(batch["mfg_date"])
    batch["expiry_date"], bad_expiry = _date(batch["expiry_date"])
    batch["batch_qty_packs"] = _number(batch["batch_qty_packs"])
    CLEAN_LOG["batch_master"].update(
        unparsed_dates=bad_mfg + bad_expiry,
        blank_mfg_site=int(_blank(batch["mfg_site"]).isna().sum()),
    )

    stockist = _prepare("stockist_master")
    stockist["appointed_on"], bad_appointed = _date(stockist["appointed_on"])
    CLEAN_LOG["stockist_master"]["unparsed_dates"] = bad_appointed

    sales = _prepare("primary_sales")
    sales["invoice_date"], bad_invoice = _date(sales["invoice_date"])
    for column in ("ordered_qty", "invoiced_qty", "free_qty", "pts_inr", "net_value_inr"):
        sales[column] = _number(sales[column])
    sales["batch_no"] = _blank(sales["batch_no"])
    sales["scheme_code"] = _blank(sales["scheme_code"])
    CLEAN_LOG["primary_sales"].update(
        unparsed_dates=bad_invoice,
        not_supplied_lines=int(sales["batch_no"].isna().sum()),
    )

    claims = _prepare("expiry_claims")
    bad_dates = 0
    for column in ("claim_date", "expiry_date_as_claimed", "credit_note_date"):
        claims[column], bad = _date(claims[column])
        bad_dates += bad
    for column in ("qty_claimed", "claim_value_inr", "credit_value_inr"):
        claims[column] = _number(claims[column])
    claims["original_invoice_ref"] = _blank(claims["original_invoice_ref"])
    claims["batch_no"] = _blank(claims["batch_no"])
    CLEAN_LOG["expiry_claims"]["unparsed_dates"] = bad_dates

    stock = _prepare("cnf_stock_snapshot")
    stock["snapshot_date"], bad_snapshot = _date(stock["snapshot_date"])
    stock["expiry_date"], bad_stock_expiry = _date(stock["expiry_date"])
    for column in ("qty_on_hand_packs", "avg_monthly_outward_packs"):
        stock[column] = _number(stock[column])
    stock["batch_no"] = _blank(stock["batch_no"])
    CLEAN_LOG["cnf_stock_snapshot"]["unparsed_dates"] = bad_snapshot + bad_stock_expiry

    emails = _prepare("claim_emails")
    emails["received_date"], bad_received = _date(emails["received_date"])
    CLEAN_LOG["claim_emails"]["unparsed_dates"] = bad_received

    return {
        "sku": sku,
        "batch": batch,
        "stockist": stockist,
        "sales": sales,
        "claims": claims,
        "stock": stock,
        "emails": emails,
    }
