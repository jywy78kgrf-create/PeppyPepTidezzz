import { useEffect, useState } from 'react'
import * as mock from '../mock'
import type { Quote } from '../types'
import { num } from '../lib/format'

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

export default function TickerTape() {
  const [tape, setTape] = useState<Quote[]>(() => mock.mockTape())

  useEffect(() => {
    const id = setInterval(() => setTape(mock.mockTape()), 4000)
    return () => clearInterval(id)
  }, [])

  const doubled = [...tape, ...tape]

  return (
    <div
      className="glass relative flex h-9 items-center overflow-hidden"
      style={{ borderRadius: 11 }}
    >
      <div className="absolute left-0 top-0 z-10 flex h-full items-center gap-2 bg-[var(--color-panel)]/80 px-3.5 backdrop-blur-sm">
        <span
          className="pulse-dot"
          style={{ width: 6, height: 6, borderRadius: 99, background: 'var(--color-teal)', boxShadow: '0 0 8px var(--color-teal)' }}
        />
        <span className="panel-title">Live Tape</span>
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
