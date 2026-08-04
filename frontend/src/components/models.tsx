"use client";

import { useState, useEffect, useCallback } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Progress } from "@/components/ui/progress";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Brain, Play, RefreshCw, Loader2 } from "lucide-react";
import { apiService, ModelInfo, ModelPerformance } from "@/lib/api";
import { toast } from "sonner";

interface ModelRow {
  key: string;
  type: string;
  symbol: string;
  version: string;
  accuracy: number | null;
  mape: number | null;
  lastTrained: string | null;
}

export function Models() {
  const [rows, setRows] = useState<ModelRow[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [showTrainForm, setShowTrainForm] = useState(false);
  const [training, setTraining] = useState(false);
  const [trainRequest, setTrainRequest] = useState({ symbol: "", modelType: "ensemble" });

  const load = useCallback(async () => {
    const [models, performances] = await Promise.allSettled([
      apiService.getModels(),
      apiService.getModelPerformance(),
    ]);
    const perfIndex = new Map<string, ModelPerformance>();
    if (performances.status === "fulfilled") {
      for (const p of performances.value) {
        perfIndex.set(`${p.model_type}:${p.symbol}`, p);
      }
    }
    const modelRows: ModelRow[] =
      models.status === "fulfilled"
        ? models.value.map((m: ModelInfo) => {
            const perf = perfIndex.get(`${m.model_type}:${m.symbol}`);
            return {
              key: `${m.model_type}:${m.symbol}:${m.version}`,
              type: m.model_type,
              symbol: m.symbol,
              version: m.version,
              accuracy:
                perf?.directional_accuracy != null ? perf.directional_accuracy * 100 : null,
              mape: perf?.mape ?? null,
              lastTrained: m.last_trained,
            };
          })
        : [];
    setRows(modelRows);
    setLoaded(true);
    if (models.status === "rejected") toast.error("Could not load models");
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleTrain = async (symbol: string, modelType: string) => {
    if (!symbol) {
      toast.error("Enter a symbol to train on (e.g. AAPL, XAU, BTC)");
      return;
    }
    setTraining(true);
    try {
      await apiService.trainModel(symbol.toUpperCase(), modelType);
      toast.success(`Training ${modelType} on ${symbol.toUpperCase()} started. This runs in the background.`);
      setShowTrainForm(false);
      setTrainRequest({ symbol: "", modelType: "ensemble" });
      // Training takes a while; refresh the list a bit later.
      setTimeout(load, 30_000);
    } catch {
      toast.error("Failed to start training");
    } finally {
      setTraining(false);
    }
  };

  const accuracies = rows.map((r) => r.accuracy).filter((v): v is number => v !== null);
  const avgAccuracy = accuracies.length
    ? accuracies.reduce((s, v) => s + v, 0) / accuracies.length
    : null;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Models</h1>
          <p className="text-muted-foreground">Manage and monitor ML models</p>
        </div>
        <Button onClick={() => setShowTrainForm((v) => !v)}>
          <Brain className="mr-2 h-4 w-4" />
          Train New Model
        </Button>
      </div>

      {/* Train form */}
      {showTrainForm && (
        <Card>
          <CardHeader>
            <CardTitle>Train a Model</CardTitle>
            <CardDescription>Fetches history for the symbol and trains in the background</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="space-y-2">
                <Label htmlFor="train-symbol">Symbol</Label>
                <Input
                  id="train-symbol"
                  placeholder="AAPL, XAU, BTC..."
                  value={trainRequest.symbol}
                  onChange={(e) => setTrainRequest({ ...trainRequest, symbol: e.target.value.toUpperCase() })}
                />
              </div>
              <div className="space-y-2">
                <Label>Model Type</Label>
                <Select
                  value={trainRequest.modelType}
                  onValueChange={(value) => setTrainRequest({ ...trainRequest, modelType: value })}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="ensemble">Ensemble</SelectItem>
                    <SelectItem value="xgboost">XGBoost</SelectItem>
                    <SelectItem value="lightgbm">LightGBM</SelectItem>
                    <SelectItem value="catboost">CatBoost</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="flex items-end">
                <Button
                  className="w-full"
                  disabled={training}
                  onClick={() => handleTrain(trainRequest.symbol, trainRequest.modelType)}
                >
                  {training ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Play className="mr-2 h-4 w-4" />}
                  {training ? "Starting..." : "Start Training"}
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Model Stats */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Trained Models</CardTitle>
            <Play className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{rows.length}</div>
            <p className="text-xs text-muted-foreground">On disk, ready to serve</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Symbols Covered</CardTitle>
            <RefreshCw className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{new Set(rows.map((r) => r.symbol)).size}</div>
            <p className="text-xs text-muted-foreground">Distinct symbols with a model</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Avg Directional Accuracy</CardTitle>
            <Brain className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            {avgAccuracy !== null ? (
              <>
                <div className="text-2xl font-bold">{avgAccuracy.toFixed(1)}%</div>
                <Progress value={avgAccuracy} className="mt-2" />
              </>
            ) : (
              <div className="text-sm text-muted-foreground">No evaluated models yet</div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Models Table */}
      <Card>
        <CardHeader>
          <CardTitle>Model Performance</CardTitle>
          <CardDescription>All trained models and their metrics</CardDescription>
        </CardHeader>
        <CardContent>
          {rows.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              {loaded ? "No trained models yet. Train one above, or run a forecast (it trains on the fly)." : "Loading..."}
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Type</TableHead>
                  <TableHead>Symbol</TableHead>
                  <TableHead>Directional Accuracy</TableHead>
                  <TableHead>MAPE</TableHead>
                  <TableHead>Version</TableHead>
                  <TableHead>Last Trained</TableHead>
                  <TableHead>Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((model) => (
                  <TableRow key={model.key}>
                    <TableCell>
                      <Badge variant="outline">{model.type}</Badge>
                    </TableCell>
                    <TableCell className="font-medium">{model.symbol}</TableCell>
                    <TableCell>{model.accuracy !== null ? `${model.accuracy.toFixed(1)}%` : "n/a"}</TableCell>
                    <TableCell>{model.mape !== null ? `${model.mape.toFixed(2)}%` : "n/a"}</TableCell>
                    <TableCell>{model.version}</TableCell>
                    <TableCell>
                      {model.lastTrained ? new Date(model.lastTrained).toLocaleString() : "n/a"}
                    </TableCell>
                    <TableCell>
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={training}
                        onClick={() => handleTrain(model.symbol, model.type)}
                        title="Retrain this model"
                      >
                        <RefreshCw className="h-4 w-4" />
                      </Button>
                    </TableCell>
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
