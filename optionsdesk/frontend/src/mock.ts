// Rich, realistic MOCK data so `npm run dev` is fully demoable standalone.
// Every api call in src/api.ts falls back here when the backend is unreachable.
// Shapes MUST match PHASE2_CONTRACT.md exactly (same as the live backend).

import type {
  BacktestResponse,
  BrokerStatus,
  ClosedReasons,
  EquityPoint,
  HealthResponse,
  HoldoutInfo,
  LearnIteration,
  LearnResponse,
  PaperBookResponse,
  PaperHistoryPoint,
  PaperHistoryResponse,
  PaperPosition,
  Quote,
  Regimes,
  Suggestion,
  SuggestionsResponse,
  TradeSummary,
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

function hashStr(s: string): number {
  let h = 2166136261
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
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
export interface MockBacktestRequest {
  strategy?: string
  tickers?: string[]
  start?: string
  end?: string
  params?: Record<string, unknown>
}

const SHORT_PREMIUM = new Set([
  'bull_put_spread', 'bear_call_spread', 'iron_condor', 'covered_call', 'short_straddle',
])

export function mockBacktest(req: MockBacktestRequest = {}): BacktestResponse {
  // NOTE: every mock result is branded simulated: true so the UI can never
  // present fabricated numbers as a real run.
  const strategy = req.strategy ?? 'bull_put_spread'
  const tickers = req.tickers?.length ? req.tickers : ['SPY', 'QQQ', 'NVDA', 'AAPL']
  const start = req.start ?? '2023-01-03'
  const end = req.end ?? '2025-01-03'
  const seed = hashStr(`${strategy}|${tickers.join(',')}|${start}|${end}`)
  const rng = mulberry32(seed)
  const premium = SHORT_PREMIUM.has(strategy)

  const t0 = new Date(start).getTime()
  const t1 = Math.max(t0 + 90 * 86400000, new Date(end).getTime())
  const n = Math.min(504, Math.max(60, Math.round(((t1 - t0) / 86400000) * (5 / 7))))
  const day = 86400000

  let equity = 100000
  const curve: EquityPoint[] = []
  // regime cycling produces organic up-trends punctuated by drawdowns
  const edge = premium ? 0.0012 + rng() * 0.0005 : 0.0006 + rng() * 0.0006
  const volMul = premium ? 1 : 1.7
  for (let i = 0; i < n; i++) {
    const regime = Math.sin(i / 47) * 0.0006 + edge
    const shock = (rng() - 0.5) * 0.0105 * volMul
    const cluster = i % 130 > 95 && i % 130 < 120 ? -0.0055 : 0 // vol cluster -> drawdown
    equity *= 1 + regime + shock + cluster
    const date = new Date(t0 + i * day * (7 / 5)) // skip weekends roughly
    curve.push({ asof: date.toISOString().slice(0, 10), equity: Math.round(equity * 100) / 100 })
  }

  const totalReturn = equity / 100000 - 1
  const years = n / 252
  const cagr = Math.pow(1 + totalReturn, 1 / years) - 1

  // how trades actually ended — realistic per-style mix, sums to n_trades
  const nTrades = Math.round(n * 0.55 + rng() * 40)
  const weights: Record<string, number> = premium
    ? { target: 0.52, stop: 0.17, close_dte: 0.12, expiry: 0.11, assigned: 0.05, delisted: 0.01, end: 0.02 }
    : { target: 0.31, stop: 0.34, close_dte: 0.18, expiry: 0.13, assigned: 0, delisted: 0.01, end: 0.03 }
  const closed_reasons: ClosedReasons = {}
  let assigned = 0
  const keys = Object.keys(weights)
  keys.forEach((k, i) => {
    const c = i === keys.length - 1
      ? nTrades - assigned
      : Math.round(nTrades * weights[k] * (0.9 + rng() * 0.2))
    if (c > 0) closed_reasons[k] = c
    assigned += c
  })

  // sampled trade list (what /api/backtest returns after downsampling)
  const trades: TradeSummary[] = []
  const reasonPool = Object.entries(closed_reasons).flatMap(([r, c]) =>
    Array<string>(Math.max(1, Math.round((c / nTrades) * 40))).fill(r),
  )
  for (let i = 0; i < Math.min(40, nTrades); i++) {
    const oi = Math.floor((i / 40) * (n - 22))
    const reason = reasonPool[Math.floor(rng() * reasonPool.length)]
    const win = reason === 'target' || (reason !== 'stop' && rng() > 0.42)
    trades.push({
      spec_name: strategy,
      ticker: tickers[Math.floor(rng() * tickers.length)],
      opened: curve[oi].asof,
      closed: curve[Math.min(n - 1, oi + 5 + Math.floor(rng() * 18))].asof,
      pnl: Math.round((win ? 90 + rng() * 240 : -(120 + rng() * 380)) * 100) / 100,
      costs: Math.round((6 + rng() * 9) * 100) / 100,
      closed_reason: reason,
    })
  }

  const winRate = premium ? 0.62 + rng() * 0.1 : 0.44 + rng() * 0.1
  return {
    config: strategy,
    params: req.params ?? { delta: 0.3, dte: 30, profit_target: 0.5, stop: 2.0 },
    start: curve[0].asof,
    end: curve[curve.length - 1].asof,
    n_trades: nTrades,
    cagr: Math.round(cagr * 10000) / 10000,
    total_return: Math.round(totalReturn * 10000) / 10000,
    sharpe: Math.round((premium ? 1.6 + rng() * 0.7 : 0.9 + rng() * 0.7) * 100) / 100,
    sortino: Math.round((premium ? 2.2 + rng() * 0.9 : 1.2 + rng() * 0.8) * 100) / 100,
    max_drawdown: -Math.round((premium ? 0.11 + rng() * 0.06 : 0.16 + rng() * 0.09) * 1000) / 1000,
    win_rate: Math.round(winRate * 1000) / 1000,
    profit_factor: Math.round((premium ? 1.9 + rng() * 0.6 : 1.3 + rng() * 0.5) * 100) / 100,
    avg_trade: Math.round(((equity - 100000) / nTrades) * 100) / 100,
    total_costs: Math.round(nTrades * (9 + rng() * 5) * 100) / 100,
    total_holding_cost: Math.round(nTrades * (2 + rng() * 2) * 100) / 100,
    universe_size: tickers.length,
    delisted_included: 1,
    survivorship_note:
      'Universe reconstructed from point-in-time index membership; delisted names retained. No look-ahead in chain selection.',
    closed_reasons,
    equity_curve: curve,
    trades,
    simulated: true,
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
      strategy: 'bull_put_spread',
      oos_score: Math.round(score * 1000) / 1000,
      is_score: Math.round(clamp(score + 0.05 + (rng() - 0.5) * 0.06, 0, 1) * 1000) / 1000,
      accepted,
      params: trial,
      note: accepted ? 'accepted: OOS improved' : 'rejected',
    })
  }

  const bestSummary = mockBacktest({ strategy: 'bull_put_spread', params: bestParams })
  const holdout: HoldoutInfo = {
    start: '2024-09-16',
    end: '2025-01-03',
    score: Math.round((best - 0.07 + rng() * 0.05) * 1000) / 1000,
    summary: { ...bestSummary, equity_curve: [], trades: [] },
    note:
      'final ~15% of the range, reserved before the search and evaluated exactly once on best_params',
  }
  const regimes: Regimes = {
    low: { days: 168, total_return: 0.078, sharpe: 2.31, max_drawdown: -0.041 },
    mid: { days: 171, total_return: 0.054, sharpe: 1.62, max_drawdown: -0.072 },
    high: { days: 165, total_return: -0.012, sharpe: 0.34, max_drawdown: -0.138 },
  }

  return {
    best: { ...bestSummary, equity_curve: [], trades: [] },
    best_params: bestParams,
    objective: 'sortino',
    folds: {
      in_sample: ['2023-01-03', '2024-03-29'],
      out_of_sample: ['2024-04-01', '2024-09-13'],
      holdout: ['2024-09-16', '2025-01-03'],
    },
    history,
    holdout,
    regimes,
    simulated: true,
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
/*  Paper trading — stateful mock book so marks drift like a live feed   */
/* --------------------------------------------------------------------- */
const STARTING_CASH = 100000

/** Live during regular US market hours (Mon–Fri 9:30–16:00 ET), else EOD. */
function marketIsOpen(now = new Date()): boolean {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    weekday: 'short',
    hour: 'numeric',
    minute: 'numeric',
    hour12: false,
  }).formatToParts(now)
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? ''
  const wd = get('weekday')
  if (wd === 'Sat' || wd === 'Sun') return false
  const mins = parseInt(get('hour'), 10) * 60 + parseInt(get('minute'), 10)
  return mins >= 9 * 60 + 30 && mins < 16 * 60
}

