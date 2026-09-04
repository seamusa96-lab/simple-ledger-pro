// Exact integer-cents money helpers, kept out of the floating-point Number type
// (which rounds values like 0.1 and loses precision past 2^53). Used by the
// journal entry form so every cent typed by the user reaches the API unchanged.

// Parse a money string to integer cents exactly. Returns 0 for blank/invalid input.
export const toCents = (s: string): bigint => {
  const t = s.trim()
  if (t === '' || t === '-' || !/^-?\d*(?:\.\d*)?$/.test(t)) return 0n
  const neg = t.startsWith('-')
  const [whole, frac = ''] = t.replace('-', '').split('.')
  const cents = BigInt(whole || '0') * 100n + BigInt((frac + '00').slice(0, 2).padEnd(2, '0'))
  return neg ? -cents : cents
}

// Render integer cents back to a fixed 2-decimal string for the API / display.
export const centsToStr = (c: bigint): string => {
  const neg = c < 0n
  const abs = neg ? -c : c
  return `${neg ? '-' : ''}${abs / 100n}.${(abs % 100n).toString().padStart(2, '0')}`
}
