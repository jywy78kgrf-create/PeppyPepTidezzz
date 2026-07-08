// The Trading Desk — the app's main stage. The forward paper test in full
// view: headline equity + day P&L, the book equity curve against its $100k
// baseline, live greeks gauges, rich open-position cards that move as marks
// land, the ledger's closed-trade record, and realized P&L by strategy.
// Every number is real (paper book / ledger); nothing here is simulated.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  closePosition,
  getLedgerTrades,
  getPaperBook,
  getPaperGreeks,
  getPaperHistory,
  postPaperMark,
} from '../api'
import type {
  LedgerTrade,
  PaperBookResponse,
  PaperGreeksResponse,
  PaperHistoryPoint,
  PaperPosition,
} from '../types'
import Panel from './Panel'
import { usd } from '../lib/format'

// Re-mark every 2 min while visible. Gentle on the Alpha Vantage rate limit
// (the key is often shared with other apps); for a multi-week paper test,
// 2-min marks lose no meaningful fidelity. The autopilot also marks on its
// own trade cycle during market hours.
const REFRESH_MS = 120_000

/* ------------------------------------------------------------------ */
/*  Small pieces                                                        */
/* ------------------------------------------------------------------ */

function LivePill({ live, asof }: { live: boolean; asof: string }) {
  const t = new Date(asof)
  const time = Number.isNaN(t.getTime())
    ? '—'
    : t.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })
  return (
    <span
      className="pill"
      title={live ? 'Marked from Alpha Vantage realtime options' : 'Marked from latest stored chains (EOD)'}
      style={{ color: live ? 'var(--color-teal)' : 'var(--color-ink-faint)' }}
    >
      <span
        className={live ? 'pulse-dot inline-block h-1.5 w-1.5 rounded-full' : 'inline-block h-1.5 w-1.5 rounded-full'}
        style={{ background: live ? 'var(--color-teal)' : 'var(--color-ink-faint)' }}
      />
      {live ? 'LIVE' : 'EOD'} {time}
    </span>
  )
}

function Headline({
  label,
  value,
  tone,
  big = false,
  sub,
}: {
  label: string
  value: string
  tone?: 'up' | 'down' | 'gold'
  big?: boolean
  sub?: string
}) {
  const color =
    tone === 'up'
      ? 'var(--color-up)'
      : tone === 'down'
        ? 'var(--color-down)'
        : tone === 'gold'
          ? 'var(--color-gold-bright)'
          : 'var(--color-ink)'
  return (
    <div className="rounded-lg border border-[var(--color-edge-soft)] bg-[var(--color-void)]/40 px-3 py-2">
      <div className="text-[9px] tracking-[0.14em] text-[var(--color-ink-faint)]">{label}</div>
      <AnimatePresence mode="popLayout">
        <motion.div
          key={value}
          initial={{ opacity: 0, y: 5 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -5 }}
          transition={{ duration: 0.35 }}
          className={`num font-semibold ${big ? 'text-[20px]' : 'text-[14px]'}`}
          style={{ color }}
        >
          {value}
        </motion.div>
      </AnimatePresence>
      {sub && <div className="num mt-0.5 text-[9px] text-[var(--color-ink-faint)]">{sub}</div>}
    </div>
  )
}

