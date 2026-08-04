// All calls go through the Next.js server-side proxy (auth-gated by the
// middleware); the FastAPI is never exposed to the browser directly.
const API_BASE_URL = '/api/upstream/signal';

export interface ForecastRequest {
  symbol: string;
  forecast_horizon: number;
  model_type: string;
  include_confidence?: boolean;
  include_features?: boolean;
}

export interface ForecastResponse {
  job_id: string;
  status: string;
  message: string;
}

export interface ForecastResult {
  metadata: {
    symbol: string;
    forecast_horizon: number;
    model_type: string;
    created_at: string;
  };
  predictions: Array<{
    date: string;
    predicted_price: number;
    probability_up?: number;
    confidence_lower?: number;
    confidence_upper?: number;
  }>;
  performance_metrics?: {
    mape: number;
    mae: number;
    rmse: number;
    directional_accuracy: number;
  };
}

export interface ModelPerformance {
  model_type: string;
  symbol: string;
  version: string;
  mape: number | null;
  mae: number | null;
  rmse: number | null;
  directional_accuracy: number | null;
  training_date: string | null;
}

export interface ModelInfo {
  model_type: string;
  symbol: string;
  version: string;
  last_trained: string | null;
  performance?: Record<string, number> | null;
  file_size?: number | null;
}

export interface RecentForecastJob {
  job_id: string;
  symbol: string;
  status: string;
  model_type: string;
  forecast_horizon: number;
  created_at: string;
  completed_at: string | null;
  error_message: string | null;
  last_prediction: number | null;
  mape: number | null;
  confidence: number | null;
}

export interface DataSourceInfo {
  name: string;
  description?: string;
  enabled: boolean;
}

export interface DataStats {
  total_symbols: number;
  total_data_points: number;
  data_sources: Record<string, number>;
  last_updated: string | null;
  storage_size: number;
}

export interface DetailedHealth {
  status: string;
  components: Record<string, { status: string; [key: string]: unknown }>;
}

export interface AppSettings {
  version: string;
  rate_limit_per_minute: number;
  rate_limit_per_hour: number;
  default_forecast_horizon: number;
  max_forecast_horizon: number;
  min_historical_data_days: number;
  model_cache_size: number;
  yahoo_finance_enabled: boolean;
  alpha_vantage_enabled: boolean;
}

class ApiService {
  private async request<T>(endpoint: string, options?: RequestInit): Promise<T> {
    const url = `${API_BASE_URL}${endpoint}`;
    const response = await fetch(url, {
      headers: {
        'Content-Type': 'application/json',
        ...options?.headers,
      },
      ...options,
    });

    if (response.status === 401 && typeof window !== "undefined") {
      // Session expired: land on the login page instead of dead panels.
      window.location.href = "/login";
      throw new Error("Session expired");
    }
    if (!response.ok) {
      let detail = response.statusText;
      try {
        const body = await response.json();
        if (typeof body?.detail === "string") detail = body.detail;
      } catch {
        // non-JSON error body; keep statusText
      }
      throw new Error(detail);
    }

    return response.json();
  }

  // Health check
  async getHealth() {
    return this.request<{ status: string; timestamp: number; version: string; service: string }>('/health');
  }

  // Create a new forecast
  async createForecast(data: ForecastRequest): Promise<ForecastResponse> {
    return this.request<ForecastResponse>('/api/v1/forecast/single', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  // Get forecast status
  async getForecastStatus(jobId: string) {
    return this.request<{ status: string; error_message?: string | null; result?: ForecastResult }>(`/api/v1/forecast/status/${jobId}`);
  }

  // Get forecast results
  async getForecastResults(jobId: string): Promise<ForecastResult> {
    return this.request<ForecastResult>(`/api/v1/forecast/results/${jobId}`);
  }

  // Get model performance (backend wraps the list)
  async getModelPerformance(): Promise<ModelPerformance[]> {
    const body = await this.request<{ performances: ModelPerformance[]; total_count: number }>(
      '/api/v1/models/performance',
    );
    return body.performances;
  }

  // List trained models
  async getModels(): Promise<ModelInfo[]> {
    const body = await this.request<{ models: ModelInfo[]; total_count: number }>(
      '/api/v1/models/list',
    );
    return body.models;
  }

  // Recent forecast jobs (dashboard feed)
  async getRecentForecasts(limit = 20): Promise<RecentForecastJob[]> {
    const body = await this.request<{ jobs: RecentForecastJob[] }>(
      `/api/v1/forecast/recent?limit=${limit}`,
    );
    return body.jobs;
  }

  // Get available symbols (backend wraps the list)
  async getSymbols(): Promise<string[]> {
    const body = await this.request<{ symbols: string[]; total_count: number }>(
      '/api/v1/data/symbols',
    );
    return body.symbols;
  }

  // Get data sources (objects with enabled flags)
  async getDataSources(): Promise<DataSourceInfo[]> {
    const body = await this.request<{ sources: DataSourceInfo[] }>('/api/v1/data/sources');
    return body.sources;
  }

  // Data storage statistics
  async getDataStats(): Promise<DataStats> {
    return this.request<DataStats>('/api/v1/data/stats');
  }

  // Component-level health (DB, Redis, storage, ML libs)
  async getDetailedHealth(): Promise<DetailedHealth> {
    return this.request<DetailedHealth>('/api/v1/health/detailed');
  }

  // Read-only runtime configuration
  async getAppSettings(): Promise<AppSettings> {
    return this.request<AppSettings>('/api/v1/settings');
  }

  // Upload data
  async uploadData(file: File, symbol: string, source: string = 'custom') {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('symbol', symbol);
    formData.append('source', source);

    return this.request('/api/v1/data/upload', {
      method: 'POST',
      body: formData,
      headers: {}, // Let browser set Content-Type for FormData
    });
  }

  // Train model
  async trainModel(symbol: string, modelType: string, testSize: number = 0.2) {
    return this.request('/api/v1/models/train', {
      method: 'POST',
      body: JSON.stringify({
        symbol,
        model_type: modelType,
        test_size: testSize,
        retrain_existing: false,
      }),
    });
  }
}

export const apiService = new ApiService(); 