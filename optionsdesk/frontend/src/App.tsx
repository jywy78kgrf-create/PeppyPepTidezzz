import { Suspense, lazy } from 'react'
import HeaderBar from './components/HeaderBar'
import TickerTape from './components/TickerTape'
import SuggestionsPanel from './components/SuggestionsPanel'
import BacktestPanel from './components/BacktestPanel'
import LearningPanel from './components/LearningPanel'
import PaperPanel from './components/PaperPanel'
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

        {/* multi-panel desk grid: 3 cols, suggestions tall on the left,
            backtest + learning stacked center, paper on the right */}
        <main className="grid min-h-0 flex-1 grid-cols-1 gap-3 lg:grid-cols-12 lg:grid-rows-2">
          <ErrorBoundary label="Suggestions">
            <SuggestionsPanel className="lg:col-span-3 lg:row-span-2" />
          </ErrorBoundary>
          <ErrorBoundary label="Backtest">
            <BacktestPanel className="lg:col-span-6 lg:row-span-1" />
          </ErrorBoundary>
          <ErrorBoundary label="Paper">
            <PaperPanel className="lg:col-span-3 lg:row-span-2" />
          </ErrorBoundary>
          <div className="flex min-h-0 lg:col-span-6 lg:row-span-1">
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
