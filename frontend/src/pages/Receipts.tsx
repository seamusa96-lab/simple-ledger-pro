import { useState } from 'react'
import { api, money, today, yearStart } from '../api'
import { AccountSelect, Alert, DownloadLink } from '../components'
import { useAsync } from '../useAsync'

export function ReceiptsPage() {
  const accounts = useAsync(api.accounts)
  const receipts = useAsync(api.receipts)
  const [form, setForm] = useState({ receipt_date: today(), vendor: '', total: '', hst_amount: '', expense_account: '', paid_from: 'Liabilities:Current:CreditCard', description: '' })
  const [file, setFile] = useState<File | null>(null)
  const [msg, setMsg] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)
  const [start, setStart] = useState(yearStart())
  const [end, setEnd] = useState(today())

  const accts = accounts.data ?? []
  const selected = accts.find((a) => a.name === form.expense_account)
  const autoHst = selected?.hst_treatment === 'taxable' && form.total ? (Number(form.total) - Number(form.total) / 1.13).toFixed(2) : '0.00'

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!file) return
    const fd = new FormData()
    fd.set('file', file)
    Object.entries(form).forEach(([k, v]) => v !== '' && fd.set(k, v))
    try {
      const r = await api.uploadReceipt(fd)
      setMsg({ kind: 'ok', text: `Receipt filed: ${r.vendor} ${money(r.total)} (ITC ${money(r.hst)}), entry ${r.transaction_id}.` })
      setForm({ ...form, vendor: '', total: '', hst_amount: '', description: '' })
      setFile(null)
      receipts.reload()
    } catch (err) {
      setMsg({ kind: 'error', text: (err as Error).message })
    }
  }

  return (
    <>
      <h2>Receipts</h2>
      <p className="muted">Each receipt is stored under documents/&lt;account&gt;/YYYY-MM-DD.vendor.ext, recorded as a Beancount <code>document</code> directive and linked to the expense entry it supports. CRA requires retention for 6 years; originals are never deleted.</p>
      {msg && <Alert kind={msg.kind}>{msg.text}</Alert>}

      <form className="panel" onSubmit={submit}>
        <h3>Upload receipt</h3>
        <div className="row">
          <div><label>Date</label><input type="date" required value={form.receipt_date} onChange={(e) => setForm({ ...form, receipt_date: e.target.value })} /></div>
          <div className="grow"><label>Vendor</label><input required value={form.vendor} onChange={(e) => setForm({ ...form, vendor: e.target.value })} /></div>
          <div><label>Total incl. HST (CAD)</label><input type="number" step="0.01" min="0.01" required value={form.total} onChange={(e) => setForm({ ...form, total: e.target.value })} /></div>
          <div><label>HST on receipt (blank = auto {autoHst})</label><input type="number" step="0.01" min="0" value={form.hst_amount} onChange={(e) => setForm({ ...form, hst_amount: e.target.value })} placeholder={autoHst} /></div>
        </div>
        <div className="row" style={{ marginTop: 10 }}>
          <div className="grow"><label>Expense account</label><AccountSelect accounts={accts} value={form.expense_account} onChange={(v) => setForm({ ...form, expense_account: v })} filter={(a) => a.type === 'Expenses' || a.type === 'Assets'} /></div>
          <div className="grow"><label>Paid from</label><AccountSelect accounts={accts} value={form.paid_from} onChange={(v) => setForm({ ...form, paid_from: v })} filter={(a) => a.name.includes('Bank') || a.name.includes('Cash') || a.name.includes('CreditCard') || a.name.includes('Shareholder') || a.name.includes('AccountsPayable')} /></div>
          <div className="grow"><label>Description</label><input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></div>
        </div>
        <div className="row" style={{ marginTop: 10 }}>
          <div className="grow"><label>File (PDF / image)</label><input type="file" required accept=".pdf,image/*" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></div>
          <div className="shrink"><button className="btn" type="submit" disabled={!file || !form.expense_account}>File receipt & post</button></div>
        </div>
      </form>

      <div className="panel">
        <h3>Download</h3>
        <div className="row">
          <div><label>From</label><input type="date" value={start} onChange={(e) => setStart(e.target.value)} /></div>
          <div><label>To</label><input type="date" value={end} onChange={(e) => setEnd(e.target.value)} /></div>
          <div className="shrink"><DownloadLink href={`/api/receipts/register?start=${start}&end=${end}`} label="Receipts register (CSV)" /></div>
          <div className="shrink"><DownloadLink href={`/api/receipts/bundle?start=${start}&end=${end}`} label="Receipts + register (ZIP)" /></div>
        </div>
      </div>

      <div className="panel">
        <h3>Filed receipts</h3>
        {receipts.error && <Alert kind="error">{receipts.error}</Alert>}
        <table>
          <thead><tr><th>Date</th><th>Vendor</th><th>Account</th><th>Paid from</th><th className="num">Total</th><th className="num">ITC</th><th className="num">Net</th><th>Entry</th><th></th></tr></thead>
          <tbody>
            {(receipts.data ?? []).map((r) => (
              <tr key={r.id}>
                <td>{r.date}</td>
                <td>{r.vendor}{r.description && <div className="muted">{r.description}</div>}</td>
                <td className="mono">{r.expense_account}</td>
                <td className="mono">{r.paid_from}</td>
                <td className="num">{money(r.total)}</td>
                <td className="num">{money(r.hst)}</td>
                <td className="num">{money(r.net)}</td>
                <td className="mono">{r.transaction_id ?? '—'}</td>
                <td><DownloadLink href={`/api/receipts/file/${r.file}`} label="Download" /></td>
              </tr>
            ))}
            {(receipts.data ?? []).length === 0 && <tr><td colSpan={9} className="muted">No receipts filed yet.</td></tr>}
          </tbody>
        </table>
      </div>
    </>
  )
}
