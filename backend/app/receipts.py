"""Receipt (source document) management.

A receipt is stored under ``data/documents/<Account path>/YYYY-MM-DD.<vendor>.<ext>``
(Beancount's documents convention) and recorded with a ``document`` directive
linked to the journal entry it supports via ``^receipt-<id>``. CRA requires
source documents to be retained for six years from the end of the tax year;
originals are never deleted by the application.
"""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from .banking import hst_split
from .config import DOCUMENTS_DIR
from .ledger import Ledger, LedgerError, q

ALLOWED_EXT = {".pdf", ".png", ".jpg", ".jpeg", ".heic", ".webp", ".gif", ".tif", ".tiff"}
REGISTER = DOCUMENTS_DIR / "receipts.jsonl"


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-")[:40] or "receipt"


def save_receipt(
    ledger: Ledger,
    filename: str,
    content: bytes,
    receipt_date: date,
    vendor: str,
    total: Decimal,
    expense_account: str,
    paid_from: str,
    hst_amount: Decimal | None = None,
    hst_included: bool = True,
    description: str = "",
    created_by: str = "api",
    create_entry: bool = True,
) -> dict:
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise LedgerError(f"Unsupported receipt type {ext}; allowed: {sorted(ALLOWED_EXT)}")
    if not content:
        raise LedgerError("Empty file")
    names = ledger.account_names()
    if expense_account not in names or paid_from not in names:
        raise LedgerError("Unknown expense or payment account")
    total = q(total)
    if total <= 0:
        raise LedgerError("Receipt total must be positive")

    hst_by_account = {a["name"]: a["hst_treatment"] for a in ledger.open_accounts()}
    if hst_amount is None:
        if hst_included and hst_by_account.get(expense_account) == "taxable":
            split = hst_split(expense_account, total)
            hst_amount = q(sum(Decimal(p["amount"]) for p in split if p["account"] == "Liabilities:HST:ITC"))
        else:
            hst_amount = Decimal("0.00")
    hst_amount = q(hst_amount)
    if hst_amount < 0 or hst_amount >= total:
        raise LedgerError("HST amount must be between 0 and the receipt total")
    net = q(total - hst_amount)

    folder = DOCUMENTS_DIR / Path(*expense_account.split(":"))
    folder.mkdir(parents=True, exist_ok=True)
    base = f"{receipt_date.isoformat()}.{_slug(vendor)}"
    path = folder / f"{base}{ext}"
    n = 1
    while path.exists():
        n += 1
        path = folder / f"{base}-{n}{ext}"
    path.write_bytes(content)

    txn = None
    link = f"receipt-{datetime.now().strftime('%Y%m%d%H%M%S%f')[:-3]}"
    try:
        ledger.add_document(expense_account, path, receipt_date, links=[link])
    except LedgerError:
        path.unlink(missing_ok=True)
        raise
    if create_entry:
        postings = [{"account": expense_account, "amount": net}]
        if hst_amount:
            postings.append({"account": "Liabilities:HST:ITC", "amount": hst_amount})
        postings.append({"account": paid_from, "amount": -total})
        txn = ledger.add_transaction(
            receipt_date,
            description or f"Receipt {vendor}",
            postings,
            payee=vendor,
            links=[link],
            meta={"receipt": path.relative_to(DOCUMENTS_DIR.parent).as_posix(), "hst_amount": str(hst_amount)},
            created_by=created_by,
            source="receipt",
        )

    record = {
        "id": link,
        "date": receipt_date.isoformat(),
        "vendor": vendor,
        "description": description,
        "total": str(total),
        "hst": str(hst_amount),
        "net": str(net),
        "expense_account": expense_account,
        "paid_from": paid_from,
        "file": path.relative_to(DOCUMENTS_DIR).as_posix(),
        "transaction_id": txn["id"] if txn else None,
        "uploaded_at": datetime.now().isoformat(timespec="seconds"),
        "uploaded_by": created_by,
    }
    with REGISTER.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
    return record


def list_receipts() -> list[dict]:
    if not REGISTER.exists():
        return []
    out = [json.loads(ln) for ln in REGISTER.read_text(encoding="utf-8").splitlines() if ln.strip()]
    out.sort(key=lambda r: r["date"], reverse=True)
    return out


def receipt_path(rel: str) -> Path:
    p = (DOCUMENTS_DIR / rel).resolve()
    if DOCUMENTS_DIR.resolve() not in p.parents or not p.is_file():
        raise LedgerError("Receipt not found")
    return p


def register_csv(start: date | None = None, end: date | None = None) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        ["date", "vendor", "description", "total", "hst_itc", "net", "expense_account", "paid_from", "transaction_id", "file", "uploaded_at", "uploaded_by"]
    )
    for r in sorted(list_receipts(), key=lambda r: r["date"]):
        d = date.fromisoformat(r["date"])
        if (start and d < start) or (end and d > end):
            continue
        w.writerow(
            [
                r["date"],
                r["vendor"],
                r["description"],
                r["total"],
                r["hst"],
                r["net"],
                r["expense_account"],
                r["paid_from"],
                r["transaction_id"] or "",
                r["file"],
                r["uploaded_at"],
                r["uploaded_by"],
            ]
        )
    return buf.getvalue()
