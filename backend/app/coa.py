"""Default chart of accounts for an Ontario small business.

Account numbering follows the common Canadian convention (1xxx assets, 2xxx
liabilities, 3xxx equity, 4xxx income, 5xxx+ expenses). Expense accounts carry
the CRA T2125 / GIFI line they roll up to so year-end filing maps directly.
Beancount account roots (Assets/Liabilities/Equity/Income/Expenses) are the
five fundamental account types; the balance sheet identity
Assets = Liabilities + Equity is enforced by the engine on every posting.
"""

import csv
import io
from dataclasses import asdict, dataclass
from datetime import date

from .config import CURRENCY

OPEN_DATE = date(2000, 1, 1)


@dataclass(frozen=True)
class Account:
    code: str
    name: str
    description: str
    gifi: str = ""
    t2125_line: str = ""
    hst_treatment: str = ""  # taxable | exempt | zero-rated | n/a

    @property
    def type(self) -> str:
        return self.name.split(":")[0]

    @property
    def normal_balance(self) -> str:
        return "debit" if self.type in ("Assets", "Expenses") else "credit"


DEFAULT_ACCOUNTS: list[Account] = [
    # ---- Assets -----------------------------------------------------------
    Account("1000", "Assets:Current:Cash", "Petty cash on hand", "1001"),
    Account("1010", "Assets:Current:Bank:Chequing", "Business chequing account", "1002"),
    Account("1020", "Assets:Current:Bank:Savings", "Business savings account", "1002"),
    Account("1200", "Assets:Current:AccountsReceivable", "Trade receivables from customers", "1060"),
    Account("1210", "Assets:Current:AllowanceDoubtfulAccounts", "Contra-asset: allowance for doubtful accounts", "1061"),
    Account("1300", "Assets:Current:Inventory", "Inventory held for resale", "1120"),
    Account("1400", "Assets:Current:PrepaidExpenses", "Prepaid insurance, rent, subscriptions", "1484"),
    Account("1450", "Assets:Current:DueFromShareholder", "Amounts advanced to shareholder", "1300"),
    Account("1500", "Assets:Fixed:Equipment", "Furniture and equipment (CCA class 8)", "1740"),
    Account("1510", "Assets:Fixed:AccumulatedDepreciation:Equipment", "Contra-asset: accumulated CCA on equipment", "1741"),
    Account("1520", "Assets:Fixed:Vehicles", "Motor vehicles (CCA class 10/10.1)", "1740"),
    Account("1530", "Assets:Fixed:AccumulatedDepreciation:Vehicles", "Contra-asset: accumulated CCA on vehicles", "1741"),
    Account("1540", "Assets:Fixed:ComputerHardware", "Computer hardware (CCA class 50)", "1774"),
    Account("1550", "Assets:Fixed:AccumulatedDepreciation:ComputerHardware", "Contra-asset: accumulated CCA on computers", "1775"),
    # ---- Liabilities ------------------------------------------------------
    Account("2000", "Liabilities:Current:AccountsPayable", "Trade payables to suppliers", "2620"),
    Account("2100", "Liabilities:Current:CreditCard", "Business credit card", "2707"),
    Account("2200", "Liabilities:HST:Collected", "HST collected on sales (GST/HST return line 103/105)", "2680", "", "n/a"),
    Account("2210", "Liabilities:HST:ITC", "Contra-liability: input tax credits on purchases (line 106/108)", "2680", "", "n/a"),
    Account("2220", "Liabilities:HST:Instalments", "Contra-liability: HST instalments remitted to CRA (line 110)", "2680", "", "n/a"),
    Account("2300", "Liabilities:Current:PayrollDeductions:CPP", "Employee + employer CPP owing to CRA", "2627"),
    Account("2310", "Liabilities:Current:PayrollDeductions:EI", "Employee + employer EI owing to CRA", "2627"),
    Account("2320", "Liabilities:Current:PayrollDeductions:IncomeTax", "Source deductions (federal + Ontario) owing to CRA", "2627"),
    Account("2330", "Liabilities:Current:EHT", "Ontario Employer Health Tax payable", "2627"),
    Account("2340", "Liabilities:Current:WSIB", "WSIB premiums payable", "2627"),
    Account("2400", "Liabilities:Current:CorporateTaxPayable", "Federal + Ontario corporate income tax payable", "2680"),
    Account("2500", "Liabilities:Current:DueToShareholder", "Shareholder loan (owed to shareholder)", "2780"),
    Account("2600", "Liabilities:Current:DeferredRevenue", "Customer deposits / unearned revenue", "2520"),
    Account("2700", "Liabilities:LongTerm:BankLoan", "Term loans and lines of credit (long-term portion)", "3140"),
    Account("2710", "Liabilities:LongTerm:CEBA", "Canada Emergency Business Account loan", "3140"),
    # ---- Equity -----------------------------------------------------------
    Account("3000", "Equity:ShareCapital:Common", "Common shares issued", "3500"),
    Account("3100", "Equity:RetainedEarnings", "Accumulated earnings less dividends", "3600"),
    Account("3200", "Equity:Dividends", "Dividends declared to shareholders (contra-equity)", "3700"),
    Account("3300", "Equity:OwnerContributions", "Sole proprietor: capital contributed", "3600"),
    Account("3310", "Equity:OwnerDrawings", "Sole proprietor: drawings (contra-equity)", "3600"),
    Account("3900", "Equity:Opening-Balances", "Offset for opening balance entries only", "3600"),
    # ---- Income -----------------------------------------------------------
    Account("4000", "Income:Sales:Services", "Revenue from services (HST taxable 13%)", "8000", "3A", "taxable"),
    Account("4100", "Income:Sales:Products", "Revenue from goods sold (HST taxable 13%)", "8000", "3A", "taxable"),
    Account("4200", "Income:Sales:ZeroRated", "Zero-rated supplies (exports, basic groceries)", "8000", "3A", "zero-rated"),
    Account("4300", "Income:Sales:Exempt", "HST-exempt supplies", "8000", "3A", "exempt"),
    Account("4400", "Income:Sales:Discounts", "Contra-revenue: discounts and returns", "8000", "3A", "taxable"),
    Account("4500", "Income:Other:Interest", "Interest earned on bank balances", "8090", "8230", "exempt"),
    Account("4600", "Income:Other:GainOnDisposal", "Gain on disposal of capital assets", "8210", "8230", "n/a"),
    Account("4900", "Income:Other:Misc", "Miscellaneous income", "8230", "8230", "n/a"),
    Account("4990", "Income:Uncategorized", "Bank-imported deposits awaiting classification", "8230", "8230", "n/a"),
    # ---- Expenses (T2125 Part 4 lines) -----------------------------------
    Account("5000", "Expenses:CostOfSales:Purchases", "Purchases of goods for resale", "8320", "8320", "taxable"),
    Account("5010", "Expenses:CostOfSales:Subcontracts", "Subcontractor costs", "8360", "8360", "taxable"),
    Account("5020", "Expenses:CostOfSales:DirectWages", "Direct labour", "8340", "8340", "n/a"),
    Account("5100", "Expenses:Advertising", "Advertising and promotion", "8521", "8521", "taxable"),
    Account("5110", "Expenses:MealsEntertainment", "Meals & entertainment (50% deductible, 50% ITC)", "8523", "8523", "taxable"),
    Account("5120", "Expenses:BadDebts", "Bad debt expense", "8590", "8590", "n/a"),
    Account("5130", "Expenses:Insurance", "Business insurance (HST exempt)", "8690", "8690", "exempt"),
    Account("5140", "Expenses:InterestBankCharges", "Interest and bank charges (HST exempt)", "8710", "8710", "exempt"),
    Account("5150", "Expenses:BusinessTaxesLicences", "Business taxes, licences and memberships", "8760", "8760", "n/a"),
    Account("5160", "Expenses:OfficeExpenses", "General office expenses", "8810", "8810", "taxable"),
    Account("5170", "Expenses:OfficeSupplies", "Office stationery and supplies", "8811", "8811", "taxable"),
    Account("5180", "Expenses:ProfessionalFees", "Legal, accounting and other professional fees", "8860", "8860", "taxable"),
    Account("5190", "Expenses:ManagementFees", "Management and administration fees", "8871", "8871", "taxable"),
    Account("5200", "Expenses:Rent", "Rent for business premises", "8910", "8910", "taxable"),
    Account("5210", "Expenses:RepairsMaintenance", "Repairs and maintenance", "8960", "8960", "taxable"),
    Account("5220", "Expenses:Salaries", "Salaries, wages and benefits (employer CPP/EI/EHT)", "9060", "9060", "n/a"),
    Account("5230", "Expenses:PropertyTaxes", "Property taxes", "9180", "9180", "n/a"),
    Account("5240", "Expenses:Travel", "Travel (transportation, lodging)", "9200", "9200", "taxable"),
    Account("5250", "Expenses:Utilities", "Heat, electricity, water", "9220", "9220", "taxable"),
    Account("5260", "Expenses:Telephone", "Telephone and internet", "9225", "9225", "taxable"),
    Account("5270", "Expenses:Software", "Software and SaaS subscriptions", "8810", "8810", "taxable"),
    Account("5280", "Expenses:Fuel", "Fuel costs (excluding motor vehicle)", "9224", "9224", "taxable"),
    Account("5290", "Expenses:DeliveryFreight", "Delivery, freight and express", "9275", "9275", "taxable"),
    Account("5300", "Expenses:MotorVehicle", "Motor vehicle expenses (business-use %)", "9281", "9281", "taxable"),
    Account("5310", "Expenses:Depreciation", "Capital cost allowance / amortization", "9936", "9936", "n/a"),
    Account("5320", "Expenses:HomeOffice", "Business-use-of-home expenses", "9945", "9945", "n/a"),
    Account("5330", "Expenses:Training", "Training and conferences", "8760", "8760", "taxable"),
    Account("5340", "Expenses:Other", "Other expenses", "9270", "9270", "taxable"),
    Account("5900", "Expenses:IncomeTax", "Corporate income tax expense", "9990", "", "n/a"),
    Account("5990", "Expenses:Uncategorized", "Bank-imported payments awaiting classification", "9270", "9270", "taxable"),
]


