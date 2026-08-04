"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Plus, TrendingUp, Clock, CheckCircle, XCircle, Loader2 } from "lucide-react";
import { apiService, ForecastRequest, RecentForecastJob } from "@/lib/api";
import { toast } from "sonner";

interface Forecast {
  id: string;
  symbol: string;
  modelType: string;
  horizon: number;
  status: "pending" | "running" | "completed" | "failed";
  prediction: number | null;
  confidence: number | null;
  error: string | null;
  createdAt: string;
}

const POLL_INTERVAL_MS = 3000;
const POLL_TIMEOUT_MS = 3 * 60 * 1000;

function jobToRow(job: RecentForecastJob & { confidence?: number | null }): Forecast {
  return {
    id: job.job_id,
    symbol: job.symbol,
    modelType: job.model_type,
    horizon: job.forecast_horizon,
    status: (job.status as Forecast["status"]) ?? "pending",
    prediction: job.last_prediction,
    confidence: job.confidence ?? null,
    error: job.error_message,
    createdAt: job.created_at,
  };
}

export function Forecasts() {
  const [forecasts, setForecasts] = useState<Forecast[]>([]);
  const [loading, setLoading] = useState(false);
  const [newForecast, setNewForecast] = useState({
    symbol: "",
    modelType: "ensemble",
    horizon: 7
  });
  const pollTimers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  const patchRow = useCallback((id: string, patch: Partial<Forecast>) => {
    setForecasts(prev => prev.map(row => (row.id === id ? { ...row, ...patch } : row)));
  }, []);

  const pollJob = useCallback((jobId: string, startedAt: number) => {
    const tick = async () => {
      try {
        const status = await apiService.getForecastStatus(jobId);
        if (status.status === "completed") {
          const result = await apiService.getForecastResults(jobId);
          const predictions = result.predictions ?? [];
          const last = predictions.length ? predictions[predictions.length - 1].predicted_price : null;
          const confidence = (result.metadata as { confidence?: number })?.confidence ?? null;
          patchRow(jobId, { status: "completed", prediction: last, confidence });
          toast.success("Forecast completed!");
          return;
        }
        if (status.status === "failed") {
          const message = (status as { error_message?: string }).error_message ?? "Forecast failed";
          patchRow(jobId, { status: "failed", error: message });
          toast.error(message);
          return;
        }
        patchRow(jobId, { status: status.status as Forecast["status"] });
        if (Date.now() - startedAt < POLL_TIMEOUT_MS) {
          pollTimers.current.set(jobId, setTimeout(tick, POLL_INTERVAL_MS));
        } else {
          patchRow(jobId, { status: "failed", error: "Timed out waiting for result" });
        }
      } catch {
        if (Date.now() - startedAt < POLL_TIMEOUT_MS) {
          pollTimers.current.set(jobId, setTimeout(tick, POLL_INTERVAL_MS));
        }
      }
    };
    pollTimers.current.set(jobId, setTimeout(tick, POLL_INTERVAL_MS));
  }, [patchRow]);

  useEffect(() => {
    const timers = pollTimers.current;
    const load = async () => {
      try {
        const jobs = await apiService.getRecentForecasts(50);
        setForecasts(jobs.map(jobToRow));
        // Resume polling for jobs still in flight (e.g. after a page reload)
        jobs.filter(j => j.status === "pending" || j.status === "running")
            .forEach(j => pollJob(j.job_id, Date.now()));
      } catch {
        toast.error("Could not load recent forecasts");
      }
    };
    load();
    return () => {
      timers.forEach(t => clearTimeout(t));
      timers.clear();
    };
  }, [pollJob]);

  const getStatusIcon = (status: string) => {
    switch (status) {
      case "completed":
        return <CheckCircle className="h-4 w-4 text-green-500" />;
      case "running":
        return <Loader2 className="h-4 w-4 text-yellow-500 animate-spin" />;
      case "failed":
        return <XCircle className="h-4 w-4 text-red-500" />;
      default:
        return <Clock className="h-4 w-4 text-gray-500" />;
    }
  };

  const getStatusBadge = (status: string) => {
    const variants = {
      completed: "default",
      running: "secondary",
      failed: "destructive",
      pending: "outline"
    } as const;

    return <Badge variant={variants[status as keyof typeof variants]}>{status}</Badge>;
  };

  const handleCreateForecast = async () => {
    if (!newForecast.symbol) {
      toast.error("Please enter a symbol (e.g. AAPL, XAU, BTC)");
      return;
    }

    setLoading(true);
    try {
      const request: ForecastRequest = {
        symbol: newForecast.symbol.toUpperCase(),
        forecast_horizon: newForecast.horizon,
        model_type: newForecast.modelType,
        include_confidence: true,
        include_features: false
      };

      const response = await apiService.createForecast(request);
      
      // Add the new forecast to the list
      const newForecastItem: Forecast = {
        id: response.job_id,
        symbol: newForecast.symbol.toUpperCase(),
        modelType: newForecast.modelType,
        horizon: newForecast.horizon,
        status: "pending",
        prediction: null,
        confidence: null,
        error: null,
        createdAt: new Date().toISOString()
      };

      setForecasts(prev => [newForecastItem, ...prev]);
      setNewForecast({ symbol: "", modelType: "ensemble", horizon: 7 });
      toast.success("Forecast started. This can take a minute.");
      pollJob(response.job_id, Date.now());
    } catch (error) {
      console.error("Error creating forecast:", error);
      toast.error(error instanceof Error && error.message ? error.message : "Failed to create forecast. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Forecasts</h1>
          <p className="text-muted-foreground">Generate and manage stock predictions</p>
        </div>
      </div>

      {/* New Forecast Form */}
      <Card>
        <CardHeader>
          <CardTitle>Generate New Forecast</CardTitle>
          <CardDescription>Create a new stock price prediction</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="space-y-2">
              <Label htmlFor="symbol">Symbol</Label>
              <Input
                id="symbol"
                placeholder="AAPL, XAU, BTC, OIL..."
                value={newForecast.symbol}
                onChange={(e) => setNewForecast({ ...newForecast, symbol: e.target.value.toUpperCase() })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="model">Model Type</Label>
              <Select value={newForecast.modelType} onValueChange={(value) => setNewForecast({ ...newForecast, modelType: value })}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="ensemble">Ensemble</SelectItem>
                  <SelectItem value="xgboost">XGBoost</SelectItem>
                  <SelectItem value="lstm">LSTM</SelectItem>
                  <SelectItem value="lightgbm">LightGBM</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="horizon">Forecast Horizon</Label>
              <Select value={newForecast.horizon.toString()} onValueChange={(value) => setNewForecast({ ...newForecast, horizon: parseInt(value) })}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="7">7 days</SelectItem>
                  <SelectItem value="30">30 days</SelectItem>
                  <SelectItem value="90">90 days</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="mt-4">
            <Button 
              className="w-full md:w-auto" 
              onClick={handleCreateForecast}
              disabled={loading}
            >
              {loading ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Plus className="mr-2 h-4 w-4" />
              )}
              {loading ? "Creating..." : "Generate Forecast"}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Forecasts Table */}
      <Card>
        <CardHeader>
          <CardTitle>Recent Forecasts</CardTitle>
          <CardDescription>View all generated predictions</CardDescription>
        </CardHeader>
        <CardContent>
          {forecasts.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              No forecasts yet. Create your first forecast above.
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Symbol</TableHead>
                  <TableHead>Model</TableHead>
                  <TableHead>Horizon</TableHead>
                  <TableHead>Prediction</TableHead>
                  <TableHead>Confidence</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Created</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {forecasts.map((forecast) => (
                  <TableRow key={forecast.id}>
                    <TableCell className="font-medium">{forecast.symbol}</TableCell>
                    <TableCell>
                      <Badge variant="outline">{forecast.modelType}</Badge>
                    </TableCell>
                    <TableCell>{forecast.horizon} days</TableCell>
                    <TableCell>
                      {forecast.status === "failed" ? (
                        <span className="text-sm text-destructive" title={forecast.error ?? undefined}>
                          {forecast.error ?? "failed"}
                        </span>
                      ) : forecast.prediction !== null ? (
                        `$${forecast.prediction.toFixed(2)}`
                      ) : (
                        "Pending"
                      )}
                    </TableCell>
                    <TableCell>
                      {forecast.confidence !== null ? `${(forecast.confidence * 100).toFixed(0)}%` : "n/a"}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center space-x-2">
                        {getStatusIcon(forecast.status)}
                        {getStatusBadge(forecast.status)}
                      </div>
                    </TableCell>
                    <TableCell>{new Date(forecast.createdAt).toLocaleDateString()}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
} 