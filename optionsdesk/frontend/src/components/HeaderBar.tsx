import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { getBrokerStatus, getHealth, getPaperBook, getPaperHistory, onSourceChange } from '../api'
import type { BrokerStatus } from '../types'
import { usd } from '../lib/format'

function Clock() {
  const [now, setNow] = useState(new Date())
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(id)
  }, [])
  const time = now.toLocaleTimeString('en-US', {
    hour12: false,
    timeZone: 'America/New_York',
  })
  const date = now.toLocaleDateString('en-US', {
    weekday: 'short',
    month: 'short',
    day: '2-digit',
    timeZone: 'America/New_York',
  })
  return (
    <div className="flex flex-col items-end leading-none">
      <span className="num text-[15px] font-medium tracking-wide text-[var(--color-ink)]">
        {time}
        <span className="ml-1 text-[10px] text-[var(--color-ink-faint)]">EST</span>
      </span>
      <span className="text-[10px] tracking-wide text-[var(--color-ink-faint)]">{date}</span>
    </div>
  )
}

function StatusPill({ b }: { b: BrokerStatus }) {
  const color = b.connected ? 'var(--color-teal)' : 'var(--color-down)'
  return (
    <div className="pill" title={b.detail}>
      <span
        className={b.connected ? 'pulse-dot' : ''}
        style={{
          width: 6,
          height: 6,
          borderRadius: 99,
          background: color,
          boxShadow: `0 0 8px ${color}`,
        }}
      />
      <span className="text-[var(--color-ink-dim)]">{b.name}</span>
      {b.latency_ms != null && b.connected && (
        <span className="num text-[9px] text-[var(--color-ink-faint)]">{b.latency_ms}ms</span>
      )}
    </div>
  )
}

function AnimatedEquity({ value }: { value: number }) {
  const [display, setDisplay] = useState(value)
  useEffect(() => {
    const start = display
    const t0 = performance.now()
    const dur = 800
    let raf = 0
    const tick = (t: number) => {
      const k = Math.min(1, (t - t0) / dur)
      const eased = 1 - Math.pow(1 - k, 3)
      setDisplay(start + (value - start) * eased)
      if (k < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value])
  return <span className="num text-[20px] font-semibold text-[var(--color-ink)]">{usd(display)}</span>
}

export default function HeaderBar() {
  const [brokers, setBrokers] = useState<BrokerStatus[]>([])
  const [live, setLive] = useState<boolean | null>(null)
  const [equity, setEquity] = useState<number | null>(null)
  const [dayPnl, setDayPnl] = useState<number | null>(null)

  useEffect(() => {
    getHealth()

    // Real account figures from the paper book: total equity, and day P&L as
    // the change since the first history point on the current calendar day.
    const refresh = () => {
      getBrokerStatus().then(setBrokers)
      getPaperBook().then((book) => setEquity(book.equity.total))
      getPaperHistory().then((h) => {
        const pts = h.points
        if (pts.length === 0) return setDayPnl(0)
        const today = new Date().toDateString()
        const first =
          pts.find((p) => new Date(p.ts).toDateString() === today) ?? pts[0]
        setDayPnl(pts[pts.length - 1].equity - first.equity)
      })
    }
    refresh()
    const off = onSourceChange(setLive)
    const poll = setInterval(refresh, 15000)
    return () => {
      off()
      clearInterval(poll)
    }
  }, [])

  return (
    <motion.header
      initial={{ opacity: 0, y: -12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
      className="glass flex items-center justify-between gap-6 px-5 py-3"
      style={{ borderRadius: 14 }}
    >
      {/* brand */}
      <div className="flex items-center gap-3.5">
        <div className="relative grid h-9 w-9 place-items-center">
          <div
            className="absolute inset-0 rounded-[10px]"
            style={{
              background: 'linear-gradient(145deg, #1a2230, #0a0f17)',
              border: '1px solid color-mix(in srgb, var(--color-gold) 30%, transparent)',
              boxShadow: '0 0 18px -6px var(--color-gold), inset 0 1px 0 rgba(255,255,255,.08)',
            }}
          />
          <svg viewBox="0 0 24 24" className="relative h-5 w-5" fill="none">
            <path
              d="M12 2 L21 19 H3 Z"
              stroke="var(--color-gold-bright)"
              strokeWidth="1.4"
              strokeLinejoin="round"
            />
            <path d="M7.5 13 H16.5" stroke="var(--color-gold)" strokeWidth="1.2" />
            <circle cx="12" cy="9" r="1.1" fill="var(--color-gold-bright)" />
          </svg>
        </div>
        <div className="leading-tight">
          <div className="flex items-center gap-2">
            <span className="text-[17px] font-semibold tracking-[0.22em] text-[var(--color-ink)]">
              ATLAS
            </span>
            <span className="tag">v1.4</span>
          </div>
          <span className="text-[9.5px] tracking-[0.34em] text-[var(--color-ink-faint)]">
            AUTOMATED OPTIONS DESK
          </span>
        </div>
      </div>

      {/* equity */}
      <div className="flex items-center gap-7">
        <div className="hidden flex-col items-end leading-tight md:flex">
          <span className="panel-title">Account Equity</span>
          {equity === null ? (
            <span className="num text-[19px] font-semibold text-[var(--color-ink-faint)]">—</span>
          ) : (
            <AnimatedEquity value={equity} />
          )}
        </div>
        <div className="hidden flex-col items-end leading-tight lg:flex">
          <span className="panel-title">Day P&L</span>
          <span
            className="num text-[15px] font-semibold"
            style={{
              color:
                dayPnl === null
                  ? 'var(--color-ink-faint)'
                  : dayPnl >= 0
                    ? 'var(--color-up)'
                    : 'var(--color-down)',
            }}
          >
            {dayPnl === null ? '—' : `${dayPnl >= 0 ? '+' : ''}${usd(dayPnl)}`}
          </span>
        </div>

        <div className="h-9 w-px bg-[var(--color-edge)]" />

        {/* connection pills */}
        <div className="flex items-center gap-2">
          {brokers.map((b) => (
            <StatusPill key={b.name} b={b} />
          ))}
          <AnimatePresence>
            {live === false && (
              <motion.span
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0 }}
                className="pill"
                style={{
                  borderColor: 'color-mix(in srgb, var(--color-amber) 45%, transparent)',
                  color: 'var(--color-amber)',
                }}
                title="Backend unreachable — serving simulated data"
              >
                SIMULATED
              </motion.span>
            )}
          </AnimatePresence>
        </div>

        <div className="h-9 w-px bg-[var(--color-edge)]" />
        <Clock />
      </div>
    </motion.header>
  )
}
