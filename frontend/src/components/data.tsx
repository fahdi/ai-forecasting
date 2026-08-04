"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Upload, Loader2 } from "lucide-react";
import { apiService, DataSourceInfo, DataStats } from "@/lib/api";
import { toast } from "sonner";

export function Data() {
  const [sources, setSources] = useState<DataSourceInfo[]>([]);
  const [stats, setStats] = useState<DataStats | null>(null);
  const [symbols, setSymbols] = useState<string[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [uploadSymbol, setUploadSymbol] = useState("");
  const [uploading, setUploading] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    const [sourcesRes, statsRes, symbolsRes] = await Promise.allSettled([
      apiService.getDataSources(),
      apiService.getDataStats(),
      apiService.getSymbols(),
    ]);
    if (sourcesRes.status === "fulfilled") setSources(sourcesRes.value);
    if (statsRes.status === "fulfilled") setStats(statsRes.value);
    if (symbolsRes.status === "fulfilled") setSymbols(symbolsRes.value);
    setLoaded(true);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleUpload = async (file: File) => {
    if (!uploadSymbol) {
      toast.error("Enter the symbol this CSV belongs to first");
      return;
    }
    setUploading(true);
    try {
      await apiService.uploadData(file, uploadSymbol.toUpperCase());
      toast.success(`Uploaded data for ${uploadSymbol.toUpperCase()}`);
      setUploadSymbol("");
      load();
    } catch {
      toast.error("Upload failed. The file must be a CSV with OHLCV columns.");
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Data Management</h1>
        <p className="text-muted-foreground">Upload and manage market data</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <Card>
          <CardHeader>
            <CardTitle>Data Sources</CardTitle>
            <CardDescription>Availability from server configuration</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {sources.length ? (
                sources.map((source) => (
                  <div key={source.name} className="flex items-center justify-between">
                    <span className="capitalize">{source.name.replace("_", " ")}</span>
                    <Badge variant={source.enabled ? "default" : "outline"}>
                      {source.enabled ? "Enabled" : "Disabled"}
                    </Badge>
                  </div>
                ))
              ) : (
                <div className="text-sm text-muted-foreground">
                  {loaded ? "No sources reported" : "Loading..."}
                </div>
              )}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Upload Data</CardTitle>
            <CardDescription>Import a custom OHLCV CSV for a symbol</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              <div className="space-y-2">
                <Label htmlFor="upload-symbol">Symbol</Label>
                <Input
                  id="upload-symbol"
                  placeholder="MYASSET"
                  value={uploadSymbol}
                  onChange={(e) => setUploadSymbol(e.target.value.toUpperCase())}
                />
              </div>
              <input
                ref={fileInput}
                type="file"
                accept=".csv"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) handleUpload(file);
                }}
              />
              <Button className="w-full" disabled={uploading} onClick={() => fileInput.current?.click()}>
                {uploading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Upload className="mr-2 h-4 w-4" />}
                {uploading ? "Uploading..." : "Upload CSV"}
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Data Stats</CardTitle>
            <CardDescription>Live from server storage</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              <div className="flex justify-between">
                <span>Cached Symbols</span>
                <span className="font-bold">{stats ? stats.total_symbols.toLocaleString() : loaded ? "0" : "..."}</span>
              </div>
              <div className="flex justify-between">
                <span>Data Points</span>
                <span className="font-bold">{stats ? stats.total_data_points.toLocaleString() : loaded ? "0" : "..."}</span>
              </div>
              <div className="flex justify-between">
                <span>Storage</span>
                <span className="font-bold">
                  {stats ? `${(stats.storage_size / 1024 / 1024).toFixed(1)} MB` : loaded ? "0 MB" : "..."}
                </span>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Cached Symbols</CardTitle>
          <CardDescription>Symbols with locally cached history (populated by forecasts and uploads)</CardDescription>
        </CardHeader>
        <CardContent>
          {symbols.length ? (
            <div className="flex flex-wrap gap-2">
              {symbols.map((symbol) => (
                <Badge key={symbol} variant="outline">{symbol}</Badge>
              ))}
            </div>
          ) : (
            <div className="text-sm text-muted-foreground">
              {loaded ? "Nothing cached yet. Run a forecast to pull data." : "Loading..."}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