interface MockBookState {
  positions: PaperPosition[]
  realized: number
  history: PaperHistoryPoint[]
}

function seedPositions(): PaperPosition[] {
  // cost_basis / current_value follow broker semantics: negative = credit
  // (cash received at open / paid to close); upnl = current_value - cost_basis.
  return [
    {
      ticker: 'NVDA', spec_name: 'bull_put_spread', opened: '2026-06-18T14:31:00+00:00',
      legs: [
        { action: 'SELL', kind: 'P', strike: 1160, expiry: '2026-07-17', quantity: 4, price: 14.2 },
        { action: 'BUY', kind: 'P', strike: 1140, expiry: '2026-07-17', quantity: 4, price: 12.05 },
      ],
      cost_basis: -860, current_value: -524, upnl: 336, status: 'OPEN',
    },
    {
      ticker: 'SPY', spec_name: 'iron_condor', opened: '2026-06-23T13:45:00+00:00',
      legs: [
        { action: 'SELL', kind: 'P', strike: 585, expiry: '2026-07-10', quantity: 6, price: 2.4 },
        { action: 'BUY', kind: 'P', strike: 575, expiry: '2026-07-10', quantity: 6, price: 1.62 },
        { action: 'SELL', kind: 'C', strike: 640, expiry: '2026-07-10', quantity: 6, price: 1.9 },
        { action: 'BUY', kind: 'C', strike: 650, expiry: '2026-07-10', quantity: 6, price: 1.0 },
      ],
      cost_basis: -1008, current_value: -843, upnl: 165, status: 'OPEN',
    },
    {
      ticker: 'AAPL', spec_name: 'calendar_call', opened: '2026-06-12T15:02:00+00:00',
      legs: [
        { action: 'BUY', kind: 'C', strike: 215, expiry: '2026-08-21', quantity: 3, price: 6.4 },
        { action: 'SELL', kind: 'C', strike: 215, expiry: '2026-07-17', quantity: 3, price: 3.35 },
      ],
      cost_basis: 915, current_value: 1088, upnl: 173, status: 'OPEN',
    },
    {
      ticker: 'TSLA', spec_name: 'long_put', opened: '2026-06-25T17:20:00+00:00',
      legs: [{ action: 'BUY', kind: 'P', strike: 240, expiry: '2026-07-24', quantity: 2, price: 3.9 }],
      cost_basis: 780, current_value: 642, upnl: -138, status: 'OPEN',
    },
    {
      ticker: 'QQQ', spec_name: 'short_straddle', opened: '2026-06-20T14:05:00+00:00',
      legs: [
        { action: 'SELL', kind: 'C', strike: 548, expiry: '2026-07-17', quantity: 2, price: 8.4 },
        { action: 'SELL', kind: 'P', strike: 548, expiry: '2026-07-17', quantity: 2, price: 7.9 },
      ],
      cost_basis: -3260, current_value: -3542, upnl: -282, status: 'OPEN',
    },
  ]
}

