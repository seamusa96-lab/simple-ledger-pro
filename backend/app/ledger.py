"""Beancount-backed ledger.

The plain-text ``main.beancount`` file is the single source of truth. Every
write is staged to a temporary copy, re-parsed and validated by the Beancount
loader (which enforces that each transaction balances to zero and that every
posting hits an open account) before the real file is replaced. That makes it
impossible to persist an unbalanced entry.
"""

from __future__ import annotations

import hashlib
import shutil
import tempfile
import threading
import uuid
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from beancount import loader
from beancount.core import data
from beancount.core.amount import Amount
from beancount.parser import printer

from . import coa
from .config import COA_FILE, CURRENCY, DATA_DIR, DOCUMENTS_DIR, LEDGER_FILE, STATEMENTS_DIR

CENT = Decimal("0.01")
ROOT_TYPES = ("Assets", "Liabilities", "Equity", "Income", "Expenses")


class LedgerError(ValueError):
    pass


def q(x: Decimal | str | int | float) -> Decimal:
    """Quantize to cents using half-up (CRA rounding convention)."""
    return Decimal(str(x)).quantize(CENT, rounding=ROUND_HALF_UP)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Ledger:
    def __init__(self, path: Path = LEDGER_FILE, coa_path: Path = COA_FILE):
        self.path = Path(path)
        self.coa_path = Path(coa_path)
        self._lock = threading.RLock()
        self.ensure_initialized()

    # ------------------------------------------------------------------ setup
    def ensure_initialized(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
        STATEMENTS_DIR.mkdir(parents=True, exist_ok=True)
        if not self.coa_path.exists():
            self.coa_path.write_text(coa.to_beancount(), encoding="utf-8")
        if not self.path.exists():
            self.path.write_text(
                "\n".join(
                    [
                        ";; Simple Ledger Pro - general journal",
                        'option "title" "Simple Ledger Pro"',
                        f'option "operating_currency" "{CURRENCY}"',
                        f'include "{self.coa_path.name}"',
                        ";; strict mode: every account must be opened in accounts.beancount",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

    # ------------------------------------------------------------------ load
    def load(self, path: Path | None = None):
        entries, errors, options = loader.load_file(str(path or self.path))
        return entries, errors, options

    def check(self) -> list[str]:
        _, errors, _ = self.load()
        return [printer.format_error(e).strip() for e in errors]

    # -------------------------------------------------------------- accounts
    def open_accounts(self) -> list[dict]:
        entries, _, _ = self.load()
        closed = {e.account for e in entries if isinstance(e, data.Close)}
        out = []
        for e in entries:
            if isinstance(e, data.Open):
                meta = {k: str(v) for k, v in e.meta.items() if k not in ("filename", "lineno")}
                root = e.account.split(":")[0]
                out.append(
                    {
                        "name": e.account,
                        "type": root,
                        "normal_balance": "debit" if root in ("Assets", "Expenses") else "credit",
                        "code": meta.get("code", ""),
                        "description": meta.get("description", ""),
                        "gifi": meta.get("gifi", ""),
                        "t2125_line": meta.get("t2125_line", ""),
                        "hst_treatment": meta.get("hst", ""),
                        "open_date": e.date.isoformat(),
                        "closed": e.account in closed,
                    }
                )
        out.sort(key=lambda a: (a["code"] or "9999", a["name"]))
        return out

    def account_names(self) -> set[str]:
        return {a["name"] for a in self.open_accounts() if not a["closed"]}

    def add_account(
        self,
        name: str,
        code: str = "",
        description: str = "",
        gifi: str = "",
        t2125_line: str = "",
        hst_treatment: str = "",
        open_date: date | None = None,
    ) -> dict:
        root = name.split(":")[0]
        if root not in ROOT_TYPES:
            raise LedgerError(f"Account must start with one of {ROOT_TYPES}")
        if name in {a["name"] for a in self.open_accounts()}:
            raise LedgerError(f"Account {name} already exists")
        for part in name.split(":"):
            if not part or not (part[0].isupper() or part[0].isdigit()):
                raise LedgerError("Each account component must start with an uppercase letter or digit")
        if hst_treatment and hst_treatment not in ("taxable", "exempt", "zero-rated", "n/a"):
            raise LedgerError("hst_treatment must be one of taxable, exempt, zero-rated, n/a")
        meta = data.new_metadata("<api>", 0)
        if code:
            meta["code"] = code
        if description:
            meta["description"] = description
        if gifi:
            meta["gifi"] = gifi
        if t2125_line:
            meta["t2125_line"] = t2125_line
        if hst_treatment:
            meta["hst"] = hst_treatment
        entry = data.Open(meta, open_date or coa.OPEN_DATE, name, [CURRENCY], None)
        self._append(printer.format_entry(entry), target=self.coa_path)
        return {"name": name, "code": code, "description": description, "gifi": gifi, "t2125_line": t2125_line, "hst_treatment": hst_treatment}

    # ---------------------------------------------------------- transactions
    def add_transaction(
        self,
        txn_date: date,
        narration: str,
        postings: list[dict],
        payee: str | None = None,
        tags: list[str] | None = None,
        links: list[str] | None = None,
        meta: dict | None = None,
        created_by: str = "api",
        source: str = "manual",
        flag: str = "*",
    ) -> dict:
        with self._lock:
            entry = self._build_transaction(txn_date, narration, postings, payee, tags, links, meta, created_by, source, flag)
            self._append(printer.format_entry(entry))
            return self.get_transaction(entry.meta["id"])

    def find_similar(self, txn_date: date, narration: str, amount: Decimal) -> list[dict]:
        """Possible duplicates: same date, same narration, same magnitude.

        Magnitude is the entry's total debits (== total credits, since it balances),
        so the comparison is independent of posting order. This is advisory only -
        callers surface it as a warning and let the user decide whether to post.
        """
        want = q(abs(amount))
        out = []
        for t in self.transactions(start=txn_date, end=txn_date):
            if t["narration"].strip().casefold() != narration.strip().casefold():
                continue
            debits = q(sum((Decimal(p["amount"]) for p in t["postings"] if Decimal(p["amount"]) > 0), Decimal("0")))
            if debits == want:
                out.append(t)
        return out

    def suggest_account(self, narration: str) -> dict | None:
        """Suggest the account most often used before for this exact narration.

        Keeps coding consistent: the same description maps to the same account (and
        therefore the same CoA code / GIFI / T2125 line). Bank/cash/uncategorized
        legs are ignored so the suggestion is the expense or income side. Returns the
        account with its metadata, or None if the description has not been seen.
        """
        key = narration.strip().casefold()
        if not key:
            return None
        counts: dict[str, int] = defaultdict(int)
        for t in self.transactions():
            if t["narration"].strip().casefold() != key:
                continue
            for p in t["postings"]:
                acct = p["account"]
                root = acct.split(":")[0]
                if root in ("Income", "Expenses") and not acct.endswith(":Uncategorized"):
                    counts[acct] += 1
        if not counts:
            return None
        best = max(counts, key=lambda a: (counts[a], a))
        meta = next((a for a in self.open_accounts() if a["name"] == best), None)
        return {
            "account": best,
            "count": counts[best],
            "code": (meta or {}).get("code", ""),
            "gifi": (meta or {}).get("gifi", ""),
            "t2125_line": (meta or {}).get("t2125_line", ""),
        }

    def add_transactions(self, specs: list[dict]) -> list[dict]:
        """Append several transactions in one atomic, validated commit.

        Every spec is built and the whole batch is written and re-validated once, so
        either all entries persist or none do. Holding the lock across build+commit
        also prevents concurrent writers from interleaving or discarding entries.
        Each spec is a kwargs dict for :meth:`_build_transaction` (without ``self``).
        """
        with self._lock:
            entries = [
                self._build_transaction(
                    s["txn_date"],
                    s["narration"],
                    s["postings"],
                    s.get("payee"),
                    s.get("tags"),
                    s.get("links"),
                    s.get("meta"),
                    s.get("created_by", "api"),
                    s.get("source", "manual"),
                    s.get("flag", "*"),
                )
                for s in specs
            ]
            if not entries:
                return []
            self._append("\n\n".join(printer.format_entry(e) for e in entries))
            return [self.get_transaction(e.meta["id"]) for e in entries]

    def _build_transaction(
        self,
        txn_date: date,
        narration: str,
        postings: list[dict],
        payee: str | None,
        tags: list[str] | None,
        links: list[str] | None,
        meta: dict | None,
        created_by: str,
        source: str,
        flag: str,
        txn_id: str | None = None,
    ) -> data.Transaction:
        if len(postings) < 2:
            raise LedgerError("A journal entry needs at least two postings (double-entry).")
        names = self.account_names()
        total = Decimal("0")
        built: list[data.Posting] = []
        for p in postings:
            acct = p["account"]
            if acct not in names:
                raise LedgerError(f"Unknown or closed account: {acct}")
            amt = q(p["amount"])
            if amt == 0:
                raise LedgerError(f"Zero-amount posting to {acct} is not allowed.")
            total += amt
            pmeta = None
            if p.get("meta"):
                pmeta = {k: str(v) for k, v in p["meta"].items()}
            built.append(data.Posting(acct, Amount(amt, CURRENCY), None, None, None, pmeta))
        if total != 0:
            raise LedgerError(f"Entry does not balance: debits and credits differ by {total} {CURRENCY}.")
        if flag not in ("*", "!"):
            raise LedgerError("Flag must be '*' (cleared) or '!' (pending).")

        txn_id = txn_id or uuid.uuid4().hex[:12]
        m = data.new_metadata("<api>", 0)
        m["id"] = txn_id
        m["created_at"] = _now_iso()
        m["created_by"] = created_by
        m["source"] = source
        for k, v in (meta or {}).items():
            m[k] = str(v)
        entry = data.Transaction(
            m,
            txn_date,
            flag,
            payee or None,
            narration,
            frozenset(t.strip("#") for t in (tags or []) if t),
            frozenset(lk.strip("^") for lk in (links or []) if lk),
            built,
        )
        return entry

    def void_transaction(self, txn_id: str, reason: str, created_by: str = "api") -> dict:
        """Audit-safe reversal: never edit history, post the mirror entry.

        The already-voided check and the reversal write happen under one lock so two
        concurrent voids cannot both pass the check and post duplicate reversals.
        """
        with self._lock:
            original = self.get_transaction(txn_id)
            if original is None:
                raise LedgerError(f"Transaction {txn_id} not found")
            if any(t["meta"].get("reverses") == txn_id for t in self.transactions()):
                raise LedgerError("Transaction already voided")
            reversal = self.add_transaction(
                date.today(),
                f"REVERSAL of {txn_id}: {reason}",
                [{"account": p["account"], "amount": -Decimal(p["amount"])} for p in original["postings"]],
                payee=original.get("payee"),
                links=[f"void-{txn_id}"],
                meta={"reverses": txn_id},
                created_by=created_by,
                source="reversal",
            )
            return reversal

    def revise_pending(self, txn_id: str, postings: list[dict], narration: str | None = None, payee: str | None = None, created_by: str = "api") -> dict:
        """Replace a *pending* ('!') entry in place, e.g. to categorize a bank import.

        Cleared ('*') entries are immutable; use ``void_transaction`` instead.
        The original audit fields are carried forward and ``revised_at`` is stamped.
        """
        with self._lock:
            entries, _, _ = self.load()
            target = next((e for e in entries if isinstance(e, data.Transaction) and e.meta.get("id") == txn_id), None)
            if target is None:
                raise LedgerError(f"Transaction {txn_id} not found")
            if target.flag != "!":
                raise LedgerError("Only pending ('!') entries may be revised; post a reversal for cleared entries.")
            if Path(target.meta["filename"]).resolve() != self.path.resolve():
                raise LedgerError("Entry does not live in the main journal")
            carried = {k: str(v) for k, v in target.meta.items() if k not in ("filename", "lineno", "id", "created_at", "created_by", "source", "__tolerances__")}
            carried["revised_at"] = _now_iso()
            carried["revised_by"] = created_by
            carried["original_created_at"] = str(target.meta.get("created_at", ""))
            carried["original_created_by"] = str(target.meta.get("created_by", ""))
            lines = self.raw_text().splitlines(keepends=True)
            start = target.meta["lineno"] - 1
            end = start + 1
            while end < len(lines) and (lines[end].startswith((" ", "\t")) or lines[end].strip() == ""):
                end += 1
            remaining = "".join(lines[:start] + lines[end:])
            new = self._build_transaction(
                target.date,
                narration or target.narration,
                postings,
                payee if payee is not None else target.payee,
                sorted(target.tags),
                sorted(target.links),
                carried,
                created_by,
                str(target.meta.get("source", "manual")),
                "*",
                txn_id=txn_id,
            )
            self._rewrite(remaining.rstrip("\n") + "\n\n" + printer.format_entry(new))
        return self.get_transaction(txn_id)

    def transactions(
        self,
        start: date | None = None,
        end: date | None = None,
        account: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        entries, _, _ = self.load()
        out = []
        for e in entries:
            if not isinstance(e, data.Transaction):
                continue
            if start and e.date < start:
                continue
            if end and e.date > end:
                continue
            if account and not any(p.account == account or p.account.startswith(account + ":") for p in e.postings):
                continue
            out.append(self._txn_to_dict(e))
        out.sort(key=lambda t: (t["date"], t["meta"].get("created_at", "")), reverse=True)
        return out[:limit] if limit else out

    def get_transaction(self, txn_id: str) -> dict | None:
        entries, _, _ = self.load()
        for e in entries:
            if isinstance(e, data.Transaction) and e.meta.get("id") == txn_id:
                return self._txn_to_dict(e)
        return None

    @staticmethod
    def _txn_to_dict(e: data.Transaction) -> dict:
        meta = {k: (v.isoformat() if isinstance(v, date) else str(v)) for k, v in e.meta.items() if k not in ("filename", "lineno", "__tolerances__")}
        return {
            "id": meta.get("id", f"L{e.meta.get('lineno', 0)}"),
            "date": e.date.isoformat(),
            "flag": e.flag,
            "payee": e.payee,
            "narration": e.narration,
            "tags": sorted(e.tags),
            "links": sorted(e.links),
            "meta": meta,
            "postings": [
                {
                    "account": p.account,
                    "amount": str(p.units.number),
                    "currency": p.units.currency,
                    "debit": str(p.units.number) if p.units.number > 0 else "",
                    "credit": str(-p.units.number) if p.units.number < 0 else "",
                    "meta": {k: str(v) for k, v in (p.meta or {}).items() if k not in ("filename", "lineno")},
                }
                for p in e.postings
            ],
        }

    # -------------------------------------------------------------- balances
    def balances(self, start: date | None = None, end: date | None = None, include_pending: bool = True) -> dict[str, Decimal]:
        """Signed Beancount balances (credits negative) per account, CAD only."""
        entries, _, _ = self.load()
        bal: dict[str, Decimal] = defaultdict(Decimal)
        for e in entries:
            if not isinstance(e, data.Transaction):
                continue
            if start and e.date < start:
                continue
            if end and e.date > end:
                continue
            if not include_pending and e.flag == "!":
                continue
            for p in e.postings:
                if p.units.currency == CURRENCY:
                    bal[p.account] += p.units.number
        return dict(bal)

    # -------------------------------------------------------------- documents
    def add_document(self, account: str, filename: Path, doc_date: date, links: list[str] | None = None, tags: list[str] | None = None) -> None:
        if account not in self.account_names():
            raise LedgerError(f"Unknown account: {account}")
        rel = Path(filename).resolve().relative_to(DATA_DIR.resolve())
        meta = data.new_metadata("<api>", 0)
        entry = data.Document(meta, doc_date, account, rel.as_posix(), frozenset(tags or []), frozenset(links or []))
        self._append(printer.format_entry(entry))

    def documents(self) -> list[dict]:
        entries, _, _ = self.load()
        out = []
        for e in entries:
            if isinstance(e, data.Document):
                out.append(
                    {
                        "date": e.date.isoformat(),
                        "account": e.account,
                        "filename": e.filename,
                        "links": sorted(e.links or []),
                        "tags": sorted(e.tags or []),
                    }
                )
        out.sort(key=lambda d: d["date"], reverse=True)
        return out

    # ------------------------------------------------------------- integrity
    def import_ids(self) -> set[str]:
        entries, _, _ = self.load()
        return {str(e.meta["import_id"]) for e in entries if isinstance(e, data.Transaction) and "import_id" in e.meta}

    @staticmethod
    def make_import_id(*parts: str) -> str:
        return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]

    def raw_text(self) -> str:
        return self.path.read_text(encoding="utf-8")

    # ------------------------------------------------------------------ write
    def _append(self, text: str, target: Path | None = None) -> None:
        target = target or self.path
        self._rewrite(target.read_text(encoding="utf-8").rstrip("\n") + "\n\n" + text.rstrip("\n") + "\n", target)

    def _rewrite(self, content: str, target: Path | None = None) -> None:
        """Stage-validate-commit. Rejects anything that makes the ledger invalid."""
        target = target or self.path
        with self._lock:
            with tempfile.TemporaryDirectory() as tmp:
                tmpdir = Path(tmp)
                for f in (self.path, self.coa_path):
                    shutil.copy(f, tmpdir / f.name)
                for d in (DOCUMENTS_DIR, STATEMENTS_DIR):
                    if d.exists():
                        (tmpdir / d.name).symlink_to(d.resolve(), target_is_directory=True)
                (tmpdir / target.name).write_text(content, encoding="utf-8")
                _, errors, _ = loader.load_file(str(tmpdir / self.path.name))
                fatal = [printer.format_error(e).strip() for e in errors]
                if fatal:
                    raise LedgerError("Ledger validation failed:\n" + "\n".join(fatal))
                target.write_text(content, encoding="utf-8")


_ledger: Ledger | None = None


def get_ledger() -> Ledger:
    global _ledger
    if _ledger is None:
        _ledger = Ledger()
    return _ledger


def reset_ledger() -> None:
    global _ledger
    _ledger = None
