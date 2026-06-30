// Rich, realistic MOCK data so `npm run dev` is fully demoable standalone.
// Every api call in src/api.ts falls back here when the backend is unreachable.

import type {
  BacktestResponse,
  BrokerStatus,
  HealthResponse,
  LearnIteration,
  LearnResponse,
  Position,
  Quote,
  Suggestion,
  SuggestionsResponse,
} from './types'

// Deterministic PRNG so the demo looks the same each load but feels organic.
function mulberry32(seed: number) {
  return function () {
    seed |= 0
    seed = (seed + 0x6d2b79f5) | 0
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

export const UNIVERSE = [
  'SPY', 'QQQ', 'AAPL', 'MSFT', 'NVDA', 'AMD', 'TSLA', 'AMZN',
  'META', 'GOOGL', 'IWM', 'XLE', 'SMH', 'COIN', 'NFLX',
]

export function mockHealth(): HealthResponse {
  return { status: 'ok', version: 'atlas-1.4.2', asof: new Date().toISOString() }
}

/* --------------------------------------------------------------------- */
/*  Suggestions                                                           */
/* --------------------------------------------------------------------- */
const BASE_SUGGESTIONS: Suggestion[] = [
  {
    name: 'Bull Put Credit Spread',
    ticker: 'NVDA',
    score: 0.92,
    pop: 0.78,
    max_profit: 215,
    max_loss: 785,
    rationale:
      'IV rank 71st pct; 30Δ short put rests below the 50-day VWAP shelf. Skew rich, theta tailwind into a low-realized-vol regime.',
    tags: ['Defined Risk', 'High IVR', 'Bullish', '30DTE'],
  },
  {
    name: 'Iron Condor',
    ticker: 'SPY',
    score: 0.88,
    pop: 0.82,
    max_profit: 168,
    max_loss: 332,
    rationale:
      'Range-bound term structure with compressed expected move. 16Δ wings capture elevated weekly variance risk premium.',
    tags: ['Neutral', 'Theta', 'Defined Risk', '21DTE'],
  },
  {
    name: 'Put Ratio Backspread',
    ticker: 'TSLA',
    score: 0.81,
    pop: 0.64,
    max_profit: 940,
    max_loss: 410,
    rationale:
      'Negative skew steepening into earnings drift; convex payoff funded by overpriced ATM put. Vega-positive tail hedge.',
    tags: ['Convex', 'Earnings', 'Vega+', 'Directional'],
  },
  {
    name: 'Calendar Call Spread',
    ticker: 'AAPL',
    score: 0.76,
    pop: 0.69,
    max_profit: 305,
    max_loss: 190,
    rationale:
      'Front-month IV trades 6 vol over back; pins toward strike on contango roll-down. Clean liquidity, tight spreads.',
    tags: ['Theta', 'Vega+', 'Pin', '45/14'],
  },
  {
    name: 'Short Strangle',
    ticker: 'QQQ',
    score: 0.72,
    pop: 0.74,
    max_profit: 410,
    max_loss: -1,
    rationale:
      'VRP elevated post-OPEX; 15Δ strangle harvests crush. Undefined risk — sized at 4% of buying power with mechanical roll.',
    tags: ['Neutral', 'High VRP', 'Undefined', '30DTE'],
  },
  {
    name: 'Diagonal Put Spread',
    ticker: 'AMD',
    score: 0.69,
    pop: 0.66,
    max_profit: 260,
    max_loss: 240,
    rationale:
      'Long-dated put financed by weekly short premium; benefits from gentle downtrend and term-structure inversion.',
    tags: ['Bearish', 'Theta', 'Defined Risk', '60/7'],
  },
]

export function mockSuggestions(ticker?: string, topK = 6): SuggestionsResponse {
  let list = BASE_SUGGESTIONS
  if (ticker && ticker !== 'ALL') {
    const filtered = BASE_SUGGESTIONS.filter((s) => s.ticker === ticker)
    list = filtered.length
      ? filtered
      : BASE_SUGGESTIONS.map((s) => ({ ...s, ticker }))
  }
  return {
    asof: new Date().toISOString(),
    ticker: ticker ?? 'ALL',
    suggestions: list.slice(0, topK),
  }
}

/* --------------------------------------------------------------------- */
/*  Backtest — climbing equity curve with realistic drawdowns            */
/* --------------------------------------------------------------------- */
export function mockBacktest(): BacktestResponse {
  const rng = mulberry32(20240117)
  const n = 504 // ~2 trading years
  const start = new Date('2023-01-03').getTime()
  const day = 86400000
  let equity = 100000
  let peak = equity
  const curve: { asof: string; equity: number }[] = []

  // regime cycling produces organic up-trends punctuated by drawdowns
  for (let i = 0; i < n; i++) {
    const regime = Math.sin(i / 47) * 0.0006 + 0.00125 // positive drifting edge
    const shock = (rng() - 0.5) * 0.0105
    // occasional vol cluster -> drawdown
    const cluster = i % 130 > 95 && i % 130 < 120 ? -0.0055 : 0
    const ret = regime + shock + cluster
    equity *= 1 + ret
    peak = Math.max(peak, equity)
    const date = new Date(start + i * day * (7 / 5)) // skip weekends roughly
    curve.push({ asof: date.toISOString().slice(0, 10), equity: Math.round(equity * 100) / 100 })
  }

  const ret = equity / 100000 - 1
  const years = n / 252
  const cagr = Math.pow(1 + ret, 1 / years) - 1

  return {
    config: {
      strategy: 'bull_put_spread',
      params: { delta: 0.3, dte: 30, profit_target: 0.5, stop: 2.0 },
      tickers: ['SPY', 'QQQ', 'NVDA', 'AAPL'],
      start: '2023-01-03',
      end: curve[curve.length - 1].asof,
    },
    cagr,
    sharpe: 1.94,
    sortino: 2.71,
    max_drawdown: -0.142,
    win_rate: 0.683,
    profit_factor: 2.18,
    n_trades: 318,
    survivorship_note:
      'Universe reconstructed from point-in-time index membership; delisted names retained. No look-ahead in chain selection.',
    equity_curve: curve,
  }
}

/* --------------------------------------------------------------------- */
/*  Learning loop — recursive optimisation that improves OOS over time   */
/* --------------------------------------------------------------------- */
export function mockLearnHistory(nIter = 64): LearnResponse {
  const rng = mulberry32(7)
  const history: LearnIteration[] = []
  let best = 0.42
  let bestParams: Record<string, number> = { delta: 0.3, dte: 30, pt: 0.5, stop: 2.0 }

  for (let i = 0; i < nIter; i++) {
    // proposal jitters around current best, with annealing
    const temp = 1 - i / nIter
    const trial = {
      delta: clamp(bestParams.delta + (rng() - 0.5) * 0.12 * temp, 0.1, 0.45),
      dte: Math.round(clamp(bestParams.dte + (rng() - 0.5) * 14 * temp, 14, 60)),
      pt: clamp(bestParams.pt + (rng() - 0.5) * 0.25 * temp, 0.25, 0.9),
      stop: clamp(bestParams.stop + (rng() - 0.5) * 0.8 * temp, 1.0, 3.0),
    }
    // score trends up with noise; sometimes worse (rejected)
    const drift = 0.42 + (i / nIter) * 0.46
    const score = clamp(drift + (rng() - 0.5) * 0.16, 0, 1)
    const accepted = score > best
    if (accepted) {
      best = score
      bestParams = trial
    }
    history.push({
      iteration: i + 1,
      oos_score: Math.round(score * 1000) / 1000,
      accepted,
      params: trial,
    })
  }

  const bestIter = history.reduce((a, b) => (b.oos_score > a.oos_score ? b : a))
  return {
    best: {
      oos_score: bestIter.oos_score,
      params: bestIter.params,
      iteration: bestIter.iteration,
    },
    history,
  }
}

// A single fresh iteration for the live-streaming learning panel.
export function mockNextIteration(prev: LearnIteration | undefined, bestScore: number): LearnIteration {
  const rng = mulberry32((prev?.iteration ?? 0) * 131 + Date.now() % 9973)
  const iteration = (prev?.iteration ?? 0) + 1
  const drift = clamp(bestScore + 0.015, 0.4, 0.97)
  const score = clamp(drift + (rng() - 0.5) * 0.14, 0, 1)
  const base = prev?.params ?? { delta: 0.3, dte: 30, pt: 0.5, stop: 2.0 }
  return {
    iteration,
    oos_score: Math.round(score * 1000) / 1000,
    accepted: score > bestScore,
    params: {
      delta: clamp(base.delta + (rng() - 0.5) * 0.05, 0.1, 0.45),
      dte: Math.round(clamp(base.dte + (rng() - 0.5) * 6, 14, 60)),
      pt: clamp(base.pt + (rng() - 0.5) * 0.1, 0.25, 0.9),
      stop: clamp(base.stop + (rng() - 0.5) * 0.3, 1.0, 3.0),
    },
  }
}

/* --------------------------------------------------------------------- */
/*  Paper trading                                                         */
/* --------------------------------------------------------------------- */
export function mockPositions(): Position[] {
  const raw: Omit<Position, 'upnl' | 'upnl_pct'>[] = [
    { id: 'p1', ticker: 'NVDA', strategy: 'Bull Put 1180/1160', qty: 4, entry_price: 2.15, mark_price: 1.32, opened_at: '2026-06-18', dte: 16, delta: 0.18 },
    { id: 'p2', ticker: 'SPY', strategy: 'Iron Condor 545/620', qty: 6, entry_price: 1.68, mark_price: 1.41, opened_at: '2026-06-23', dte: 9, delta: -0.04 },
    { id: 'p3', ticker: 'AAPL', strategy: 'Call Calendar 215', qty: 3, entry_price: 3.05, mark_price: 3.62, opened_at: '2026-06-12', dte: 14, delta: 0.09 },
    { id: 'p4', ticker: 'TSLA', strategy: 'Put Backspread 240/220', qty: 2, entry_price: -0.40, mark_price: 0.95, opened_at: '2026-06-25', dte: 22, delta: -0.31 },
    { id: 'p5', ticker: 'QQQ', strategy: 'Short Strangle 460/520', qty: 2, entry_price: 4.10, mark_price: 4.85, opened_at: '2026-06-20', dte: 12, delta: -0.06 },
  ]
  return raw.map((p) => {
    const upnl = Math.round((p.entry_price - p.mark_price) * -1 * p.qty * 100 * 100) / 100
    const upnl_pct = Math.round((upnl / (Math.abs(p.entry_price) * p.qty * 100)) * 1000) / 10
    return { ...p, upnl, upnl_pct }
  })
}

/* --------------------------------------------------------------------- */
/*  Brokers + quotes                                                      */
/* --------------------------------------------------------------------- */
export function mockBrokers(): BrokerStatus[] {
  return [
    { name: 'Alpha Vantage', connected: true, latency_ms: 142, detail: 'market data' },
    { name: 'IBKR', connected: true, latency_ms: 38, detail: 'TWS gateway' },
    { name: 'Paper', connected: true, latency_ms: 4, detail: 'simulator' },
  ]
}

const QUOTE_BASE: Record<string, number> = {
  SPY: 612.4, QQQ: 548.1, AAPL: 213.7, MSFT: 498.2, NVDA: 1192.5,
  AMD: 168.3, TSLA: 248.9, AMZN: 201.6, META: 712.4, GOOGL: 184.2,
  IWM: 224.1, XLE: 96.7, SMH: 281.3, COIN: 312.8, NFLX: 998.4,
}

export function mockQuote(ticker: string): Quote {
  const base = QUOTE_BASE[ticker] ?? 100
  const change = (mulberry32(ticker.charCodeAt(0) * 31 + Date.now() % 997)() - 0.45) * base * 0.02
  return {
    ticker,
    price: Math.round((base + change) * 100) / 100,
    change: Math.round(change * 100) / 100,
    change_pct: Math.round((change / base) * 10000) / 100,
  }
}

export function mockTape(): Quote[] {
  return UNIVERSE.map((t) => mockQuote(t))
}

function clamp(x: number, lo: number, hi: number) {
  return Math.max(lo, Math.min(hi, x))
}
