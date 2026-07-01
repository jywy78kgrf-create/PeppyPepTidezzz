// Data layer. Talks to the ATLAS backend at VITE_API_URL (default :8000).
// Every call gracefully falls back to rich MOCK data when the backend is
// unreachable, so `npm run dev` is fully demoable standalone.

import * as mock from './mock'
import type {
  AutoActivityEvent,
  AutoStatus,
  BacktestResponse,
  BrokerStatus,
  HealthResponse,
  LearnResponse,
  PaperBookResponse,
  PaperHistoryResponse,
  Quote,
  SuggestionsResponse,
} from './types'

const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://localhost:8000'

// Tracks whether we are running against a live backend or the mock layer.
// Components can subscribe to surface a "SIMULATED" badge.
type SourceListener = (live: boolean) => void
const listeners = new Set<SourceListener>()
let lastLive: boolean | null = null

export function onSourceChange(fn: SourceListener) {
  listeners.add(fn)
  if (lastLive !== null) fn(lastLive)
  return () => listeners.delete(fn)
}

function setSource(live: boolean) {
  if (live !== lastLive) {
    lastLive = live
    listeners.forEach((fn) => fn(live))
  }
}

// Short timeout for polling/status endpoints; heavy compute (universe scan,
// backtest, learn) needs much longer or it aborts to mock on real data.
const TIMEOUT_FAST = 3000
const TIMEOUT_HEAVY = 90000

