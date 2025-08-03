const API_BASE_URL = 'http://localhost:8000';

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
    value: number;
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
  accuracy: number;
  mape: number;
  mae: number;
  rmse: number;
  directional_accuracy: number;
  last_updated: string;
}

export interface DataSymbol {
  symbol: string;
  source: string;
  last_updated: string;
  data_points: number;
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

    if (!response.ok) {
      throw new Error(`API request failed: ${response.statusText}`);
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
    return this.request<{ status: string; progress?: number; result?: ForecastResult }>(`/api/v1/forecast/status/${jobId}`);
  }

  // Get forecast results
  async getForecastResults(jobId: string): Promise<ForecastResult> {
    return this.request<ForecastResult>(`/api/v1/forecast/results/${jobId}`);
  }

  // Get model performance
  async getModelPerformance(): Promise<ModelPerformance[]> {
    return this.request<ModelPerformance[]>('/api/v1/models/performance');
  }

  // Get available symbols
  async getSymbols(): Promise<DataSymbol[]> {
    return this.request<DataSymbol[]>('/api/v1/data/symbols');
  }

  // Get data sources
  async getDataSources() {
    return this.request<{ sources: string[] }>('/api/v1/data/sources');
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