import { useState } from 'react'
import { getUser, setUser } from './api'
import { AccountsPage } from './pages/Accounts'
import { BankPage } from './pages/Bank'
import { DashboardPage } from './pages/Dashboard'
import { JournalPage } from './pages/Journal'
import { ReceiptsPage } from './pages/Receipts'
import { ReportsPage } from './pages/Reports'

const PAGES = [
  ['dashboard', 'Dashboard'],
  ['journal', 'Journal'],
  ['accounts', 'Chart of Accounts'],
  ['bank', 'Bank Statements'],
  ['receipts', 'Receipts'],
  ['reports', 'Reports'],
] as const

type Page = (typeof PAGES)[number][0]

export default function App() {
  const [page, setPage] = useState<Page>('dashboard')
  const [user, setUserState] = useState(getUser())
  return (
    <div className="layout">
      <nav className="sidebar">
        <h1>
          Simple Ledger Pro
          <small>Beancount · Ontario · CAD · HST 13%</small>
        </h1>
        {PAGES.map(([id, label]) => (
          <button key={id} className={page === id ? 'active' : ''} onClick={() => setPage(id)}>
            {label}
          </button>
        ))}
        <div className="user">
          Posting as (audit trail)
          <input
            value={user}
            onChange={(e) => {
              setUserState(e.target.value)
              setUser(e.target.value)
            }}
          />
        </div>
      </nav>
      <main>
        {page === 'dashboard' && <DashboardPage />}
        {page === 'journal' && <JournalPage />}
        {page === 'accounts' && <AccountsPage />}
        {page === 'bank' && <BankPage />}
        {page === 'receipts' && <ReceiptsPage />}
        {page === 'reports' && <ReportsPage />}
      </main>
    </div>
  )
}
