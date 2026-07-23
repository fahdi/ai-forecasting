const SIGNAL_API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const FREQTRADE_BASE_URL = process.env.NEXT_PUBLIC_FREQTRADE_URL || 'http://localhost:8080';
const FREQTRADE_USER = process.env.NEXT_PUBLIC_FREQTRADE_USER || '';
const FREQTRADE_PASS = process.env.NEXT_PUBLIC_FREQTRADE_PASS || '';

export const UNIVERSE_PAIRS = ['BTC-USDT', 'ETH-USDT', 'SOL-USDT', 'BNB-USDT'] as const;
export type UniversePair = (typeof UNIVERSE_PAIRS)[number];

// ---------------------------------------------------------------------------
// Signal API types
// ---------------------------------------------------------------------------

export interface SignalFeature {
  name: string;
  value: number;
}

export interface TradingSignal {
  pair: string;
  direction: 'long' | 'flat';
  confidence: number;
  horizon: string;
  model_votes: Record<string, string>;
  top_features: SignalFeature[];
  model_version: string;
  generated_at: string;
  stale: boolean;
}

// ---------------------------------------------------------------------------
// Model health API types (contract per issue #14 — backend in progress)
// ---------------------------------------------------------------------------

export interface CalibrationBucket {
  bucket_low: number;
  bucket_high: number;
  predicted_mean: number;
  realized_hit_rate: number;
  count: number;
}

export interface PairModelHealth {
  pair: string;
  directional_accuracy_7d: number | null;
  directional_accuracy_30d: number | null;
  n_predictions: number;
  calibration: CalibrationBucket[];
}

export interface ModelHealthResponse {
  pairs: PairModelHealth[];
}

// ---------------------------------------------------------------------------
// Freqtrade REST API types (subset of fields the dashboard consumes)
// ---------------------------------------------------------------------------

export interface FreqtradeTrade {
  trade_id: number;
  pair: string;
  amount: number;
  open_rate: number;
  current_rate?: number;
  /** Newer Freqtrade versions: ratio, e.g. 0.0123 = +1.23% */
  profit_ratio?: number;
  /** Some versions expose percentage directly */
  profit_pct?: number;
  /** Legacy field name for current profit ratio */
  current_profit?: number;
  open_date?: string;
  stake_amount?: number;
}

export interface FreqtradeProfit {
  profit_closed_coin?: number;
  profit_closed_percent_mean?: number;
  profit_closed_percent_sum?: number;
  profit_all_coin?: number;
  profit_all_percent_mean?: number;
  trade_count?: number;
  closed_trade_count?: number;
  winning_trades?: number;
  losing_trades?: number;
  first_trade_timestamp?: number;
  latest_trade_timestamp?: number;
  best_pair?: string;
}

export interface FreqtradeBalanceCurrency {
  currency: string;
  free: number;
  balance: number;
  used: number;
  est_stake?: number;
}

export interface FreqtradeBalance {
  currencies?: FreqtradeBalanceCurrency[];
  total?: number;
  symbol?: string;
  value?: number;
  stake?: string;
}

export interface HealthStatus {
  status: string;
}

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: {
      Accept: 'application/json',
      ...init?.headers,
    },
  });

  if (!response.ok) {
    throw new Error(`Request failed (${response.status} ${response.statusText})`);
  }

  return response.json() as Promise<T>;
}

function freqtradeAuthHeaders(): Record<string, string> {
  if (!FREQTRADE_USER && !FREQTRADE_PASS) return {};
  // btoa is fine here: all trading-api consumers are client components.
  return { Authorization: `Basic ${btoa(`${FREQTRADE_USER}:${FREQTRADE_PASS}`)}` };
}

// ---------------------------------------------------------------------------
// Signal API
// ---------------------------------------------------------------------------

export async function getSignal(pair: string): Promise<TradingSignal> {
  return requestJson<TradingSignal>(`${SIGNAL_API_BASE_URL}/api/v1/signal/${pair}`);
}

export async function getModelHealth(): Promise<ModelHealthResponse> {
  return requestJson<ModelHealthResponse>(`${SIGNAL_API_BASE_URL}/api/v1/models/health`);
}

export async function pingSignalApi(): Promise<HealthStatus> {
  return requestJson<HealthStatus>(`${SIGNAL_API_BASE_URL}/health`);
}

// ---------------------------------------------------------------------------
// Freqtrade API
// ---------------------------------------------------------------------------

export async function getFreqtradeStatus(): Promise<FreqtradeTrade[]> {
  return requestJson<FreqtradeTrade[]>(`${FREQTRADE_BASE_URL}/api/v1/status`, {
    headers: freqtradeAuthHeaders(),
  });
}

export async function getFreqtradeProfit(): Promise<FreqtradeProfit> {
  return requestJson<FreqtradeProfit>(`${FREQTRADE_BASE_URL}/api/v1/profit`, {
    headers: freqtradeAuthHeaders(),
  });
}

export async function getFreqtradeBalance(): Promise<FreqtradeBalance> {
  return requestJson<FreqtradeBalance>(`${FREQTRADE_BASE_URL}/api/v1/balance`, {
    headers: freqtradeAuthHeaders(),
  });
}

export async function pingFreqtrade(): Promise<HealthStatus> {
  return requestJson<HealthStatus>(`${FREQTRADE_BASE_URL}/api/v1/ping`, {
    headers: freqtradeAuthHeaders(),
  });
}

// ---------------------------------------------------------------------------
// Normalization helpers
// ---------------------------------------------------------------------------

/** Current profit of an open trade as a percentage (e.g. 1.23 = +1.23%). */
export function tradeProfitPercent(trade: FreqtradeTrade): number {
  if (typeof trade.profit_pct === 'number') return trade.profit_pct;
  if (typeof trade.profit_ratio === 'number') return trade.profit_ratio * 100;
  if (typeof trade.current_profit === 'number') return trade.current_profit * 100;
  return 0;
}
