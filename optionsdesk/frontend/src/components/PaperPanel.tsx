import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { closePosition, getPositions } from '../api'
import type { Position } from '../types'
import Panel from './Panel'
import { num, usd } from '../lib/format'

function jitter(p: Position): Position {
  const mark = Math.max(0.01, p.mark_price + (Math.random() - 0.5) * 0.06)
  const upnl = Math.round((p.entry_price - mark) * -1 * p.qty * 100 * 100) / 100
  const upnl_pct = Math.round((upnl / (Math.abs(p.entry_price) * p.qty * 100)) * 1000) / 10
  return { ...p, mark_price: Math.round(mark * 100) / 100, upnl, upnl_pct }
}

export default function PaperPanel({ className }: { className?: string }) {
  const [positions, setPositions] = useState<Position[]>([])
  const [closing, setClosing] = useState<string | null>(null)

  useEffect(() => {
    getPositions().then(setPositions)
  }, [])

  // live mark drift
  useEffect(() => {
    const id = setInterval(() => {
      setPositions((ps) => ps.map(jitter))
    }, 1500)
    return () => clearInterval(id)
  }, [])

  const handleClose = async (id: string) => {
    setClosing(id)
    await closePosition(id)
    setTimeout(() => {
      setPositions((ps) => ps.filter((p) => p.id !== id))
      setClosing(null)
    }, 300)
  }

  const totalUpnl = positions.reduce((a, p) => a + p.upnl, 0)

  return (
    <Panel
      className={className}
      title="Paper Trading"
      subtitle={`${positions.length} open`}
      right={
        <div className="flex items-center gap-1.5">
          <span className="panel-title">Net uPnL</span>
          <span
            className="num text-[13px] font-semibold"
            style={{ color: totalUpnl >= 0 ? 'var(--color-up)' : 'var(--color-down)' }}
          >
            {totalUpnl >= 0 ? '+' : ''}
            {usd(totalUpnl)}
          </span>
        </div>
      }
    >
      <div className="overflow-hidden">
        <table className="w-full border-separate border-spacing-y-1 text-left">
          <thead>
            <tr className="text-[9px] uppercase tracking-[0.12em] text-[var(--color-ink-faint)]">
              <th className="pb-1 pl-2 font-medium">Position</th>
              <th className="pb-1 text-right font-medium">Qty</th>
              <th className="pb-1 text-right font-medium">Entry</th>
              <th className="pb-1 text-right font-medium">Mark</th>
              <th className="pb-1 text-right font-medium">DTE</th>
              <th className="pb-1 text-right font-medium">uPnL</th>
              <th className="pb-1 pr-2 text-right font-medium"></th>
            </tr>
          </thead>
          <tbody>
            <AnimatePresence mode="popLayout">
              {positions.map((p) => {
                const up = p.upnl >= 0
                const color = up ? 'var(--color-up)' : 'var(--color-down)'
                return (
                  <motion.tr
                    key={p.id}
                    layout
                    initial={{ opacity: 0, x: -8 }}
                    animate={{
                      opacity: closing === p.id ? 0.3 : 1,
                      x: 0,
                    }}
                    exit={{ opacity: 0, x: 16, height: 0 }}
                    transition={{ duration: 0.3 }}
                    className="group"
                  >
                    <td className="rounded-l-lg border-y border-l border-[var(--color-edge-soft)] bg-[var(--color-panel-2)]/40 py-2 pl-2">
                      <div className="text-[12px] font-semibold text-[var(--color-ink)]">{p.ticker}</div>
                      <div className="text-[10px] text-[var(--color-ink-faint)]">{p.strategy}</div>
                    </td>
                    <td className="num border-y border-[var(--color-edge-soft)] bg-[var(--color-panel-2)]/40 text-right text-[11px] text-[var(--color-ink-dim)]">
                      {p.qty}
                    </td>
                    <td className="num border-y border-[var(--color-edge-soft)] bg-[var(--color-panel-2)]/40 text-right text-[11px] text-[var(--color-ink-dim)]">
                      {num(p.entry_price)}
                    </td>
                    <td className="num border-y border-[var(--color-edge-soft)] bg-[var(--color-panel-2)]/40 text-right text-[11px] text-[var(--color-ink)]">
                      {num(p.mark_price)}
                    </td>
                    <td className="num border-y border-[var(--color-edge-soft)] bg-[var(--color-panel-2)]/40 text-right text-[11px] text-[var(--color-ink-faint)]">
                      {p.dte}d
                    </td>
                    <td className="num border-y border-[var(--color-edge-soft)] bg-[var(--color-panel-2)]/40 px-2 text-right">
                      <div className="text-[12px] font-semibold" style={{ color }}>
                        {up ? '+' : ''}
                        {usd(p.upnl)}
                      </div>
                      <div className="text-[9.5px]" style={{ color }}>
                        {up ? '+' : ''}
                        {p.upnl_pct.toFixed(1)}%
                      </div>
                    </td>
                    <td className="rounded-r-lg border-y border-r border-[var(--color-edge-soft)] bg-[var(--color-panel-2)]/40 py-2 pr-2 text-right">
                      <button
                        className="btn btn-danger px-2 py-1 text-[10px]"
                        onClick={() => handleClose(p.id)}
                        disabled={closing === p.id}
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
        {positions.length === 0 && (
          <div className="py-8 text-center text-[11px] text-[var(--color-ink-faint)]">
            No open positions — flat.
          </div>
        )}
      </div>
    </Panel>
  )
}
