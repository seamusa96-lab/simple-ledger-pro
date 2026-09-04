import { useState } from 'react'
import { api, money } from '../api'
import { Alert, DownloadLink } from '../components'
import { useAsync } from '../useAsync'

export function AccountsPage() {
  const { data, error, reload } = useAsync(api.accounts)
  const [form, setForm] = useState({ name: '', code: '', description: '', gifi: '', t2125_line: '', hst_treatment: '' })
  const [msg, setMsg] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)
  const [typeFilter, setTypeFilter] = useState('')

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      await api.createAccount(form)
      setMsg({ kind: 'ok', text: `Opened ${form.name}` })
      setForm({ name: '', code: '', description: '', gifi: '', t2125_line: '', hst_treatment: '' })
      reload()
    } catch (err) {
      setMsg({ kind: 'error', text: String((err as Error).message) })
    }
  }

  const rows = (data ?? []).filter((a) => !typeFilter || a.type === typeFilter)
  return (
    <>
      <h2>Chart of Accounts</h2>
      <p className="muted">
        Ontario small-business chart (CPA Canada / ASPE). Codes follow the 1xxx–5xxx convention; expense accounts carry their CRA T2125 line and GIFI code for year-end filing.
      </p>
      <div className="downloads">
        <DownloadLink href="/api/accounts/export?format=csv" label="Download CSV" />
        <DownloadLink href="/api/accounts/export?format=beancount" label="Download .beancount" />
        <DownloadLink href="/api/accounts/template?format=csv" label="Download stock template (CSV)" />
        <DownloadLink href="/api/ledger/export" label="Download full ledger bundle (.zip)" />
      </div>
      {error && <Alert kind="error">{error}</Alert>}
      {msg && <Alert kind={msg.kind}>{msg.text}</Alert>}

      <form className="panel" onSubmit={submit}>
        <h3>Open a new account</h3>
        <div className="row">
          <div className="grow">
            <label>Account name (Assets:… / Liabilities:… / Equity:… / Income:… / Expenses:…)</label>
            <input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Expenses:Consulting" />
          </div>
          <div>
            <label>Code</label>
            <input value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} placeholder="5350" />
          </div>
          <div className="grow">
            <label>Description</label>
            <input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </div>
        </div>
        <div className="row" style={{ marginTop: 10 }}>
          <div>
            <label>GIFI</label>
            <input value={form.gifi} onChange={(e) => setForm({ ...form, gifi: e.target.value })} placeholder="8810" />
          </div>
          <div>
            <label>T2125 line</label>
            <input value={form.t2125_line} onChange={(e) => setForm({ ...form, t2125_line: e.target.value })} placeholder="8810" />
          </div>
          <div>
            <label>HST treatment</label>
            <select value={form.hst_treatment} onChange={(e) => setForm({ ...form, hst_treatment: e.target.value })}>
              <option value="">Not set</option>
              {['taxable', 'exempt', 'zero-rated', 'n/a'].map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </div>
          <div className="shrink">
            <label>&nbsp;</label>
            <button className="btn" type="submit">Open account</button>
          </div>
        </div>
      </form>

      <div className="panel">
        <div className="row" style={{ marginBottom: 12 }}>
          <div className="shrink" style={{ minWidth: 200 }}>
            <label>Filter by type</label>
            <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
              <option value="">All types</option>
              {['Assets', 'Liabilities', 'Equity', 'Income', 'Expenses'].map((t) => (
                <option key={t}>{t}</option>
              ))}
            </select>
          </div>
        </div>
        <table>
          <thead>
            <tr><th>Code</th><th>Account</th><th>Type</th><th>Normal</th><th>HST</th><th>T2125 / GIFI</th><th>Description</th><th className="num">Balance</th></tr>
          </thead>
          <tbody>
            {rows.map((a) => (
              <tr key={a.name}>
                <td>{a.code}</td>
                <td className="mono">{a.name}</td>
                <td>{a.type}</td>
                <td>{a.normal_balance}</td>
                <td>{a.hst_treatment}</td>
                <td>{[a.t2125_line, a.gifi].filter(Boolean).join(' / ')}</td>
                <td className="muted">{a.description}</td>
                <td className="num">{Number(a.balance) !== 0 ? money(a.balance) : <span className="muted">—</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}
