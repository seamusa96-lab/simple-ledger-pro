# Simple Ledger Pro

Double-entry bookkeeping for an Ontario small business, built on [Beancount](https://beancount.github.io/).
The plain-text ledger (`backend/data/main.beancount`) is the single source of truth; every write is
validated by the Beancount loader before it is persisted, so an unbalanced or mis-typed entry can never
reach the books.

## Features

| Area | What you get |
| --- | --- |
| Chart of accounts | Ontario small-business CoA (ASPE) with GIFI / T2125 / HST metadata. Download as CSV or `.beancount`. |
| Journal | Balanced entries with `created_by` / `created_at` / `source` audit metadata; pending (`!`) entries can be revised, cleared (`*`) entries can only be reversed. |
| Bank statements | Import CSV from Canadian banks (headered or positional), auto-categorize by vendor rules, duplicate-safe re-import, reconcile against the ledger. Download the stored original or a ledger-side statement (CSV/PDF). |
| Receipts | Upload PDF/image, stored as a Beancount `document` directive, 13% HST/ITC split, optional auto-posted entry. Download originals, a receipts register CSV, or a ZIP bundle. |
| Reports | Trial balance, income statement, balance sheet (A = L + E check), GST/HST return worksheet (lines 101-115), general ledger CSV, dashboard. PDF export. |

All money is handled as `Decimal` quantized to cents with `ROUND_HALF_UP`.

## Run

Backend (Python 3.10+):

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Frontend (Node 22):

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173, proxies /api to :8000
```

Set the `SLP_DATA_DIR` environment variable to move the ledger/documents directory (default `backend/data`).
`POST /api/demo/seed` posts a few illustrative transactions.

## Test / lint

```bash
cd backend && ruff check . && pytest
cd frontend && npm run lint && npm run build
```

## Layout

```
backend/app/
  ledger.py    Beancount I/O, validation, audit metadata, reversals
  coa.py       Ontario chart of accounts
  banking.py   CSV parsing, import, rules, reconciliation
  receipts.py  document directives + register
  reports.py   TB / IS / BS / HST / GL / dashboard
  main.py      FastAPI routes
frontend/src/  React (Vite) UI
.github/agents/accounting-expert.md   CPA Canada (Ontario) review agent
```
