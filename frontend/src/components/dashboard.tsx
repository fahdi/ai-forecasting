"use client";

import { useState, useEffect } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import {
  TrendingUp,
  Activity,
  Database,
  Brain,
  Clock,
  CheckCircle,
  XCircle
} from "lucide-react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, AreaChart, Area } from "recharts";
import { apiService, RecentForecastJob } from "@/lib/api";
import { toast } from "sonner";

interface DayPoint {
  date: string;
  accuracy: number | null;
  volume: number;
}

interface DashboardState {
  recentJobs: RecentForecastJob[];
  activeModels: number;
  modelTypes: string[];
  dataPoints: number;
  totalSymbols: number;
  accuracy: number | null;
  apiStatus: "healthy" | "unhealthy" | "checking";
  loaded: boolean;
}

function buildDailySeries(jobs: RecentForecastJob[]): DayPoint[] {
  const byDay = new Map<string, { volume: number; accuracies: number[] }>();
  for (const job of jobs) {
    const day = new Date(job.created_at).toISOString().slice(0, 10);
    const bucket = byDay.get(day) ?? { volume: 0, accuracies: [] };
    bucket.volume += 1;
    if (job.status === "completed" && job.mape !== null) {
      bucket.accuracies.push(Math.max(0, 100 - job.mape));
    }
    byDay.set(day, bucket);
  }
  return [...byDay.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([date, bucket]) => ({
      date,
      volume: bucket.volume,
      accuracy: bucket.accuracies.length
        ? bucket.accuracies.reduce((s, v) => s + v, 0) / bucket.accuracies.length
        : null,
    }));
}

