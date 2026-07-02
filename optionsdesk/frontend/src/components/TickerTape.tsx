import { useEffect, useState } from 'react'
import { getTape } from '../api'
import type { Quote } from '../types'
import { num } from '../lib/format'

const REFRESH_MS = 60_000 // one bulk quote call per minute — rate-limit friendly

function Item({ q }: { q: Quote }) {
  const up = q.change >= 0
  const color = up ? 'var(--color-up)' : 'var(--color-down)'
  return (
    <div className="flex items-center gap-2.5 px-5">
      <span className="text-[12px] font-semibold tracking-wide text-[var(--color-ink)]">
        {q.ticker}
      </span>
      <span className="num text-[12px] text-[var(--color-ink-dim)]">{num(q.price)}</span>
      <span className="num flex items-center gap-1 text-[11px]" style={{ color }}>
        <svg width="8" height="8" viewBox="0 0 8 8" style={{ transform: up ? '' : 'rotate(180deg)' }}>
          <path d="M4 0 L8 6 H0 Z" fill={color} />
        </svg>
        {up ? '+' : ''}
        {q.change_pct.toFixed(2)}%
      </span>
    </div>
  )
}

type Source = 'live' | 'eod' | 'sim'

const SOURCE_LABEL: Record<Source, string> = {
  live: 'Live Tape',
  eod: 'EOD Tape',
  sim: 'Sim Tape',
}
const SOURCE_COLOR: Record<Source, string> = {
  live: 'var(--color-teal)',
  eod: 'var(--color-ink-faint)',
  sim: 'var(--color-amber)',
}

export default function TickerTape() {
  const [tape, setTape] = useState<Quote[]>([])
  const [source, setSource] = useState<Source>('eod')

  // Real quotes only: one backend call per minute (which is itself a single
  // Alpha Vantage bulk request when live). No client-side fake jitter — the
  // label always states exactly where the prices came from.
  useEffect(() => {
    const refresh = () =>
      getTape().then((r) => {
        setTape(r.quotes)
        setSource(r.simulated ? 'sim' : r.live ? 'live' : 'eod')
      })
    refresh()
    const id = setInterval(refresh, REFRESH_MS)
    return () => clearInterval(id)
  }, [])

  if (tape.length === 0) return null
  const doubled = [...tape, ...tape]
  const color = SOURCE_COLOR[source]

  return (
    <div
      className="glass relative flex h-9 items-center overflow-hidden"
      style={{ borderRadius: 11 }}
    >
      <div className="absolute left-0 top-0 z-10 flex h-full items-center gap-2 bg-[var(--color-panel)]/80 px-3.5 backdrop-blur-sm">
        <span
          className={source === 'live' ? 'pulse-dot' : ''}
          style={{ width: 6, height: 6, borderRadius: 99, background: color, boxShadow: source === 'live' ? `0 0 8px ${color}` : 'none' }}
        />
        <span className="panel-title" style={source === 'sim' ? { color } : undefined}>
          {SOURCE_LABEL[source]}
        </span>
      </div>
      {/* edge fades */}
      <div
        className="pointer-events-none absolute inset-y-0 left-0 z-10 w-28"
        style={{ background: 'linear-gradient(90deg, var(--color-panel), transparent)' }}
      />
      <div
        className="pointer-events-none absolute inset-y-0 right-0 z-10 w-16"
        style={{ background: 'linear-gradient(270deg, var(--color-panel), transparent)' }}
      />
      <div className="animate-ticker flex shrink-0 items-center whitespace-nowrap pl-32">
        {doubled.map((q, i) => (
          <div key={i} className="flex items-center">
            <Item q={q} />
            <span className="text-[var(--color-edge)]">|</span>
          </div>
        ))}
      </div>
    </div>
  )
}
