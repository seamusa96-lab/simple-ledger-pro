import { useState } from 'react'
import { api, money } from '../api'
import { Alert, Flag } from '../components'
import { useAsync } from '../useAsync'

export function DashboardPage() {
  const { data, error, reload } = useAsync(api.dashboard)
  const [msg, setMsg] = useState<string | null>(null)
  if (error) return <Alert kind="error">{error}</Alert>
  if (!data) return <p className="muted">Loading…</p>
  const seed = async () => {
    const r = await api.seed()
    setMsg(r.seeded ? 'Demo transactions posted.' : 'Demo data already present.')
    reload()
  }
  const sign = (v: string) => (Number(v) < 0 ? 'neg' : Number(v) > 0 ? 'pos' : '')
  return (
    <>
      <h2>Dashboard <span className="muted">as of {data.as_of}</span></h2>
      {data.ledger_errors.length > 0 && <Alert kind="error">Ledger errors:\n{data.ledger_errors.join('\n')}</Alert>}
      <Alert kind="info">{msg}</Alert>
      <div className="cards">
        <div className="card"><div className="label">Cash & bank</div><div className={`value ${sign(data.cash)}`}>{money(data.cash)}</div></div>
        <div className="card"><div className="label">Receivables</div><div className="value">{money(data.receivables)}</div></div>
        <div className="card"><div className="label">Payables & cards</div><div className="value">{money(data.payables)}</div></div>
        <div className="card"><div className="label">HST owing (net)</div><div className={`value ${Number(data.hst_owing) > 0 ? 'neg' : ''}`}>{money(data.hst_owing)}</div></div>
        <div className="card"><div className="label">YTD revenue</div><div className="value">{money(data.ytd_revenue)}</div></div>
        <div className="card"><div className="label">YTD expenses</div><div className="value">{money(data.ytd_expenses)}</div></div>
        <div className="card"><div className="label">YTD net income</div><div className={`value ${sign(data.ytd_net_income)}`}>{money(data.ytd_net_income)}</div></div>
        <div className="card"><div className="label">Needs review</div><div className="value">{data.uncategorized_count} <span className="muted">uncategorized</span></div></div>
      </div>
      <div className="panel">
        <h3>Recent activity</h3>
        <table>
          <thead><tr><th>Date</th><th>Status</th><th>Payee / description</th><th>Accounts</th><th className="num">Amount</th></tr></thead>
          <tbody>
            {data.recent.map((t) => (
              <tr key={t.id}>
                <td>{t.date}</td>
                <td><Flag flag={t.flag} /></td>
                <td>{[t.payee, t.narration].filter(Boolean).join(' — ')}</td>
                <td className="mono">{t.postings.map((p) => p.account).join(', ')}</td>
                <td className="num">{money(t.postings.filter((p) => Number(p.amount) > 0).reduce((s, p) => s + Number(p.amount), 0))}</td>
              </tr>
            ))}
            {data.recent.length === 0 && (
              <tr><td colSpan={5} className="muted">No transactions yet. <button className="btn small" onClick={seed}>Post demo data</button></td></tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  )
}
