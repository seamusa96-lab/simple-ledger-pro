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
