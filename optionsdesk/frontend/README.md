# ATLAS — Automated Options Desk (frontend)

A high-end, single-screen trading-desk UI for the ATLAS automated options
engine. Dark glassmorphism, a GPU-driven volumetric background, and live,
motion-rich panels styled after a Bloomberg-terminal-meets-luxury-fintech
aesthetic.

## Stack

- **Vite + React + TypeScript**
- **three / @react-three/fiber / @react-three/drei** — animated, depthful
  WebGL background (a morphing volatility-surface wireframe with fog, a
  drifting particle field, and cursor parallax).
- **framer-motion** — panel entrances, value transitions, list animations.
- **tailwindcss v4** — layout + the dark glass design system.
- **recharts** — equity curve, underwater drawdown, and the learning-loop
  objective chart.

## Run

```bash
npm install
npm run dev        # http://localhost:5173
```

Production build + local preview:

```bash
npm run build      # type-checks then builds to dist/
npm run preview
```

## Backend / data layer

All data goes through `src/api.ts`, which calls the backend at
`import.meta.env.VITE_API_URL` (default `http://localhost:8000`).

Copy `.env.example` to `.env` to point at a different backend:

```bash
cp .env.example .env
```

Endpoints used:

| Method | Path |
| ------ | ---- |
| GET  | `/api/health` |
| GET  | `/api/universe` |
| GET  | `/api/suggestions?ticker=&date=&top_k=` |
| POST | `/api/backtest` |
| POST | `/api/learn` |
| GET  | `/api/paper/positions` |
| POST | `/api/paper/open` |
| POST | `/api/paper/close` |
| GET  | `/api/live/quote?ticker=` |
| GET  | `/api/brokers/status` |

**Standalone demo:** every call gracefully falls back to rich, realistic
**mock data** in `src/mock.ts` when the backend is unreachable (2.5s timeout).
When that happens a `SIMULATED` badge appears in the header. So
`npm run dev` is fully demoable with no backend running.

## Structure

```
src/
  api.ts                      # fetch layer + mock fallback + live/sim source signal
  mock.ts                     # deterministic, realistic demo data
  types.ts                    # domain types mirroring backend contracts
  lib/format.ts               # currency / percent / number formatters
  three/
    VolatilityBackground.tsx  # R3F canvas: vol-surface shader, particles, parallax
  components/
    Panel.tsx                 # reusable glass panel shell
    HeaderBar.tsx             # brand, live clock, equity, connection pills
    TickerTape.tsx            # scrolling live market strip
    SuggestionsPanel.tsx      # ranked strategy cards (POP, P/L, score, tags)
    BacktestPanel.tsx         # equity + drawdown charts, metrics, survivorship badge
    LearningPanel.tsx         # live-streaming recursive optimisation + best params
    PaperPanel.tsx            # open positions table, live uPnL, close actions
  App.tsx                     # the desk grid
  index.css                   # tailwind theme + glass/noise/animation utilities
```

## The 3D background

`src/three/VolatilityBackground.tsx` renders an `@react-three/fiber` canvas:

- A high-resolution plane whose vertices are displaced every frame by a sum of
  travelling sine waves plus a Gaussian "vol smile" ridge — a stand-in for a
  slowly morphing implied-volatility surface. A custom `ShaderMaterial` shades
  it with a depth-faded gold/teal gradient, animated topographic contour lines,
  and a fine UV grid; a second solid copy underneath gives the wireframe volume.
- A 900-point drifting particle field (additive-blended dust motes) for
  parallax depth.
- Scene-level `fog` and a cursor-driven camera `Rig` so the whole field drifts
  subtly with the pointer.

The canvas is `React.lazy`-loaded and code-split into its own chunk so the desk
paints immediately.
