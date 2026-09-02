import type { Account } from './api'

export function Alert({ kind, children }: { kind: 'error' | 'ok' | 'info'; children: React.ReactNode }) {
  if (!children) return null
  return <div className={`alert ${kind}`}>{children}</div>
}

export function AccountSelect({
  accounts,
  value,
  onChange,
  filter,
  placeholder = 'Select account',
}: {
  accounts: Account[]
  value: string
  onChange: (v: string) => void
  filter?: (a: Account) => boolean
  placeholder?: string
}) {
  const list = accounts.filter((a) => !a.closed && (!filter || filter(a)))
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">{placeholder}</option>
      {list.map((a) => (
        <option key={a.name} value={a.name}>
          {a.code ? `${a.code} - ` : ''}
          {a.name}
        </option>
      ))}
    </select>
  )
}

export function DownloadLink({ href, label }: { href: string; label: string }) {
  return (
    <a className="btn secondary small" href={href} download>
      {label}
    </a>
  )
}

export function Flag({ flag }: { flag: '*' | '!' }) {
  return flag === '!' ? <span className="badge pending">pending</span> : <span className="badge ok">cleared</span>
}
