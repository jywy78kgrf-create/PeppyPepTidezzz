export const usd = (n: number, digits = 0) =>
  n.toLocaleString('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })

export const pct = (n: number, digits = 1) => `${(n * 100).toFixed(digits)}%`

export const signed = (n: number, digits = 0) =>
  `${n >= 0 ? '+' : ''}${n.toFixed(digits)}`

export const num = (n: number, digits = 2) =>
  n.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })

export const compact = (n: number) =>
  n.toLocaleString('en-US', { notation: 'compact', maximumFractionDigits: 1 })
