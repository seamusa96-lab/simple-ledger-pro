"""Bank statement import, categorization rules, reconciliation and export.

Sign convention for statement lines: ``amount`` is from the *bank account's*
point of view - deposits positive (debit to the asset), withdrawals negative.
Each imported line becomes a pending ('!') journal entry against
Expenses:Uncategorized / Income:Uncategorized unless a rule matches, in which
case it is posted as cleared with an automatic 13% HST/ITC split where the
target account is HST-taxable.
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from .config import ONTARIO_HST_RATE, RULES_FILE, STATEMENTS_DIR, UNCATEGORIZED_EXPENSE, UNCATEGORIZED_INCOME
from .ledger import Ledger, LedgerError, q

DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y%m%d", "%d-%b-%Y", "%b %d, %Y", "%m/%d/%y", "%Y/%m/%d")


@dataclass
class StatementLine:
    date: date
    description: str
    amount: Decimal
    balance: Decimal | None = None
    reference: str = ""


DEFAULT_RULES = [
    {"pattern": r"SHELL|PETRO-?CAN|ESSO|HUSKY|PIONEER|ULTRAMAR", "account": "Expenses:MotorVehicle", "hst": True},
    {"pattern": r"BELL CANADA|ROGERS|TELUS|FREEDOM MOBILE|FIDO|KOODO", "account": "Expenses:Telephone", "hst": True},
    {"pattern": r"HYDRO ONE|TORONTO HYDRO|ALECTRA|ENBRIDGE|UNION GAS", "account": "Expenses:Utilities", "hst": True},
    {"pattern": r"STAPLES|BUREAU EN GROS|AMAZON|AMZN", "account": "Expenses:OfficeSupplies", "hst": True},
    {"pattern": r"GOOGLE|MICROSOFT|ADOBE|ZOOM|SHOPIFY|QUICKBOOKS|INTUIT|DROPBOX|GITHUB", "account": "Expenses:Software", "hst": True},
    {"pattern": r"TIM HORTONS|STARBUCKS|RESTAURANT|UBER EATS|SKIP", "account": "Expenses:MealsEntertainment", "hst": True},
    {"pattern": r"MONTHLY FEE|SERVICE CHARGE|ACCOUNT FEE|NSF|OVERDRAFT|INTEREST CHARGE", "account": "Expenses:InterestBankCharges", "hst": False},
    {"pattern": r"INTEREST (PAID|CREDIT|EARNED)", "account": "Income:Other:Interest", "hst": False},
    {"pattern": r"INTACT|AVIVA|DESJARDINS INS|CO-?OPERATORS|INSURANCE", "account": "Expenses:Insurance", "hst": False},
    {"pattern": r"CRA .*GST|CANADA REVENUE.*GST|GST/HST", "account": "Liabilities:HST:Instalments", "hst": False},
    {"pattern": r"CRA .*PAYROLL|RP0001|SOURCE DED", "account": "Liabilities:Current:PayrollDeductions:IncomeTax", "hst": False},
    {"pattern": r"CRA .*CORP|RC0001 CORP|T2 ", "account": "Liabilities:Current:CorporateTaxPayable", "hst": False},
    {"pattern": r"WSIB", "account": "Liabilities:Current:WSIB", "hst": False},
    {"pattern": r"UBER|LYFT|VIA RAIL|AIR CANADA|WESTJET|PORTER|HOTEL|MARRIOTT|HILTON", "account": "Expenses:Travel", "hst": True},
    {"pattern": r"RENT|PROPERTY MGMT", "account": "Expenses:Rent", "hst": True},
]


def load_rules() -> list[dict]:
    if RULES_FILE.exists():
        return json.loads(RULES_FILE.read_text(encoding="utf-8"))
    RULES_FILE.parent.mkdir(parents=True, exist_ok=True)
    RULES_FILE.write_text(json.dumps(DEFAULT_RULES, indent=2), encoding="utf-8")
    return list(DEFAULT_RULES)


def save_rules(rules: list[dict]) -> None:
    for r in rules:
        re.compile(r["pattern"])
    RULES_FILE.write_text(json.dumps(rules, indent=2), encoding="utf-8")


def match_rule(description: str, rules: list[dict]) -> dict | None:
    for r in rules:
        if re.search(r["pattern"], description, re.IGNORECASE):
            return r
    return None


# --------------------------------------------------------------------- parsing
def parse_date(s: str) -> date | None:
    s = s.strip().strip('"')
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_amount(s: str) -> Decimal | None:
    s = s.strip().replace("$", "").replace(",", "").replace(" ", "")
    if not s or s in ("-", "--"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    if s.endswith("CR"):
        s = s[:-2]
    try:
        v = Decimal(s)
    except Exception:
        return None
    return -v if neg else v


def _norm(h: str) -> str:
    return re.sub(r"[^a-z0-9]", "", h.lower())


def parse_statement_csv(text: str) -> list[StatementLine]:
    """Heuristic parser for Canadian bank CSV exports (RBC, TD, BMO, Scotiabank, CIBC, Tangerine, generic)."""
    text = text.lstrip("\ufeff")
    rows = [r for r in csv.reader(io.StringIO(text)) if any(c.strip() for c in r)]
    if not rows:
        return []
    header = [_norm(c) for c in rows[0]]
    has_header = parse_date(rows[0][0]) is None and any(
        any(k in h for k in ("date", "description", "amount", "debit", "credit", "withdrawal", "deposit")) for h in header
    )
    lines: list[StatementLine] = []
    if has_header:
        idx = {h: i for i, h in enumerate(header)}

        def find(*keys):
            for k in keys:
                for h, i in idx.items():
                    if k in h:
                        return i
            return None

        i_date = find("transactiondate", "dateposted", "postingdate", "date")
        i_desc = [i for h, i in idx.items() if any(k in h for k in ("description", "memo", "payee", "name", "transactiontype", "details"))]
        i_amt = find("cad", "transactionamount", "amount")
        i_debit = find("debit", "withdrawal", "moneyout", "outflow")
        i_credit = find("credit", "deposit", "moneyin", "inflow")
        i_bal = find("balance")
        i_ref = find("cheque", "reference")
        if i_date is None:
            raise LedgerError("Could not find a date column in the statement CSV")
        for r in rows[1:]:
            if len(r) <= i_date:
                continue
            d = parse_date(r[i_date])
            if d is None:
                continue
            desc = " ".join(r[i].strip() for i in i_desc if i < len(r) and r[i].strip()) or "Bank transaction"
            amt = None
            if i_debit is not None or i_credit is not None:
                deb = parse_amount(r[i_debit]) if i_debit is not None and i_debit < len(r) else None
                cre = parse_amount(r[i_credit]) if i_credit is not None and i_credit < len(r) else None
                if deb is not None or cre is not None:
                    amt = (cre or Decimal(0)) - abs(deb or Decimal(0))
            if amt is None and i_amt is not None and i_amt < len(r):
                amt = parse_amount(r[i_amt])
            if amt is None:
                continue
            bal = parse_amount(r[i_bal]) if i_bal is not None and i_bal < len(r) else None
            ref = r[i_ref].strip() if i_ref is not None and i_ref < len(r) else ""
            lines.append(StatementLine(d, desc, q(amt), q(bal) if bal is not None else None, ref))
    else:
        # Header-less positional exports (TD, CIBC, Scotiabank): date, desc, debit, credit[, balance]
        # or Scotiabank style: date, amount, *, description
        for r in rows:
            d = parse_date(r[0])
            if d is None or len(r) < 2:
                continue
            nums = [(i, parse_amount(c)) for i, c in enumerate(r[1:], start=1)]
            numeric = [(i, v) for i, v in nums if v is not None and not re.search(r"[A-Za-z]{3,}", r[i])]
            texts = [r[i].strip() for i in range(1, len(r)) if r[i].strip() and (i, parse_amount(r[i])) not in numeric]
            desc = " ".join(texts) or "Bank transaction"
            if len(numeric) >= 3:
                (_, deb), (_, cre), (_, bal) = numeric[0], numeric[1], numeric[2]
                amt = (cre or Decimal(0)) - abs(deb or Decimal(0))
            elif len(numeric) == 2:
                (_, a), (_, b) = numeric
                # TD/CIBC leave one of debit/credit empty; two numbers means debit+credit with one zero, or amount+balance
                if a == 0 or b == 0:
                    amt, bal = (b if a == 0 else -abs(a)), None
                else:
                    amt, bal = a, b
            elif len(numeric) == 1:
                amt, bal = numeric[0][1], None
            else:
                continue
            lines.append(StatementLine(d, desc, q(amt), q(bal) if bal is not None else None))
    lines.sort(key=lambda ln: ln.date)
    return lines


# ---------------------------------------------------------------------- import
def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")


def store_statement(bank_account: str, filename: str, content: bytes) -> tuple[str, Path]:
    folder = STATEMENTS_DIR / _slug(bank_account)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe = f"{stamp}_{_slug(Path(filename).stem)}{Path(filename).suffix.lower() or '.csv'}"
    path = folder / safe
    path.write_bytes(content)
    return safe, path


def list_statements() -> list[dict]:
    out = []
    for meta in STATEMENTS_DIR.glob("*/*.json"):
        out.append(json.loads(meta.read_text(encoding="utf-8")))
    out.sort(key=lambda s: s["imported_at"], reverse=True)
    return out


def import_statement(ledger: Ledger, bank_account: str, filename: str, content: bytes, created_by: str = "api") -> dict:
    if bank_account not in ledger.account_names() or not bank_account.startswith(("Assets:", "Liabilities:")):
        raise LedgerError("Bank account must be an open Assets or Liabilities account")
    lines = parse_statement_csv(content.decode("utf-8-sig", errors="replace"))
    if not lines:
        raise LedgerError("No transactions could be parsed from the file")
    stored_name, stored_path = store_statement(bank_account, filename, content)
    rules = load_rules()
    existing = ledger.import_ids()
    hst_by_account = {a["name"]: a["hst_treatment"] for a in ledger.open_accounts()}
    imported, skipped, categorized = [], 0, 0
    seen: dict[str, int] = {}
    for ln in lines:
        key = f"{bank_account}|{ln.date}|{ln.description}|{ln.amount}"
        seen[key] = seen.get(key, 0) + 1
        import_id = Ledger.make_import_id(key, str(seen[key]))
        if import_id in existing:
            skipped += 1
            continue
        rule = match_rule(ln.description, rules)
        postings = [{"account": bank_account, "amount": ln.amount}]
        if rule:
            target = rule["account"]
            if target not in hst_by_account:
                rule = None
        if rule:
            counter = -ln.amount
            if rule.get("hst") and hst_by_account.get(target) == "taxable":
                postings += hst_split(target, counter)
            else:
                postings.append({"account": target, "amount": counter})
            flag = "*"
            categorized += 1
        else:
            postings.append({"account": UNCATEGORIZED_EXPENSE if ln.amount < 0 else UNCATEGORIZED_INCOME, "amount": -ln.amount})
            flag = "!"
        meta = {"import_id": import_id, "statement": stored_name}
        if ln.reference:
            meta["reference"] = ln.reference
        if ln.balance is not None:
            meta["statement_balance"] = str(ln.balance)
        t = ledger.add_transaction(ln.date, ln.description, postings, payee=None, meta=meta, created_by=created_by, source="bank-import", flag=flag)
        imported.append(t["id"])
    summary = {
        "id": stored_name,
        "bank_account": bank_account,
        "original_filename": filename,
        "stored_path": str(stored_path.relative_to(STATEMENTS_DIR)),
        "imported_at": datetime.now().isoformat(timespec="seconds"),
        "imported_by": created_by,
        "period_start": lines[0].date.isoformat(),
        "period_end": lines[-1].date.isoformat(),
        "line_count": len(lines),
        "imported": len(imported),
        "auto_categorized": categorized,
        "skipped_duplicates": skipped,
        "closing_balance": str(lines[-1].balance) if lines[-1].balance is not None else None,
        "transaction_ids": imported,
    }
    stored_path.with_suffix(".json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def hst_split(expense_account: str, gross: Decimal, rate: Decimal = Decimal(ONTARIO_HST_RATE), itc_account: str = "Liabilities:HST:ITC") -> list[dict]:
    """Split a tax-inclusive amount into net expense + ITC. Rounding lands on the expense line."""
    gross = q(gross)
    net = q(gross / (1 + rate))
    hst = q(gross - net)
    out = [{"account": expense_account, "amount": net}]
    if hst != 0:
        out.append({"account": itc_account, "amount": hst})
    return out


# -------------------------------------------------------------- reconciliation
def reconcile(ledger: Ledger, bank_account: str, statement_id: str) -> dict:
    metas = [m for m in list_statements() if m["id"] == statement_id]
    if not metas:
        raise LedgerError("Statement not found")
    meta = metas[0]
    path = STATEMENTS_DIR / meta["stored_path"]
    lines = parse_statement_csv(path.read_text(encoding="utf-8-sig", errors="replace"))
    start, end = date.fromisoformat(meta["period_start"]), date.fromisoformat(meta["period_end"])
    ledger_txns = [t for t in ledger.transactions(start, end, bank_account)]
    by_import = {t["meta"].get("import_id"): t for t in ledger_txns if t["meta"].get("import_id")}

    seen: dict[str, int] = {}
    matched, unmatched_statement = [], []
    used = set()
    for ln in lines:
        key = f"{bank_account}|{ln.date}|{ln.description}|{ln.amount}"
        seen[key] = seen.get(key, 0) + 1
        iid = Ledger.make_import_id(key, str(seen[key]))
        t = by_import.get(iid)
        if t is None:
            # fall back to date+amount match against manually entered entries
            for cand in ledger_txns:
                if cand["id"] in used or cand["id"] in {x["id"] for x in by_import.values()}:
                    continue
                amt = sum(Decimal(p["amount"]) for p in cand["postings"] if p["account"] == bank_account)
                if cand["date"] == ln.date.isoformat() and q(amt) == ln.amount:
                    t = cand
                    break
        if t:
            used.add(t["id"])
            matched.append({"date": ln.date.isoformat(), "description": ln.description, "amount": str(ln.amount), "transaction_id": t["id"], "flag": t["flag"]})
        else:
            unmatched_statement.append({"date": ln.date.isoformat(), "description": ln.description, "amount": str(ln.amount)})
    unmatched_ledger = [
        {
            "date": t["date"],
            "id": t["id"],
            "narration": t["narration"],
            "amount": str(q(sum(Decimal(p["amount"]) for p in t["postings"] if p["account"] == bank_account))),
        }
        for t in ledger_txns
        if t["id"] not in used
    ]
    ledger_balance = q(ledger.balances(end=end).get(bank_account, Decimal(0)))
    closing = Decimal(meta["closing_balance"]) if meta.get("closing_balance") else None
    if bank_account.startswith("Liabilities:") and closing is not None:
        closing = -closing  # card statements show amount owing as positive
    return {
        "statement": meta,
        "ledger_balance_at_period_end": str(ledger_balance),
        "statement_closing_balance": str(closing) if closing is not None else None,
        "difference": str(q(ledger_balance - closing)) if closing is not None else None,
        "reconciled": closing is not None and ledger_balance == closing and not unmatched_statement and not unmatched_ledger,
        "matched": matched,
        "unmatched_statement_lines": unmatched_statement,
        "unmatched_ledger_entries": unmatched_ledger,
    }


# --------------------------------------------------------------------- export
def account_statement_rows(ledger: Ledger, account: str, start: date, end: date) -> tuple[Decimal, list[dict], Decimal]:
    opening = q(ledger.balances(end=start - timedelta(days=1)).get(account, Decimal(0)))
    running = opening
    rows = []
    for t in sorted(ledger.transactions(start, end, account), key=lambda t: (t["date"], t["meta"].get("created_at", ""))):
        amt = q(sum(Decimal(p["amount"]) for p in t["postings"] if p["account"] == account))
        running = q(running + amt)
        other = ", ".join(sorted({p["account"] for p in t["postings"] if p["account"] != account}))
        rows.append(
            {
                "date": t["date"],
                "id": t["id"],
                "flag": t["flag"],
                "description": " - ".join(x for x in (t["payee"], t["narration"]) if x),
                "counter_accounts": other,
                "debit": str(amt) if amt > 0 else "",
                "credit": str(-amt) if amt < 0 else "",
                "balance": str(running),
            }
        )
    return opening, rows, running


def account_statement_csv(ledger: Ledger, account: str, start: date, end: date) -> str:
    opening, rows, closing = account_statement_rows(ledger, account, start, end)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["account", account])
    w.writerow(["period", start.isoformat(), end.isoformat()])
    w.writerow(["opening_balance", str(opening)])
    w.writerow([])
    w.writerow(["date", "id", "flag", "description", "counter_accounts", "debit", "credit", "balance"])
    for r in rows:
        w.writerow([r[k] for k in ("date", "id", "flag", "description", "counter_accounts", "debit", "credit", "balance")])
    w.writerow([])
    w.writerow(["closing_balance", str(closing)])
    return buf.getvalue()


def statement_line_dicts(lines: list[StatementLine]) -> list[dict]:
    return [
        {**asdict(ln), "date": ln.date.isoformat(), "amount": str(ln.amount), "balance": str(ln.balance) if ln.balance is not None else None} for ln in lines
    ]
