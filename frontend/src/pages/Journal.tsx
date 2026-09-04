import { useMemo, useState } from 'react'
import { api, money, today, type Transaction } from '../api'
import { AccountSelect, Alert, DownloadLink, Flag } from '../components'
import { useAsync } from '../useAsync'

type Line = { account: string; debit: string; credit: string }
const blank = (): Line => ({ account: '', debit: '', credit: '' })

// Parse a money string to integer cents exactly, without going through the
// floating-point Number type (which loses precision past 2^53 cents / rounds
// values like 0.1). Returns 0 for blank/invalid input.
const toCents = (s: string): bigint => {
  const m = s.trim().match(/^-?\d*(?:\.\d{0,})?$/)
  if (!m || s.trim() === '' || s.trim() === '-') return 0n
  const neg = s.trim().startsWith('-')
  const [whole, frac = ''] = s.trim().replace('-', '').split('.')
  const cents = BigInt(whole || '0') * 100n + BigInt((frac + '00').slice(0, 2).padEnd(2, '0'))
  return neg ? -cents : cents
}

// Render integer cents back to a fixed 2-decimal string for the API / display.
const centsToStr = (c: bigint): string => {
  const neg = c < 0n
  const abs = neg ? -c : c
  return `${neg ? '-' : ''}${abs / 100n}.${(abs % 100n).toString().padStart(2, '0')}`
}