function seedHistory(state: MockBookState): PaperHistoryPoint[] {
  // ~60 business days of EOD verification marks climbing from starting cash
  // to the book's current total, with realistic wobble.
  const rng = mulberry32(20260701)
  const pts: PaperHistoryPoint[] = []
  const now = Date.now()
  const target = bookTotal(state)
  const nDays = 60
  let eq = STARTING_CASH
  for (let i = nDays; i >= 1; i--) {
    const d = new Date(now - i * 86400000)
    const dow = d.getUTCDay()
    if (dow === 0 || dow === 6) continue
    const k = 1 - i / nDays
    const drift = (target - STARTING_CASH) / (nDays * 0.78)
    eq += drift + (rng() - 0.48) * 260
    const upnl = (rng() - 0.4) * 500 * (0.4 + k)
    d.setUTCHours(21, 0, 0, 0) // ~16:00 ET close mark
    pts.push({
      ts: d.toISOString(),
      equity: Math.round(eq * 100) / 100,
      cash: Math.round((eq - upnl + 700) * 100) / 100,
      upnl: Math.round(upnl * 100) / 100,
      live: false,
    })
  }
  return pts
}

function bookCash(state: MockBookState): number {
  // cash = starting − entry cash flows (debits paid / credits received) + realized
  const flows = state.positions.reduce((a, p) => a + (p.status === 'OPEN' ? p.cost_basis : 0), 0)
  return STARTING_CASH - flows + state.realized
}

