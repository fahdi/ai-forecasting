"use client";

import { useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Brain, Play, Pause, Settings } from "lucide-react";

interface Model {
  id: string;
  name: string;
  type: string;
  symbol: string;
  accuracy: number;
  status: "active" | "training" | "inactive";
  lastUpdated: string;
  version: string;
}

export function Models() {
  const [models, setModels] = useState<Model[]>([
    {
      id: "1",
      name: "Ensemble Model",
      type: "ensemble",
      symbol: "AAPL",
      accuracy: 87.3,
      status: "active",
      lastUpdated: "2024-01-15T10:30:00Z",
      version: "v1.2.0"
    },
    {
      id: "2",
      name: "XGBoost Model",
      type: "xgboost",
      symbol: "GOOGL",
      accuracy: 84.7,
      status: "training",
      lastUpdated: "2024-01-15T09:15:00Z",
      version: "v1.1.5"
    },
    {
      id: "3",
      name: "LSTM Model",
      type: "lstm",
      symbol: "MSFT",
      accuracy: 89.2,
      status: "active",
      lastUpdated: "2024-01-15T08:45:00Z",
      version: "v1.3.0"
    }
  ]);

  const getStatusBadge = (status: string) => {
    const variants = {
      active: "default",
      training: "secondary",
      inactive: "outline"
    } as const;

    return <Badge variant={variants[status as keyof typeof variants]}>{status}</Badge>;
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Models</h1>
          <p className="text-muted-foreground">Manage and monitor ML models</p>
        </div>
        <Button>
          <Brain className="mr-2 h-4 w-4" />
          Train New Model
        </Button>
      </div>

      {/* Model Stats */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Active Models</CardTitle>
            <Play className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{models.filter(m => m.status === "active").length}</div>
            <p className="text-xs text-muted-foreground">
              Currently running
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Training</CardTitle>
            <Settings className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{models.filter(m => m.status === "training").length}</div>
            <p className="text-xs text-muted-foreground">
              In progress
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Avg Accuracy</CardTitle>
            <Brain className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {(models.reduce((acc, m) => acc + m.accuracy, 0) / models.length).toFixed(1)}%
            </div>
            <Progress value={models.reduce((acc, m) => acc + m.accuracy, 0) / models.length} className="mt-2" />
          </CardContent>
        </Card>
      </div>

      {/* Models Table */}
      <Card>
        <CardHeader>
          <CardTitle>Model Performance</CardTitle>
          <CardDescription>View all trained models and their metrics</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Model</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Symbol</TableHead>
                <TableHead>Accuracy</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Version</TableHead>
                <TableHead>Last Updated</TableHead>
                <TableHead>Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {models.map((model) => (
                <TableRow key={model.id}>
                  <TableCell className="font-medium">{model.name}</TableCell>
                  <TableCell>
                    <Badge variant="outline">{model.type}</Badge>
                  </TableCell>
                  <TableCell>{model.symbol}</TableCell>
                  <TableCell>{model.accuracy}%</TableCell>
                  <TableCell>{getStatusBadge(model.status)}</TableCell>
                  <TableCell>{model.version}</TableCell>
                  <TableCell>{new Date(model.lastUpdated).toLocaleDateString()}</TableCell>
                  <TableCell>
                    <div className="flex space-x-2">
                      <Button size="sm" variant="outline">
                        <Settings className="h-4 w-4" />
                      </Button>
                      <Button size="sm" variant="outline">
                        <Play className="h-4 w-4" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
} 