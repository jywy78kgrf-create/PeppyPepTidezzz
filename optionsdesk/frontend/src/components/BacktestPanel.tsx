import { useEffect, useMemo, useState } from 'react'
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { postBacktest } from '../api'
import type { BacktestResponse } from '../types'
import { CLOSED_REASONS, SIZING_METHODS, STRATEGY_NAMES } from '../types'
import Panel from './Panel'
import { compact, num, pct, usd } from '../lib/format'

interface Row {
  asof: string
  equity: number
  drawdown: number
}

function buildRows(bt: BacktestResponse): Row[] {
  let peak = -Infinity
  return bt.equity_curve.map((p) => {
    peak = Math.max(peak, p.equity)
    return { asof: p.asof, equity: p.equity, drawdown: peak > 0 ? (p.equity - peak) / peak : 0 }
  })
}

function Metric({
  label,
  value,
  tone = 'neutral',
}: {
  label: string
  value: string
  tone?: 'neutral' | 'up' | 'down' | 'gold'
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
      <div className="text-[9px] tracking-[0.12em] text-[var(--color-ink-faint)]">{label}</div>
      <div className="num mt-0.5 text-[14px] font-semibold" style={{ color }}>
        {value}
      </div>
    </div>
  )
}

/* ---- closed-reason breakdown: how trades actually ended --------------- */
const REASON_META: Record<string, { label: string; color: string }> = {
  target: { label: 'TARGET', color: 'var(--color-up)' },
  stop: { label: 'STOP', color: 'var(--color-down)' },
  close_dte: { label: 'DTE CLOSE', color: 'var(--color-teal)' },
  expiry: { label: 'EXPIRY', color: 'var(--color-iris)' },
  assigned: { label: 'ASSIGNED', color: 'var(--color-amber)' },
  delisted: { label: 'DELISTED', color: 'var(--color-ink-dim)' },
  end: { label: 'RUN END', color: 'var(--color-ink-faint)' },
}

function ClosedReasonBars({ reasons }: { reasons: Record<string, number> }) {
  // canonical order first, then any unexpected keys the backend might add
  const keys = [
    ...CLOSED_REASONS.filter((k) => (reasons[k] ?? 0) > 0),
    ...Object.keys(reasons).filter(
      (k) => !(CLOSED_REASONS as readonly string[]).includes(k) && reasons[k] > 0,
    ),
  ]
  const max = Math.max(1, ...keys.map((k) => reasons[k] ?? 0))
  if (!keys.length) {
    return (
      <div className="py-4 text-center text-[10px] text-[var(--color-ink-faint)]">
        No closed trades.
      </div>
    )
  }
  return (
    <div className="flex flex-col gap-1.5">
      {keys.map((k) => {
        const meta = REASON_META[k] ?? { label: k.toUpperCase(), color: 'var(--color-ink-faint)' }
        const count = reasons[k] ?? 0
        return (
          <div key={k} className="flex items-center gap-2" title={`${meta.label}: ${count} trades`}>
            <span className="w-16 shrink-0 text-right text-[8.5px] tracking-[0.1em] text-[var(--color-ink-faint)]">
              {meta.label}
            </span>
            <div className="relative h-3.5 min-w-0 flex-1 overflow-hidden rounded-[4px] bg-[var(--color-void)]/50">
              <div
                className="h-full rounded-[4px] transition-[width] duration-700 ease-out"
                style={{
                  width: `${Math.max(3, (count / max) * 100)}%`,
                  background: `color-mix(in srgb, ${meta.color} 55%, transparent)`,
                  boxShadow: `inset 0 0 0 1px color-mix(in srgb, ${meta.color} 45%, transparent)`,
                }}
              />
            </div>
            <span className="num w-8 shrink-0 text-right text-[10px] font-semibold text-[var(--color-ink)]">
              {count}
            </span>
          </div>
        )
      })}
    </div>
  )
}

interface TipPayload {
  payload: Row
}
function ChartTip({ active, payload }: { active?: boolean; payload?: TipPayload[] }) {
  if (!active || !payload?.length) return null
  const r = payload[0].payload
  return (
    <div className="glass px-3 py-2" style={{ borderRadius: 10 }}>
      <div className="num text-[10px] text-[var(--color-ink-faint)]">{r.asof}</div>
      <div className="num text-[12px] font-semibold text-[var(--color-ink)]">{usd(r.equity)}</div>
      <div className="num text-[11px]" style={{ color: 'var(--color-down)' }}>
        DD {pct(r.drawdown, 1)}
      </div>
    </div>
  )
}

