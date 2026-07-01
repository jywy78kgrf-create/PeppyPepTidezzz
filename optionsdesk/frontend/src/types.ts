// Shared domain types mirroring the ATLAS backend contracts (Phase-2).
// Response shapes are pinned by PHASE2_CONTRACT.md — the mock layer in
// src/mock.ts must always match these exactly.

export interface HealthResponse {
  status: string
  version?: string
  asof?: string
  data_ready?: boolean
  tickers?: string[]
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

/* --------------------------------------------------------------------- */
/*  Backtest                                                              */
/* --------------------------------------------------------------------- */
export interface EquityPoint {
  asof: string
  equity: number
  cash?: number
  open_positions?: number
}

/** How trades actually ended. The backend may emit any subset of these. */
export const CLOSED_REASONS = [
  'target',
  'stop',
  'close_dte',
  'expiry',
  'assigned',
  'delisted',
  'end',
] as const
export type ClosedReason = (typeof CLOSED_REASONS)[number]
export type ClosedReasons = Partial<Record<ClosedReason, number>> & Record<string, number>

export interface TradeSummary {
  spec_name: string
  ticker: string
  opened: string
  closed: string | null
  pnl: number | null
  gross_pnl?: number | null
  costs?: number | null
  closed_reason: string
}

/**
 * POST /api/backtest — BacktestResult.to_summary() + sampled curve/trades.
 * `config` is the strategy/config NAME (a string, not an object).
 * Numeric metrics are nullable: the API nulls non-finite floats.
 */
export interface BacktestResponse {
  config: string
  params: Record<string, unknown>
  start: string | null
  end: string | null
  n_trades: number
  cagr: number | null
  total_return: number | null
  sharpe: number | null
  sortino: number | null
  max_drawdown: number | null
  win_rate: number | null
  profit_factor: number | null
  avg_trade: number | null
  total_costs: number | null
  total_holding_cost: number | null
  universe_size: number
  delisted_included: number
  survivorship_note: string
  closed_reasons: ClosedReasons
  equity_curve: EquityPoint[]
  trades: TradeSummary[]
}

/* --------------------------------------------------------------------- */
/*  Learning loop                                                         */
/* --------------------------------------------------------------------- */
export interface LearnIteration {
  iteration: number
  oos_score: number
  accepted: boolean
  params: Record<string, number>
  strategy?: string
  is_score?: number
  metrics?: Record<string, unknown>
  note?: string
}

/** Final untouched slice of the range, scored exactly once on best_params. */
export interface HoldoutInfo {
  start: string | null
  end: string | null
  score: number | null
  summary: Partial<BacktestResponse> | null
  note: string
}

export interface RegimeStats {
  days: number
  total_return: number | null
  sharpe: number | null
  max_drawdown: number | null
}

export interface Regimes {
  low: RegimeStats
  mid: RegimeStats
  high: RegimeStats
}

export interface LearnResponse {
  best: Partial<BacktestResponse> // best-params OOS backtest summary
  best_params: Record<string, number>
  objective: string
  folds?: {
    in_sample?: [string, string]
    out_of_sample?: [string, string]
    holdout?: [string | null, string | null] | null
  } | null
  history: LearnIteration[]
  holdout: HoldoutInfo | null
  regimes: Regimes | null
}

/* --------------------------------------------------------------------- */
/*  Paper trading                                                         */
/* --------------------------------------------------------------------- */
export interface PaperLeg {
  action: 'BUY' | 'SELL'
  kind: 'C' | 'P'
  strike: number
  expiry: string // YYYY-MM-DD
  quantity: number
  price?: number
}

export interface PaperPosition {
  ticker: string
  spec_name: string
  opened: string // ISO datetime
  legs: PaperLeg[]
  cost_basis: number
  current_value: number
  upnl: number
  status: string // "OPEN" | "CLOSED"
}

export interface PaperEquity {
  cash: number
  upnl: number
  total: number
  realized?: number
  open_value?: number
  starting_cash?: number
}

/** GET /api/paper/positions and POST /api/paper/mark share this shape. */
export interface PaperBookResponse {
  positions: PaperPosition[]
  equity: PaperEquity
  live: boolean
  asof: string // ISO-8601 timestamp of this marking
}

export interface PaperHistoryPoint {
  ts: string
  equity: number
  cash: number
  upnl: number
  live: boolean
}

/** GET /api/paper/history */
export interface PaperHistoryResponse {
  points: PaperHistoryPoint[]
}

/** GET /api/paper/greeks — book-level exposure. Delta is share-equivalent;
 *  theta $/day; vega $ per vol point. */
export interface PaperGreeksResponse {
  asof: string
  totals: { delta: number; gamma: number; theta: number; vega: number }
  by_ticker: Record<string, { delta: number; gamma: number; theta: number; vega: number }>
  unmatched_legs: number
}

/* --------------------------------------------------------------------- */
/*  AutoPilot                                                             */
/* --------------------------------------------------------------------- */
export interface PromotedConfig {
  id: string
  strategy: string
  tickers: string[]
  params: Record<string, number>
  holdout_score: number
  holdout_return: number | null
  promoted_at: string
  realized_pnl: number
  closed_trades: number
  consecutive_losses: number
  active: boolean
}

export interface AutoStatus {
  enabled: boolean
  activated_at: string | null
  last_trade_cycle: string | null
  last_research: string | null
  breaker: { tripped: boolean; reason: string | null; at: string | null }
  promoted: PromotedConfig[]
  managed_positions: number
  config: Record<string, unknown>
}

export interface AutoActivityEvent {
  ts: string
  kind: string // enable | disable | research | promote | open | close | demote | breaker | error
  detail: string
}

/* --------------------------------------------------------------------- */
/*  Misc                                                                  */
/* --------------------------------------------------------------------- */
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

export const STRATEGY_NAMES = [
  'bull_put_spread',
  'bear_call_spread',
  'iron_condor',
  'long_call',
  'long_put',
  'covered_call',
  'calendar_call',
  'short_straddle',
  'long_strangle',
] as const

export const SIZING_METHODS = ['fixed', 'fixed_fraction', 'kelly', 'risk_parity'] as const
export type SizingMethod = (typeof SIZING_METHODS)[number]
