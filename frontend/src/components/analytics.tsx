"use client";

import { useState, useEffect } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { apiService, DetailedHealth, ModelPerformance } from "@/lib/api";

interface Aggregates {
  accuracy: number | null;
  directional: number | null;
  rmse: number | null;
  evaluated: number;
}

function aggregate(performances: ModelPerformance[]): Aggregates {
  const mapes = performances.map((p) => p.mape).filter((v): v is number => v !== null);
  const dirs = performances
    .map((p) => p.directional_accuracy)
    .filter((v): v is number => v !== null);
  const rmses = performances.map((p) => p.rmse).filter((v): v is number => v !== null);
  const avg = (xs: number[]) => (xs.length ? xs.reduce((s, v) => s + v, 0) / xs.length : null);
  const avgMape = avg(mapes);
  return {
    accuracy: avgMape !== null ? Math.max(0, 100 - avgMape) : null,
    directional: avg(dirs),
    rmse: avg(rmses),
    evaluated: performances.length,
  };
}

function statusColor(status: string): string {
  if (status === "healthy" || status === "available") return "text-green-600";
  if (status === "degraded" || status === "not_configured") return "text-orange-600";
  return "text-red-600";
}

export function Analytics() {
  const [aggregates, setAggregates] = useState<Aggregates | null>(null);
  const [health, setHealth] = useState<DetailedHealth | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    const load = async () => {
      const [perfRes, healthRes] = await Promise.allSettled([
        apiService.getModelPerformance(),
        apiService.getDetailedHealth(),
      ]);
      if (perfRes.status === "fulfilled") setAggregates(aggregate(perfRes.value));
      if (healthRes.status === "fulfilled") setHealth(healthRes.value);
      setLoaded(true);
    };
    load();
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Analytics</h1>
        <p className="text-muted-foreground">Model performance and system status, live from the API</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle>Performance Metrics</CardTitle>
            <CardDescription>
              {aggregates?.evaluated
                ? `Averaged over ${aggregates.evaluated} evaluated model${aggregates.evaluated === 1 ? "" : "s"}`
                : "Model accuracy and predictions"}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {aggregates && aggregates.evaluated > 0 ? (
              <div className="space-y-4">
                <div className="flex justify-between">
                  <span>Avg Accuracy (100 - MAPE)</span>
                  <span className="font-bold text-green-600">
                    {aggregates.accuracy !== null ? `${aggregates.accuracy.toFixed(1)}%` : "n/a"}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span>Directional Accuracy</span>
                  <span className="font-bold text-blue-600">
                    {aggregates.directional !== null ? `${aggregates.directional.toFixed(1)}%` : "n/a"}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span>RMSE</span>
                  <span className="font-bold text-orange-600">
                    {aggregates.rmse !== null ? aggregates.rmse.toFixed(2) : "n/a"}
                  </span>
                </div>
              </div>
            ) : (
              <div className="text-sm text-muted-foreground">
                {loaded
                  ? "No evaluated models yet. Train a model or run a forecast first."
                  : "Loading..."}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>System Health</CardTitle>
            <CardDescription>Component probes from /health/detailed</CardDescription>
          </CardHeader>
          <CardContent>
            {health ? (
              <div className="space-y-4">
                {Object.entries(health.components).map(([name, component]) => (
                  <div key={name} className="flex justify-between">
                    <span className="capitalize">{name.replace("_", " ")}</span>
                    <span className={`font-bold capitalize ${statusColor(component.status)}`}>
                      {component.status}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-sm text-muted-foreground">
                {loaded ? "Health probe unavailable" : "Loading..."}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
