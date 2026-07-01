import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children: ReactNode
  /** Rendered instead of children when a render error is caught. */
  fallback?: ReactNode
  /** Label shown in the default fallback + console (e.g. the panel name). */
  label?: string
  /** When true, render nothing on error (used for the decorative 3D layer). */
  silent?: boolean
}

interface State {
  error: Error | null
}

/**
 * Catches render/runtime errors in a subtree so one failing panel (or the WebGL
 * background) can't blank the whole desk. Without this, a single throw — e.g. a
 * shader that won't compile on Safari's WebGL fallback — unmounts the entire app
 * and leaves a black screen.
 */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Surface it for diagnostics; harmless in production.
    console.error(`[ATLAS] ${this.props.label ?? 'component'} error:`, error, info)
  }

  render() {
    if (this.state.error) {
      if (this.props.silent) return null
      if (this.props.fallback) return <>{this.props.fallback}</>
      return (
        <div className="glass flex h-full min-h-0 flex-col items-center justify-center gap-2 p-4 text-center">
          <div className="panel-title text-down">{this.props.label ?? 'Panel'} unavailable</div>
          <div className="max-w-full overflow-hidden text-ellipsis text-[11px] text-ink-dim">
            {this.state.error.message}
          </div>
        </div>
      )
    }
    return this.props.children
  }
}
