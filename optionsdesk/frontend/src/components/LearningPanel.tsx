import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  XAxis,
  YAxis,
  ZAxis,
} from 'recharts'
import { postLearn } from '../api'
import type { HoldoutInfo, LearnIteration, Regimes } from '../types'
import { STRATEGY_NAMES } from '../types'
import { num, pct } from '../lib/format'

interface Pt {
  iteration: number
  oos_score: number
  best: number
  accepted: boolean
}

/* ---- HOLDOUT — the number to trust (never touched during the search) --- */
function HoldoutChip({ holdout }: { holdout: HoldoutInfo | null }) {
  if (!holdout) return null
  const range =
    holdout.start && holdout.end ? `${holdout.start} → ${holdout.end}` : 'no holdout reserved'
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.92 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
      className="flex items-center gap-2 rounded-full px-3 py-1"
      style={{
        border: '1px solid color-mix(in srgb, var(--color-gold) 55%, transparent)',
        background: 'color-mix(in srgb, var(--color-gold) 9%, transparent)',
        boxShadow:
          '0 0 14px -4px var(--color-gold), inset 0 1px 0 color-mix(in srgb, #ffffff 10%, transparent)',
      }}
      title={`${holdout.note}\n${range}`}
    >
      <span
        className="text-[9px] font-semibold tracking-[0.16em]"
        style={{ color: 'var(--color-gold-bright)' }}
      >
        HOLDOUT
      </span>
      <span className="num text-[13px] font-bold" style={{ color: 'var(--color-gold-bright)' }}>
        {num(holdout.score, 3)}
      </span>
      <span className="hidden text-[8.5px] tracking-[0.06em] text-[var(--color-ink-dim)] xl:inline">
        the number to trust
      </span>
    </motion.div>
  )
}

/* ---- per-vol-regime performance mini-table ---------------------------- */
const REGIME_ROWS: { key: keyof Regimes; label: string; color: string }[] = [
  { key: 'low', label: 'LOW VOL', color: 'var(--color-teal)' },
  { key: 'mid', label: 'MID VOL', color: 'var(--color-amber)' },
  { key: 'high', label: 'HIGH VOL', color: 'var(--color-down)' },
]

