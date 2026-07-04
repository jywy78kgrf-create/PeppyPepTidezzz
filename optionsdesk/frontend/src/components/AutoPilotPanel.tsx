// The autonomous loop's control panel: kill switch, promoted configs, the
// live research engine, and the activity feed. Extracted from the old
// PaperPanel sidebar when the trading desk became the app's main stage.
import { useCallback, useEffect, useState } from 'react'
import {
  getAutoActivity,
  getAutoStatus,
  postAutoDisable,
  postAutoEnable,
} from '../api'
import type { AutoActivityEvent, AutoStatus } from '../types'
import Panel from './Panel'
import ResearchEngine from './ResearchEngine'

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

export default function AutoPilotPanel({ className }: { className?: string }) {
  const [status, setStatus] = useState<AutoStatus | null>(null)
  const [events, setEvents] = useState<AutoActivityEvent[]>([])
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(() => {
    getAutoStatus().then(setStatus)
    getAutoActivity(30).then((r) => setEvents(r.events))
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
      getAutoActivity(30).then((r) => setEvents(r.events))
    } finally {
      setBusy(false)
    }
  }

  const enabled = status?.enabled ?? false
  const tripped = status?.breaker?.tripped ?? false
  const activeConfigs = (status?.promoted ?? []).filter((p) => p.active)

  return (
    <Panel
      className={className}
      title="AutoPilot"
      delay={0.08}
      right={
        <div className="flex items-center gap-2">
          {tripped ? (
            <span className="pill" style={{ color: 'var(--color-down)' }}>
              ⛔ BREAKER
            </span>
          ) : (
            <span
              className="pill"
              style={{ color: enabled ? 'var(--color-teal)' : 'var(--color-ink-faint)' }}
            >
              <span
                className={
                  enabled
                    ? 'pulse-dot inline-block h-1.5 w-1.5 rounded-full'
                    : 'inline-block h-1.5 w-1.5 rounded-full'
                }
                style={{ background: enabled ? 'var(--color-teal)' : 'var(--color-ink-faint)' }}
              />
              {enabled ? 'AUTONOMOUS' : 'STANDBY'}
            </span>
          )}
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
      }
    >
      <div className="flex h-full min-h-0 flex-col gap-2">
        {tripped && status?.breaker?.reason && (
          <div className="shrink-0 rounded border border-[color-mix(in_srgb,var(--color-down)_35%,transparent)] px-2 py-1 text-[9.5px] text-[var(--color-down)]">
            {status.breaker.reason} — re-engage to resume.
          </div>
        )}

        {/* live window into the number-crunching */}
        <div className="shrink-0">
          <ResearchEngine />
        </div>

        {/* promoted configs the loop is trading */}
        {activeConfigs.length > 0 && (
          <div className="shrink-0">
            <div className="mb-1 text-[8.5px] tracking-[0.14em] text-[var(--color-ink-faint)]">
              PROMOTED — TRADING LIVE ON PAPER
            </div>
            <div className="flex flex-wrap gap-1">
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
          </div>
        )}

        {/* activity feed */}
        <div className="min-h-0 flex-1">
          <div className="mb-1 text-[8.5px] tracking-[0.14em] text-[var(--color-ink-faint)]">
            ACTIVITY
          </div>
          <div className="max-h-full space-y-0.5 overflow-y-auto">
            {events.map((e, i) => (
              <div key={`${e.ts}-${i}`} className="flex gap-1.5 text-[9.5px] leading-snug">
                <span className="num shrink-0 text-[var(--color-ink-faint)]">
                  {new Date(e.ts).toLocaleTimeString('en-US', {
                    hour: '2-digit',
                    minute: '2-digit',
                  })}
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
            {events.length === 0 && (
              <div className="py-4 text-center text-[10px] text-[var(--color-ink-faint)]">
                No activity yet — engage the autopilot to start the loop.
              </div>
            )}
          </div>
        </div>
      </div>
    </Panel>
  )
}