function bookTotal(state: MockBookState): number {
  const openValue = state.positions.reduce(
    (a, p) => a + (p.status === 'OPEN' ? p.current_value : 0), 0)
  return bookCash(state) + openValue
}

let _book: MockBookState | null = null
function book(): MockBookState {
  if (!_book) {
    _book = { positions: seedPositions(), realized: 2140.55, history: [] }
    _book.history = seedHistory(_book)
    appendHistoryPoint(_book, marketIsOpen())
  }
  return _book
}

function appendHistoryPoint(state: MockBookState, live: boolean) {
  const upnl = state.positions.reduce((a, p) => a + (p.status === 'OPEN' ? p.upnl : 0), 0)
  state.history.push({
    ts: new Date().toISOString(),
    equity: Math.round(bookTotal(state) * 100) / 100,
    cash: Math.round(bookCash(state) * 100) / 100,
    upnl: Math.round(upnl * 100) / 100,
    live,
  })
  if (state.history.length > 500) state.history = state.history.slice(-500)
}

function bookResponse(state: MockBookState, live: boolean): PaperBookResponse {
  // like the backend broker: ALL positions (open + closed); close is by index
  // into this same list, so the panel must keep original indices.
  const open = state.positions.filter((p) => p.status === 'OPEN')
  const upnl = open.reduce((a, p) => a + p.upnl, 0)
  const openValue = open.reduce((a, p) => a + p.current_value, 0)
  const cash = bookCash(state)
  return {
    positions: state.positions.map((p) => ({ ...p, legs: p.legs.map((l) => ({ ...l })) })),
    equity: {
      cash: Math.round(cash * 100) / 100,
      open_value: Math.round(openValue * 100) / 100,
      upnl: Math.round(upnl * 100) / 100,
      realized: Math.round(state.realized * 100) / 100,
      total: Math.round((cash + openValue) * 100) / 100,
      starting_cash: STARTING_CASH,
    },
    live,
    asof: new Date().toISOString(),
  }
}

export function mockPaperBook(): PaperBookResponse {
  return bookResponse(book(), marketIsOpen())
}

/** POST /api/paper/mark — drift marks, snapshot, return the re-marked book. */
export function mockPaperMark(): PaperBookResponse {
  const state = book()
  const live = marketIsOpen()
  for (const p of state.positions) {
    if (p.status !== 'OPEN') continue
    const scale = Math.max(60, Math.abs(p.current_value))
    const drift = (Math.random() - 0.5) * 0.012 * scale
    p.current_value = Math.round((p.current_value + drift) * 100) / 100
    p.upnl = Math.round((p.current_value - p.cost_basis) * 100) / 100
  }
  appendHistoryPoint(state, live)
  return bookResponse(state, live)
}

