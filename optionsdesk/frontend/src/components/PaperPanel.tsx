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
import {
  closePosition,
  getAutoActivity,
  getAutoStatus,
  getPaperBook,
  getPaperGreeks,
  getPaperHistory,
  postAutoDisable,
  postAutoEnable,
  postPaperMark,
} from '../api'
import type {
  AutoActivityEvent,
  AutoStatus,
  PaperBookResponse,
  PaperGreeksResponse,
  PaperHistoryPoint,
  PaperPosition,
} from '../types'
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
/*  AutoPilot console — the autonomous loop + its kill switch           */
/* ------------------------------------------------------------------ */

const KIND_COLOR: Record<string, string> = {
  open: 'var(--color-teal)',
  close: 'var(--color-gold)',
  promote: 'var(--color-up)',
  demote: 'var(--color-down)',
  breaker: 'var(--color-down)',
  error: 'var(--color-down)',
  research: 'var(--color-iris)',
  enable: 'var(--color-teal)',
  disable: 'var(--color-ink-faint)',
}

function AutoPilotConsole() {
  const [status, setStatus] = useState<AutoStatus | null>(null)
  const [events, setEvents] = useState<AutoActivityEvent[]>([])
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(() => {
    getAutoStatus().then(setStatus)
    getAutoActivity(12).then((r) => setEvents(r.events))
  }, [])

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, 15_000)
    return () => clearInterval(id)
  }, [refresh])

  const toggle = async () => {
    if (!status || busy) return
    setBusy(true)
    try {
      const next = status.enabled ? await postAutoDisable() : await postAutoEnable()
      setStatus(next)
      getAutoActivity(12).then((r) => setEvents(r.events))
    } finally {
      setBusy(false)
    }
  }

  const enabled = status?.enabled ?? false
  const tripped = status?.breaker?.tripped ?? false
  const activeConfigs = (status?.promoted ?? []).filter((p) => p.active)

  return (
    <div
      className="rounded-lg border p-2"
      style={{
        borderColor: tripped
          ? 'color-mix(in srgb, var(--color-down) 45%, transparent)'
          : enabled
            ? 'color-mix(in srgb, var(--color-teal) 30%, transparent)'
            : 'var(--color-edge-soft)',
        background: 'color-mix(in srgb, var(--color-void) 40%, transparent)',
      }}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="panel-title">AutoPilot</span>
          {tripped ? (
            <span className="pill" style={{ color: 'var(--color-down)' }}>
              ⛔ BREAKER TRIPPED
            </span>
          ) : (
            <span
              className="pill"
              style={{ color: enabled ? 'var(--color-teal)' : 'var(--color-ink-faint)' }}
            >
              <span
                className={enabled ? 'pulse-dot inline-block h-1.5 w-1.5 rounded-full' : 'inline-block h-1.5 w-1.5 rounded-full'}
                style={{ background: enabled ? 'var(--color-teal)' : 'var(--color-ink-faint)' }}
              />
              {enabled ? 'AUTONOMOUS' : 'STANDBY'}
            </span>
          )}
        </div>
        {/* the kill switch — always visible, one click to stop everything */}
        <button
          onClick={toggle}
          disabled={busy || status === null}
          className="rounded-md px-3 py-1 text-[10.5px] font-bold tracking-[0.08em] transition-all"
          style={
            enabled
              ? {
                  color: '#fff',
                  background: 'color-mix(in srgb, var(--color-down) 75%, black)',
                  border: '1px solid var(--color-down)',
                  boxShadow: '0 0 14px -4px var(--color-down)',
                }
              : {
                  color: 'var(--color-teal)',
                  background: 'color-mix(in srgb, var(--color-teal) 10%, transparent)',
                  border: '1px solid color-mix(in srgb, var(--color-teal) 45%, transparent)',
                }
          }
        >
          {enabled ? 'KILL' : 'ENGAGE'}
        </button>
      </div>

      {tripped && status?.breaker?.reason && (
        <div className="mt-1.5 rounded border border-[color-mix(in_srgb,var(--color-down)_35%,transparent)] px-2 py-1 text-[9.5px] text-[var(--color-down)]">
          {status.breaker.reason} — re-engage to resume.
        </div>
      )}

      {/* promoted configs the loop is trading */}
      {activeConfigs.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {activeConfigs.map((p) => (
            <span
              key={p.id}
              className="tag"
              title={`${p.tickers.join(', ')} · realized ${p.realized_pnl >= 0 ? '+' : ''}${p.realized_pnl.toFixed(0)} over ${p.closed_trades} closes`}
            >
              {p.strategy}
              <span className="num ml-1 text-[var(--color-gold-bright)]">
                {p.holdout_score.toFixed(2)}
              </span>
            </span>
          ))}
        </div>
      )}

      {/* activity feed */}
      {enabled && events.length > 0 && (
        <div className="mt-1.5 max-h-[72px] space-y-0.5 overflow-y-auto">
          {events.map((e, i) => (
            <div key={`${e.ts}-${i}`} className="flex gap-1.5 text-[9.5px] leading-snug">
              <span className="num shrink-0 text-[var(--color-ink-faint)]">
                {new Date(e.ts).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })}
              </span>
              <span
                className="shrink-0 font-semibold uppercase"
                style={{ color: KIND_COLOR[e.kind] ?? 'var(--color-ink-dim)' }}
              >
                {e.kind}
              </span>
              <span className="truncate text-[var(--color-ink-dim)]" title={e.detail}>
                {e.detail}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Panel                                                               */
/* ------------------------------------------------------------------ */

export default function PaperPanel({ className }: { className?: string }) {
  const [book, setBook] = useState<PaperBookResponse | null>(null)
  const [history, setHistory] = useState<PaperHistoryPoint[]>([])
  const [greeks, setGreeks] = useState<PaperGreeksResponse | null>(null)
  const [closing, setClosing] = useState<number | null>(null)
  const timer = useRef<ReturnType<typeof setInterval> | null>(null)

  const refreshHistory = useCallback(() => {
    getPaperHistory().then((h) => setHistory(h.points))
    getPaperGreeks().then(setGreeks)
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
        {/* the autonomous loop + its kill switch */}
        <AutoPilotConsole />

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

        {/* book-level greeks — aggregate exposure across every open leg */}
        {greeks && (
          <div className="flex items-center justify-between rounded-lg border border-[var(--color-edge-soft)] bg-[var(--color-void)]/40 px-2.5 py-1">
            <span className="text-[8.5px] uppercase tracking-[0.14em] text-[var(--color-ink-faint)]">
              Book Greeks
            </span>
            <div className="num flex gap-3 text-[10.5px]">
              {(
                [
                  ['Δ', greeks.totals.delta, 'share-equivalent delta'],
                  ['Γ', greeks.totals.gamma, 'gamma'],
                  ['Θ', greeks.totals.theta, '$ per day'],
                  ['V', greeks.totals.vega, '$ per vol point'],
                ] as const
              ).map(([sym, v, tip]) => (
                <span key={sym} title={tip}>
                  <span className="text-[var(--color-ink-faint)]">{sym} </span>
                  <span
                    style={{
                      color:
                        v === 0
                          ? 'var(--color-ink-dim)'
                          : v > 0
                            ? 'var(--color-up)'
                            : 'var(--color-down)',
                    }}
                  >
                    {v > 0 ? '+' : ''}
                    {v.toFixed(1)}
                  </span>
                </span>
              ))}
            </div>
          </div>
        )}

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
