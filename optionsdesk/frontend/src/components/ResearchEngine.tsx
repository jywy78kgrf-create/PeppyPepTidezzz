// Live window into the autopilot's research engine — what batch is being
// crunched right now, each optimizer iteration as it lands, and progress
// through the full strategy x universe sweep. Every number here is real
// telemetry polled from /api/auto/research; when nothing is running it says
// so instead of animating theater.
import { useEffect, useState } from 'react'
import { getResearchStatus } from '../api'
import type { ResearchStatus } from '../types'
import { num } from '../lib/format'

function fmtDur(s: number | null | undefined): string {
  if (s == null || !Number.isFinite(s)) return '—'
  const m = Math.floor(s / 60)
  const sec = Math.round(s % 60)
  return m ? `${m}m ${String(sec).padStart(2, '0')}s` : `${sec}s`
}

export default function ResearchEngine() {
  const [st, setSt] = useState<ResearchStatus | null>(null)
  const [drift, setDrift] = useState(0) // seconds since last poll, keeps the clock ticking

  useEffect(() => {
    let alive = true
    const load = () => {
      if (document.hidden) return
      getResearchStatus()
        .then((r) => {
          if (alive) {
            setSt(r)
            setDrift(0)
          }
        })
        .catch(() => {
          /* strict layer: keep last real telemetry, retry next poll */
        })
    }
    load()
    const poll = setInterval(load, 5_000)
    const tick = setInterval(() => setDrift((d) => d + 1), 1_000)
    return () => {
      alive = false
      clearInterval(poll)
      clearInterval(tick)
    }
  }, [])

  if (!st) return null
  const cur = st.current
  const parked = st.research_enabled === false
  const active = cur.active && !parked
  const iters = cur.iterations ?? []
  const nIter = Math.max(cur.n_iter ?? 0, iters.length)
  const elapsed = active && cur.elapsed_s != null ? cur.elapsed_s + drift : null
  const maxAbs = Math.max(1e-9, ...iters.map((i) => Math.abs(i.oos_score ?? 0)))

  return (
    <div
      className="mt-1.5 rounded-md border px-2 py-1.5"
      style={{
        borderColor: active
          ? 'color-mix(in srgb, var(--color-iris) 40%, transparent)'
          : 'var(--color-edge-soft)',
        background: 'color-mix(in srgb, var(--color-void) 55%, transparent)',
      }}
    >
      {/* header: state dot + sweep progress */}
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5">
          <span
            className={active ? 'pulse-dot h-1.5 w-1.5 rounded-full' : 'h-1.5 w-1.5 rounded-full'}
            style={{
              background: active ? 'var(--color-iris)' : 'var(--color-ink-faint)',
              boxShadow: active ? '0 0 8px var(--color-iris)' : 'none',
            }}
          />
          <span className="text-[8.5px] font-semibold tracking-[0.16em] text-[var(--color-ink-faint)]">
            RESEARCH ENGINE
          </span>
        </span>
        {parked ? (
          <span
            className="rounded-full border px-1.5 py-[1px] text-[8px] font-semibold tracking-[0.16em]"
            style={{
              color: 'var(--color-gold)',
              borderColor: 'color-mix(in srgb, var(--color-gold) 45%, transparent)',
              background: 'color-mix(in srgb, var(--color-gold) 10%, transparent)',
            }}
            title="Research is hard-parked (AUTO_RESEARCH=0). No new backtests will run. The paper desk keeps trading its promoted strategies."
          >
            PARKED
          </span>
        ) : (
          st.sweep_total > 0 && (
            <span
              className="num text-[8.5px] text-[var(--color-ink-faint)]"
              title={`batch ${st.sweep_done} of ${st.sweep_total} in pass #${st.sweep_number} over every strategy × ticker batch`}
            >
              sweep {st.sweep_number} · {st.sweep_done}/{st.sweep_total}
            </span>
          )
        )}
      </div>

      {/* whole-sweep progress hairline */}
      {st.sweep_total > 0 && (
        <div className="mt-1 h-[3px] overflow-hidden rounded-full bg-[var(--color-void)]/60">
          <div
            className="h-full rounded-full transition-[width] duration-700"
            style={{
              width: `${((100 * st.sweep_done) / st.sweep_total).toFixed(1)}%`,
              background: 'linear-gradient(90deg, var(--color-iris), var(--color-gold))',
            }}
          />
        </div>
      )}

      {active ? (
        <>
          <div className="mt-1.5 flex items-center justify-between gap-2">
            <span className="truncate text-[10px] font-semibold text-[var(--color-ink)]">
              {cur.strategy?.replace(/_/g, ' ')}
              <span className="ml-1.5 text-[8.5px] font-normal text-[var(--color-ink-faint)]">
                {(cur.tickers ?? []).join(' ')}
              </span>
            </span>
            <span className="num shrink-0 text-[9px]" style={{ color: 'var(--color-iris)' }}>
              {fmtDur(elapsed)}
            </span>
          </div>

          {/* one bar per optimizer iteration, landing live as each finishes */}
          <div className="mt-1 flex items-end gap-[3px]" style={{ height: 26 }}>
            {Array.from({ length: nIter }, (_, i) => {
              const it = iters[i]
              if (!it) {
                const isNext = i === iters.length
                return (
                  <div
                    key={i}
                    className={isNext ? 'flex-1 animate-pulse rounded-sm' : 'flex-1 rounded-sm'}
                    style={{
                      height: 4,
                      background: isNext
                        ? 'color-mix(in srgb, var(--color-iris) 45%, transparent)'
                        : 'var(--color-edge-soft)',
                    }}
                    title={isNext ? 'evaluating…' : 'queued'}
                  />
                )
              }
              const h = 6 + (20 * Math.abs(it.oos_score ?? 0)) / maxAbs
              return (
                <div
                  key={i}
                  className="flex-1 rounded-sm"
                  title={`iter ${it.iteration}: OOS ${num(it.oos_score, 3)}${it.accepted ? ' · accepted' : ''} · ${it.n_trades ?? 0} trades simulated`}
                  style={{
                    height: h,
                    background: it.accepted
                      ? 'var(--color-iris)'
                      : 'color-mix(in srgb, var(--color-ink-faint) 45%, transparent)',
                    boxShadow: it.accepted ? '0 0 6px -1px var(--color-iris)' : 'none',
                  }}
                />
              )
            })}
          </div>

          <div className="mt-1 flex items-center justify-between text-[8.5px] text-[var(--color-ink-faint)]">
            <span className="num">
              {iters.length}/{nIter} configs · {(cur.trades_simulated ?? 0).toLocaleString()}{' '}
              trades simulated
            </span>
            <span className="num">
              {cur.start} → {cur.end}
            </span>
          </div>
        </>
      ) : parked ? (
        <div className="mt-1.5 text-[9px] leading-snug text-[var(--color-ink-dim)]">
          Parked — no new backtests will run. The desk keeps trading its
          promoted strategies; re-enable by removing{' '}
          <span className="num text-[var(--color-gold)]">AUTO_RESEARCH=0</span> and
          rebuilding.
        </div>
      ) : st.last ? (
        <div className="mt-1.5 text-[9px] leading-snug text-[var(--color-ink-dim)]">
          <span className="font-semibold text-[var(--color-ink)]">
            {st.last.strategy.replace(/_/g, ' ')}
          </span>{' '}
          on {st.last.tickers.join(', ')} —{' '}
          <span
            style={{
              color: st.last.verdict === 'promoted' ? 'var(--color-up)' : 'var(--color-amber)',
            }}
            title={st.last.verdict ?? undefined}
          >
            {st.last.verdict ?? 'finished'}
          </span>
          <span className="num">
            {' '}
            · holdout {num(st.last.holdout_score, 2)} · {st.last.iterations} configs ·{' '}
            {st.last.trades_simulated.toLocaleString()} trades · {fmtDur(st.last.duration_s)}
          </span>
        </div>
      ) : (
        <div className="mt-1.5 text-[9px] text-[var(--color-ink-faint)]">
          idle — no batch this session yet
          {st.enabled ? '; the next one starts on schedule' : ' (autopilot is off)'}
        </div>
      )}
    </div>
  )
}
