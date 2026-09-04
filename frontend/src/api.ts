export type Account = {
  name: string
  type: string
  normal_balance: 'debit' | 'credit'
  code: string
  description: string
  gifi: string
  t2125_line: string
  hst_treatment: string
  balance: string
  closed: boolean
}

export type Posting = { account: string; amount: string; debit: string; credit: string }

export type Transaction = {
  id: string
  date: string
  flag: '*' | '!'
  payee: string | null
  narration: string
  tags: string[]
  links: string[]
  meta: Record<string, string>
  postings: Posting[]
}

export type Dashboard = {
  as_of: string
  cash: string
  receivables: string
  payables: string
  hst_owing: string
  ytd_revenue: string
  ytd_expenses: string
  ytd_net_income: string
  pending_count: number
  uncategorized_count: number
  ledger_errors: string[]
  recent: Transaction[]
}

export type Statement = {
  id: string
  bank_account: string
  original_filename: string
  imported_at: string
  period_start: string
  period_end: string
  line_count: number
  imported: number
  auto_categorized: number
  skipped_duplicates: number
  closing_balance: string | null
}

export type Reconciliation = {
  ledger_balance_at_period_end: string
  statement_closing_balance: string | null
  difference: string | null
  reconciled: boolean
  matched: { date: string; description: string; amount: string; transaction_id: string; flag: string }[]
  unmatched_statement_lines: { date: string; description: string; amount: string }[]
  unmatched_ledger_entries: { date: string; id: string; narration: string; amount: string }[]
}

export type Receipt = {
  id: string
  date: string
  vendor: string
  description: string
  total: string
  hst: string
  net: string
  expense_account: string
  paid_from: string
  file: string
  transaction_id: string | null
}

export type ReportRow = { account: string; code: string; balance: string }
export type Section = { rows: ReportRow[]; total: string }

const USER_KEY = 'slp_user'
export const getUser = () => localStorage.getItem(USER_KEY) || 'owner'
export const setUser = (u: string) => localStorage.setItem(USER_KEY, u)

export class ApiError extends Error {}

async function request<T>(url: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('X-User', getUser())
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  const res = await fetch(url, { ...init, headers })
  if (!res.ok) throw new ApiError(await res.text())
  return (await res.json()) as T
}

export const api = {
  dashboard: () => request<Dashboard>('/api/dashboard'),
  accounts: () => request<Account[]>('/api/accounts'),
  createAccount: (b: { name: string; code: string; description: string; gifi: string; t2125_line: string; hst_treatment: string }) =>
    request('/api/accounts', { method: 'POST', body: JSON.stringify(b) }),
  transactions: (params: Record<string, string> = {}) =>
    request<Transaction[]>('/api/transactions?' + new URLSearchParams(params)),
  createTransaction: (b: unknown) => request<Transaction>('/api/transactions', { method: 'POST', body: JSON.stringify(b) }),
  similarTransactions: (date: string, amount: string, narration: string) =>
    request<Transaction[]>('/api/transactions/similar?' + new URLSearchParams({ date, amount, narration })),
  suggestAccount: (narration: string) =>
    request<{ account: string; count: number; code: string; gifi: string; t2125_line: string } | null>(
      '/api/transactions/suggest-account?' + new URLSearchParams({ narration }),
    ),
  voidTransaction: (id: string, reason: string) =>
    request<Transaction>(`/api/transactions/${id}/void`, { method: 'POST', body: JSON.stringify({ reason }) }),
  categorize: (id: string, account: string, hst: boolean) => {
    const fd = new FormData()
    fd.set('account', account)
    fd.set('hst', String(hst))
    return request<Transaction>(`/api/transactions/${id}/categorize`, { method: 'POST', body: fd })
  },
  statements: () => request<Statement[]>('/api/bank/statements'),
  importStatement: (account: string, file: File) => {
    const fd = new FormData()
    fd.set('account', account)
    fd.set('file', file)
    return request<Statement>('/api/bank/statements/import', { method: 'POST', body: fd })
  },
  reconcile: (id: string) => request<Reconciliation>(`/api/bank/statements/${id}/reconcile`),
  receipts: () => request<Receipt[]>('/api/receipts'),
  uploadReceipt: (fd: FormData) => request<Receipt>('/api/receipts', { method: 'POST', body: fd }),
  trialBalance: (asOf: string) =>
    request<{ rows: { code: string; account: string; debit: string; credit: string }[]; total_debit: string; total_credit: string; balanced: boolean }>(
      `/api/reports/trial-balance?as_of=${asOf}`,
    ),
  incomeStatement: (start: string, end: string) =>
    request<{ revenue: Section; expenses: Section; net_income: string }>(`/api/reports/income-statement?start=${start}&end=${end}`),
  balanceSheet: (asOf: string) =>
    request<{ assets: Section; liabilities: Section; equity: Section; total_liabilities_and_equity: string; balanced: boolean }>(
      `/api/reports/balance-sheet?as_of=${asOf}`,
    ),
  hst: (start: string, end: string) =>
    request<{ lines: Record<string, string>; expected_collected_at_rate: string }>(`/api/reports/hst?start=${start}&end=${end}`),
  seed: () => request<{ seeded: boolean }>('/api/demo/seed', { method: 'POST' }),
}

export const money = (v: string | number) =>
  Number(v).toLocaleString('en-CA', { style: 'currency', currency: 'CAD' })

export const today = () => new Date().toISOString().slice(0, 10)
export const yearStart = () => `${new Date().getFullYear()}-01-01`
