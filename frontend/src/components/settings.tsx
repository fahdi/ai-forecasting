"use client";

import { useState, useEffect } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { apiService, AppSettings } from "@/lib/api";

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between items-center">
      <span>{label}</span>
      <span className="text-sm text-muted-foreground">{value}</span>
    </div>
  );
}

export function Settings() {
  const [config, setConfig] = useState<AppSettings | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    apiService
      .getAppSettings()
      .then(setConfig)
      .catch(() => {})
      .finally(() => setLoaded(true));
  }, []);

  if (!config) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold">Settings</h1>
          <p className="text-muted-foreground">Live server configuration (read-only)</p>
        </div>
        <div className="text-sm text-muted-foreground">
          {loaded ? "Could not load configuration from the API." : "Loading..."}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Settings</h1>
        <p className="text-muted-foreground">
          Live server configuration (read-only; values are set via server environment)
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle>API</CardTitle>
            <CardDescription>Service limits and version</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <Row label="Version" value={config.version} />
              <Row label="Rate Limit" value={`${config.rate_limit_per_minute} req/min`} />
              <Row label="Hourly Limit" value={`${config.rate_limit_per_hour} req/hour`} />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Data Sources</CardTitle>
            <CardDescription>Provider availability</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <Row
                label="Yahoo Finance"
                value={<Badge variant={config.yahoo_finance_enabled ? "default" : "outline"}>{config.yahoo_finance_enabled ? "Enabled" : "Disabled"}</Badge>}
              />
              <Row
                label="Alpha Vantage"
                value={<Badge variant={config.alpha_vantage_enabled ? "default" : "outline"}>{config.alpha_vantage_enabled ? "Enabled" : "Disabled"}</Badge>}
              />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Forecasting</CardTitle>
            <CardDescription>Horizon and data requirements</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <Row label="Default Horizon" value={`${config.default_forecast_horizon} days`} />
              <Row label="Max Horizon" value={`${config.max_forecast_horizon} days`} />
              <Row label="Min History Required" value={`${config.min_historical_data_days} days`} />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Models</CardTitle>
            <CardDescription>Runtime model handling</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <Row label="Model Cache Size" value={`${config.model_cache_size} models`} />
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