export function mockPaperHistory(): PaperHistoryResponse {
  return { points: book().history.map((p) => ({ ...p })) }
}

/** POST /api/paper/close — close by positions[] index; realize its uPnL. */
export function mockPaperClose(idx: number): PaperBookResponse {
  // Mirrors the backend broker: idx addresses the FULL positions list
  // (open + closed), and closing an already-closed position is a no-op.
  const state = book()
  const target = state.positions[idx]
  if (target && target.status === 'OPEN') {
    target.status = 'CLOSED'
    state.realized += target.upnl
  }
  appendHistoryPoint(state, marketIsOpen())
  return bookResponse(state, marketIsOpen())
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

/* --------------------------------------------------------------------- */
/*  AutoPilot mocks                                                       */
/* --------------------------------------------------------------------- */
import type { AutoActivityEvent, AutoStatus, PromotedConfig } from './types'

let _autoEnabled = false

const AUTO_PROMOTED: PromotedConfig[] = [
  {
    id: 'bull_put_spread@mock',
    strategy: 'bull_put_spread',
    tickers: ['NVDA', 'MSFT', 'AAPL'],
    params: { short_delta: 0.28, dte_target: 30, profit_target: 0.55 },
    holdout_score: 1.12,
    holdout_return: 0.031,
    promoted_at: new Date(Date.now() - 3600e3).toISOString(),
    realized_pnl: 412.5,
    closed_trades: 3,
    consecutive_losses: 0,
    active: true,
  },
  {
    id: 'iron_condor@mock',
    strategy: 'iron_condor',
    tickers: ['SPY', 'QQQ'],
    params: { short_delta: 0.16, dte_target: 21 },
    holdout_score: 0.74,
    holdout_return: 0.012,
    promoted_at: new Date(Date.now() - 7200e3).toISOString(),
    realized_pnl: -86.2,
    closed_trades: 2,
    consecutive_losses: 1,
    active: true,
  },
]

export function mockAutoStatus(): AutoStatus {
  return {
    enabled: _autoEnabled,
    activated_at: _autoEnabled ? new Date(Date.now() - 1800e3).toISOString() : null,
    last_trade_cycle: _autoEnabled ? new Date(Date.now() - 90e3).toISOString() : null,
    last_research: new Date(Date.now() - 5400e3).toISOString(),
    breaker: { tripped: false, reason: null, at: null },
    promoted: _autoEnabled ? AUTO_PROMOTED : [],
    managed_positions: _autoEnabled ? 2 : 0,
    config: { trade_interval_min: 5, daily_loss_limit_frac: 0.03 },
  }
}

export function mockAutoToggle(on: boolean): AutoStatus {
  _autoEnabled = on
  return mockAutoStatus()
}

export function mockAutoActivity(): AutoActivityEvent[] {
  if (!_autoEnabled) return []
  const now = Date.now()
  return [
    { ts: new Date(now - 60e3).toISOString(), kind: 'open', detail: 'NVDA bull_put_spread x2 (risk $1,570, holdout=1.12)' },
    { ts: new Date(now - 420e3).toISOString(), kind: 'close', detail: 'SPY iron_condor -> target pnl=+84.00' },
    { ts: new Date(now - 3600e3).toISOString(), kind: 'promote', detail: 'bull_put_spread holdout=1.12 ret=0.031 on NVDA,MSFT,AAPL' },
    { ts: new Date(now - 5400e3).toISOString(), kind: 'research', detail: 'learning iron_condor on SPY,QQQ' },
    { ts: new Date(now - 1800e3).toISOString(), kind: 'enable', detail: 'autopilot ENGAGED (kill switch armed)' },
  ]
}

export function mockPaperGreeks() {
  const on = book().positions.some((p) => p.status === 'OPEN')
  return {
    asof: new Date().toISOString().slice(0, 10),
    totals: on
      ? { delta: -42.6, gamma: -1.8, theta: 28.4, vega: -184.2 }
      : { delta: 0, gamma: 0, theta: 0, vega: 0 },
    by_ticker: {},
    unmatched_legs: 0,
  }
}