function RegimesTable({ regimes }: { regimes: Regimes }) {
  return (
    <div className="flex w-56 shrink-0 flex-col rounded-xl border border-[var(--color-edge-soft)] bg-[var(--color-void)]/40 p-2.5">
      <div className="mb-1.5 text-[8.5px] tracking-[0.14em] text-[var(--color-ink-faint)]">
        REGIME PERFORMANCE
      </div>
      <table className="w-full text-right">
        <thead>
          <tr className="text-[8px] uppercase tracking-[0.1em] text-[var(--color-ink-faint)]">
            <th className="pb-1 text-left font-medium">Regime</th>
            <th className="pb-1 font-medium">Return</th>
            <th className="pb-1 font-medium">Sharpe</th>
            <th className="pb-1 font-medium">MaxDD</th>
          </tr>
        </thead>
        <tbody>
          {REGIME_ROWS.map(({ key, label, color }) => {
            const r = regimes[key]
            if (!r) return null
            return (
              <tr key={key} className="text-[10px]">
                <td className="py-0.5 text-left">
                  <span className="flex items-center gap-1.5">
                    <span
                      style={{
                        width: 5,
                        height: 5,
                        borderRadius: 99,
                        background: color,
                        boxShadow: `0 0 6px ${color}`,
                      }}
                    />
                    <span className="text-[8.5px] tracking-[0.08em] text-[var(--color-ink-dim)]">
                      {label}
                    </span>
                  </span>
                </td>
                <td
                  className="num py-0.5 font-semibold"
                  style={{
                    color: (r.total_return ?? 0) >= 0 ? 'var(--color-up)' : 'var(--color-down)',
                  }}
                >
                  {pct(r.total_return)}
                </td>
                <td className="num py-0.5 text-[var(--color-ink)]">{num(r.sharpe, 2)}</td>
                <td className="num py-0.5" style={{ color: 'var(--color-down)' }}>
                  {pct(r.max_drawdown)}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export default function LearningPanel() {
  const [history, setHistory] = useState<LearnIteration[]>([])
  const [best, setBest] = useState<{ score: number; params: Record<string, number>; iter: number }>({
    score: 0,
    params: {},
    iter: 0,
  })
  const [series, setSeries] = useState<Pt[]>([])
  const [holdout, setHoldout] = useState<HoldoutInfo | null>(null)
  const [regimes, setRegimes] = useState<Regimes | null>(null)
  const [flash, setFlash] = useState(false)
  const histRef = useRef<LearnIteration[]>([])

  // run controls — every number on this panel comes from a real learn run
  // (backend or the mock layer when offline); nothing is synthesized on a
  // timer, so what you see is what the optimizer actually did.
  const [strategy, setStrategy] = useState('bull_put_spread')
  const [tickersInput, setTickersInput] = useState('SPY,QQQ,NVDA')
  const [nIter, setNIter] = useState(12)
  const [running, setRunning] = useState(false)

  const runLearn = () => {
    if (running) return
    setRunning(true)
    postLearn({
      strategy,
      tickers: tickersInput.split(',').map((t) => t.trim().toUpperCase()).filter(Boolean),
      start: '2023-01-03',
      end: '2025-01-03',
      n_iter: nIter,
    })
      .then((r) => {
        const hist = r.history ?? []
        histRef.current = hist
        setHistory(hist)
        let run = 0
        let bestIter = 0
        const pts: Pt[] = hist.map((h) => {
          if (h.oos_score > run) {
            run = h.oos_score
            bestIter = h.iteration
          }
          return { iteration: h.iteration, oos_score: h.oos_score, best: run, accepted: h.accepted }
        })
        setSeries(pts)
        setBest({ score: run, params: r.best_params ?? {}, iter: bestIter })
        setHoldout(r.holdout ?? null)
        setRegimes(r.regimes ?? null)
        setFlash(true)
        setTimeout(() => setFlash(false), 700)
      })
      .finally(() => setRunning(false))
  }

  // one real run on mount so the panel isn't empty
  useEffect(() => {
    runLearn()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const accepted = series.filter((p) => p.accepted)
  const rejected = series.filter((p) => !p.accepted)
  const acceptCount = history.filter((h) => h.accepted).length

  return (
    <motion.section
      initial={{ opacity: 0, y: 14, filter: 'blur(6px)' }}
      animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
      transition={{ duration: 0.6, delay: 0.15, ease: [0.16, 1, 0.3, 1] }}
      className="glass relative flex min-h-0 w-full flex-1 flex-col overflow-hidden"
    >
      <header className="flex shrink-0 items-center justify-between px-4 pt-3 pb-2">
        <div className="flex items-center gap-2.5">
          <span
            className="pulse-dot"
            style={{ width: 7, height: 7, borderRadius: 99, background: 'var(--color-iris)', boxShadow: '0 0 9px var(--color-iris)' }}
          />
          <h2 className="panel-title">Learning Loop</h2>
          <span className="num text-[10px] text-[var(--color-ink-faint)]">
            iter {history.length ? history[history.length - 1].iteration : 0}
          </span>
        </div>
        <div className="flex items-center gap-3">
          <HoldoutChip holdout={holdout} />
          <span className="num text-[10px] text-[var(--color-ink-faint)]">
            {acceptCount} accepted
          </span>
          {/* run controls */}
          <select
            value={strategy}
            onChange={(e) => setStrategy(e.target.value)}
            className="num rounded-md border border-[var(--color-edge)] bg-[var(--color-panel-2)] px-1.5 py-0.5 text-[10px] text-[var(--color-ink-dim)] outline-none focus:border-[var(--color-iris)]"
          >
            {STRATEGY_NAMES.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
          <input
            value={tickersInput}
            onChange={(e) => setTickersInput(e.target.value)}
            className="num w-[110px] rounded-md border border-[var(--color-edge)] bg-[var(--color-panel-2)] px-1.5 py-0.5 text-[10px] text-[var(--color-ink-dim)] outline-none focus:border-[var(--color-iris)]"
            title="Comma-separated tickers"
          />
          <input
            type="number"
            min={2}
            max={60}
            value={nIter}
            onChange={(e) => setNIter(Math.max(2, Math.min(60, Number(e.target.value) || 12)))}
            className="num w-[46px] rounded-md border border-[var(--color-edge)] bg-[var(--color-panel-2)] px-1.5 py-0.5 text-[10px] text-[var(--color-ink-dim)] outline-none focus:border-[var(--color-iris)]"
            title="Iterations"
          />
          <button onClick={runLearn} disabled={running} className="btn px-2.5 py-0.5 text-[10px]">
            {running ? 'Learning…' : 'Run'}
          </button>
        </div>
      </header>
      <div className="hairline mx-3 shrink-0" />

      <div className="grid min-h-0 flex-1 grid-rows-[1fr_auto] gap-2 p-4 pt-3">
        {/* climbing objective chart */}
        <div className="relative min-h-0">
          <div className="pointer-events-none absolute left-1 top-0 z-10 text-[9px] tracking-[0.12em] text-[var(--color-ink-faint)]">
            OOS OBJECTIVE
          </div>
          <ResponsiveContainer width="100%" height="100%">
            <ScatterChart margin={{ top: 14, right: 8, left: -8, bottom: 0 }}>
              <CartesianGrid stroke="var(--color-edge-soft)" strokeDasharray="2 4" vertical={false} />
              <XAxis
                type="number"
                dataKey="iteration"
                domain={['dataMin', 'dataMax']}
                tick={{ fill: 'var(--color-ink-faint)', fontSize: 9 }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                type="number"
                dataKey="oos_score"
                domain={[0.3, 1]}
                tick={{ fill: 'var(--color-ink-faint)', fontSize: 9 }}
                axisLine={false}
                tickLine={false}
                width={28}
              />
              <ZAxis range={[24, 24]} />
              {holdout?.score != null && (
                <ReferenceLine
                  y={holdout.score}
                  stroke="var(--color-gold-bright)"
                  strokeDasharray="6 3"
                  strokeOpacity={0.65}
                  label={{
                    value: 'holdout',
                    position: 'insideTopRight',
                    fill: 'var(--color-gold-bright)',
                    fontSize: 8.5,
                  }}
                />
              )}
              <ReferenceLine y={best.score} stroke="var(--color-iris)" strokeDasharray="4 4" strokeOpacity={0.5} />
              <Scatter data={rejected} fill="var(--color-ink-faint)" fillOpacity={0.35} isAnimationActive={false} />
              <Scatter
                data={accepted}
                fill="var(--color-iris)"
                isAnimationActive={false}
                shape={(props: { cx?: number; cy?: number }) => (
                  <circle
                    cx={props.cx}
                    cy={props.cy}
                    r={3.4}
                    fill="var(--color-iris)"
                    stroke="#fff"
                    strokeOpacity={0.4}
                    style={{ filter: 'drop-shadow(0 0 4px var(--color-iris))' }}
                  />
                )}
              />
            </ScatterChart>
          </ResponsiveContainer>
          {/* overlaid best-so-far climbing line */}
          <div className="pointer-events-none absolute inset-0">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={series} margin={{ top: 14, right: 8, left: -8, bottom: 0 }}>
                <XAxis type="number" dataKey="iteration" domain={['dataMin', 'dataMax']} hide />
                <YAxis type="number" domain={[0.3, 1]} hide width={28} />
                <Line
                  type="stepAfter"
                  dataKey="best"
                  stroke="var(--color-gold-bright)"
                  strokeWidth={1.8}
                  dot={false}
                  isAnimationActive={false}
                  style={{ filter: 'drop-shadow(0 0 5px var(--color-gold))' }}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* current best params + per-regime performance */}
        <div className="flex gap-2">
          <motion.div
            animate={
              flash
                ? { boxShadow: '0 0 0 1px var(--color-iris), 0 0 22px -6px var(--color-iris)' }
                : { boxShadow: '0 0 0 1px transparent' }
            }
            transition={{ duration: 0.5 }}
            className="min-w-0 flex-1 rounded-xl border border-[var(--color-edge-soft)] bg-[var(--color-void)]/40 p-2.5"
          >
            <div className="mb-2 flex items-center justify-between">
              <span className="panel-title">Current Best</span>
              <AnimatePresence mode="popLayout">
                <motion.span
                  key={best.score}
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="num text-[14px] font-semibold text-[var(--color-iris)]"
                >
                  {best.score.toFixed(3)}
                </motion.span>
              </AnimatePresence>
            </div>
            <div className="grid grid-cols-4 gap-2">
              {Object.entries(best.params).map(([k, v]) => (
                <div
                  key={k}
                  className="rounded-lg border border-[var(--color-edge-soft)] bg-[var(--color-panel)]/50 px-2 py-1.5 text-center"
                >
                  <div className="num text-[12px] font-semibold text-[var(--color-ink)]">
                    {typeof v === 'number' ? (Number.isInteger(v) ? v : v.toFixed(2)) : String(v)}
                  </div>
                  <div className="text-[8px] uppercase tracking-[0.12em] text-[var(--color-ink-faint)]">
                    {k}
                  </div>
                </div>
              ))}
            </div>
          </motion.div>
          {regimes && <RegimesTable regimes={regimes} />}
        </div>
      </div>
    </motion.section>
  )
}
