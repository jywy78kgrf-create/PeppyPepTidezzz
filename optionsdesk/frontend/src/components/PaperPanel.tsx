import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { closePosition, getPaperBook, getPaperHistory, postPaperMark } from '../api'
import type { PaperBookResponse, PaperHistoryPoint, PaperPosition } from '../types'
import Panel from './Panel'
import { usd } from '../lib/format'

const REFRESH_MS = 30_000

/* ------------------------------------------------------------------ */
/*  Small pieces                                                        */
/* ------------------------------------------------------------------ */

function LivePill({ live, asof }: { live: boolean; asof: string }) {
  const t = asof ? new Date(asof) : null
  const stamp = t
    ? t.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })
    : '—'
  return (
    <span
      className="pill"
      style={{
        borderColor: live
          ? 'color-mix(in srgb, var(--color-teal) 45%, transparent)'
          : undefined,
      }}
      title={live ? 'Marked from Alpha Vantage realtime quotes' : 'Marked from last end-of-day chain'}
    >
      <span
        className={live ? 'pulse-dot inline-block h-1.5 w-1.5 rounded-full' : 'inline-block h-1.5 w-1.5 rounded-full'}
        style={{ background: live ? 'var(--color-teal)' : 'var(--color-ink-faint)' }}
      />
      <span style={{ color: live ? 'var(--color-teal)' : 'var(--color-ink-dim)' }}>
        {live ? 'LIVE' : 'EOD'}
      </span>
      <span className="num text-[9.5px] text-[var(--color-ink-faint)]">{stamp}</span>
    </span>
  )
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: 'up' | 'down' }) {
  const color =
    tone === 'up' ? 'var(--color-up)' : tone === 'down' ? 'var(--color-down)' : 'var(--color-ink)'
  return (
    <div className="rounded-lg border border-[var(--color-edge-soft)] bg-[var(--color-void)]/40 px-2 py-1.5 text-center">
      <div className="num text-[12.5px] font-semibold" style={{ color }}>
        {value}
      </div>
      <div className="text-[8.5px] uppercase tracking-[0.12em] text-[var(--color-ink-faint)]">
        {label}
      </div>
    </div>
  )
}

function legsSummary(p: PaperPosition): string {
  return p.legs
    .map((l) => `${l.action === 'SELL' ? '−' : '+'}${l.quantity} ${l.kind}${l.strike}`)
    .join(' / ')
}

