import { useState } from 'react'
import { api, money, today, yearStart, type Section } from '../api'
import { Alert, DownloadLink } from '../components'
import { useAsync } from '../useAsync'

type Tab = 'tb' | 'is' | 'bs' | 'hst'

function SectionRows({ title, section }: { title: string; section: Section }) {
  return (
    <>
      <tr className="section"><td colSpan={3}>{title}</td></tr>
      {section.rows.map((r) => (
        <tr key={r.account}><td>{r.code}</td><td className="mono">{r.account}</td><td className="num">{money(r.balance)}</td></tr>
      ))}
      <tr className="total"><td></td><td>Total {title.toLowerCase()}</td><td className="num">{money(section.total)}</td></tr>
    </>
  )
}

export function ReportsPage() {
  const [tab, setTab] = useState<Tab>('tb')
  const [start, setStart] = useState(yearStart())
  const [end, setEnd] = useState(today())
  const tb = useAsync(() => api.trialBalance(end), [end])
  const is = useAsync(() => api.incomeStatement(start, end), [start, end])
  const bs = useAsync(() => api.balanceSheet(end), [end])
  const hst = useAsync(() => api.hst(start, end), [start, end])

  const tabs: [Tab, string, string][] = [
    ['tb', 'Trial Balance', `/api/reports/trial-balance?as_of=${end}`],
    ['is', 'Income Statement', `/api/reports/income-statement?start=${start}&end=${end}`],
    ['bs', 'Balance Sheet', `/api/reports/balance-sheet?as_of=${end}`],
    ['hst', 'GST/HST Return', `/api/reports/hst?start=${start}&end=${end}`],
  ]
  const current = tabs.find((t) => t[0] === tab)!
  const HST_LABELS: Record<string, string> = {
    '101_sales_and_revenue': 'Line 101 — Sales and other revenue (excl. HST)',
    '103_hst_collected': 'Line 103 — HST collected / collectible',
    '105_total_hst_adjustments': 'Line 105 — Total HST and adjustments',
    '106_itc': 'Line 106 — Input tax credits (ITCs)',
    '108_total_itc_adjustments': 'Line 108 — Total ITCs and adjustments',
    '109_net_tax': 'Line 109 — Net tax',
    '110_instalments': 'Line 110 — Instalments paid',
    '113_balance': 'Line 113 — Balance (refund if negative)',
    '114_refund_claimed': 'Line 114 — Refund claimed',
    '115_payment_enclosed': 'Line 115 — Payment enclosed',
  }

  return (
    <>
      <h2>Reports</h2>
      <div className="panel">
        <div className="row">
          <div className="grow">
            <label>Report</label>
            <div className="row">
              {tabs.map(([id, label]) => (
                <button key={id} type="button" className={`btn ${tab === id ? '' : 'secondary'}`} onClick={() => setTab(id)}>{label}</button>
              ))}
            </div>
          </div>
          <div><label>Period start</label><input type="date" value={start} onChange={(e) => setStart(e.target.value)} disabled={tab === 'tb' || tab === 'bs'} /></div>
          <div><label>{tab === 'tb' || tab === 'bs' ? 'As of' : 'Period end'}</label><input type="date" value={end} onChange={(e) => setEnd(e.target.value)} /></div>
          <div className="shrink"><DownloadLink href={`${current[2]}&format=pdf`} label="Download PDF" /></div>
          {tab === 'tb' && <div className="shrink"><DownloadLink href={`${current[2]}&format=csv`} label="Download CSV" /></div>}
        </div>
      </div>

      <div className="panel">
        {tab === 'tb' && (tb.error ? <Alert kind="error">{tb.error}</Alert> : tb.data && (
          <>
            <h3>Trial balance as of {end} {tb.data.balanced ? <span className="badge ok">balanced</span> : <span className="badge err">OUT OF BALANCE</span>}</h3>
            <table>
              <thead><tr><th>Code</th><th>Account</th><th className="num">Debit</th><th className="num">Credit</th></tr></thead>
              <tbody>
                {tb.data.rows.map((r) => <tr key={r.account}><td>{r.code}</td><td className="mono">{r.account}</td><td className="num">{Number(r.debit) ? money(r.debit) : ''}</td><td className="num">{Number(r.credit) ? money(r.credit) : ''}</td></tr>)}
                <tr className="total"><td></td><td>Total</td><td className="num">{money(tb.data.total_debit)}</td><td className="num">{money(tb.data.total_credit)}</td></tr>
              </tbody>
            </table>
          </>
        ))}
        {tab === 'is' && (is.error ? <Alert kind="error">{is.error}</Alert> : is.data && (
          <>
            <h3>Income statement {start} to {end}</h3>
            <table><tbody>
              <SectionRows title="Revenue" section={is.data.revenue} />
              <SectionRows title="Expenses" section={is.data.expenses} />
              <tr className="total"><td></td><td>NET INCOME</td><td className="num">{money(is.data.net_income)}</td></tr>
            </tbody></table>
          </>
        ))}
        {tab === 'bs' && (bs.error ? <Alert kind="error">{bs.error}</Alert> : bs.data && (
          <>
            <h3>Balance sheet as of {end} {bs.data.balanced ? <span className="badge ok">A = L + E</span> : <span className="badge err">DOES NOT BALANCE</span>}</h3>
            <table><tbody>
              <SectionRows title="Assets" section={bs.data.assets} />
              <SectionRows title="Liabilities" section={bs.data.liabilities} />
              <SectionRows title="Equity" section={bs.data.equity} />
              <tr className="total"><td></td><td>TOTAL LIABILITIES + EQUITY</td><td className="num">{money(bs.data.total_liabilities_and_equity)}</td></tr>
            </tbody></table>
          </>
        ))}
        {tab === 'hst' && (hst.error ? <Alert kind="error">{hst.error}</Alert> : hst.data && (
          <>
            <h3>GST/HST return worksheet (GST34) — Ontario 13% — {start} to {end}</h3>
            <table><tbody>
              {Object.entries(hst.data.lines).map(([k, v]) => (
                <tr key={k} className={k.startsWith('109') || k.startsWith('113') ? 'total' : ''}><td>{HST_LABELS[k] ?? k}</td><td className="num">{money(v)}</td></tr>
              ))}
            </tbody></table>
            <p className="muted">Sanity check: 13% of line 101 = {money(hst.data.expected_collected_at_rate)}. A large gap vs line 103 usually means exempt/zero-rated sales or missing HST postings.</p>
          </>
        ))}
      </div>
    </>
  )
}