def by_name() -> dict[str, Account]:
    return {a.name: a for a in DEFAULT_ACCOUNTS}


def to_beancount(accounts: list[Account] | None = None) -> str:
    accounts = accounts or DEFAULT_ACCOUNTS
    lines = [
        ";; Chart of accounts - Ontario small business (CPA Canada / ASPE)",
        ";; Generated by Simple Ledger Pro. Currency: CAD. HST: 13% (Ontario).",
        "",
    ]
    for a in accounts:
        lines.append(f"{OPEN_DATE.isoformat()} open {a.name} {CURRENCY}")
        lines.append(f'  code: "{a.code}"')
        lines.append(f'  description: "{a.description}"')
        if a.gifi:
            lines.append(f'  gifi: "{a.gifi}"')
        if a.t2125_line:
            lines.append(f'  t2125_line: "{a.t2125_line}"')
        if a.hst_treatment:
            lines.append(f'  hst: "{a.hst_treatment}"')
        lines.append("")
    return "\n".join(lines)


def to_csv(accounts: list[Account] | None = None) -> str:
    accounts = accounts or DEFAULT_ACCOUNTS
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["code", "account", "type", "normal_balance", "description", "gifi", "t2125_line", "hst_treatment"])
    for a in accounts:
        w.writerow([a.code, a.name, a.type, a.normal_balance, a.description, a.gifi, a.t2125_line, a.hst_treatment])
    return buf.getvalue()


def to_dicts(accounts: list[Account] | None = None) -> list[dict]:
    out = []
    for a in accounts or DEFAULT_ACCOUNTS:
        d = asdict(a)
        d["type"] = a.type
        d["normal_balance"] = a.normal_balance
        out.append(d)
    return out
