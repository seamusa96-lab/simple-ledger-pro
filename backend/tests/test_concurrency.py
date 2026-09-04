"""Concurrency invariants for the ledger write path.

These exercise the fix for the "concurrent writes erase ledger entries" bug:
``add_transaction``/``add_transactions``/``void_transaction``/``revise_pending``
must each hold the ledger lock across their whole read/check/build/write
sequence so overlapping requests cannot discard or duplicate entries.

The lock is an in-process ``RLock``, so these run threads against a single
``Ledger`` instance (the deployment caveat about multiple Uvicorn workers is
documented in ``void_transaction``).
"""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from app import coa
from app.config import DATA_DIR
from app.ledger import Ledger, LedgerError

BANK = "Assets:Current:Bank:Chequing"
RENT = "Expenses:Rent"
Y = date.today().year


def _fresh_ledger() -> Ledger:
    """An isolated ledger (own main + coa files) inside the shared test data dir.

    Sharing DATA_DIR keeps the module-level documents/statements staging dirs
    used by ``_rewrite`` valid while giving each test its own journal.
    """
    tag = uuid.uuid4().hex[:8]
    coa_path = DATA_DIR / f"accounts_{tag}.beancount"
    coa_path.write_text(coa.to_beancount(), encoding="utf-8")
    return Ledger(path=DATA_DIR / f"main_{tag}.beancount", coa_path=coa_path)


def _post(ledger: Ledger, i: int):
    return ledger.add_transaction(
        date(Y, 3, 1),
        f"concurrent entry {i}",
        [{"account": RENT, "amount": "1.00"}, {"account": BANK, "amount": "-1.00"}],
    )


def test_concurrent_appends_preserve_all_entries():
    ledger = _fresh_ledger()
    n = 25
    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(lambda i: _post(ledger, i), range(n)))
    txns = ledger.transactions()
    assert len(txns) == n
    # every id is unique and every entry balances
    ids = {t["id"] for t in txns}
    assert len(ids) == n
    assert ledger.check() == []


def test_concurrent_voids_create_single_reversal():
    ledger = _fresh_ledger()
    original = _post(ledger, 0)
    results = []

    def _void():
        try:
            results.append(("ok", ledger.void_transaction(original["id"], "concurrent void")))
        except LedgerError as e:
            results.append(("err", str(e)))

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(lambda _: _void(), range(8)))

    oks = [r for r in results if r[0] == "ok"]
    errs = [r for r in results if r[0] == "err"]
    assert len(oks) == 1, f"expected exactly one reversal, got {len(oks)}"
    assert len(errs) == 7
    reversals = [t for t in ledger.transactions() if t["meta"].get("reverses") == original["id"]]
    assert len(reversals) == 1
    assert ledger.check() == []


def test_concurrent_revisions_do_not_drop_other_entries():
    ledger = _fresh_ledger()
    # Two independent pending entries; revising one must never remove the other.
    a = ledger.add_transaction(
        date(Y, 3, 1),
        "pending A",
        [{"account": "Expenses:Uncategorized", "amount": "5.00"}, {"account": BANK, "amount": "-5.00"}],
        flag="!",
    )
    b = ledger.add_transaction(
        date(Y, 3, 1),
        "pending B",
        [{"account": "Expenses:Uncategorized", "amount": "7.00"}, {"account": BANK, "amount": "-7.00"}],
        flag="!",
    )

    def _revise(txn, amt, acct):
        ledger.revise_pending(txn["id"], [{"account": acct, "amount": amt}, {"account": BANK, "amount": f"-{amt}"}])

    with ThreadPoolExecutor(max_workers=2) as ex:
        f1 = ex.submit(_revise, a, "5.00", RENT)
        f2 = ex.submit(_revise, b, "7.00", "Expenses:OfficeSupplies")
        f1.result()
        f2.result()

    # both entries survive, each keeps its own id, and the ledger stays valid
    assert ledger.get_transaction(a["id"]) is not None
    assert ledger.get_transaction(b["id"]) is not None
    assert ledger.get_transaction(a["id"])["flag"] == "*"
    assert ledger.get_transaction(b["id"])["flag"] == "*"
    assert ledger.check() == []