async function request<T>(path: string, init?: RequestInit, timeoutMs = TIMEOUT_FAST): Promise<T> {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeoutMs)
  try {
    const res = await fetch(`${BASE}${path}`, {
      ...init,
      signal: ctrl.signal,
      headers: { 'content-type': 'application/json', ...(init?.headers ?? {}) },
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = (await res.json()) as T
    setSource(true)
    return data
  } finally {
    clearTimeout(timer)
  }
}

// Wrap a live request with its mock fallback.
async function withFallback<T>(live: () => Promise<T>, fallback: () => T): Promise<T> {
  try {
    return await live()
  } catch {
    setSource(false)
    return fallback()
  }
}

/* --------------------------------------------------------------------- */
/*  Endpoints                                                             */
/* --------------------------------------------------------------------- */

export function getHealth(): Promise<HealthResponse> {
  return withFallback(() => request<HealthResponse>('/api/health'), mock.mockHealth)
}

export function getUniverse(): Promise<string[]> {
  return withFallback(
    () => request<{ tickers: string[] } | string[]>('/api/universe').then((r) =>
      Array.isArray(r) ? r : r.tickers,
    ),
    () => mock.UNIVERSE,
  )
}

export function getSuggestions(
  ticker?: string,
  date?: string,
  topK = 6,
): Promise<SuggestionsResponse> {
  const qs = new URLSearchParams()
  if (ticker && ticker !== 'ALL') qs.set('ticker', ticker)
  if (date) qs.set('date', date)
  qs.set('top_k', String(topK))
  return withFallback(
    () => request<SuggestionsResponse>(`/api/suggestions?${qs.toString()}`, undefined, TIMEOUT_HEAVY),
    () => mock.mockSuggestions(ticker, topK),
  )
}

export interface BacktestRequest {
  strategy: string
  params: Record<string, unknown>
  tickers: string[]
  start: string
  end: string
  capital?: number
  risk?: Record<string, unknown> // RiskConfig fields, e.g. { method: 'kelly' }
}

export function postBacktest(body: BacktestRequest): Promise<BacktestResponse> {
  return withFallback(
    () => request<BacktestResponse>('/api/backtest', { method: 'POST', body: JSON.stringify(body) }, TIMEOUT_HEAVY),
    () => mock.mockBacktest(body),
  )
}

export interface LearnRequest {
  strategy: string
  tickers: string[]
  start: string
  end: string
  n_iter: number
  objective?: string
}

export function postLearn(body: LearnRequest): Promise<LearnResponse> {
  return withFallback(
    () => request<LearnResponse>('/api/learn', { method: 'POST', body: JSON.stringify(body) }, TIMEOUT_HEAVY),
    () => mock.mockLearnHistory(body.n_iter),
  )
}

/* ------------------------------ paper --------------------------------- */

/** GET /api/paper/positions — the current paper book, marked. */
export function getPaperBook(): Promise<PaperBookResponse> {
  return withFallback(
    () => request<PaperBookResponse>('/api/paper/positions'),
    () => mock.mockPaperBook(),
  )
}

/** POST /api/paper/mark — re-mark the book (live when AV is configured). */
export function postPaperMark(): Promise<PaperBookResponse> {
  return withFallback(
    () => request<PaperBookResponse>('/api/paper/mark', { method: 'POST', body: '{}' }),
    () => mock.mockPaperMark(),
  )
}

/** GET /api/paper/history — the real-world verification equity curve. */
export function getPaperHistory(): Promise<PaperHistoryResponse> {
  return withFallback(
    () => request<PaperHistoryResponse>('/api/paper/history'),
    () => mock.mockPaperHistory(),
  )
}

/** POST /api/paper/close — close the position at index `idx` in the book. */
export function closePosition(idx: number): Promise<PaperBookResponse> {
  return withFallback(
    () => request<PaperBookResponse>('/api/paper/close', {
      method: 'POST',
      body: JSON.stringify({ idx }),
    }).then(() => request<PaperBookResponse>('/api/paper/positions')),
    () => mock.mockPaperClose(idx),
  )
}

/* ------------------------------ autopilot ------------------------------ */

export function getAutoStatus(): Promise<AutoStatus> {
  return withFallback(
    () => request<AutoStatus>('/api/auto/status'),
    () => mock.mockAutoStatus(),
  )
}

export function postAutoEnable(): Promise<AutoStatus> {
  return withFallback(
    () => request<AutoStatus>('/api/auto/enable', { method: 'POST', body: '{}' }),
    () => mock.mockAutoToggle(true),
  )
}

export function postAutoDisable(): Promise<AutoStatus> {
  return withFallback(
    () => request<AutoStatus>('/api/auto/disable', { method: 'POST', body: '{}' }),
    () => mock.mockAutoToggle(false),
  )
}

export function getAutoActivity(limit = 30): Promise<{ events: AutoActivityEvent[] }> {
  return withFallback(
    () => request<{ events: AutoActivityEvent[] }>(`/api/auto/activity?limit=${limit}`),
    () => ({ events: mock.mockAutoActivity() }),
  )
}

/* ------------------------------ live ---------------------------------- */

export function getQuote(ticker: string): Promise<Quote> {
  return withFallback(
    () => request<Quote>(`/api/live/quote?ticker=${encodeURIComponent(ticker)}`),
    () => mock.mockQuote(ticker),
  )
}

interface RawBrokersStatus {
  brokers?: BrokerStatus[]
  ibkr?: { connected?: boolean; detail?: string }
  alpha_vantage?: { configured?: boolean }
}

export function getBrokerStatus(): Promise<BrokerStatus[]> {
  return withFallback(
    () => request<RawBrokersStatus | BrokerStatus[]>('/api/brokers/status').then((r) => {
      if (Array.isArray(r)) return r
      if (r.brokers) return r.brokers
      const out: BrokerStatus[] = []
      if (r.alpha_vantage) {
        out.push({
          name: 'Alpha Vantage',
          connected: Boolean(r.alpha_vantage.configured),
          detail: 'market data',
        })
      }
      if (r.ibkr) {
        out.push({ name: 'IBKR', connected: Boolean(r.ibkr.connected), detail: r.ibkr.detail })
      }
      out.push({ name: 'Paper', connected: true, detail: 'simulator' })
      return out
    }),
    () => mock.mockBrokers(),
  )
}
