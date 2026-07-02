// Data layer. Talks to the ATLAS backend at VITE_API_URL (default :8000).
// Polling/status calls gracefully fall back to MOCK data when the backend is
// unreachable, so `npm run dev` is demoable standalone. User-initiated
// compute (backtest, learn) is STRICT: real result or a visible error —
// never mock numbers wearing a real run's clothes.

import * as mock from './mock'
import type {
  AutoActivityEvent,
  AutoStatus,
  BacktestResponse,
  BrokerStatus,
  HealthResponse,
  HoldoutInfo,
  LearnIteration,
  LearnResponse,
  PaperBookResponse,
  PaperGreeksResponse,
  PaperHistoryResponse,
  Quote,
  Regimes,
  ResearchStatus,
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
// Ceiling for user-initiated compute (backtest). Matches nginx's
// proxy_read_timeout — a run that hasn't answered in an hour is dead.
const TIMEOUT_COMPUTE = 3_600_000

async function request<T>(path: string, init?: RequestInit, timeoutMs = TIMEOUT_FAST): Promise<T> {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeoutMs)
  try {
    const res = await fetch(`${BASE}${path}`, {
      ...init,
      signal: ctrl.signal,
      headers: { 'content-type': 'application/json', ...(init?.headers ?? {}) },
    })
    if (!res.ok) {
      let detail = ''
      try {
        detail = (await res.text()).slice(0, 200)
      } catch {
        /* body unreadable — status alone will have to do */
      }
      throw new Error(`HTTP ${res.status}${detail ? ` — ${detail}` : ''}`)
    }
    const data = (await res.json()) as T
    setSource(true)
    return data
  } finally {
    clearTimeout(timer)
  }
}

/** Human-readable reason for a failed strict (no-mock-fallback) call. */
export function describeRunError(e: unknown): string {
  if (e instanceof DOMException && e.name === 'AbortError') {
    return 'timed out after 60 min — the backend is likely saturated (a research batch may be running); retry with fewer tickers or a shorter range'
  }
  if (e instanceof TypeError) return 'could not reach the backend — is the stack running?'
  return e instanceof Error ? e.message : String(e)
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

// STRICT: a user-initiated backtest must never silently degrade to mock —
// it either returns the real result or throws (the panel shows the error).
export function postBacktest(body: BacktestRequest): Promise<BacktestResponse> {
  return request<BacktestResponse>(
    '/api/backtest',
    { method: 'POST', body: JSON.stringify(body) },
    TIMEOUT_COMPUTE,
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

// STRICT for the same reason as postBacktest. Prefer streamLearn() in UI —
// it shows live per-iteration progress instead of a long silent wait.
export function postLearn(body: LearnRequest): Promise<LearnResponse> {
  return request<LearnResponse>(
    '/api/learn',
    { method: 'POST', body: JSON.stringify(body) },
    TIMEOUT_COMPUTE,
  )
}

export interface LearnDone {
  best: Record<string, unknown> | null // best-params OOS backtest summary
  best_params: Record<string, number>
  holdout: HoldoutInfo | null
  regimes: Regimes | null
}

export interface LearnStreamHandlers {
  onIter: (it: LearnIteration) => void
  onDone: (r: LearnDone) => void
  onError: (msg: string) => void
}

/**
 * GET /api/learn/stream — server-sent events, one per learning iteration as
 * it completes, so a multi-minute real-data run shows live progress instead
 * of a frozen button. Never falls back to mock. Returns a cancel function.
 */
export function streamLearn(req: LearnRequest, h: LearnStreamHandlers): () => void {
  const qs = new URLSearchParams({
    strategy: req.strategy,
    tickers: req.tickers.join(','),
    start: req.start,
    end: req.end,
    n_iter: String(req.n_iter),
  })
  if (req.objective) qs.set('objective', req.objective)
  const es = new EventSource(`${BASE}/api/learn/stream?${qs.toString()}`)
  let finished = false
  const finish = () => {
    finished = true
    es.close()
  }
  es.onmessage = (ev) => {
    let data: LearnIteration & { error?: string }
    try {
      data = JSON.parse(ev.data)
    } catch {
      return
    }
    if (data.error) {
      finish()
      h.onError(String(data.error))
      return
    }
    setSource(true)
    h.onIter(data)
  }
  es.addEventListener('done', (ev) => {
    finish()
    try {
      h.onDone(JSON.parse((ev as MessageEvent).data) as LearnDone)
    } catch {
      h.onError('run finished but the final result could not be parsed')
    }
  })
  es.onerror = () => {
    if (finished) return
    finish()
    h.onError('connection to the backend lost — the run may still be going; check the autopilot feed or retry')
  }
  return finish
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

/** POST /api/paper/open — send a suggested strategy to the paper book. */
export function openPaper(body: {
  ticker: string
  strategy: string
  date: string
  qty?: number
}): Promise<{ ok: boolean }> {
  return withFallback(
    () =>
      request<unknown>('/api/paper/open', {
        method: 'POST',
        body: JSON.stringify({ qty: 1, ...body }),
      }).then(() => ({ ok: true })),
    () => {
      mock.mockPaperMark() // nudge the demo book so something visibly changes
      return { ok: true }
    },
  )
}

/** GET /api/paper/greeks — aggregate greeks of the open paper book. */
export function getPaperGreeks(): Promise<PaperGreeksResponse> {
  return withFallback(
    () => request<PaperGreeksResponse>('/api/paper/greeks'),
    () => mock.mockPaperGreeks(),
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

/** GET /api/auto/research — live engine telemetry. The offline fallback is an
 *  honest "idle" (never a fake crunching animation). */
export function getResearchStatus(): Promise<ResearchStatus> {
  return withFallback(
    () => request<ResearchStatus>('/api/auto/research'),
    () => ({
      enabled: false,
      current: { active: false },
      last: null,
      batches_done: 0,
      sweep_total: 0,
      sweep_done: 0,
      sweep_number: 0,
    }),
  )
}

/* ------------------------------ live ---------------------------------- */

export interface TapeResponse {
  quotes: Quote[]
  live: boolean
  asof: string
  simulated?: boolean
}

/** GET /api/live/tape — one bulk AV call when live, EOD closes otherwise. */
export function getTape(): Promise<TapeResponse> {
  return withFallback(
    () => request<TapeResponse>('/api/live/tape', undefined, 15000),
    () => ({
      quotes: mock.mockTape(),
      live: false,
      asof: new Date().toISOString(),
      simulated: true,
    }),
  )
}


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
