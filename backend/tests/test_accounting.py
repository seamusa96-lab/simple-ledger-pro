"""Accounting invariants: double entry, Decimal precision, HST, audit trail, reports."""

import io
from datetime import date
from decimal import Decimal

from app.banking import hst_split, parse_amount
from app.ledger import q

BANK = "Assets:Current:Bank:Chequing"
Y = date.today().year


def _txn(client, postings, narration="test", d=f"{Y}-03-01", flag="*"):
    return client.post(
        "/api/transactions",
        json={"date": d, "narration": narration, "postings": [{"account": a, "amount": v} for a, v in postings], "flag": flag},
    )


# ------------------------------------------------------------------ rounding
def test_quantize_half_up():
    assert q("1.005") == Decimal("1.01")
    assert q("2.675") == Decimal("2.68")
    assert q(0.1 + 0.2) == Decimal("0.30")


def test_hst_split_sums_to_gross():
    for gross in ("113.00", "0.01", "1695.00", "136.00", "101.69", "999.99"):
        parts = hst_split("Expenses:Rent", Decimal(gross))
        assert sum(p["amount"] for p in parts) == Decimal(gross)
        assert all(p["amount"] == q(p["amount"]) for p in parts)
    parts = hst_split("Expenses:Rent", Decimal("113.00"))
    assert parts[0]["amount"] == Decimal("100.00")
    assert parts[1]["amount"] == Decimal("13.00")


def test_hst_split_meals_half_itc():
    # Meals & entertainment: only 50% of the HST is a recoverable ITC; the
    # non-creditable half stays on the expense and postings still sum to gross.
    parts = hst_split("Expenses:MealsEntertainment", Decimal("113.00"))
    by_acct = {p["account"]: p["amount"] for p in parts}
    assert by_acct["Liabilities:HST:ITC"] == Decimal("6.50")
    assert by_acct["Expenses:MealsEntertainment"] == Decimal("106.50")
    assert sum(p["amount"] for p in parts) == Decimal("113.00")


def test_parse_amount_formats():
    assert parse_amount("$1,234.56") == Decimal("1234.56")
    assert parse_amount("(50.00)") == Decimal("-50.00")
    assert parse_amount("25.00 CR") == Decimal("25.00")
    assert parse_amount("--") is None


# ------------------------------------------------------------------ double entry
def test_unbalanced_entry_rejected(seeded):
    r = _txn(seeded, [(BANK, "100.00"), ("Expenses:Rent", "-99.00")])
    assert r.status_code == 422
    assert "balance" in r.text.lower()


def test_unknown_account_rejected(seeded):
    r = _txn(seeded, [(BANK, "-10.00"), ("Expenses:DoesNotExist", "10.00")])
    assert r.status_code == 422


def test_zero_or_single_posting_rejected(seeded):
    assert _txn(seeded, [(BANK, "0.00"), ("Expenses:Rent", "0.00")]).status_code == 422
    assert _txn(seeded, [(BANK, "10.00")]).status_code == 422


def test_balanced_entry_persists_with_audit_meta(seeded):
    r = _txn(seeded, [("Expenses:Rent", "100.00"), (BANK, "-100.00")], narration="audit test")
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["meta"]["created_by"] == "pytest"
    assert t["meta"]["created_at"]
    assert t["meta"]["id"]
    assert sum(Decimal(p["amount"]) for p in t["postings"]) == 0


# ------------------------------------------------------------------ reports
def test_trial_balance_balanced(seeded):
    tb = seeded.get("/api/reports/trial-balance").json()
    assert tb["balanced"] is True
    assert Decimal(tb["total_debit"]) == Decimal(tb["total_credit"])
    assert Decimal(tb["total_debit"]) > 0


def test_balance_sheet_equation(seeded):
    bs = seeded.get(f"/api/reports/balance-sheet?as_of={Y}-12-31").json()
    assert bs["balanced"] is True
    assets = Decimal(bs["assets"]["total"])
    liab = Decimal(bs["liabilities"]["total"])
    equity = Decimal(bs["equity"]["total"])
    assert assets == liab + equity
    assert Decimal(bs["total_liabilities_and_equity"]) == assets


def test_income_statement_net_income(seeded):
    is_ = seeded.get(f"/api/reports/income-statement?start={Y}-01-01&end={Y}-12-31").json()
    assert Decimal(is_["revenue"]["total"]) - Decimal(is_["expenses"]["total"]) == Decimal(is_["net_income"])


def test_hst_return_lines(seeded):
    hst = seeded.get(f"/api/reports/hst?start={Y}-01-01&end={Y}-12-31").json()
    lines = {k.split("_")[0]: Decimal(v) for k, v in hst["lines"].items()}
    assert lines["101"] >= Decimal("5000.00")
    assert lines["105"] >= Decimal("650.00")
    assert lines["108"] >= Decimal("195.00")
    assert lines["109"] == lines["105"] - lines["108"]
    assert lines["113"] == lines["109"] - lines["110"]


# ------------------------------------------------------------------ audit-safe corrections
def test_void_creates_reversal_not_edit(seeded):
    t = _txn(seeded, [("Expenses:Advertising", "50.00"), (BANK, "-50.00")], narration="to void").json()
    r = seeded.post(f"/api/transactions/{t['id']}/void", json={"reason": "posted in error"})
    assert r.status_code in (200, 201), r.text
    rev = r.json()
    assert rev["meta"]["reverses"] == t["id"]
    by_acct = {p["account"]: Decimal(p["amount"]) for p in rev["postings"]}
    assert by_acct["Expenses:Advertising"] == Decimal("-50.00")
    assert by_acct[BANK] == Decimal("50.00")
    # original still present, untouched
    assert seeded.get(f"/api/transactions/{t['id']}").json()["narration"] == "to void"
    # second void rejected
    assert seeded.post(f"/api/transactions/{t['id']}/void", json={"reason": "again"}).status_code == 422


