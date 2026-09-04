from __future__ import annotations

import io
import zipfile
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field

from . import banking, coa, receipts, reports
from .config import CURRENCY, ONTARIO_HST_RATE, STATEMENTS_DIR
from .ledger import Ledger, LedgerError, get_ledger
from .pdf import table_pdf

app = FastAPI(
    title="Simple Ledger Pro", version="0.1.0", description="Beancount double-entry accounting for Ontario small businesses (CPA Canada / CRA conventions)."
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def ledger_dep() -> Ledger:
    return get_ledger()


def user_dep(x_user: str | None = Header(default=None)) -> str:
    return x_user or "anonymous"


@app.exception_handler(LedgerError)
async def ledger_error_handler(_, exc: LedgerError):
    return Response(content=str(exc), status_code=422, media_type="text/plain")


def _csv(content: str, name: str) -> Response:
    return Response(content, media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{name}"'})


def _pdf(content: bytes, name: str) -> Response:
    return Response(content, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}"'})


def _dec(v: str) -> Decimal:
    try:
        return Decimal(str(v))
    except InvalidOperation:
        raise LedgerError(f"Invalid amount: {v}") from None


# ------------------------------------------------------------------- schemas
class PostingIn(BaseModel):
    account: str
    amount: str = Field(description="Signed CAD amount: positive = debit, negative = credit")
    meta: dict[str, str] | None = None


class TransactionIn(BaseModel):
    date: date
    narration: str
    payee: str | None = None
    postings: list[PostingIn]
    tags: list[str] = []
    links: list[str] = []
    meta: dict[str, str] = {}
    flag: str = "*"


class ReviseIn(BaseModel):
    postings: list[PostingIn]
    narration: str | None = None
    payee: str | None = None


class VoidIn(BaseModel):
    reason: str


class AccountIn(BaseModel):
    name: str
    code: str = ""
    description: str = ""
    gifi: str = ""
    t2125_line: str = ""
    hst_treatment: str = ""


class RuleIn(BaseModel):
    pattern: str
    account: str
    hst: bool = False


# --------------------------------------------------------------------- meta
@app.get("/api/health")
def health(ledger: Ledger = Depends(ledger_dep)):
    errors = ledger.check()
    return {
        "status": "ok" if not errors else "errors",
        "currency": CURRENCY,
        "hst_rate": ONTARIO_HST_RATE,
        "ledger_errors": errors,
        "ledger_file": str(ledger.path),
    }


@app.get("/api/dashboard")
def dashboard(ledger: Ledger = Depends(ledger_dep)):
    return reports.dashboard(ledger)


# ------------------------------------------------------------------ accounts
@app.get("/api/accounts")
def list_accounts(ledger: Ledger = Depends(ledger_dep)):
    bal = ledger.balances()
    out = ledger.open_accounts()
    for a in out:
        signed = bal.get(a["name"], Decimal(0))
        a["balance"] = str(reports._natural(a["name"], signed))
    return out


@app.post("/api/accounts", status_code=201)
def create_account(body: AccountIn, ledger: Ledger = Depends(ledger_dep)):
    return ledger.add_account(body.name, body.code, body.description, body.gifi, body.t2125_line, body.hst_treatment)


@app.get("/api/accounts/export")
def export_accounts(format: str = Query("csv", pattern="^(csv|beancount|json)$"), ledger: Ledger = Depends(ledger_dep)):
    if format == "json":
        return ledger.open_accounts()
    if format == "beancount":
        return PlainTextResponse(
            ledger.coa_path.read_text(encoding="utf-8"), headers={"Content-Disposition": 'attachment; filename="chart_of_accounts.beancount"'}
        )
    live = ledger.open_accounts()
    rows = [coa.Account(a["code"], a["name"], a["description"], a["gifi"], a["t2125_line"], a["hst_treatment"]) for a in live]
    return _csv(coa.to_csv(rows), "chart_of_accounts.csv")


@app.get("/api/accounts/template")
def coa_template(format: str = Query("csv", pattern="^(csv|beancount)$")):
    """The stock Ontario small-business chart of accounts, independent of the live ledger."""
    if format == "beancount":
        return PlainTextResponse(coa.to_beancount(), headers={"Content-Disposition": 'attachment; filename="chart_of_accounts_template.beancount"'})
    return _csv(coa.to_csv(), "chart_of_accounts_template.csv")


# -------------------------------------------------------------- transactions
@app.get("/api/transactions")
def list_transactions(
    start: date | None = None, end: date | None = None, account: str | None = None, limit: int | None = None, ledger: Ledger = Depends(ledger_dep)
):
    return ledger.transactions(start, end, account, limit)


@app.post("/api/transactions", status_code=201)
def create_transaction(body: TransactionIn, ledger: Ledger = Depends(ledger_dep), user: str = Depends(user_dep)):
    return ledger.add_transaction(
        body.date, body.narration, [p.model_dump() for p in body.postings], body.payee, body.tags, body.links, body.meta, created_by=user, flag=body.flag
    )


@app.get("/api/transactions/{txn_id}")
def get_transaction(txn_id: str, ledger: Ledger = Depends(ledger_dep)):
    t = ledger.get_transaction(txn_id)
    if not t:
        raise HTTPException(404, "Transaction not found")
    return t


@app.post("/api/transactions/{txn_id}/void", status_code=201)
def void_transaction(txn_id: str, body: VoidIn, ledger: Ledger = Depends(ledger_dep), user: str = Depends(user_dep)):
    return ledger.void_transaction(txn_id, body.reason, created_by=user)


@app.put("/api/transactions/{txn_id}")
def revise_transaction(txn_id: str, body: ReviseIn, ledger: Ledger = Depends(ledger_dep), user: str = Depends(user_dep)):
    return ledger.revise_pending(txn_id, [p.model_dump() for p in body.postings], body.narration, body.payee, created_by=user)


@app.post("/api/transactions/{txn_id}/categorize")
def categorize(txn_id: str, account: str = Form(...), hst: bool = Form(False), ledger: Ledger = Depends(ledger_dep), user: str = Depends(user_dep)):
    """Replace the Uncategorized leg of a pending bank import with a real account (optional 13% ITC split)."""
    t = ledger.get_transaction(txn_id)
    if not t:
        raise HTTPException(404, "Transaction not found")
    hst_ok = {a["name"]: a["hst_treatment"] for a in ledger.open_accounts()}.get(account) == "taxable"
    postings: list[dict] = []
    for p in t["postings"]:
        if p["account"].endswith(":Uncategorized"):
            amt = Decimal(p["amount"])
            if hst and hst_ok and amt > 0:
                postings += banking.hst_split(account, amt)
            elif hst and hst_ok and amt < 0:
                split = banking.hst_split(account, -amt, itc_account="Liabilities:HST:Collected")
                postings += [{"account": s["account"], "amount": -Decimal(s["amount"])} for s in split]
            else:
                postings.append({"account": account, "amount": amt})
        else:
            postings.append({"account": p["account"], "amount": p["amount"]})
    return ledger.revise_pending(txn_id, postings, created_by=user)


@app.get("/api/ledger/raw", response_class=PlainTextResponse)
def raw_ledger(ledger: Ledger = Depends(ledger_dep)):
    return ledger.raw_text()


@app.get("/api/ledger/export")
def export_ledger(ledger: Ledger = Depends(ledger_dep)):
    """Full ledger bundle (.beancount files + documents + statements) as a zip for the accountant."""
    buf = io.BytesIO()
    root = ledger.path.parent
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in root.rglob("*"):
            if p.is_file():
                z.write(p, p.relative_to(root).as_posix())
    return Response(buf.getvalue(), media_type="application/zip", headers={"Content-Disposition": 'attachment; filename="ledger_bundle.zip"'})


# ------------------------------------------------------------------- reports
def _period(start: date | None, end: date | None) -> tuple[date, date]:
    end = end or date.today()
    start = start or date(end.year, 1, 1)
    if start > end:
        raise LedgerError("start must be on or before end")
    return start, end


@app.get("/api/reports/trial-balance")
def trial_balance(as_of: date | None = None, format: str = "json", ledger: Ledger = Depends(ledger_dep)):
    tb = reports.trial_balance(ledger, as_of)
    if format == "csv":
        rows = "\n".join(f"{r['code']},{r['account']},{r['debit']},{r['credit']}" for r in tb["rows"])
        return _csv(f"code,account,debit,credit\n{rows}\n,TOTAL,{tb['total_debit']},{tb['total_credit']}\n", f"trial_balance_{tb['as_of']}.csv")
    if format == "pdf":
        return _pdf(
            table_pdf(
                "Trial Balance",
                f"As of {tb['as_of']} - {CURRENCY}",
                ["Code", "Account", "Debit", "Credit"],
                [[r["code"], r["account"], r["debit"], r["credit"]] for r in tb["rows"]],
                [["", "TOTAL", tb["total_debit"], tb["total_credit"]]],
            ),
            f"trial_balance_{tb['as_of']}.pdf",
        )
    return tb


@app.get("/api/reports/income-statement")
def income_statement(start: date | None = None, end: date | None = None, format: str = "json", ledger: Ledger = Depends(ledger_dep)):
    s, e = _period(start, end)
    rep = reports.income_statement(ledger, s, e)
    if format == "pdf":
        rows = (
            [["REVENUE", "", ""]]
            + [[r["code"], r["account"], r["balance"]] for r in rep["revenue"]["rows"]]
            + [["", "Total revenue", rep["revenue"]["total"]], ["EXPENSES", "", ""]]
            + [[r["code"], r["account"], r["balance"]] for r in rep["expenses"]["rows"]]
            + [["", "Total expenses", rep["expenses"]["total"]]]
        )
        return _pdf(
            table_pdf("Income Statement", f"{s} to {e} - {CURRENCY}", ["Code", "Account", "Amount"], rows, [["", "NET INCOME", rep["net_income"]]]),
            f"income_statement_{s}_{e}.pdf",
        )
    return rep


@app.get("/api/reports/balance-sheet")
def balance_sheet(as_of: date | None = None, format: str = "json", ledger: Ledger = Depends(ledger_dep)):
    rep = reports.balance_sheet(ledger, as_of or date.today())
    if format == "pdf":
        rows = []
        for sec in ("assets", "liabilities", "equity"):
            rows.append([sec.upper(), "", ""])
            rows += [[r["code"], r["account"], r["balance"]] for r in rep[sec]["rows"]]
            rows.append(["", f"Total {sec}", rep[sec]["total"]])
        return _pdf(
            table_pdf(
                "Balance Sheet",
                f"As of {rep['as_of']} - {CURRENCY}",
                ["Code", "Account", "Amount"],
                rows,
                [["", "TOTAL LIABILITIES + EQUITY", rep["total_liabilities_and_equity"]]],
            ),
            f"balance_sheet_{rep['as_of']}.pdf",
        )
    return rep


@app.get("/api/reports/hst")
def hst(start: date | None = None, end: date | None = None, format: str = "json", ledger: Ledger = Depends(ledger_dep)):
    s, e = _period(start, end)
    rep = reports.hst_return(ledger, s, e)
    if format == "pdf":
        rows = [[k.split("_")[0], k.split("_", 1)[1].replace("_", " "), v] for k, v in rep["lines"].items()]
        return _pdf(
            table_pdf(
                "GST/HST Return Worksheet (GST34)", f"Reporting period {s} to {e} - Ontario HST {ONTARIO_HST_RATE}", ["Line", "Description", "Amount"], rows
            ),
            f"hst_return_{s}_{e}.pdf",
        )
    return rep


@app.get("/api/reports/general-ledger")
def general_ledger(start: date | None = None, end: date | None = None, account: str | None = None, ledger: Ledger = Depends(ledger_dep)):
    return _csv(reports.general_ledger_csv(ledger, start, end, account), "general_ledger.csv")


# ------------------------------------------------------------------- banking
@app.get("/api/bank/statements")
def statements():
    return banking.list_statements()


@app.post("/api/bank/statements/import", status_code=201)
async def import_statement(account: str = Form(...), file: UploadFile = File(...), ledger: Ledger = Depends(ledger_dep), user: str = Depends(user_dep)):
    content = await file.read()
    return banking.import_statement(ledger, account, file.filename or "statement.csv", content, created_by=user)


@app.post("/api/bank/statements/preview")
async def preview_statement(file: UploadFile = File(...)):
    content = await file.read()
    lines = banking.parse_statement_csv(content.decode("utf-8-sig", errors="replace"))
    return banking.statement_line_dicts(lines)


@app.get("/api/bank/statements/{statement_id}/download")
def download_statement_original(statement_id: str):
    metas = [m for m in banking.list_statements() if m["id"] == statement_id]
    if not metas:
        raise HTTPException(404, "Statement not found")
    path = STATEMENTS_DIR / metas[0]["stored_path"]
    return FileResponse(path, filename=metas[0]["original_filename"])


@app.get("/api/bank/statements/{statement_id}/reconcile")
def reconcile(statement_id: str, ledger: Ledger = Depends(ledger_dep)):
    metas = [m for m in banking.list_statements() if m["id"] == statement_id]
    if not metas:
        raise HTTPException(404, "Statement not found")
    return banking.reconcile(ledger, metas[0]["bank_account"], statement_id)


@app.get("/api/bank/accounts/{account:path}/statement")
def account_statement(account: str, start: date | None = None, end: date | None = None, format: str = "json", ledger: Ledger = Depends(ledger_dep)):
    """Ledger-side bank statement (opening balance, activity, running balance, closing balance)."""
    s, e = _period(start, end)
    if account not in ledger.account_names():
        raise HTTPException(404, "Account not found")
    if format == "csv":
        return _csv(banking.account_statement_csv(ledger, account, s, e), f"statement_{account.replace(':', '_')}_{s}_{e}.csv")
    opening, rows, closing = banking.account_statement_rows(ledger, account, s, e)
    if format == "pdf":
        return _pdf(
            table_pdf(
                f"Account Statement - {account}",
                f"{s} to {e} - {CURRENCY}",
                ["Date", "Description", "Counter account", "Debit", "Credit", "Balance"],
                [["", "Opening balance", "", "", "", str(opening)]]
                + [[r["date"], r["description"][:45], r["counter_accounts"][:40], r["debit"], r["credit"], r["balance"]] for r in rows],
                [["", "Closing balance", "", "", "", str(closing)]],
            ),
            f"statement_{account.replace(':', '_')}_{s}_{e}.pdf",
        )
    return {
        "account": account,
        "period": {"start": s.isoformat(), "end": e.isoformat()},
        "opening_balance": str(opening),
        "rows": rows,
        "closing_balance": str(closing),
    }


@app.get("/api/bank/rules")
def rules():
    return banking.load_rules()


@app.put("/api/bank/rules")
def set_rules(body: list[RuleIn], ledger: Ledger = Depends(ledger_dep)):
    names = ledger.account_names()
    for r in body:
        if r.account not in names:
            raise LedgerError(f"Unknown account in rule: {r.account}")
    banking.save_rules([r.model_dump() for r in body])
    return banking.load_rules()


# ------------------------------------------------------------------ receipts
@app.get("/api/receipts")
def list_receipts():
    return receipts.list_receipts()


@app.post("/api/receipts", status_code=201)
async def upload_receipt(
    file: UploadFile = File(...),
    receipt_date: date = Form(...),
    vendor: str = Form(...),
    total: str = Form(...),
    expense_account: str = Form(...),
    paid_from: str = Form(...),
    hst_amount: str | None = Form(None),
    hst_included: bool = Form(True),
    description: str = Form(""),
    create_entry: bool = Form(True),
    ledger: Ledger = Depends(ledger_dep),
    user: str = Depends(user_dep),
):
    content = await file.read()
    return receipts.save_receipt(
        ledger,
        file.filename or "receipt.pdf",
        content,
        receipt_date,
        vendor,
        _dec(total),
        expense_account,
        paid_from,
        _dec(hst_amount) if hst_amount not in (None, "") else None,
        hst_included,
        description,
        created_by=user,
        create_entry=create_entry,
    )


@app.get("/api/receipts/register")
def receipts_register(start: date | None = None, end: date | None = None):
    return _csv(receipts.register_csv(start, end), "receipts_register.csv")


@app.get("/api/receipts/bundle")
def receipts_bundle(start: date | None = None, end: date | None = None):
    """Zip of receipt originals + register CSV for the period (audit support package)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("receipts_register.csv", receipts.register_csv(start, end))
        for r in receipts.list_receipts():
            d = date.fromisoformat(r["date"])
            if (start and d < start) or (end and d > end):
                continue
            try:
                z.write(receipts.receipt_path(r["file"]), r["file"])
            except LedgerError:
                continue
    return Response(buf.getvalue(), media_type="application/zip", headers={"Content-Disposition": 'attachment; filename="receipts_bundle.zip"'})


@app.get("/api/receipts/file/{rel:path}")
def receipt_file(rel: str):
    return FileResponse(receipts.receipt_path(rel), filename=Path(rel).name)


@app.get("/api/documents")
def documents(ledger: Ledger = Depends(ledger_dep)):
    return ledger.documents()


# ---------------------------------------------------------------------- demo
@app.post("/api/demo/seed", status_code=201)
def seed(ledger: Ledger = Depends(ledger_dep), user: str = Depends(user_dep)):
    """Post a small set of illustrative Ontario transactions (idempotent by tag)."""
    if any("demo" in t["tags"] for t in ledger.transactions()):
        return {"seeded": False, "reason": "demo data already present"}
    y = date.today().year
    entries = [
        (
            date(y, 1, 2),
            "Owner",
            "Opening balance - share capital",
            [("Assets:Current:Bank:Chequing", "25000.00"), ("Equity:ShareCapital:Common", "-25000.00")],
        ),
        (
            date(y, 1, 15),
            "Acme Corp",
            "Invoice #1001 consulting",
            [("Assets:Current:AccountsReceivable", "5650.00"), ("Income:Sales:Services", "-5000.00"), ("Liabilities:HST:Collected", "-650.00")],
        ),
        (
            date(y, 1, 31),
            "Acme Corp",
            "Payment received #1001",
            [("Assets:Current:Bank:Chequing", "5650.00"), ("Assets:Current:AccountsReceivable", "-5650.00")],
        ),
        (
            date(y, 2, 1),
            "Regus",
            "February office rent",
            [("Expenses:Rent", "1500.00"), ("Liabilities:HST:ITC", "195.00"), ("Assets:Current:Bank:Chequing", "-1695.00")],
        ),
        (
            date(y, 2, 10),
            "Staples",
            "Printer paper and toner",
            [("Expenses:OfficeSupplies", "120.35"), ("Liabilities:HST:ITC", "15.65"), ("Liabilities:Current:CreditCard", "-136.00")],
        ),
        (
            date(y, 2, 14),
            "Bell Canada",
            "Business internet",
            [("Expenses:Telephone", "89.99"), ("Liabilities:HST:ITC", "11.70"), ("Assets:Current:Bank:Chequing", "-101.69")],
        ),
        (
            date(y, 2, 28),
            "Intact Insurance",
            "Commercial liability (HST exempt)",
            [("Expenses:Insurance", "210.00"), ("Assets:Current:Bank:Chequing", "-210.00")],
        ),
    ]
    ids = []
    for d, payee, narr, posts in entries:
        t = ledger.add_transaction(
            d, narr, [{"account": a, "amount": Decimal(v)} for a, v in posts], payee=payee, tags=["demo"], created_by=user, source="demo"
        )
        ids.append(t["id"])
    return {"seeded": True, "transaction_ids": ids}