interface TipProps {
  active?: boolean
  payload?: Array<{ payload: PaperHistoryPoint }>
}
function EquityTooltip({ active, payload }: TipProps) {
  if (!active || !payload?.length) return null
  const pt = payload[0].payload
  return (
    <div className="glass px-3 py-2" style={{ borderRadius: 10 }}>
      <div className="num text-[10px] text-[var(--color-ink-faint)]">
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

/* ---- greeks gauges: signed bars around zero -------------------------- */
const GREEK_META: Array<{
  key: 'delta' | 'gamma' | 'theta' | 'vega'
  sym: string
  scale: number
  tip: string
}> = [
  { key: 'delta', sym: 'Δ', scale: 1000, tip: 'share-equivalent directional exposure' },
  { key: 'gamma', sym: 'Γ', scale: 100, tip: 'delta change per $1 underlying move' },
  { key: 'theta', sym: 'Θ', scale: 500, tip: '$ earned (+) or paid (−) per day of time decay' },
  { key: 'vega', sym: 'V', scale: 1000, tip: '$ per 1-point volatility move' },
]

function GreeksGauges({ greeks }: { greeks: PaperGreeksResponse }) {
  return (
    <div className="rounded-lg border border-[var(--color-edge-soft)] bg-[var(--color-void)]/40 px-3 py-2">
      <div className="mb-1.5 flex items-center justify-between">
        <span className="text-[8.5px] tracking-[0.14em] text-[var(--color-ink-faint)]">
          BOOK GREEKS
        </span>
        {greeks.unmatched_legs > 0 && (
          <span className="text-[8px] text-[var(--color-amber)]" title="legs without a live quote at the last mark">
            {greeks.unmatched_legs} unmatched
          </span>
        )}
      </div>
      <div className="grid grid-cols-4 gap-3">
        {GREEK_META.map(({ key, sym, scale, tip }) => {
          const v = greeks.totals[key]
          const frac = Math.max(-1, Math.min(1, v / scale))
          const color = v === 0 ? 'var(--color-ink-dim)' : v > 0 ? 'var(--color-up)' : 'var(--color-down)'
          return (
            <div key={key} title={tip}>
              <div className="flex items-baseline justify-between">
                <span className="text-[10px] text-[var(--color-ink-faint)]">{sym}</span>
                <span className="num text-[11px] font-semibold" style={{ color }}>
                  {v > 0 ? '+' : ''}
                  {v.toFixed(1)}
                </span>
              </div>
              {/* signed bar: grows right for +, left for − */}
              <div className="relative mt-1 h-[5px] overflow-hidden rounded-full bg-[var(--color-void)]/70">
                <div className="absolute left-1/2 top-0 h-full w-px bg-[var(--color-edge)]" />
                <div
                  className="absolute top-0 h-full rounded-full transition-all duration-700"
                  style={{
                    left: frac >= 0 ? '50%' : `${50 + frac * 50}%`,
                    width: `${Math.abs(frac) * 50}%`,
                    background: `color-mix(in srgb, ${color} 70%, transparent)`,
                    boxShadow: `0 0 6px -1px ${color}`,
                  }}
                />
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

/* ---- open position card ---------------------------------------------- */
function legLine(l: { action: string; kind: string; strike: number; expiry: string; quantity?: number }) {
  const q = l.quantity && l.quantity !== 1 ? ` ×${l.quantity}` : ''
  return `${l.action} ${l.strike}${l.kind}${q} · ${l.expiry}`
}

function ageDays(openedIso: string): string {
  const ms = Date.now() - new Date(openedIso).getTime()
  if (!Number.isFinite(ms) || ms < 0) return '—'
  const d = ms / 86_400_000
  return d < 1 ? `${Math.max(1, Math.round(d * 24))}h` : `${Math.floor(d)}d`
}

function PositionCard({
  p,
  onClose,
  closing,
}: {
  p: PaperPosition
  onClose: () => void
  closing: boolean
}) {
  const up = p.upnl >= 0
  const color = up ? 'var(--color-up)' : 'var(--color-down)'
  const denom = Math.abs(p.cost_basis)
  const pct = denom > 1e-9 ? (p.upnl / denom) * 100 : null
  // meter: uPnL as a fraction of basis, clamped to ±50% for display
  const frac = pct === null ? 0 : Math.max(-1, Math.min(1, pct / 50))
  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 10, scale: 0.98 }}
      animate={{ opacity: closing ? 0.35 : 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, scale: 0.96, transition: { duration: 0.25 } }}
      transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
      className="flex flex-col gap-1 rounded-xl border p-2"
      style={{
        borderColor: `color-mix(in srgb, ${color} 22%, var(--color-edge-soft))`,
        background: 'color-mix(in srgb, var(--color-panel-2) 55%, transparent)',
        boxShadow: `inset 0 1px 0 color-mix(in srgb, #ffffff 5%, transparent), 0 0 18px -12px ${color}`,
      }}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-baseline gap-1.5">
            <span className="text-[14px] font-bold text-[var(--color-ink)]">{p.ticker}</span>
            <span className="truncate text-[9.5px] text-[var(--color-ink-faint)]">
              {p.spec_name.replace(/_/g, ' ')}
            </span>
          </div>
          <div className="num text-[8.5px] text-[var(--color-ink-faint)]">
            open {ageDays(p.opened)}
          </div>
        </div>
        <div className="text-right">
          <AnimatePresence mode="popLayout">
            <motion.div
              key={p.upnl.toFixed(2)}
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -4 }}
              className="num text-[14px] font-bold"
              style={{ color }}
            >
              {up ? '+' : ''}
              {usd(p.upnl)}
            </motion.div>
          </AnimatePresence>
          <div className="num text-[9px]" style={{ color }}>
            {pct === null ? '—' : `${up ? '+' : ''}${pct.toFixed(1)}% on basis`}
          </div>
        </div>
      </div>

      {/* legs */}
      <div className="num space-y-px text-[9px] leading-snug text-[var(--color-ink-dim)]">
        {p.legs.map((l, i) => (
          <div key={i} className="flex items-center gap-1">
            <span
              className="inline-block h-1 w-1 rounded-full"
              style={{
                background: l.action === 'SELL' ? 'var(--color-amber)' : 'var(--color-teal)',
              }}
            />
            {legLine(l)}
          </div>
        ))}
      </div>

      {/* uPnL meter */}
      <div className="relative h-[4px] overflow-hidden rounded-full bg-[var(--color-void)]/70">
        <div className="absolute left-1/2 top-0 h-full w-px bg-[var(--color-edge)]" />
        <div
          className="absolute top-0 h-full rounded-full transition-all duration-700"
          style={{
            left: frac >= 0 ? '50%' : `${50 + frac * 50}%`,
            width: `${Math.abs(frac) * 50}%`,
            background: `color-mix(in srgb, ${color} 70%, transparent)`,
          }}
        />
      </div>

      <div className="flex items-center justify-between">
        <span className="num text-[9px] text-[var(--color-ink-faint)]">
          basis {usd(p.cost_basis)} → mark {usd(p.current_value)}
        </span>
        <button className="btn btn-danger px-2 py-0.5 text-[9px]" onClick={onClose} disabled={closing}>
          Close
        </button>
      </div>
    </motion.div>
  )
}

/* ---- closed trades (ledger) ------------------------------------------ */
const REASON_COLOR: Record<string, string> = {
  target: 'var(--color-up)',
  stop: 'var(--color-down)',
  close_dte: 'var(--color-teal)',
  expiry: 'var(--color-iris)',
  assigned: 'var(--color-amber)',
  manual: 'var(--color-ink-dim)',
  breaker: 'var(--color-down)',
}

function ClosedTrades({ trades }: { trades: LedgerTrade[] }) {
  if (!trades.length) {
    return (
      <div className="py-4 text-center text-[9.5px] text-[var(--color-ink-faint)]">
        No closed trades yet — the record starts with the first exit.
      </div>
    )
  }
  return (
    <div className="space-y-1">
      {trades.map((t, i) => {
        const pnl = t.pnl ?? 0
        const up = pnl >= 0
        return (
          <div
            key={`${t.ticker}-${t.opened}-${i}`}
            className="flex items-center gap-2 rounded-md border border-[var(--color-edge-soft)] bg-[var(--color-void)]/30 px-2 py-1"
            title={`${t.strategy} on ${t.ticker} · opened ${t.opened?.slice(0, 10)} closed ${t.closed?.slice(0, 10)} · qty ${t.qty}`}
          >
            <span className="w-10 shrink-0 text-[10px] font-semibold text-[var(--color-ink)]">
              {t.ticker}
            </span>
            <span className="min-w-0 flex-1 truncate text-[8.5px] text-[var(--color-ink-faint)]">
              {t.strategy.replace(/_/g, ' ')}
            </span>
            <span
              className="shrink-0 rounded-full px-1.5 text-[7.5px] font-semibold uppercase tracking-[0.08em]"
              style={{
                color: REASON_COLOR[t.close_reason ?? ''] ?? 'var(--color-ink-dim)',
                border: `1px solid color-mix(in srgb, ${REASON_COLOR[t.close_reason ?? ''] ?? 'var(--color-ink-dim)'} 40%, transparent)`,
              }}
            >
              {(t.close_reason ?? '?').replace(/_/g, ' ')}
            </span>
            <span
              className="num w-14 shrink-0 text-right text-[10px] font-semibold"
              style={{ color: up ? 'var(--color-up)' : 'var(--color-down)' }}
            >
              {up ? '+' : ''}
              {usd(pnl)}
            </span>
          </div>
        )
      })}
    </div>
  )
}

/* ---- realized P&L by strategy ----------------------------------------- */
function StrategyPnL({ trades }: { trades: LedgerTrade[] }) {
  const rows = useMemo(() => {
    const agg = new Map<string, { pnl: number; n: number }>()
    for (const t of trades) {
      if (t.pnl === null) continue
      const cur = agg.get(t.strategy) ?? { pnl: 0, n: 0 }
      cur.pnl += t.pnl
      cur.n += 1
      agg.set(t.strategy, cur)
    }
    return [...agg.entries()]
      .map(([strategy, { pnl, n }]) => ({ strategy, pnl, n }))
      .sort((a, b) => b.pnl - a.pnl)
      .slice(0, 6)
  }, [trades])

  if (!rows.length) return null
  const maxAbs = Math.max(...rows.map((r) => Math.abs(r.pnl)), 1)
  return (
    <div>
      <div className="mb-1 text-[8.5px] tracking-[0.14em] text-[var(--color-ink-faint)]">
        REALIZED BY STRATEGY
      </div>
      <div className="space-y-1">
        {rows.map((r) => {
          const up = r.pnl >= 0
          const color = up ? 'var(--color-up)' : 'var(--color-down)'
          return (
            <div key={r.strategy} className="flex items-center gap-1.5" title={`${r.n} closed trades`}>
              <span className="w-24 shrink-0 truncate text-[8.5px] text-[var(--color-ink-dim)]">
                {r.strategy.replace(/_/g, ' ')}
              </span>
              <div className="relative h-[8px] min-w-0 flex-1 overflow-hidden rounded-[3px] bg-[var(--color-void)]/50">
                <div
                  className="h-full rounded-[3px] transition-[width] duration-700"
                  style={{
                    width: `${Math.max(4, (Math.abs(r.pnl) / maxAbs) * 100)}%`,
                    background: `color-mix(in srgb, ${color} 55%, transparent)`,
                    boxShadow: `inset 0 0 0 1px color-mix(in srgb, ${color} 45%, transparent)`,
                  }}
                />
              </div>
              <span className="num w-14 shrink-0 text-right text-[9.5px] font-semibold" style={{ color }}>
                {up ? '+' : ''}
                {usd(r.pnl)}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Desk                                                                */
/* ------------------------------------------------------------------ */

export default function TradingDesk({ className }: { className?: string }) {
  const [book, setBook] = useState<PaperBookResponse | null>(null)
  const [history, setHistory] = useState<PaperHistoryPoint[]>([])
  const [greeks, setGreeks] = useState<PaperGreeksResponse | null>(null)
  const [trades, setTrades] = useState<LedgerTrade[]>([])
  const [closing, setClosing] = useState<number | null>(null)
  // strict data layer: on failure we KEEP the last real state and flag it
  // stale — this desk never shows mock data
  const [stale, setStale] = useState(false)
  const timer = useRef<ReturnType<typeof setInterval> | null>(null)

  const refreshSide = useCallback(() => {
    getPaperHistory().then((h) => setHistory(h.points)).catch(() => setStale(true))
    getPaperGreeks().then(setGreeks).catch(() => setStale(true))
    getLedgerTrades(40, true).then((r) => setTrades(r.trades)).catch(() => setStale(true))
  }, [])

  const mark = useCallback(() => {
    postPaperMark()
      .then((b) => {
        setBook(b)
        setStale(false)
        refreshSide()
      })
      .catch(() => setStale(true))
  }, [refreshSide])

  useEffect(() => {
    getPaperBook()
      .then((b) => {
        setBook(b)
        setStale(false)
      })
      .catch(() => setStale(true))
    refreshSide()
  }, [refreshSide])

  // re-mark every 30s while the tab is visible
  useEffect(() => {
    const start = () => {
      if (timer.current === null) timer.current = setInterval(mark, REFRESH_MS)
    }
    const stop = () => {
      if (timer.current !== null) {
        clearInterval(timer.current)
        timer.current = null
      }
    }
    const onVisibility = () => {
      if (document.visibilityState === 'visible') {
        mark()
        start()
      } else stop()
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
      setStale(false)
      refreshSide()
    } catch {
      setStale(true) // close did NOT happen — keep the position on screen
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

  // day P&L: equity now vs the first mark of today (falls back to first point)
  const dayPnl = useMemo(() => {
    if (history.length < 2) return null
    const today = new Date().toDateString()
    const anchor = history.find((pt) => new Date(pt.ts).toDateString() === today) ?? history[0]
    return history[history.length - 1].equity - anchor.equity
  }, [history])

  const winStats = useMemo(() => {
    const closed = trades.filter((t) => t.pnl !== null)
    if (!closed.length) return null
    const wins = closed.filter((t) => (t.pnl ?? 0) > 0).length
    return { n: closed.length, winRate: wins / closed.length }
  }, [trades])

  return (
    <Panel
      className={className}
      title="Trading Desk"
      subtitle="forward paper test — the numbers that decide if this goes live"
      right={
        <span className="flex items-center gap-1.5">
          {stale && (
            <span
              className="pill"
              style={{
                borderColor: 'color-mix(in srgb, var(--color-amber) 55%, transparent)',
                color: 'var(--color-amber)',
              }}
              title="The backend didn't answer the last refresh (it may be busy crunching research). Showing the last real data — never mock. Retries automatically."
            >
              ⚠ STALE — reconnecting
            </span>
          )}
          {book ? <LivePill live={book.live} asof={book.asof} /> : null}
        </span>
      }
    >
      <div className="flex h-full min-h-0 flex-col gap-2.5">
        {/* headline strip */}
        <div className="grid shrink-0 grid-cols-3 gap-2 xl:grid-cols-6">
          <Headline label="TOTAL EQUITY" value={usd(eq?.total)} tone="gold" big />
          <Headline
            label="DAY P&L"
            value={dayPnl === null ? '—' : `${dayPnl >= 0 ? '+' : ''}${usd(dayPnl)}`}
            tone={dayPnl === null || dayPnl >= 0 ? 'up' : 'down'}
          />
          <Headline
            label="REALIZED P&L"
            value={`${realized >= 0 ? '+' : ''}${usd(realized)}`}
            tone={realized >= 0 ? 'up' : 'down'}
          />
          <Headline
            label="OPEN uPnL"
            value={`${upnl >= 0 ? '+' : ''}${usd(upnl)}`}
            tone={upnl >= 0 ? 'up' : 'down'}
          />
          <Headline label="CASH" value={usd(eq?.cash)} />
          <Headline
            label="WIN RATE"
            value={winStats ? `${(winStats.winRate * 100).toFixed(0)}%` : '—'}
            sub={winStats ? `${winStats.n} closed` : 'no closes yet'}
          />
        </div>

        {/* equity curve + greeks | ledger rail — compact fixed-height band so
            the open-positions grid below gets everything that's left */}
        <div className="flex h-[185px] shrink-0 gap-2.5">
          <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-2">
            <div className="min-h-0 flex-1">
              {history.length >= 2 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={history} margin={{ top: 6, right: 6, bottom: 0, left: 4 }}>
                    <defs>
                      <linearGradient id="deskEq" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="var(--color-teal)" stopOpacity={0.3} />
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
                      width={34}
                    />
                    <Tooltip
                      content={<EquityTooltip />}
                      cursor={{ stroke: 'var(--color-edge)', strokeDasharray: '3 3' }}
                    />
                    {/* the line to beat: starting capital */}
                    <ReferenceLine
                      y={100_000}
                      stroke="var(--color-gold)"
                      strokeDasharray="5 4"
                      strokeOpacity={0.5}
                      label={{
                        value: 'start 100k',
                        position: 'insideBottomRight',
                        fill: 'var(--color-gold)',
                        fontSize: 8.5,
                        opacity: 0.8,
                      }}
                    />
                    <Area
                      type="monotone"
                      dataKey="equity"
                      stroke="var(--color-teal)"
                      strokeWidth={2}
                      fill="url(#deskEq)"
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
            {greeks && (
              <div className="shrink-0">
                <GreeksGauges greeks={greeks} />
              </div>
            )}
          </div>

          {/* ledger rail */}
          <div className="flex w-60 shrink-0 flex-col gap-2 xl:w-72">
            <div className="min-h-0 flex-1 overflow-hidden rounded-lg border border-[var(--color-edge-soft)] bg-[var(--color-void)]/30 p-2">
              <div className="mb-1 flex items-baseline justify-between">
                <span className="text-[8.5px] tracking-[0.14em] text-[var(--color-ink-faint)]">
                  CLOSED TRADES
                </span>
                <span className="text-[8px] text-[var(--color-ink-faint)]">ledger · append-only</span>
              </div>
              <div className="h-[calc(100%-18px)] overflow-y-auto">
                <ClosedTrades trades={trades} />
              </div>
            </div>
            <div className="shrink-0 rounded-lg border border-[var(--color-edge-soft)] bg-[var(--color-void)]/30 p-2">
              <StrategyPnL trades={trades} />
              {trades.filter((t) => t.pnl !== null).length === 0 && (
                <div className="text-[8.5px] text-[var(--color-ink-faint)]">
                  Strategy P&L appears after the first closed trade.
                </div>
              )}
            </div>
          </div>
        </div>

        {/* open positions — the desk's centerpiece: takes ALL remaining space */}
        <div className="flex min-h-0 flex-1 flex-col">
          <div className="mb-1.5 flex shrink-0 items-baseline justify-between">
            <span className="panel-title">
              Open Positions
              <span className="num ml-2 text-[10px] font-normal text-[var(--color-ink-faint)]">
                {open.length} live
              </span>
            </span>
            <span className="text-[9px] text-[var(--color-ink-faint)]">
              marked every 2 min while visible
            </span>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto pr-1">
            {open.length ? (
              <div
                className="grid gap-2"
                style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(215px, 1fr))' }}
              >
                <AnimatePresence mode="popLayout">
                  {open.map(({ p, i }) => (
                    <PositionCard
                      key={`${p.ticker}-${p.opened}-${i}`}
                      p={p}
                      closing={closing === i}
                      onClose={() => handleClose(i)}
                    />
                  ))}
                </AnimatePresence>
              </div>
            ) : (
              <div className="grid h-full place-items-center rounded-lg border border-dashed border-[var(--color-edge-soft)] text-[10.5px] text-[var(--color-ink-faint)]">
                No open positions — the autopilot opens them when a promoted strategy signals.
              </div>
            )}
          </div>
        </div>
      </div>
    </Panel>
  )
}
