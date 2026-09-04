"""Financial statements derived from the Beancount ledger.

Sign convention: Beancount stores credit-normal accounts (Liabilities, Equity,
Income) as negative numbers. Reports present every figure in its *natural*
balance (positive), and only the trial balance shows raw debit/credit columns.
"""

from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal

from .config import ONTARIO_HST_RATE
from .ledger import Ledger, q

ZERO = Decimal("0.00")


def _natural(account: str, signed: Decimal) -> Decimal:
    root = account.split(":")[0]
    return q(signed) if root in ("Assets", "Expenses") else q(-signed)


def _sum(bal: dict[str, Decimal], prefix: str) -> Decimal:
    return q(sum((v for k, v in bal.items() if k == prefix or k.startswith(prefix + ":")), Decimal("0")))


def _rows(bal: dict[str, Decimal], prefix: str, accounts_meta: dict[str, dict]) -> list[dict]:
    rows = []
    for acct in sorted(k for k in bal if k == prefix or k.startswith(prefix + ":")):
        if q(bal[acct]) == 0:
            continue
        meta = accounts_meta.get(acct, {})
        rows.append({"account": acct, "code": meta.get("code", ""), "balance": str(_natural(acct, bal[acct]))})
    return rows


def trial_balance(ledger: Ledger, as_of: date | None = None) -> dict:
    bal = ledger.balances(end=as_of)
    meta = {a["name"]: a for a in ledger.open_accounts()}
    rows, dr, cr = [], ZERO, ZERO
    for acct in sorted(bal):
        v = q(bal[acct])
        if v == 0:
            continue
        d = v if v > 0 else ZERO
        c = -v if v < 0 else ZERO
        dr += d
        cr += c
        rows.append({"code": meta.get(acct, {}).get("code", ""), "account": acct, "debit": str(d), "credit": str(c)})
    return {"as_of": (as_of or date.today()).isoformat(), "rows": rows, "total_debit": str(dr), "total_credit": str(cr), "balanced": dr == cr}


def income_statement(ledger: Ledger, start: date, end: date) -> dict:
    bal = ledger.balances(start=start, end=end)
    meta = {a["name"]: a for a in ledger.open_accounts()}
    revenue = -_sum(bal, "Income")
    expenses = _sum(bal, "Expenses")
    return {
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "revenue": {"rows": _rows(bal, "Income", meta), "total": str(revenue)},
        "expenses": {"rows": _rows(bal, "Expenses", meta), "total": str(expenses)},
        "net_income": str(q(revenue - expenses)),
    }


def balance_sheet(ledger: Ledger, as_of: date) -> dict:
    bal = ledger.balances(end=as_of)
    meta = {a["name"]: a for a in ledger.open_accounts()}
    assets = _sum(bal, "Assets")
    liabilities = -_sum(bal, "Liabilities")
    equity_accounts = -_sum(bal, "Equity")
    # Books are never "closed" in Beancount; cumulative earnings roll into equity.
    earnings = q(-_sum(bal, "Income") - _sum(bal, "Expenses"))
    equity_rows = _rows(bal, "Equity", meta)
    equity_rows.append({"account": "Equity:Earnings:Current", "code": "3999", "balance": str(earnings)})
    total_equity = q(equity_accounts + earnings)
    return {
        "as_of": as_of.isoformat(),
        "assets": {"rows": _rows(bal, "Assets", meta), "total": str(assets)},
        "liabilities": {"rows": _rows(bal, "Liabilities", meta), "total": str(liabilities)},
        "equity": {"rows": equity_rows, "total": str(total_equity)},
        "total_liabilities_and_equity": str(q(liabilities + total_equity)),
        "balanced": assets == q(liabilities + total_equity),
    }


def hst_return(ledger: Ledger, start: date, end: date) -> dict:
    """GST/HST return worksheet (GST34) for an Ontario registrant, 13% HST.

    Line 101: total sales & other revenue (excluding HST)
    Line 103/105: HST collected/collectible
    Line 106/108: input tax credits
    Line 109: net tax (105 - 108)
    Line 110: instalments paid
    Line 113/114/115: balance / refund / payment
    """
    bal = ledger.balances(start=start, end=end)
    sales = -_sum(bal, "Income")
    collected = -_sum(bal, "Liabilities:HST:Collected")
    itc = _sum(bal, "Liabilities:HST:ITC")
    instalments = _sum(bal, "Liabilities:HST:Instalments")
    net = q(collected - itc)
    balance = q(net - instalments)
    return {
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "rate": ONTARIO_HST_RATE,
        "lines": {
            "101_sales_and_revenue": str(sales),
            "103_hst_collected": str(collected),
            "105_total_hst_adjustments": str(collected),
            "106_itc": str(itc),
            "108_total_itc_adjustments": str(itc),
            "109_net_tax": str(net),
            "110_instalments": str(instalments),
            "113_balance": str(balance),
            "114_refund_claimed": str(-balance if balance < 0 else ZERO),
            "115_payment_enclosed": str(balance if balance > 0 else ZERO),
        },
        "expected_collected_at_rate": str(q(sales * Decimal(ONTARIO_HST_RATE))),
    }


def general_ledger_csv(ledger: Ledger, start: date | None, end: date | None, account: str | None = None) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["date", "id", "flag", "payee", "narration", "account", "debit", "credit", "created_by", "created_at", "source"])
    for t in sorted(ledger.transactions(start, end, account), key=lambda t: t["date"]):
        for p in t["postings"]:
            w.writerow(
                [
                    t["date"],
                    t["id"],
                    t["flag"],
                    t["payee"] or "",
                    t["narration"],
                    p["account"],
                    p["debit"],
                    p["credit"],
                    t["meta"].get("created_by", ""),
                    t["meta"].get("created_at", ""),
                    t["meta"].get("source", ""),
                ]
            )
    return buf.getvalue()


def dashboard(ledger: Ledger, today: date | None = None) -> dict:
    today = today or date.today()
    fy_start = date(today.year, 1, 1)
    bal = ledger.balances(end=today)
    ytd = ledger.balances(start=fy_start, end=today)
    pending = [t for t in ledger.transactions() if t["flag"] == "!"]
    uncategorized = [t for t in ledger.transactions() if any(p["account"].endswith(":Uncategorized") for p in t["postings"])]
    return {
        "as_of": today.isoformat(),
        "cash": str(_sum(bal, "Assets:Current:Bank") + _sum(bal, "Assets:Current:Cash")),
        "receivables": str(_sum(bal, "Assets:Current:AccountsReceivable")),
        "payables": str(-_sum(bal, "Liabilities:Current:AccountsPayable") - _sum(bal, "Liabilities:Current:CreditCard")),
        "hst_owing": str(q(-_sum(bal, "Liabilities:HST"))),
        "ytd_revenue": str(-_sum(ytd, "Income")),
        "ytd_expenses": str(_sum(ytd, "Expenses")),
        "ytd_net_income": str(q(-_sum(ytd, "Income") - _sum(ytd, "Expenses"))),
        "pending_count": len(pending),
        "uncategorized_count": len(uncategorized),
        "ledger_errors": ledger.check(),
        "recent": ledger.transactions(limit=10),
    }
