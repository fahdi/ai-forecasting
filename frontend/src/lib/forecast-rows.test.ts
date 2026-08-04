/**
 * Forecast table rows must show the holdout hit rate (directional accuracy
 * on held-out data), NOT the model's self-reported confidence — the latter
 * sits near 100% on smooth extrapolations and misleads users about quality.
 */
import { describe, expect, it } from "vitest";

import { jobToRow } from "./forecast-rows";
import type { RecentForecastJob } from "./api";

function job(overrides: Partial<RecentForecastJob> = {}): RecentForecastJob {
  return {
    job_id: "j1",
    symbol: "XAU",
    status: "completed",
    model_type: "ensemble",
    forecast_horizon: 7,
    created_at: "2026-08-05T10:00:00Z",
    completed_at: "2026-08-05T10:01:00Z",
    error_message: null,
    last_prediction: 4033.71,
    mape: 21.5,
    directional_accuracy: 83.3,
    evaluation_points: 6,
    confidence: 0.998,
    ...overrides,
  };
}

describe("jobToRow", () => {
  it("maps the holdout hit rate, not the self-reported confidence", () => {
    const row = jobToRow(job());
    expect(row.hitRate).toBe(83.3);
    expect(row.sampleSize).toBe(6);
    expect("confidence" in row).toBe(false);
  });

  it("failed jobs carry the error and no metrics", () => {
    const row = jobToRow(job({
      status: "failed",
      last_prediction: null,
      directional_accuracy: null,
      error_message: "No historical data available",
    }));
    expect(row.status).toBe("failed");
    expect(row.hitRate).toBeNull();
    expect(row.error).toBe("No historical data available");
  });

  it("pending jobs have no prediction or hit rate yet", () => {
    const row = jobToRow(job({
      status: "pending",
      last_prediction: null,
      directional_accuracy: null,
      completed_at: null,
    }));
    expect(row.prediction).toBeNull();
    expect(row.hitRate).toBeNull();
  });
});
