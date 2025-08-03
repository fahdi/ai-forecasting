"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Database, Upload, Download, RefreshCw } from "lucide-react";

export function Data() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Data Management</h1>
        <p className="text-muted-foreground">Upload and manage stock data</p>
      </div>
      
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <Card>
          <CardHeader>
            <CardTitle>Data Sources</CardTitle>
            <CardDescription>Manage data connections</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <span>Yahoo Finance</span>
                <Badge variant="default">Active</Badge>
              </div>
              <div className="flex items-center justify-between">
                <span>Alpha Vantage</span>
                <Badge variant="secondary">Connected</Badge>
              </div>
            </div>
          </CardContent>
        </Card>
        
        <Card>
          <CardHeader>
            <CardTitle>Upload Data</CardTitle>
            <CardDescription>Import custom datasets</CardDescription>
          </CardHeader>
          <CardContent>
            <Button className="w-full">
              <Upload className="mr-2 h-4 w-4" />
              Upload CSV
            </Button>
          </CardContent>
        </Card>
        
        <Card>
          <CardHeader>
            <CardTitle>Data Stats</CardTitle>
            <CardDescription>System overview</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              <div className="flex justify-between">
                <span>Total Symbols</span>
                <span className="font-bold">1,247</span>
              </div>
              <div className="flex justify-between">
                <span>Data Points</span>
                <span className="font-bold">45,678</span>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
} 