def test_cleared_entry_cannot_be_revised(seeded):
    t = _txn(seeded, [("Expenses:Advertising", "10.00"), (BANK, "-10.00")]).json()
    r = seeded.put(f"/api/transactions/{t['id']}", json={"postings": [{"account": "Expenses:Rent", "amount": "10.00"}, {"account": BANK, "amount": "-10.00"}]})
    assert r.status_code == 422


# ------------------------------------------------------------------ bank import
CSV = f"""Date,Description,Debit,Credit,Balance
{Y}-03-02,SHELL 1234 TORONTO,45.20,,25000.00
{Y}-03-03,MYSTERY VENDOR,80.00,,24920.00
{Y}-03-04,E-TRANSFER FROM CLIENT,,1130.00,26050.00
"""


def test_bank_import_categorizes_and_dedups(seeded):
    files = {"file": ("march.csv", io.BytesIO(CSV.encode()), "text/csv")}
    r = seeded.post("/api/bank/statements/import", data={"account": BANK}, files=files)
    assert r.status_code in (200, 201), r.text
    s = r.json()
    assert s["imported"] == 3
    assert s["auto_categorized"] >= 1
    assert s["imported"] - s["auto_categorized"] >= 1
    assert seeded.get("/api/reports/trial-balance").json()["balanced"] is True

    files = {"file": ("march.csv", io.BytesIO(CSV.encode()), "text/csv")}
    again = seeded.post("/api/bank/statements/import", data={"account": BANK}, files=files).json()
    assert again["imported"] == 0
    assert again["skipped_duplicates"] == 3

    pending = [t for t in seeded.get("/api/transactions?flag=!").json() if "MYSTERY" in t["narration"].upper()]
    assert pending
    r = seeded.post(f"/api/transactions/{pending[0]['id']}/categorize", data={"account": "Expenses:OfficeSupplies", "hst": "true"})
    assert r.status_code == 200, r.text
    accts = {p["account"]: Decimal(p["amount"]) for p in r.json()["postings"]}
    assert accts["Expenses:OfficeSupplies"] + accts["Liabilities:HST:ITC"] == Decimal("80.00")
    assert accts["Liabilities:HST:ITC"] == Decimal("9.20")
    assert r.json()["flag"] == "*"

    rec = seeded.get(f"/api/bank/statements/{s['id']}/reconcile")
    assert rec.status_code == 200, rec.text
    assert rec.json()["unmatched_statement_lines"] == []


# ------------------------------------------------------------------ receipts
def test_receipt_creates_document_and_entry(seeded):
    pdf = b"%PDF-1.4\n%%EOF\n"
    r = seeded.post(
        "/api/receipts",
        data={
            "receipt_date": f"{Y}-03-05",
            "vendor": "Home Depot",
            "total": "113.00",
            "expense_account": "Expenses:RepairsMaintenance",
            "paid_from": "Liabilities:Current:CreditCard",
        },
        files={"file": ("receipt.pdf", io.BytesIO(pdf), "application/pdf")},
    )
    assert r.status_code == 201, r.text
    rc = r.json()
    assert Decimal(rc["hst"]) == Decimal("13.00")
    assert Decimal(rc["net"]) == Decimal("100.00")
    assert rc["transaction_id"]
    docs = seeded.get("/api/documents").json()
    assert any("Home" in d["filename"] for d in docs)
    dl = seeded.get(f"/api/receipts/file/{rc['file']}")
    assert dl.status_code == 200 and dl.content == pdf
    assert seeded.get("/api/health").json()["ledger_errors"] == []


def test_receipt_meals_half_itc(seeded):
    # Meals receipt: only 50% of the HST is a recoverable ITC; the non-creditable
    # half stays on the expense so total = net + ITC still holds.
    pdf = b"%PDF-1.4\n%%EOF\n"
    r = seeded.post(
        "/api/receipts",
        data={
            "receipt_date": f"{Y}-03-06",
            "vendor": "The Keg",
            "total": "113.00",
            "expense_account": "Expenses:MealsEntertainment",
            "paid_from": "Liabilities:Current:CreditCard",
        },
        files={"file": ("meal.pdf", io.BytesIO(pdf), "application/pdf")},
    )
    assert r.status_code == 201, r.text
    rc = r.json()
    assert Decimal(rc["hst"]) == Decimal("6.50")
    assert Decimal(rc["net"]) == Decimal("106.50")
    assert Decimal(rc["net"]) + Decimal(rc["hst"]) == Decimal(rc["total"])
    assert seeded.get("/api/health").json()["ledger_errors"] == []


def test_receipt_bad_type_rejected(seeded):
    r = seeded.post(
        "/api/receipts",
        data={"receipt_date": f"{Y}-03-05", "vendor": "X", "total": "1.00", "expense_account": "Expenses:Rent", "paid_from": BANK},
        files={"file": ("evil.exe", io.BytesIO(b"x"), "application/octet-stream")},
    )
    assert r.status_code == 422


# ------------------------------------------------------------------ downloads
def test_downloads(seeded):
    for url in [
        "/api/accounts/export?format=csv",
        "/api/accounts/export?format=beancount",
        "/api/ledger/export",
        "/api/reports/general-ledger",
        "/api/receipts/register",
        "/api/receipts/bundle",
        "/api/reports/trial-balance?format=pdf",
        f"/api/bank/accounts/{BANK}/statement?format=pdf",
    ]:
        r = seeded.get(url)
        assert r.status_code == 200, url
        assert len(r.content) > 0
