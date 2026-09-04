import { useState } from 'react'
import { api, money, today, yearStart, type Reconciliation } from '../api'
import { AccountSelect, Alert, DownloadLink } from '../components'
import { useAsync } from '../useAsync'

export function BankPage() {
  const accounts = useAsync(api.accounts)
  const statements = useAsync(api.statements)
  const [account, setAccount] = useState('Assets:Current:Bank:Chequing')
  const [file, setFile] = useState<File | null>(null)
  const [msg, setMsg] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)
  const [recon, setRecon] = useState<{ id: string; data: Reconciliation } | null>(null)
  const [exportAccount, setExportAccount] = useState('Assets:Current:Bank:Chequing')
  const [start, setStart] = useState(yearStart())
  const [end, setEnd] = useState(today())

  const upload = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!file || !account) return
    try {
      const s = await api.importStatement(account, file)
      setMsg({ kind: 'ok', text: `Imported ${s.imported} of ${s.line_count} lines (${s.auto_categorized} auto-categorized, ${s.skipped_duplicates} duplicates skipped). Pending lines need categorizing in the Journal.` })
      setFile(null)
      statements.reload()
    } catch (err) {
      setMsg({ kind: 'error', text: (err as Error).message })
    }
  }

  const reconcile = async (id: string) => {
    try {
      setRecon({ id, data: await api.reconcile(id) })
    } catch (err) {
      setMsg({ kind: 'error', text: (err as Error).message })
    }
  }

  const accts = accounts.data ?? []
  const bankFilter = (a: { type: string; name: string }) => (a.type === 'Assets' && a.name.includes('Bank')) || a.name.includes('Cash') || a.name.includes('CreditCard') || a.name.includes('Loan')
  const stmtQuery = `account=${encodeURIComponent(exportAccount)}&start=${start}&end=${end}`
  return (
    <>
      <h2>Bank Statements</h2>
      {msg && <Alert kind={msg.kind}>{msg.text}</Alert>}

      <form className="panel" onSubmit={upload}>
        <h3>Import statement (CSV)</h3>
        <p className="muted">Supports RBC, TD, BMO, Scotiabank, CIBC, Tangerine and generic date/description/amount exports. Lines matching a rule are posted as cleared with a 13% ITC split; the rest are posted as pending against Uncategorized for review. Re-importing the same file is safe — duplicates are skipped.</p>
        <div className="row">
          <div className="grow"><label>Bank / card account</label><AccountSelect accounts={accts} value={account} onChange={setAccount} filter={bankFilter} /></div>
          <div className="grow"><label>CSV file</label><input type="file" accept=".csv,text/csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></div>
          <div className="shrink"><button className="btn" type="submit" disabled={!file || !account}>Import</button></div>
        </div>
      </form>

      <div className="panel">
        <h3>Download account statement from the ledger</h3>
        <div className="row">
          <div className="grow"><label>Account</label><AccountSelect accounts={accts} value={exportAccount} onChange={setExportAccount} filter={bankFilter} /></div>
          <div><label>From</label><input type="date" value={start} onChange={(e) => setStart(e.target.value)} /></div>
          <div><label>To</label><input type="date" value={end} onChange={(e) => setEnd(e.target.value)} /></div>
          <div className="shrink"><DownloadLink href={`/api/bank/accounts/${encodeURIComponent(exportAccount)}/statement?format=csv&${stmtQuery}`} label="CSV" /></div>
          <div className="shrink"><DownloadLink href={`/api/bank/accounts/${encodeURIComponent(exportAccount)}/statement?format=pdf&${stmtQuery}`} label="PDF" /></div>
        </div>
      </div>

      <div className="panel">
        <h3>Imported statements</h3>
        {statements.error && <Alert kind="error">{statements.error}</Alert>}
        <table>
          <thead><tr><th>Imported</th><th>Account</th><th>File</th><th>Period</th><th className="num">Lines</th><th className="num">Closing</th><th></th></tr></thead>
          <tbody>
            {(statements.data ?? []).map((s) => (
              <tr key={s.id}>
                <td>{s.imported_at.slice(0, 16)}</td>
                <td className="mono">{s.bank_account}</td>
                <td>{s.original_filename}</td>
                <td>{s.period_start} → {s.period_end}</td>
                <td className="num">{s.imported}/{s.line_count}</td>
                <td className="num">{s.closing_balance ? money(s.closing_balance) : '—'}</td>
                <td style={{ whiteSpace: 'nowrap' }}>
                  <button className="btn small" onClick={() => reconcile(s.id)}>Reconcile</button>{' '}
                  <DownloadLink href={`/api/bank/statements/${encodeURIComponent(s.id)}/download`} label="Original" />
                </td>
              </tr>
            ))}
            {(statements.data ?? []).length === 0 && <tr><td colSpan={7} className="muted">No statements imported yet.</td></tr>}
          </tbody>
        </table>
      </div>

      {recon && (
        <div className="panel">
          <h3>Reconciliation — {recon.id} {recon.data.reconciled ? <span className="badge ok">reconciled</span> : <span className="badge err">differences</span>}</h3>
          <div className="cards">
            <div className="card"><div className="label">Ledger balance</div><div className="value">{money(recon.data.ledger_balance_at_period_end)}</div></div>
            <div className="card"><div className="label">Statement closing</div><div className="value">{recon.data.statement_closing_balance ? money(recon.data.statement_closing_balance) : '—'}</div></div>
            <div className="card"><div className="label">Difference</div><div className={`value ${Number(recon.data.difference) !== 0 ? 'neg' : 'pos'}`}>{recon.data.difference ? money(recon.data.difference) : '—'}</div></div>
            <div className="card"><div className="label">Matched lines</div><div className="value">{recon.data.matched.length}</div></div>
          </div>
          {recon.data.unmatched_statement_lines.length > 0 && (
            <>
              <h3>On statement, not in ledger</h3>
              <table><tbody>{recon.data.unmatched_statement_lines.map((l, i) => <tr key={i}><td>{l.date}</td><td>{l.description}</td><td className="num">{money(l.amount)}</td></tr>)}</tbody></table>
            </>
          )}
          {recon.data.unmatched_ledger_entries.length > 0 && (
            <>
              <h3>In ledger, not on statement (outstanding items)</h3>
              <table><tbody>{recon.data.unmatched_ledger_entries.map((l) => <tr key={l.id}><td>{l.date}</td><td className="mono">{l.id}</td><td>{l.narration}</td><td className="num">{money(l.amount)}</td></tr>)}</tbody></table>
            </>
          )}
          {Number(recon.data.difference) !== 0 && recon.data.unmatched_statement_lines.length === 0 && (
            <p className="muted">All statement lines are in the ledger; the remaining difference is the opening balance or ledger-only items listed above. Post an opening-balance entry against Equity:Opening-Balances if this is the first statement.</p>
          )}
        </div>
      )}
    </>
  )
}
