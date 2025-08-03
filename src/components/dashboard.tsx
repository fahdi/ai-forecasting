"use client";

import { useState, useEffect } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { 
  TrendingUp, 
  TrendingDown, 
  Activity, 
  Database, 
  Brain, 
  Clock,
  ArrowUpRight,
  ArrowDownRight
} from "lucide-react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, AreaChart, Area } from "recharts";

interface DashboardStats {
  totalForecasts: number;
  activeModels: number;
  dataPoints: number;
  accuracy: number;
  recentForecasts: Array<{
    symbol: string;
    prediction: number;
    change: number;
    timestamp: string;
  }>;
  performanceData: Array<{
    date: string;
    accuracy: number;
    volume: number;
  }>;
}

export function Dashboard() {
  const [stats, setStats] = useState<DashboardStats>({
    totalForecasts: 1247,
    activeModels: 8,
    dataPoints: 45678,
    accuracy: 87.3,
    recentForecasts: [
      { symbol: "AAPL", prediction: 185.42, change: 2.3, timestamp: "2024-01-15" },
      { symbol: "GOOGL", prediction: 142.18, change: -1.2, timestamp: "2024-01-15" },
      { symbol: "MSFT", prediction: 378.95, change: 3.1, timestamp: "2024-01-15" },
      { symbol: "TSLA", prediction: 245.67, change: -0.8, timestamp: "2024-01-15" },
    ],
    performanceData: [
      { date: "Jan 10", accuracy: 85, volume: 120 },
      { date: "Jan 11", accuracy: 87, volume: 145 },
      { date: "Jan 12", accuracy: 89, volume: 167 },
      { date: "Jan 13", accuracy: 86, volume: 134 },
      { date: "Jan 14", accuracy: 88, volume: 156 },
      { date: "Jan 15", accuracy: 87, volume: 142 },
    ]
  });

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Dashboard</h1>
          <p className="text-muted-foreground">AI Forecasting System Overview</p>
        </div>
        <Button>
          <Activity className="mr-2 h-4 w-4" />
          Generate Forecast
        </Button>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total Forecasts</CardTitle>
            <TrendingUp className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats.totalForecasts.toLocaleString()}</div>
            <p className="text-xs text-muted-foreground">
              +12% from last month
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Active Models</CardTitle>
            <Brain className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats.activeModels}</div>
            <p className="text-xs text-muted-foreground">
              XGBoost, LSTM, Ensemble
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Data Points</CardTitle>
            <Database className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats.dataPoints.toLocaleString()}</div>
            <p className="text-xs text-muted-foreground">
              +8% from last week
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Accuracy</CardTitle>
            <Activity className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats.accuracy}%</div>
            <Progress value={stats.accuracy} className="mt-2" />
          </CardContent>
        </Card>
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Performance Chart */}
        <Card>
          <CardHeader>
            <CardTitle>Performance Trend</CardTitle>
            <CardDescription>Model accuracy over time</CardDescription>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={300}>
              <AreaChart data={stats.performanceData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" />
                <YAxis />
                <Tooltip />
                <Area type="monotone" dataKey="accuracy" stroke="#8884d8" fill="#8884d8" fillOpacity={0.3} />
              </AreaChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        {/* Volume Chart */}
        <Card>
          <CardHeader>
            <CardTitle>Forecast Volume</CardTitle>
            <CardDescription>Daily forecast requests</CardDescription>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={stats.performanceData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" />
                <YAxis />
                <Tooltip />
                <Line type="monotone" dataKey="volume" stroke="#82ca9d" strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>

      {/* Recent Forecasts */}
      <Card>
        <CardHeader>
          <CardTitle>Recent Forecasts</CardTitle>
          <CardDescription>Latest predictions and their performance</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            {stats.recentForecasts.map((forecast, index) => (
              <div key={index} className="flex items-center justify-between p-4 border rounded-lg">
                <div className="flex items-center space-x-4">
                  <div>
                    <div className="font-semibold">{forecast.symbol}</div>
                    <div className="text-sm text-muted-foreground">
                      ${forecast.prediction.toFixed(2)}
                    </div>
                  </div>
                </div>
                <div className="flex items-center space-x-2">
                  {forecast.change > 0 ? (
                    <ArrowUpRight className="h-4 w-4 text-green-500" />
                  ) : (
                    <ArrowDownRight className="h-4 w-4 text-red-500" />
                  )}
                  <Badge variant={forecast.change > 0 ? "default" : "secondary"}>
                    {forecast.change > 0 ? "+" : ""}{forecast.change}%
                  </Badge>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
} 