export function JournalPage() {
  const accounts = useAsync(api.accounts)
  const txns = useAsync(() => api.transactions({ limit: '200' }))
  const [date, setDate] = useState(today())
  const [payee, setPayee] = useState('')
  const [narration, setNarration] = useState('')
  const [lines, setLines] = useState<Line[]>([blank(), blank()])
  const [msg, setMsg] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)
  const [voidTarget, setVoidTarget] = useState<Transaction | null>(null)
  const [voidReason, setVoidReason] = useState('')
  const [catTarget, setCatTarget] = useState<Transaction | null>(null)
  const [catAccount, setCatAccount] = useState('')
  const [catHst, setCatHst] = useState(true)

  const totals = useMemo(() => {
    const d = lines.reduce((s, l) => s + toCents(l.debit), 0n)
    const c = lines.reduce((s, l) => s + toCents(l.credit), 0n)
    return { d: centsToStr(d), c: centsToStr(c), diff: centsToStr(d > c ? d - c : c - d), ok: d === c && d > 0n }
  }, [lines])

  const setLine = (i: number, patch: Partial<Line>) => setLines(lines.map((l, j) => (j === i ? { ...l, ...patch } : l)))

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      await api.createTransaction({
        date,
        payee: payee || null,
        narration,
        postings: lines
          .filter((l) => l.account)
          .map((l) => ({ account: l.account, amount: centsToStr(toCents(l.debit) - toCents(l.credit)) })),
      })
      setMsg({ kind: 'ok', text: 'Journal entry posted.' })
      setPayee('')
      setNarration('')
      setLines([blank(), blank()])
      txns.reload()
    } catch (err) {
      setMsg({ kind: 'error', text: (err as Error).message })
    }
  }

  const doVoid = async () => {
    if (!voidTarget) return
    try {
      await api.voidTransaction(voidTarget.id, voidReason || 'Voided')
      setMsg({ kind: 'ok', text: `Reversal posted for ${voidTarget.id}.` })
      setVoidTarget(null)
      setVoidReason('')
      txns.reload()
    } catch (err) {
      setMsg({ kind: 'error', text: (err as Error).message })
    }
  }

  const doCategorize = async () => {
    if (!catTarget || !catAccount) return
    try {
      await api.categorize(catTarget.id, catAccount, catHst)
      setMsg({ kind: 'ok', text: `Categorized ${catTarget.id} → ${catAccount}` })
      setCatTarget(null)
      txns.reload()
    } catch (err) {
      setMsg({ kind: 'error', text: (err as Error).message })
    }
  }

  const accts = accounts.data ?? []
  return (
    <>
      <h2>General Journal</h2>
      <div className="downloads">
        <DownloadLink href="/api/reports/general-ledger" label="Download general ledger (CSV)" />
        <DownloadLink href="/api/ledger/raw" label="Download main.beancount" />
      </div>
      {msg && <Alert kind={msg.kind}>{msg.text}</Alert>}

      <form className="panel" onSubmit={submit}>
        <h3>New journal entry</h3>
        <div className="row">
          <div><label>Date</label><input type="date" value={date} onChange={(e) => setDate(e.target.value)} required /></div>
          <div><label>Payee</label><input value={payee} onChange={(e) => setPayee(e.target.value)} /></div>
          <div className="grow"><label>Description</label><input value={narration} onChange={(e) => setNarration(e.target.value)} required /></div>
        </div>
        <div className="postings" style={{ marginTop: 12 }}>
          {lines.map((l, i) => (
            <div className="row" key={i}>
              <div className="grow">
                {i === 0 && <label>Account</label>}
                <AccountSelect accounts={accts} value={l.account} onChange={(v) => setLine(i, { account: v })} />
              </div>
              <div>
                {i === 0 && <label>Debit (CAD)</label>}
                <input type="number" step="0.01" min="0" value={l.debit} onChange={(e) => setLine(i, { debit: e.target.value, credit: '' })} />
              </div>
              <div>
                {i === 0 && <label>Credit (CAD)</label>}
                <input type="number" step="0.01" min="0" value={l.credit} onChange={(e) => setLine(i, { credit: e.target.value, debit: '' })} />
              </div>
              <div className="shrink">
                <button type="button" className="btn secondary small" onClick={() => setLines(lines.filter((_, j) => j !== i))} disabled={lines.length <= 2}>×</button>
              </div>
            </div>
          ))}
        </div>
        <div className={`balance-check ${totals.ok ? 'ok' : 'bad'}`}>
          Debits {money(totals.d)} · Credits {money(totals.c)} · {totals.ok ? 'Balanced' : `Out of balance by ${money(totals.diff)}`}
        </div>
        <div className="row">
          <div className="shrink"><button type="button" className="btn secondary" onClick={() => setLines([...lines, blank()])}>Add line</button></div>
          <div className="shrink"><button type="submit" className="btn" disabled={!totals.ok}>Post entry</button></div>
        </div>
      </form>

      {voidTarget && (
        <div className="panel">
          <h3>Void {voidTarget.id}</h3>
          <p className="muted">Cleared entries are immutable. A mirror-image reversal dated today will be posted and linked to the original.</p>
          <div className="row">
            <div className="grow"><label>Reason</label><input value={voidReason} onChange={(e) => setVoidReason(e.target.value)} /></div>
            <div className="shrink"><button className="btn danger" onClick={doVoid}>Post reversal</button></div>
            <div className="shrink"><button className="btn secondary" onClick={() => setVoidTarget(null)}>Cancel</button></div>
          </div>
        </div>
      )}
      {catTarget && (
        <div className="panel">
          <h3>Categorize {catTarget.id} — {catTarget.narration}</h3>
          <div className="row">
            <div className="grow">
              <label>Account</label>
              <AccountSelect accounts={accts} value={catAccount} onChange={setCatAccount} filter={(a) => a.type === 'Expenses' || a.type === 'Income' || a.type === 'Liabilities' || a.type === 'Assets'} />
            </div>
            <div className="shrink">
              <label>&nbsp;</label>
              <label style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 14, color: 'inherit' }}>
                <input type="checkbox" style={{ width: 'auto' }} checked={catHst} onChange={(e) => setCatHst(e.target.checked)} /> Split 13% HST
              </label>
            </div>
            <div className="shrink"><button className="btn" onClick={doCategorize} disabled={!catAccount}>Save</button></div>
            <div className="shrink"><button className="btn secondary" onClick={() => setCatTarget(null)}>Cancel</button></div>
          </div>
        </div>
      )}

      <div className="panel">
        <h3>Entries</h3>
        {txns.error && <Alert kind="error">{txns.error}</Alert>}
        <table>
          <thead><tr><th>Date</th><th>Status</th><th>Payee / description</th><th>Postings</th><th className="num">Debit</th><th className="num">Credit</th><th>Audit</th><th></th></tr></thead>
          <tbody>
            {(txns.data ?? []).map((t) => (
              <tr key={t.id}>
                <td>{t.date}</td>
                <td><Flag flag={t.flag} /></td>
                <td>
                  {[t.payee, t.narration].filter(Boolean).join(' — ')}
                  {t.links.length > 0 && <div className="muted">^{t.links.join(' ^')}</div>}
                </td>
                <td className="mono">{t.postings.map((p) => <div key={p.account + p.amount}>{p.account}</div>)}</td>
                <td className="num">{t.postings.map((p) => <div key={p.account + p.amount}>{p.debit ? money(p.debit) : '\u00a0'}</div>)}</td>
                <td className="num">{t.postings.map((p) => <div key={p.account + p.amount}>{p.credit ? money(p.credit) : '\u00a0'}</div>)}</td>
                <td className="muted">
                  {t.meta.created_by} · {t.meta.source}
                  <br />{t.meta.created_at?.slice(0, 16)}
                  {t.meta.revised_at && <><br />revised {t.meta.revised_at.slice(0, 16)}</>}
                </td>
                <td>
                  {t.flag === '!' ? (
                    <button className="btn small" onClick={() => { setCatTarget(t); setCatAccount('') }}>Categorize</button>
                  ) : (
                    !t.meta.reverses && <button className="btn secondary small" onClick={() => setVoidTarget(t)}>Void</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}
