import { Suspense, lazy } from 'react'
import HeaderBar from './components/HeaderBar'
import TickerTape from './components/TickerTape'
import LearningPanel from './components/LearningPanel'
import TradingDesk from './components/TradingDesk'
import AutoPilotPanel from './components/AutoPilotPanel'
import ErrorBoundary from './components/ErrorBoundary'

// Lazy-load the WebGL background so the desk paints instantly.
const VolatilityBackground = lazy(() => import('./three/VolatilityBackground'))

export default function App() {
  return (
    <div className="relative h-screen w-screen overflow-hidden">
      {/* fallback background gradient (always painted, furthest back) */}
      <div className="app-bg" />

      {/* GPU-driven volumetric background, painted over the gradient. If
          WebGL/shaders fail (e.g. Safari's WebGL fallback), the boundary drops
          it silently instead of blanking the whole desk — the gradient remains. */}
      <ErrorBoundary silent>
        <Suspense fallback={null}>
          <VolatilityBackground />
        </Suspense>
      </ErrorBoundary>

      {/* texture + focus overlays */}
      <div className="vignette" />
      <div className="noise-overlay" />

      {/* desk — each panel is isolated so one failure can't black out the rest */}
      <div className="relative z-10 flex h-full flex-col gap-3 p-3 lg:p-4">
        <ErrorBoundary label="Header" silent>
          <HeaderBar />
        </ErrorBoundary>

        {/* the trading desk owns the screen: desk + autopilot rail on top
            (~2/3 height), the learning loop full-width below. Suggestions
            and manual backtest were retired once the autopilot took over
            research — the desk IS the product now. */}
        <main className="grid min-h-0 flex-1 grid-cols-1 gap-3 lg:grid-cols-12 lg:grid-rows-[minmax(0,13fr)_minmax(0,6fr)]">
          <ErrorBoundary label="Trading Desk">
            <TradingDesk className="lg:col-span-9" />
          </ErrorBoundary>
          <ErrorBoundary label="AutoPilot">
            <AutoPilotPanel className="lg:col-span-3" />
          </ErrorBoundary>
          <div className="flex min-h-0 lg:col-span-12">
            <ErrorBoundary label="Learning">
              <LearningPanel />
            </ErrorBoundary>
          </div>
        </main>

        <ErrorBoundary label="Ticker" silent>
          <TickerTape />
        </ErrorBoundary>
      </div>
    </div>
  )
}
