import { Suspense, lazy } from 'react'
import HeaderBar from './components/HeaderBar'
import TickerTape from './components/TickerTape'
import SuggestionsPanel from './components/SuggestionsPanel'
import BacktestPanel from './components/BacktestPanel'
import LearningPanel from './components/LearningPanel'
import PaperPanel from './components/PaperPanel'

// Lazy-load the WebGL background so the desk paints instantly.
const VolatilityBackground = lazy(() => import('./three/VolatilityBackground'))

export default function App() {
  return (
    <div className="relative h-screen w-screen overflow-hidden">
      {/* GPU-driven volumetric background */}
      <Suspense fallback={null}>
        <VolatilityBackground />
      </Suspense>

      {/* texture + focus overlays */}
      <div className="vignette" />
      <div className="noise-overlay" />

      {/* desk */}
      <div className="relative z-10 flex h-full flex-col gap-3 p-3 lg:p-4">
        <HeaderBar />

        {/* multi-panel desk grid: 3 cols, suggestions tall on the left,
            backtest + learning stacked center, paper on the right */}
        <main className="grid min-h-0 flex-1 grid-cols-1 gap-3 lg:grid-cols-12 lg:grid-rows-2">
          <SuggestionsPanel className="lg:col-span-3 lg:row-span-2" />
          <BacktestPanel className="lg:col-span-6 lg:row-span-1" />
          <PaperPanel className="lg:col-span-3 lg:row-span-2" />
          <div className="flex min-h-0 lg:col-span-6 lg:row-span-1">
            <LearningPanel />
          </div>
        </main>

        <TickerTape />
      </div>
    </div>
  )
}
