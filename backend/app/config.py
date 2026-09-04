import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("SLP_DATA_DIR", BASE_DIR / "data"))
LEDGER_FILE = DATA_DIR / "main.beancount"
COA_FILE = DATA_DIR / "accounts.beancount"
DOCUMENTS_DIR = DATA_DIR / "documents"
STATEMENTS_DIR = DATA_DIR / "statements"
RULES_FILE = DATA_DIR / "bank_rules.json"

CURRENCY = "CAD"
ONTARIO_HST_RATE = "0.13"
UNCATEGORIZED_EXPENSE = "Expenses:Uncategorized"
UNCATEGORIZED_INCOME = "Income:Uncategorized"

# Security. By default (dev) CORS allows the local Vite origins only, not "*".
# Set SLP_CORS_ORIGINS to a comma-separated allow-list for other deployments.
CORS_ORIGINS = [
    o.strip()
    for o in os.environ.get("SLP_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
    if o.strip()
]
# Optional shared-secret gate. When SLP_API_KEY is set, every request must send a
# matching X-API-Key header; when unset the API is open (single-user/local use).
API_KEY = os.environ.get("SLP_API_KEY") or None
