"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { BarChart3, TrendingUp, TrendingDown } from "lucide-react";

export function Analytics() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Analytics</h1>
        <p className="text-muted-foreground">Advanced insights and performance metrics</p>
      </div>
      
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle>Performance Metrics</CardTitle>
            <CardDescription>Model accuracy and predictions</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <div className="flex justify-between">
                <span>Overall Accuracy</span>
                <span className="font-bold text-green-600">87.3%</span>
              </div>
              <div className="flex justify-between">
                <span>Directional Accuracy</span>
                <span className="font-bold text-blue-600">72.1%</span>
              </div>
              <div className="flex justify-between">
                <span>RMSE</span>
                <span className="font-bold text-orange-600">3.2%</span>
              </div>
            </div>
          </CardContent>
        </Card>
        
        <Card>
          <CardHeader>
            <CardTitle>System Health</CardTitle>
            <CardDescription>Infrastructure status</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <div className="flex justify-between">
                <span>API Status</span>
                <span className="font-bold text-green-600">Healthy</span>
              </div>
              <div className="flex justify-between">
                <span>Database</span>
                <span className="font-bold text-green-600">Connected</span>
              </div>
              <div className="flex justify-between">
                <span>Models</span>
                <span className="font-bold text-green-600">Active</span>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
} 