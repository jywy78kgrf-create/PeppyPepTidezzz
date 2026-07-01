import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { getSuggestions, getUniverse } from '../api'
import type { Suggestion } from '../types'
import Panel from './Panel'
import { usd } from '../lib/format'

function ScoreRing({ score }: { score: number }) {
  const r = 15
  const c = 2 * Math.PI * r
  const dash = c * score
  return (
    <div className="relative grid h-10 w-10 place-items-center">
      <svg width="40" height="40" className="-rotate-90">
        <circle cx="20" cy="20" r={r} fill="none" stroke="var(--color-edge)" strokeWidth="3" />
        <motion.circle
          cx="20"
          cy="20"
          r={r}
          fill="none"
          stroke="var(--color-gold)"
          strokeWidth="3"
          strokeLinecap="round"
          strokeDasharray={c}
          initial={{ strokeDashoffset: c }}
          animate={{ strokeDashoffset: c - dash }}
          transition={{ duration: 1, ease: 'easeOut' }}
          style={{ filter: 'drop-shadow(0 0 4px var(--color-gold))' }}
        />
      </svg>
      <span className="num absolute text-[11px] font-semibold text-[var(--color-gold-bright)]">
        {Math.round(score * 100)}
      </span>
    </div>
  )
}

function Card({ s, i }: { s: Suggestion; i: number }) {
  // max_profit is null when unlimited (e.g. a long call), max_loss < 0 when
  // the downside is undefined (naked short premium).
  const unlimitedProfit = s.max_profit == null || !Number.isFinite(s.max_profit)
  const undefinedRisk = s.max_loss != null && s.max_loss < 0
  const pop = Number.isFinite(s.pop) ? s.pop : 0
  const score = Number.isFinite(s.score) ? s.score : 0
  return (
    <motion.article
      initial={{ opacity: 0, x: -10 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: i * 0.06, duration: 0.45, ease: [0.16, 1, 0.3, 1] }}
      whileHover={{ y: -2 }}
      className="group relative rounded-xl border border-[var(--color-edge-soft)] p-3 transition-colors hover:border-[color-mix(in_srgb,var(--color-gold)_30%,transparent)]"
      style={{
        background:
          'linear-gradient(160deg, color-mix(in srgb, var(--color-panel-2) 70%, transparent), color-mix(in srgb, var(--color-panel) 80%, transparent))',
      }}
    >
      {/* rank chip */}
      <span className="num absolute -left-1.5 -top-1.5 grid h-5 w-5 place-items-center rounded-full border border-[var(--color-edge)] bg-[var(--color-panel)] text-[9px] text-[var(--color-ink-faint)]">
        {i + 1}
      </span>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-[13px] font-semibold text-[var(--color-ink)]">{s.name}</span>
            <span className="rounded bg-[var(--color-edge-soft)] px-1.5 py-0.5 text-[10px] font-semibold tracking-wide text-[var(--color-gold-bright)]">
              {s.ticker}
            </span>
          </div>
          <p className="mt-1.5 line-clamp-2 text-[11px] leading-relaxed text-[var(--color-ink-faint)]">
            {s.rationale}
          </p>
        </div>
        <ScoreRing score={score} />
      </div>

      <div className="mt-2.5 grid grid-cols-3 gap-2 text-center">
        <Stat label="POP" value={`${Math.round(pop * 100)}%`} tone="teal" />
        <Stat label="Max Profit" value={unlimitedProfit ? '∞' : usd(s.max_profit)} tone="up" />
        <Stat
          label="Max Loss"
          value={undefinedRisk ? '∞' : usd(Math.abs(s.max_loss ?? 0))}
          tone="down"
        />
      </div>

      <div className="mt-2.5 flex flex-wrap gap-1.5">
        {s.tags.map((t) => (
          <span key={t} className="tag">
            {t}
          </span>
        ))}
      </div>
    </motion.article>
  )
}

function Stat({ label, value, tone }: { label: string; value: string; tone: 'teal' | 'up' | 'down' }) {
  const color =
    tone === 'teal' ? 'var(--color-teal)' : tone === 'up' ? 'var(--color-up)' : 'var(--color-down)'
  return (
    <div className="rounded-lg border border-[var(--color-edge-soft)] bg-[var(--color-void)]/40 py-1.5">
      <div className="num text-[12px] font-semibold" style={{ color }}>
        {value}
      </div>
      <div className="text-[8.5px] tracking-[0.12em] text-[var(--color-ink-faint)]">{label}</div>
    </div>
  )
}

export default function SuggestionsPanel({ className }: { className?: string }) {
  const [suggestions, setSuggestions] = useState<Suggestion[]>([])
  const [universe, setUniverse] = useState<string[]>([])
  const [ticker, setTicker] = useState('ALL')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getUniverse().then((u) => setUniverse(['ALL', ...u]))
  }, [])

  useEffect(() => {
    setLoading(true)
    getSuggestions(ticker, undefined, 6).then((r) => {
      setSuggestions(r.suggestions)
      setLoading(false)
    })
  }, [ticker])

  return (
    <Panel
      className={className}
      title="Strategy Suggestions"
      subtitle={`${suggestions.length} ranked`}
      right={
        <select
          value={ticker}
          onChange={(e) => setTicker(e.target.value)}
          className="num rounded-md border border-[var(--color-edge)] bg-[var(--color-panel-2)] px-2 py-1 text-[11px] text-[var(--color-ink-dim)] outline-none focus:border-[var(--color-gold)]"
        >
          {universe.map((u) => (
            <option key={u} value={u}>
              {u}
            </option>
          ))}
        </select>
      }
    >
      <div className="flex flex-col gap-2.5">
        <AnimatePresence mode="popLayout">
          {loading
            ? Array.from({ length: 3 }).map((_, i) => (
                <div
                  key={`sk-${i}`}
                  className="h-24 animate-pulse rounded-xl border border-[var(--color-edge-soft)] bg-[var(--color-panel-2)]/40"
                />
              ))
            : suggestions.map((s, i) => <Card key={`${s.name}-${s.ticker}`} s={s} i={i} />)}
        </AnimatePresence>
      </div>
    </Panel>
  )
}
