import { motion } from 'framer-motion'
import type { ReactNode } from 'react'

interface PanelProps {
  title: string
  subtitle?: string
  right?: ReactNode
  children: ReactNode
  className?: string
  delay?: number
}

export default function Panel({ title, subtitle, right, children, className = '', delay = 0 }: PanelProps) {
  return (
    <motion.section
      initial={{ opacity: 0, y: 14, filter: 'blur(6px)' }}
      animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
      transition={{ duration: 0.6, delay, ease: [0.16, 1, 0.3, 1] }}
      className={`glass flex min-h-0 flex-col overflow-hidden ${className}`}
    >
      <header className="flex shrink-0 items-center justify-between px-4 pt-3 pb-2">
        <div className="flex items-baseline gap-2.5">
          <h2 className="panel-title">{title}</h2>
          {subtitle && (
            <span className="num text-[10px] text-[var(--color-ink-faint)]">{subtitle}</span>
          )}
        </div>
        {right}
      </header>
      <div className="hairline mx-3 shrink-0" />
      <div className="min-h-0 flex-1 overflow-auto p-4 pt-3">{children}</div>
    </motion.section>
  )
}
