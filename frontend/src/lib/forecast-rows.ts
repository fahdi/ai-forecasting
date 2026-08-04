/**
 * Mapping from API forecast jobs to table rows. Quality is reported as the
 * holdout hit rate (directional accuracy on held-out data); the model's
 * self-reported confidence is deliberately NOT surfaced — it approaches
 * 100% on smooth extrapolations and misleads users about actual skill.
 */
import type { RecentForecastJob } from "./api";

export interface ForecastRow {
  id: string;
  symbol: string;
  modelType: string;
  horizon: number;
  status: "pending" | "running" | "completed" | "failed";
  prediction: number | null;
  hitRate: number | null;
  error: string | null;
  createdAt: string;
}

export function jobToRow(job: RecentForecastJob): ForecastRow {
  return {
    id: job.job_id,
    symbol: job.symbol,
    modelType: job.model_type,
    horizon: job.forecast_horizon,
    status: (job.status as ForecastRow["status"]) ?? "pending",
    prediction: job.last_prediction,
    hitRate: job.directional_accuracy ?? null,
    error: job.error_message,
    createdAt: job.created_at,
  };
}