const inputCls =
  'num rounded-md border border-[var(--color-edge-soft)] bg-[var(--color-void)]/50 px-2 py-1 ' +
  'text-[10.5px] text-[var(--color-ink)] outline-none focus:border-[var(--color-gold)]/50'

export default function BacktestPanel({ className }: { className?: string }) {
  const [bt, setBt] = useState<BacktestResponse | null>(null)
  const [running, setRunning] = useState(false)

  // run-config strip state
  const [strategy, setStrategy] = useState<string>('bull_put_spread')
  const [tickersCsv, setTickersCsv] = useState('SPY, QQQ, NVDA, AAPL')
  const [start, setStart] = useState('2023-01-03')
  const [end, setEnd] = useState('2025-01-03')
  const [sizing, setSizing] = useState<string>('fixed_fraction')

  const run = (
    cfg: { strategy: string; tickersCsv: string; start: string; end: string; sizing: string },
  ) => {
    const tickers = cfg.tickersCsv
      .split(/[,\s]+/)
      .map((t) => t.trim().toUpperCase())
      .filter(Boolean)
    if (!tickers.length || !cfg.start || !cfg.end) return
    setRunning(true)
    postBacktest({
      strategy: cfg.strategy,
      params: { delta: 0.3, dte: 30 },
      tickers,
      start: cfg.start,
      end: cfg.end,
      risk: { method: cfg.sizing },
    })
      .then(setBt)
      .finally(() => setRunning(false))
  }

  useEffect(() => {
    run({ strategy: 'bull_put_spread', tickersCsv: 'SPY, QQQ, NVDA, AAPL', start: '2023-01-03', end: '2025-01-03', sizing: 'fixed_fraction' })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const rows = useMemo(() => (bt ? buildRows(bt) : []), [bt])

  return (
    <Panel
      className={className}
      title="Backtest"
      subtitle={bt ? `${bt.config} · ${bt.n_trades} trades · ${bt.start ?? '—'} → ${bt.end ?? '—'}` : undefined}
      right={
        bt && (
          <span
            className="pill"
            style={{
              borderColor: 'color-mix(in srgb, var(--color-teal) 35%, transparent)',
              color: 'var(--color-teal)',
            }}
            title={bt.survivorship_note}
          >
            ✓ Survivorship-clean
          </span>
        )
      }
    >
      <div className="flex h-full flex-col gap-2.5">
        {/* run-config strip — actually POSTs /api/backtest */}
        <form
          className="flex shrink-0 flex-wrap items-center gap-1.5"
          onSubmit={(e) => {
            e.preventDefault()
            run({ strategy, tickersCsv, start, end, sizing })
          }}
        >
          <select
            className={inputCls}
            value={strategy}
            onChange={(e) => setStrategy(e.target.value)}
            aria-label="Strategy"
          >
            {STRATEGY_NAMES.map((s) => (
              <option key={s} value={s}>
                {s.replace(/_/g, ' ')}
              </option>
            ))}
          </select>
          <input
            className={`${inputCls} w-44 min-w-0 flex-1`}
            value={tickersCsv}
            onChange={(e) => setTickersCsv(e.target.value)}
            placeholder="SPY, QQQ, …"
            aria-label="Tickers"
            spellCheck={false}
          />
          <input
            className={inputCls}
            type="date"
            value={start}
            onChange={(e) => setStart(e.target.value)}
            aria-label="Start date"
          />
          <span className="text-[9px] text-[var(--color-ink-faint)]">→</span>
          <input
            className={inputCls}
            type="date"
            value={end}
            onChange={(e) => setEnd(e.target.value)}
            aria-label="End date"
          />
          <select
            className={inputCls}
            value={sizing}
            onChange={(e) => setSizing(e.target.value)}
            aria-label="Sizing method"
            title="Position sizing method"
          >
            {SIZING_METHODS.map((m) => (
              <option key={m} value={m}>
                {m.replace(/_/g, ' ')}
              </option>
            ))}
          </select>
          <button type="submit" className="btn px-3 py-1 text-[10px]" disabled={running}>
            {running ? 'Running…' : 'Run'}
          </button>
        </form>

        {!bt ? (
          <div className="w-full flex-1 animate-pulse rounded-lg bg-[var(--color-panel-2)]/40" />
        ) : (
          <div
            className="flex min-h-0 flex-1 flex-col gap-2.5"
            style={{ opacity: running ? 0.55 : 1, transition: 'opacity .3s' }}
          >
            {/* metric tile grid — null-safe, tabular numerals, — for null */}
            <div className="grid shrink-0 grid-cols-4 gap-2 xl:grid-cols-8">
              <Metric
                label="CAGR"
                value={pct(bt.cagr)}
                tone={(bt.cagr ?? 0) >= 0 ? 'up' : 'down'}
              />
              <Metric label="SHARPE" value={num(bt.sharpe, 2)} tone="gold" />
              <Metric label="SORTINO" value={num(bt.sortino, 2)} tone="gold" />
              <Metric label="MAX DD" value={pct(bt.max_drawdown)} tone="down" />
              <Metric label="WIN RATE" value={pct(bt.win_rate)} />
              <Metric
                label="PROFIT FACTOR"
                value={num(bt.profit_factor, 2)}
                tone={(bt.profit_factor ?? 0) >= 1 ? 'up' : 'down'}
              />
              <Metric label="TRADES" value={num(bt.n_trades, 0)} />
              <Metric label="TOTAL COSTS" value={usd(bt.total_costs)} />
            </div>

            <div className="flex min-h-0 flex-1 gap-3">
              {/* equity curve + underwater */}
              <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-1">
                <div className="min-h-0 flex-1">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={rows} margin={{ top: 6, right: 6, left: 0, bottom: 0 }}>
                      <defs>
                        <linearGradient id="eq" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="var(--color-gold)" stopOpacity={0.42} />
                          <stop offset="55%" stopColor="var(--color-gold)" stopOpacity={0.08} />
                          <stop offset="100%" stopColor="var(--color-gold)" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid stroke="var(--color-edge-soft)" strokeDasharray="2 4" vertical={false} />
                      <XAxis
                        dataKey="asof"
                        tick={{ fill: 'var(--color-ink-faint)', fontSize: 9 }}
                        tickFormatter={(d: string) => d.slice(0, 7)}
                        minTickGap={48}
                        axisLine={false}
                        tickLine={false}
                      />
                      <YAxis
                        domain={['dataMin', 'dataMax']}
                        tick={{ fill: 'var(--color-ink-faint)', fontSize: 9 }}
                        tickFormatter={(v: number) => `$${compact(v)}`}
                        width={46}
                        axisLine={false}
                        tickLine={false}
                      />
                      <Tooltip content={<ChartTip />} cursor={{ stroke: 'var(--color-gold)', strokeOpacity: 0.3 }} />
                      <Area
                        type="monotone"
                        dataKey="equity"
                        stroke="var(--color-gold-bright)"
                        strokeWidth={1.6}
                        fill="url(#eq)"
                        isAnimationActive
                        animationDuration={1100}
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>

                {/* drawdown underwater */}
                <div className="h-14 shrink-0">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={rows} margin={{ top: 2, right: 6, left: 0, bottom: 0 }}>
                      <defs>
                        <linearGradient id="dd" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="var(--color-down)" stopOpacity={0.05} />
                          <stop offset="100%" stopColor="var(--color-down)" stopOpacity={0.4} />
                        </linearGradient>
                      </defs>
                      <YAxis hide domain={['dataMin', 0]} />
                      <Area
                        type="monotone"
                        dataKey="drawdown"
                        stroke="var(--color-down)"
                        strokeWidth={1}
                        fill="url(#dd)"
                        isAnimationActive
                        animationDuration={1100}
                      />
                      <Tooltip content={() => null} />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              </div>

              {/* NEW: how trades actually ended */}
              <div className="flex w-52 shrink-0 flex-col rounded-xl border border-[var(--color-edge-soft)] bg-[var(--color-void)]/30 p-2.5">
                <div className="mb-2 text-[9px] tracking-[0.14em] text-[var(--color-ink-faint)]">
                  HOW TRADES ENDED
                </div>
                <ClosedReasonBars reasons={bt.closed_reasons ?? {}} />
              </div>
            </div>
          </div>
        )}
      </div>
    </Panel>
  )
}