function EquityTooltip({ active, payload }: { active?: boolean; payload?: Array<{ payload: PaperHistoryPoint }> }) {
  if (!active || !payload?.length) return null
  const pt = payload[0].payload
  return (
    <div className="glass px-2.5 py-1.5 text-[10.5px]">
      <div className="text-[var(--color-ink-faint)]">
        {new Date(pt.ts).toLocaleString('en-US', {
          month: 'short',
          day: 'numeric',
          hour: '2-digit',
          minute: '2-digit',
        })}
        <span className="ml-1.5" style={{ color: pt.live ? 'var(--color-teal)' : 'var(--color-ink-faint)' }}>
          {pt.live ? 'live' : 'eod'}
        </span>
      </div>
      <div className="num font-semibold text-[var(--color-ink)]">{usd(pt.equity, 2)}</div>
      <div className="num" style={{ color: pt.upnl >= 0 ? 'var(--color-up)' : 'var(--color-down)' }}>
        {pt.upnl >= 0 ? '+' : ''}
        {usd(pt.upnl, 2)} open
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Panel                                                               */
/* ------------------------------------------------------------------ */

export default function PaperPanel({ className }: { className?: string }) {
  const [book, setBook] = useState<PaperBookResponse | null>(null)
  const [history, setHistory] = useState<PaperHistoryPoint[]>([])
  const [closing, setClosing] = useState<number | null>(null)
  const timer = useRef<ReturnType<typeof setInterval> | null>(null)

  const refreshHistory = useCallback(() => {
    getPaperHistory().then((h) => setHistory(h.points))
  }, [])

  const mark = useCallback(() => {
    postPaperMark().then((b) => {
      setBook(b)
      refreshHistory()
    })
  }, [refreshHistory])

  // initial load
  useEffect(() => {
    getPaperBook().then(setBook)
    refreshHistory()
  }, [refreshHistory])

  // auto-refresh marks every 30s — only while the tab is visible
  useEffect(() => {
    const start = () => {
      if (timer.current === null) {
        timer.current = setInterval(mark, REFRESH_MS)
      }
    }
    const stop = () => {
      if (timer.current !== null) {
        clearInterval(timer.current)
        timer.current = null
      }
    }
    const onVisibility = () => {
      if (document.visibilityState === 'visible') {
        mark() // catch up immediately, then resume cadence
        start()
      } else {
        stop()
      }
    }
    start()
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      stop()
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [mark])

  const handleClose = async (idx: number) => {
    setClosing(idx)
    try {
      const b = await closePosition(idx)
      setBook(b)
      refreshHistory()
    } finally {
      setClosing(null)
    }
  }

  // open positions with their ORIGINAL index in book.positions (close-by-index)
  const open = useMemo(
    () =>
      (book?.positions ?? [])
        .map((p, i) => ({ p, i }))
        .filter(({ p }) => p.status === 'OPEN'),
    [book],
  )

  const eq = book?.equity
  const upnl = eq?.upnl ?? 0
  const realized = eq?.realized ?? 0

  return (
    <Panel
      className={className}
      title="Paper Trading"
      subtitle={`${open.length} open — real-world verification`}
      right={book ? <LivePill live={book.live} asof={book.asof} /> : null}
    >
      <div className="flex min-h-0 flex-col gap-2.5">
        {/* book header */}
        <div className="grid grid-cols-4 gap-2">
          <Stat label="Total Equity" value={usd(eq?.total)} />
          <Stat label="Cash" value={usd(eq?.cash)} />
          <Stat
            label="Open uPnL"
            value={`${upnl >= 0 ? '+' : ''}${usd(upnl)}`}
            tone={upnl >= 0 ? 'up' : 'down'}
          />
          <Stat
            label="Realized P&L"
            value={`${realized >= 0 ? '+' : ''}${usd(realized)}`}
            tone={realized >= 0 ? 'up' : 'down'}
          />
        </div>

        {/* book equity history — does the strategy survive contact with reality? */}
        <div>
          <div className="mb-1 flex items-baseline justify-between">
            <span className="panel-title">Book Equity</span>
            <span className="text-[9px] text-[var(--color-ink-faint)]">
              marked every 30s while visible
            </span>
          </div>
          <div className="h-[110px]">
            {history.length >= 2 ? (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={history} margin={{ top: 4, right: 4, bottom: 0, left: 4 }}>
                  <defs>
                    <linearGradient id="paperEq" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="var(--color-teal)" stopOpacity={0.28} />
                      <stop offset="100%" stopColor="var(--color-teal)" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke="var(--color-edge-soft)" strokeOpacity={0.5} vertical={false} />
                  <XAxis
                    dataKey="ts"
                    tickFormatter={(v: string) =>
                      new Date(v).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
                    }
                    tick={{ fill: 'var(--color-ink-faint)', fontSize: 9 }}
                    tickLine={false}
                    axisLine={false}
                    minTickGap={70}
                  />
                  <YAxis
                    domain={['auto', 'auto']}
                    tickFormatter={(v: number) => `${Math.round(v / 1000)}k`}
                    tick={{ fill: 'var(--color-ink-faint)', fontSize: 9 }}
                    tickLine={false}
                    axisLine={false}
                    width={30}
                  />
                  <Tooltip content={<EquityTooltip />} cursor={{ stroke: 'var(--color-edge)', strokeDasharray: '3 3' }} />
                  <Area
                    type="monotone"
                    dataKey="equity"
                    stroke="var(--color-teal)"
                    strokeWidth={2}
                    fill="url(#paperEq)"
                    dot={false}
                    activeDot={{ r: 3, fill: 'var(--color-teal)', stroke: 'var(--color-void)' }}
                    isAnimationActive={false}
                  />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <div className="grid h-full place-items-center rounded-lg border border-dashed border-[var(--color-edge-soft)] text-[10px] text-[var(--color-ink-faint)]">
                Book history builds as positions are marked.
              </div>
            )}
          </div>
        </div>

        <div className="hairline" />

        {/* open positions */}
        <div className="min-h-0 flex-1 overflow-y-auto">
          <table className="w-full border-separate border-spacing-y-1 text-left">
            <thead>
              <tr className="text-[9px] uppercase tracking-[0.12em] text-[var(--color-ink-faint)]">
                <th className="pb-1 pl-2 font-medium">Position</th>
                <th className="pb-1 text-right font-medium">Basis</th>
                <th className="pb-1 text-right font-medium">Value</th>
                <th className="pb-1 text-right font-medium">uPnL</th>
                <th className="pb-1 pr-2 text-right font-medium"></th>
              </tr>
            </thead>
            <tbody>
              <AnimatePresence mode="popLayout">
                {open.map(({ p, i }) => {
                  const up = p.upnl >= 0
                  const color = up ? 'var(--color-up)' : 'var(--color-down)'
                  const denom = Math.abs(p.cost_basis)
                  const upnlPct = denom > 1e-9 ? (p.upnl / denom) * 100 : null
                  return (
                    <motion.tr
                      key={`${p.ticker}-${p.opened}-${i}`}
                      layout
                      initial={{ opacity: 0, x: -8 }}
                      animate={{ opacity: closing === i ? 0.3 : 1, x: 0 }}
                      exit={{ opacity: 0, x: 16, height: 0 }}
                      transition={{ duration: 0.3 }}
                      className="group"
                    >
                      <td className="rounded-l-lg border-y border-l border-[var(--color-edge-soft)] bg-[var(--color-panel-2)]/40 py-1.5 pl-2">
                        <div className="text-[12px] font-semibold text-[var(--color-ink)]">
                          {p.ticker}
                          <span className="ml-1.5 text-[9.5px] font-normal text-[var(--color-ink-faint)]">
                            {p.spec_name}
                          </span>
                        </div>
                        <div className="num text-[9.5px] text-[var(--color-ink-faint)]">
                          {legsSummary(p)}
                        </div>
                      </td>
                      <td className="num border-y border-[var(--color-edge-soft)] bg-[var(--color-panel-2)]/40 text-right text-[11px] text-[var(--color-ink-dim)]">
                        {usd(p.cost_basis)}
                      </td>
                      <td className="num border-y border-[var(--color-edge-soft)] bg-[var(--color-panel-2)]/40 text-right text-[11px] text-[var(--color-ink)]">
                        {usd(p.current_value)}
                      </td>
                      <td className="num border-y border-[var(--color-edge-soft)] bg-[var(--color-panel-2)]/40 px-2 text-right">
                        <div className="text-[12px] font-semibold" style={{ color }}>
                          {up ? '+' : ''}
                          {usd(p.upnl)}
                        </div>
                        <div className="text-[9.5px]" style={{ color }}>
                          {upnlPct === null ? '—' : `${up ? '+' : ''}${upnlPct.toFixed(1)}%`}
                        </div>
                      </td>
                      <td className="rounded-r-lg border-y border-r border-[var(--color-edge-soft)] bg-[var(--color-panel-2)]/40 py-1.5 pr-2 text-right">
                        <button
                          className="btn btn-danger px-2 py-1 text-[10px]"
                          onClick={() => handleClose(i)}
                          disabled={closing === i}
                        >
                          Close
                        </button>
                      </td>
                    </motion.tr>
                  )
                })}
              </AnimatePresence>
            </tbody>
          </table>
          {open.length === 0 && (
            <div className="py-6 text-center text-[11px] text-[var(--color-ink-faint)]">
              No open positions — open one from Suggestions to start the real-world test.
            </div>
          )}
        </div>
      </div>
    </Panel>
  )
}
