import { describe, expect, it } from 'vitest'
import { centsToStr, toCents } from './money'

describe('toCents', () => {
  it('parses whole and fractional amounts exactly', () => {
    expect(toCents('0')).toBe(0n)
    expect(toCents('1')).toBe(100n)
    expect(toCents('1.00')).toBe(100n)
    expect(toCents('1.05')).toBe(105n)
    expect(toCents('0.1')).toBe(10n)
    expect(toCents('1234.56')).toBe(123456n)
  })

  it('handles negatives and whitespace', () => {
    expect(toCents(' -12.34 ')).toBe(-1234n)
    expect(toCents('-0.01')).toBe(-1n)
  })

  it('treats blank and malformed input as zero', () => {
    expect(toCents('')).toBe(0n)
    expect(toCents('-')).toBe(0n)
    expect(toCents('abc')).toBe(0n)
    expect(toCents('1.2.3')).toBe(0n)
  })

  it('preserves cents beyond the exact float range (>2^53)', () => {
    // 90071992547409.91 is past Number.MAX_SAFE_INTEGER when expressed in cents;
    // Number arithmetic would drop the trailing cent, bigint does not.
    const s = '90071992547409.91'
    expect(toCents(s)).toBe(9007199254740991n)
    expect(centsToStr(toCents(s))).toBe(s)
  })
})

describe('centsToStr', () => {
  it('always renders two decimals', () => {
    expect(centsToStr(0n)).toBe('0.00')
    expect(centsToStr(5n)).toBe('0.05')
    expect(centsToStr(100n)).toBe('1.00')
    expect(centsToStr(123456n)).toBe('1234.56')
    expect(centsToStr(-1n)).toBe('-0.01')
  })
})

describe('debit/credit round-trip', () => {
  it('signed posting amount equals debit minus credit exactly', () => {
    // What the journal form sends: centsToStr(toCents(debit) - toCents(credit)).
    expect(centsToStr(toCents('100.10') - toCents('0'))).toBe('100.10')
    expect(centsToStr(toCents('0') - toCents('99.99'))).toBe('-99.99')
  })
})
