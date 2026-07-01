// Shared domain types mirroring the ATLAS backend contracts.

export interface HealthResponse {
  status: string
  version?: string
  asof?: string
}

export interface Suggestion {
  name: string
  ticker: string
  score: number
  pop: number // probability of profit, 0..1
  max_profit: number | null // null = unlimited (e.g. long call)
  max_loss: number | null // < 0 = undefined risk (naked short premium)
  rationale: string
  tags: string[]
}

export interface SuggestionsResponse {
  asof: string
  ticker: string
  suggestions: Suggestion[]
}

export interface EquityPoint {
  asof: string
  equity: number
}

export interface BacktestConfig {
  strategy: string
  params: Record<string, unknown>
  tickers: string[]
  start: string
  end: string
}

export interface BacktestResponse {
  config: BacktestConfig
  cagr: number
  sharpe: number
  sortino: number
  max_drawdown: number
  win_rate: number
  profit_factor: number
  n_trades: number
  survivorship_note: string
  equity_curve: EquityPoint[]
}

export interface LearnIteration {
  iteration: number
  oos_score: number
  accepted: boolean
  params: Record<string, number>
}

export interface LearnResponse {
  best: {
    oos_score: number
    params: Record<string, number>
    iteration: number
  }
  history: LearnIteration[]
}

export interface Position {
  id: string
  ticker: string
  strategy: string
  qty: number
  entry_price: number
  mark_price: number
  upnl: number
  upnl_pct: number
  opened_at: string
  dte: number
  delta: number
}

export interface BrokerStatus {
  name: string
  connected: boolean
  latency_ms?: number
  detail?: string
}

export interface Quote {
  ticker: string
  price: number
  change: number
  change_pct: number
}
