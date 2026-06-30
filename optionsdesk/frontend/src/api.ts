// Data layer. Talks to the ATLAS backend at VITE_API_URL (default :8000).
// Every call gracefully falls back to rich MOCK data when the backend is
// unreachable, so `npm run dev` is fully demoable standalone.

import * as mock from './mock'
import type {
  BacktestResponse,
  BrokerStatus,
  HealthResponse,
  LearnResponse,
  Position,
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

const TIMEOUT_MS = 2500

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS)
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
    () => request<SuggestionsResponse>(`/api/suggestions?${qs.toString()}`),
    () => mock.mockSuggestions(ticker, topK),
  )
}

export interface BacktestRequest {
  strategy: string
  params: Record<string, unknown>
  tickers: string[]
  start: string
  end: string
}

export function postBacktest(body: BacktestRequest): Promise<BacktestResponse> {
  return withFallback(
    () => request<BacktestResponse>('/api/backtest', { method: 'POST', body: JSON.stringify(body) }),
    () => mock.mockBacktest(),
  )
}

export interface LearnRequest {
  strategy: string
  tickers: string[]
  start: string
  end: string
  n_iter: number
}

export function postLearn(body: LearnRequest): Promise<LearnResponse> {
  return withFallback(
    () => request<LearnResponse>('/api/learn', { method: 'POST', body: JSON.stringify(body) }),
    () => mock.mockLearnHistory(body.n_iter),
  )
}

export function getPositions(): Promise<Position[]> {
  return withFallback(
    () => request<{ positions: Position[] } | Position[]>('/api/paper/positions').then((r) =>
      Array.isArray(r) ? r : r.positions,
    ),
    () => mock.mockPositions(),
  )
}

export function openPosition(body: Record<string, unknown>): Promise<Position[]> {
  return withFallback(
    () => request<Position[]>('/api/paper/open', { method: 'POST', body: JSON.stringify(body) }),
    () => mock.mockPositions(),
  )
}

export function closePosition(id: string): Promise<{ ok: boolean }> {
  return withFallback(
    () => request<{ ok: boolean }>('/api/paper/close', {
      method: 'POST',
      body: JSON.stringify({ id }),
    }),
    () => ({ ok: true }),
  )
}

export function getQuote(ticker: string): Promise<Quote> {
  return withFallback(
    () => request<Quote>(`/api/live/quote?ticker=${encodeURIComponent(ticker)}`),
    () => mock.mockQuote(ticker),
  )
}

export function getBrokerStatus(): Promise<BrokerStatus[]> {
  return withFallback(
    () => request<{ brokers: BrokerStatus[] } | BrokerStatus[]>('/api/brokers/status').then((r) =>
      Array.isArray(r) ? r : r.brokers,
    ),
    () => mock.mockBrokers(),
  )
}
