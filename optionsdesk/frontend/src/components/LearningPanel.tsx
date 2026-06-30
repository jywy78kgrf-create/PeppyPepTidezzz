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
import * as mock from '../mock'
import type { LearnIteration } from '../types'

interface Pt {
  iteration: number
  oos_score: number
  best: number
  accepted: boolean
}

export default function LearningPanel() {
  const [history, setHistory] = useState<LearnIteration[]>([])
  const [best, setBest] = useState<{ score: number; params: Record<string, number>; iter: number }>({
    score: 0,
    params: {},
    iter: 0,
  })
  const [series, setSeries] = useState<Pt[]>([])
  const [flash, setFlash] = useState(false)
  const histRef = useRef<LearnIteration[]>([])

  // seed from backend/mock, then stream new iterations live
  useEffect(() => {
    let stopped = false
    postLearn({
      strategy: 'bull_put_spread',
      tickers: ['SPY', 'QQQ', 'NVDA'],
      start: '2023-01-03',
      end: '2025-01-03',
      n_iter: 40,
    }).then((r) => {
      if (stopped) return
      histRef.current = r.history
      setHistory(r.history)
      let running = 0
      const pts: Pt[] = r.history.map((h) => {
        running = Math.max(running, h.oos_score)
        return { iteration: h.iteration, oos_score: h.oos_score, best: running, accepted: h.accepted }
      })
      setSeries(pts)
      setBest({ score: r.best.oos_score, params: r.best.params, iter: r.best.iteration })
    })
    return () => {
      stopped = true
    }
  }, [])

  // live streaming of new iterations
  useEffect(() => {
    const id = setInterval(() => {
      setSeries((prev) => {
        if (!prev.length) return prev
        const prevIter = histRef.current[histRef.current.length - 1]
        const runningBest = prev[prev.length - 1].best
        const next = mock.mockNextIteration(prevIter, runningBest)
        histRef.current = [...histRef.current, next].slice(-120)
        setHistory(histRef.current)
        const newBest = Math.max(runningBest, next.oos_score)
        if (next.accepted) {
          setBest({ score: next.oos_score, params: next.params, iter: next.iteration })
          setFlash(true)
          setTimeout(() => setFlash(false), 700)
        }
        const pt: Pt = {
          iteration: next.iteration,
          oos_score: next.oos_score,
          best: newBest,
          accepted: next.accepted,
        }
        return [...prev, pt].slice(-80)
      })
    }, 2200)
    return () => clearInterval(id)
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
        <span className="num text-[10px] text-[var(--color-ink-faint)]">
          {acceptCount} accepted
        </span>
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

        {/* current best params */}
        <motion.div
          animate={
            flash
              ? { boxShadow: '0 0 0 1px var(--color-iris), 0 0 22px -6px var(--color-iris)' }
              : { boxShadow: '0 0 0 1px transparent' }
          }
          transition={{ duration: 0.5 }}
          className="rounded-xl border border-[var(--color-edge-soft)] bg-[var(--color-void)]/40 p-2.5"
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
      </div>
    </motion.section>
  )
}
