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
import Panel from './Panel'
import { compact, pct, usd } from '../lib/format'

interface Row {
  asof: string
  equity: number
  drawdown: number
}

function buildRows(bt: BacktestResponse): Row[] {
  let peak = -Infinity
  return bt.equity_curve.map((p) => {
    peak = Math.max(peak, p.equity)
    return { asof: p.asof, equity: p.equity, drawdown: (p.equity - peak) / peak }
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
      <div className="num mt-0.5 text-[15px] font-semibold" style={{ color }}>
        {value}
      </div>
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

export default function BacktestPanel({ className }: { className?: string }) {
  const [bt, setBt] = useState<BacktestResponse | null>(null)

  useEffect(() => {
    postBacktest({
      strategy: 'bull_put_spread',
      params: { delta: 0.3, dte: 30 },
      tickers: ['SPY', 'QQQ', 'NVDA', 'AAPL'],
      start: '2023-01-03',
      end: '2025-01-03',
    }).then(setBt)
  }, [])

  const rows = useMemo(() => (bt ? buildRows(bt) : []), [bt])

  return (
    <Panel
      className={className}
      title="Backtest"
      subtitle={bt ? `${bt.config.strategy} · ${bt.n_trades} trades` : undefined}
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
      {!bt ? (
        <div className="h-full w-full animate-pulse rounded-lg bg-[var(--color-panel-2)]/40" />
      ) : (
        <div className="flex h-full flex-col gap-3">
          {/* metrics */}
          <div className="grid grid-cols-3 gap-2 xl:grid-cols-6">
            <Metric label="CAGR" value={pct(bt.cagr)} tone="up" />
            <Metric label="SHARPE" value={bt.sharpe.toFixed(2)} tone="gold" />
            <Metric label="SORTINO" value={bt.sortino.toFixed(2)} tone="gold" />
            <Metric label="MAX DD" value={pct(bt.max_drawdown)} tone="down" />
            <Metric label="WIN RATE" value={pct(bt.win_rate)} />
            <Metric label="PROFIT FACTOR" value={bt.profit_factor.toFixed(2)} tone="up" />
          </div>

          {/* equity curve */}
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
          <div className="h-16 shrink-0">
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
      )}
    </Panel>
  )
}
