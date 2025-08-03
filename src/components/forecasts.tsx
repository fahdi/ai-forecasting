"use client";

import { useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Plus, TrendingUp, Clock, CheckCircle, XCircle } from "lucide-react";

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
  const [forecasts, setForecasts] = useState<Forecast[]>([
    {
      id: "1",
      symbol: "AAPL",
      modelType: "ensemble",
      horizon: 7,
      status: "completed",
      prediction: 185.42,
      confidence: 87.3,
      createdAt: "2024-01-15T10:30:00Z"
    },
    {
      id: "2",
      symbol: "GOOGL",
      modelType: "xgboost",
      horizon: 30,
      status: "running",
      prediction: 142.18,
      confidence: 82.1,
      createdAt: "2024-01-15T09:15:00Z"
    },
    {
      id: "3",
      symbol: "MSFT",
      modelType: "lstm",
      horizon: 7,
      status: "completed",
      prediction: 378.95,
      confidence: 89.7,
      createdAt: "2024-01-15T08:45:00Z"
    }
  ]);

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
        return <Clock className="h-4 w-4 text-yellow-500" />;
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
            <Button className="w-full md:w-auto">
              <Plus className="mr-2 h-4 w-4" />
              Generate Forecast
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
                  <TableCell>${forecast.prediction.toFixed(2)}</TableCell>
                  <TableCell>{forecast.confidence}%</TableCell>
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
        </CardContent>
      </Card>
    </div>
  );
} 