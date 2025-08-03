"use client";

import { useState, useEffect } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Plus, TrendingUp, Clock, CheckCircle, XCircle, Loader2 } from "lucide-react";
import { apiService, ForecastRequest } from "@/lib/api";
import { toast } from "sonner";

interface Forecast {
  id: string;
  symbol: string;
  modelType: string;
  horizon: number;
  status: "pending" | "running" | "completed" | "failed";
  prediction: number;
  confidence: number;
  createdAt: string;
}

export function Forecasts() {
  const [forecasts, setForecasts] = useState<Forecast[]>([]);
  const [loading, setLoading] = useState(false);
  const [newForecast, setNewForecast] = useState({
    symbol: "",
    modelType: "ensemble",
    horizon: 7
  });

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
      toast.error("Please enter a stock symbol");
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
        prediction: 0,
        confidence: 0,
        createdAt: new Date().toISOString()
      };

      setForecasts(prev => [newForecastItem, ...prev]);
      setNewForecast({ symbol: "", modelType: "ensemble", horizon: 7 });
      toast.success("Forecast job created successfully!");
    } catch (error) {
      console.error("Error creating forecast:", error);
      toast.error("Failed to create forecast. Please try again.");
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
              <Label htmlFor="symbol">Stock Symbol</Label>
              <Input
                id="symbol"
                placeholder="AAPL"
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
                      {forecast.prediction > 0 ? `$${forecast.prediction.toFixed(2)}` : "Pending"}
                    </TableCell>
                    <TableCell>
                      {forecast.confidence > 0 ? `${forecast.confidence}%` : "Pending"}
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