export function Dashboard({ onNavigate }: { onNavigate?: (tab: string) => void }) {
  const [state, setState] = useState<DashboardState>({
    recentJobs: [],
    activeModels: 0,
    modelTypes: [],
    dataPoints: 0,
    totalSymbols: 0,
    accuracy: null,
    apiStatus: "checking",
    loaded: false,
  });

  useEffect(() => {
    const load = async () => {
      const [health, dataStats, models, performances, recent] = await Promise.allSettled([
        apiService.getHealth(),
        apiService.getDataStats(),
        apiService.getModels(),
        apiService.getModelPerformance(),
        apiService.getRecentForecasts(100),
      ]);

      if (health.status === "rejected") {
        toast.error("API connection failed. Check if the backend is running.");
      }

      const accuracies =
        performances.status === "fulfilled"
          ? performances.value
              .map((p) => p.directional_accuracy)
              .filter((v): v is number => typeof v === "number")
          : [];

      setState({
        apiStatus: health.status === "fulfilled" ? "healthy" : "unhealthy",
        dataPoints: dataStats.status === "fulfilled" ? dataStats.value.total_data_points : 0,
        totalSymbols: dataStats.status === "fulfilled" ? dataStats.value.total_symbols : 0,
        activeModels: models.status === "fulfilled" ? models.value.length : 0,
        modelTypes:
          models.status === "fulfilled"
            ? [...new Set(models.value.map((m) => m.model_type))]
            : [],
        accuracy: accuracies.length
          ? (accuracies.reduce((s, v) => s + v, 0) / accuracies.length) * 100
          : null,
        recentJobs: recent.status === "fulfilled" ? recent.value : [],
        loaded: true,
      });
    };

    load();
  }, []);

  const series = buildDailySeries(state.recentJobs);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Dashboard</h1>
          <p className="text-muted-foreground">AI Forecasting System Overview</p>
        </div>
        <div className="flex items-center space-x-2">
          <div className="flex items-center space-x-2">
            {state.apiStatus === "healthy" ? (
              <CheckCircle className="h-4 w-4 text-green-500" />
            ) : state.apiStatus === "unhealthy" ? (
              <XCircle className="h-4 w-4 text-red-500" />
            ) : (
              <Clock className="h-4 w-4 text-yellow-500" />
            )}
            <span className="text-sm">
              API: {state.apiStatus === "healthy" ? "Connected" : state.apiStatus === "unhealthy" ? "Disconnected" : "Checking..."}
            </span>
          </div>
          <Button onClick={() => onNavigate?.("forecasts")}>
            <Activity className="mr-2 h-4 w-4" />
            Generate Forecast
          </Button>
        </div>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Forecast Jobs</CardTitle>
            <TrendingUp className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{state.recentJobs.length.toLocaleString()}</div>
            <p className="text-xs text-muted-foreground">
              {state.recentJobs.filter((j) => j.status === "completed").length} completed recently
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Trained Models</CardTitle>
            <Brain className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{state.activeModels}</div>
            <p className="text-xs text-muted-foreground">
              {state.modelTypes.length ? state.modelTypes.join(", ") : "none trained yet"}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Data Points</CardTitle>
            <Database className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{state.dataPoints.toLocaleString()}</div>
            <p className="text-xs text-muted-foreground">
              across {state.totalSymbols} cached symbols
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Directional Accuracy</CardTitle>
            <Activity className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            {state.accuracy !== null ? (
              <>
                <div className="text-2xl font-bold">{state.accuracy.toFixed(1)}%</div>
                <Progress value={state.accuracy} className="mt-2" />
              </>
            ) : (
              <div className="text-sm text-muted-foreground">No trained models yet</div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle>Performance Trend</CardTitle>
            <CardDescription>Daily avg forecast accuracy (100 - MAPE)</CardDescription>
          </CardHeader>
          <CardContent>
            {series.some((p) => p.accuracy !== null) ? (
              <ResponsiveContainer width="100%" height={300}>
                <AreaChart data={series}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="date" />
                  <YAxis />
                  <Tooltip />
                  <Area type="monotone" dataKey="accuracy" stroke="#8884d8" fill="#8884d8" fillOpacity={0.3} connectNulls />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-[300px] flex items-center justify-center text-sm text-muted-foreground">
                {state.loaded ? "No completed forecasts yet. Run one from the Forecasts tab" : "Loading..."}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Forecast Volume</CardTitle>
            <CardDescription>Forecast jobs per day</CardDescription>
          </CardHeader>
          <CardContent>
            {series.length ? (
              <ResponsiveContainer width="100%" height={300}>
                <LineChart data={series}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="date" />
                  <YAxis allowDecimals={false} />
                  <Tooltip />
                  <Line type="monotone" dataKey="volume" stroke="#82ca9d" strokeWidth={2} />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-[300px] flex items-center justify-center text-sm text-muted-foreground">
                {state.loaded ? "No forecast jobs yet" : "Loading..."}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Recent Forecasts */}
      <Card>
        <CardHeader>
          <CardTitle>Recent Forecasts</CardTitle>
          <CardDescription>Latest forecast jobs and their results</CardDescription>
        </CardHeader>
        <CardContent>
          {state.recentJobs.length ? (
            <div className="space-y-4">
              {state.recentJobs.slice(0, 8).map((job) => (
                <div key={job.job_id} className="flex items-center justify-between p-4 border rounded-lg">
                  <div className="flex items-center space-x-4">
                    <div>
                      <div className="font-semibold">{job.symbol}</div>
                      <div className="text-sm text-muted-foreground">
                        {job.status === "completed" && job.last_prediction !== null
                          ? `$${job.last_prediction.toFixed(2)} in ${job.forecast_horizon}d`
                          : job.status === "failed"
                            ? job.error_message ?? "failed"
                            : `${job.status}...`}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center space-x-2">
                    <span className="text-xs text-muted-foreground">
                      {new Date(job.created_at).toLocaleString()}
                    </span>
                    <Badge variant={job.status === "completed" ? "default" : job.status === "failed" ? "destructive" : "secondary"}>
                      {job.status}
                    </Badge>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-sm text-muted-foreground">
              {state.loaded ? "No forecasts yet. Generate one from the Forecasts tab." : "Loading..."}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
