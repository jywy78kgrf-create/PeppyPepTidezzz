// Formatters. All guard against null/undefined/non-finite so a missing or
// sanitized-to-null backend field (e.g. a long call's unlimited max_profit)
// can never crash a render.

const bad = (n: unknown): boolean =>
  n === null || n === undefined || typeof n !== 'number' || !Number.isFinite(n)

export const usd = (n: number | null | undefined, digits = 0) =>
  bad(n)
    ? '—'
    : (n as number).toLocaleString('en-US', {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      })

export const pct = (n: number | null | undefined, digits = 1) =>
  bad(n) ? '—' : `${((n as number) * 100).toFixed(digits)}%`

export const signed = (n: number | null | undefined, digits = 0) =>
  bad(n) ? '—' : `${(n as number) >= 0 ? '+' : ''}${(n as number).toFixed(digits)}`

export const num = (n: number | null | undefined, digits = 2) =>
  bad(n)
    ? '—'
    : (n as number).toLocaleString('en-US', {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      })

export const compact = (n: number | null | undefined) =>
  bad(n)
    ? '—'
    : (n as number).toLocaleString('en-US', { notation: 'compact', maximumFractionDigits: 1 })
