"use client";

import { Component, type ReactNode, useEffect, useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import {
  Activity,
  AlertTriangle,
  Bot,
  Gauge,
  HeartPulse,
  Radio,
  Wallet,
} from "lucide-react";
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import { formatDistanceToNow } from "date-fns";
import {
  UNIVERSE_PAIRS,
  type TradingSignal,
  type FreqtradeTrade,
  type FreqtradeProfit,
  type FreqtradeBalance,
  type ModelHealthResponse,
  getSignal,
  getModelHealth,
  getFreqtradeStatus,
  getFreqtradeProfit,
  getFreqtradeBalance,
  pingSignalApi,
  pingFreqtrade,
  tradeProfitPercent,
} from "@/lib/trading-api";

const REFRESH_INTERVAL_MS = 60_000;

// ---------------------------------------------------------------------------
// Per-panel error boundary
// ---------------------------------------------------------------------------

interface PanelErrorBoundaryProps {
  name: string;
  children: ReactNode;
}

class PanelErrorBoundary extends Component<PanelErrorBoundaryProps, { hasError: boolean }> {
  constructor(props: PanelErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  render() {
    if (this.state.hasError) {
      return (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium">{this.props.name}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex items-center space-x-2 text-sm text-muted-foreground">
              <AlertTriangle className="h-4 w-4 text-yellow-500" />
              <span>This panel failed to render.</span>
            </div>
          </CardContent>
        </Card>
      );
    }
    return this.props.children;
  }
}

// ---------------------------------------------------------------------------
// Signal polling (shared by SignalFeed + SystemStatus data-freshness)
// ---------------------------------------------------------------------------

type PairSignalState =
  | { status: "loading" }
  | { status: "ok"; signal: TradingSignal }
  | { status: "error"; error: string };

type SignalMap = Record<string, PairSignalState>;

function useSignals(): SignalMap {
  const [signals, setSignals] = useState<SignalMap>(() =>
    Object.fromEntries(UNIVERSE_PAIRS.map((pair) => [pair, { status: "loading" }]))
  );

  useEffect(() => {
    let cancelled = false;

    const load = () => {
      UNIVERSE_PAIRS.forEach(async (pair) => {
        try {
          const signal = await getSignal(pair);
          if (!cancelled) {
            setSignals((prev) => ({ ...prev, [pair]: { status: "ok", signal } }));
          }
        } catch (error) {
          if (!cancelled) {
            setSignals((prev) => ({
              ...prev,
              [pair]: {
                status: "error",
                error: error instanceof Error ? error.message : "Unknown error",
              },
            }));
          }
        }
      });
    };

    load();
    const interval = setInterval(load, REFRESH_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  return signals;
}

function confidencePercent(confidence: number): number {
  // Signal API reports confidence in [0, 1]; tolerate percent-style values.
  return confidence <= 1 ? confidence * 100 : confidence;
}

function relativeTime(timestamp: string): string {
  const date = new Date(timestamp);
  if (isNaN(date.getTime())) return timestamp;
  return formatDistanceToNow(date, { addSuffix: true });
}

// ---------------------------------------------------------------------------
// SignalFeed
// ---------------------------------------------------------------------------

function SignalFeed({ signals }: { signals: SignalMap }) {
  return (
    <div>
      <div className="mb-3">
        <h2 className="text-lg font-semibold">Signal Feed</h2>
        <p className="text-sm text-muted-foreground">
          Latest ensemble signals per pair (refreshes every 60s)
        </p>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        {UNIVERSE_PAIRS.map((pair) => {
          const state = signals[pair] ?? { status: "loading" as const };
          return (
            <Card key={pair}>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">{pair}</CardTitle>
                {state.status === "ok" ? (
                  state.signal.direction === "long" ? (
                    <Badge className="bg-green-500 text-white hover:bg-green-500">long</Badge>
                  ) : (
                    <Badge variant="secondary">flat</Badge>
                  )
                ) : (
                  <Radio className="h-4 w-4 text-muted-foreground" />
                )}
              </CardHeader>
              <CardContent>
                {state.status === "loading" && (
                  <p className="text-sm text-muted-foreground">Loading signal...</p>
                )}
                {state.status === "error" && (
                  <div className="flex items-center space-x-2 text-sm text-muted-foreground">
                    <AlertTriangle className="h-4 w-4 text-yellow-500" />
                    <span>Signal unavailable</span>
                  </div>
                )}
                {state.status === "ok" && (
                  <div className="space-y-3">
                    <div>
                      <div className="flex items-center justify-between text-sm">
                        <span className="text-muted-foreground">Confidence</span>
                        <span className="font-semibold">
                          {confidencePercent(state.signal.confidence).toFixed(0)}%
                        </span>
                      </div>
                      <Progress
                        value={confidencePercent(state.signal.confidence)}
                        className="mt-1"
                      />
                    </div>

                    {state.signal.stale && (
                      <Badge
                        variant="outline"
                        className="border-yellow-500 text-yellow-600 dark:text-yellow-400"
                      >
                        <AlertTriangle className="mr-1 h-3 w-3" />
                        stale
                      </Badge>
                    )}

                    {state.signal.top_features.length > 0 && (
                      <div className="space-y-1">
                        <div className="text-xs font-medium text-muted-foreground">
                          Top features
                        </div>
                        {state.signal.top_features.map((feature) => (
                          <div
                            key={feature.name}
                            className="flex items-center justify-between text-xs"
                          >
                            <span className="truncate pr-2">{feature.name}</span>
                            <span className="font-mono text-muted-foreground">
                              {feature.value.toFixed(3)}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}

                    <div className="border-t pt-2 text-xs text-muted-foreground">
                      <div className="flex items-center justify-between">
                        <span>{state.signal.model_version}</span>
                        <span>{relativeTime(state.signal.generated_at)}</span>
                      </div>
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// OpenPositions
// ---------------------------------------------------------------------------

type PositionsState =
  | { status: "loading" }
  | { status: "ok"; trades: FreqtradeTrade[] }
  | { status: "offline" };

function OpenPositions() {
  const [state, setState] = useState<PositionsState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        const trades = await getFreqtradeStatus();
        if (!cancelled) setState({ status: "ok", trades });
      } catch {
        if (!cancelled) setState({ status: "offline" });
      }
    };

    load();
    const interval = setInterval(load, REFRESH_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Open Positions</CardTitle>
        <CardDescription>Live trades from the execution engine</CardDescription>
      </CardHeader>
      <CardContent>
        {state.status === "loading" && (
          <p className="text-sm text-muted-foreground">Loading positions...</p>
        )}
        {state.status === "offline" && (
          <div className="flex items-center space-x-2 py-6 text-sm text-muted-foreground">
            <Bot className="h-4 w-4" />
            <span>Execution engine offline</span>
          </div>
        )}
        {state.status === "ok" && state.trades.length === 0 && (
          <p className="py-6 text-sm text-muted-foreground">No open positions</p>
        )}
        {state.status === "ok" && state.trades.length > 0 && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Pair</TableHead>
                <TableHead>Amount</TableHead>
                <TableHead>Open Price</TableHead>
                <TableHead>Profit</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {state.trades.map((trade) => {
                const profit = tradeProfitPercent(trade);
                return (
                  <TableRow key={trade.trade_id}>
                    <TableCell className="font-medium">{trade.pair}</TableCell>
                    <TableCell>{trade.amount}</TableCell>
                    <TableCell>{trade.open_rate}</TableCell>
                    <TableCell
                      className={profit >= 0 ? "text-green-500" : "text-red-500"}
                    >
                      {profit >= 0 ? "+" : ""}
                      {profit.toFixed(2)}%
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// EquityPanel
// ---------------------------------------------------------------------------

type EquityState =
  | { status: "loading" }
  | { status: "ok"; profit: FreqtradeProfit; balance: FreqtradeBalance | null }
  | { status: "offline" };

function EquityPanel() {
  const [state, setState] = useState<EquityState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      const [profitResult, balanceResult] = await Promise.allSettled([
        getFreqtradeProfit(),
        getFreqtradeBalance(),
      ]);
      if (cancelled) return;
      if (profitResult.status === "fulfilled") {
        setState({
          status: "ok",
          profit: profitResult.value,
          balance: balanceResult.status === "fulfilled" ? balanceResult.value : null,
        });
      } else {
        setState({ status: "offline" });
      }
    };

    load();
    const interval = setInterval(load, REFRESH_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  if (state.status === "loading") {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Equity</CardTitle>
          <CardDescription>Account balance and realized performance</CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">Loading equity...</p>
        </CardContent>
      </Card>
    );
  }

  if (state.status === "offline") {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Equity</CardTitle>
          <CardDescription>Account balance and realized performance</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-center space-x-2 py-6 text-sm text-muted-foreground">
            <Wallet className="h-4 w-4" />
            <span>Execution engine offline</span>
          </div>
        </CardContent>
      </Card>
    );
  }

  const { profit, balance } = state;
  const winning = profit.winning_trades ?? 0;
  const losing = profit.losing_trades ?? 0;
  const closedCount = winning + losing;
  const winRate = closedCount > 0 ? (winning / closedCount) * 100 : null;
  const stakeSymbol = balance?.stake ?? "USDT";

  // /api/v1/profit is an aggregate endpoint; until a proper equity time series
  // exists, plot cumulative closed profit from first to latest trade.
  const chartData =
    profit.first_trade_timestamp && profit.latest_trade_timestamp
      ? [
          {
            date: new Date(profit.first_trade_timestamp).toLocaleDateString(),
            profit: 0,
          },
          {
            date: new Date(profit.latest_trade_timestamp).toLocaleDateString(),
            profit: profit.profit_closed_coin ?? 0,
          },
        ]
      : [];

  return (
    <Card>
      <CardHeader>
        <CardTitle>Equity</CardTitle>
        <CardDescription>Account balance and realized performance</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <div className="text-xs text-muted-foreground">Total Balance</div>
            <div className="text-2xl font-bold">
              {balance?.total !== undefined
                ? `${balance.total.toFixed(2)} ${stakeSymbol}`
                : "—"}
            </div>
          </div>
          <div>
            <div className="text-xs text-muted-foreground">Closed Profit</div>
            <div
              className={`text-2xl font-bold ${
                (profit.profit_closed_coin ?? 0) >= 0 ? "text-green-500" : "text-red-500"
              }`}
            >
              {(profit.profit_closed_coin ?? 0).toFixed(2)} {stakeSymbol}
            </div>
            <div className="text-xs text-muted-foreground">
              {(profit.profit_closed_percent_mean ?? 0).toFixed(2)}% mean / trade
            </div>
          </div>
          <div>
            <div className="text-xs text-muted-foreground">Win Rate</div>
            <div className="text-2xl font-bold">
              {winRate !== null ? `${winRate.toFixed(0)}%` : "—"}
            </div>
            <div className="text-xs text-muted-foreground">
              {winning}W / {losing}L
            </div>
          </div>
          <div>
            <div className="text-xs text-muted-foreground">Trades</div>
            <div className="text-2xl font-bold">{profit.trade_count ?? 0}</div>
            <div className="text-xs text-muted-foreground">
              {profit.closed_trade_count ?? 0} closed
            </div>
          </div>
        </div>

        {chartData.length > 0 ? (
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="date" />
              <YAxis />
              <Tooltip />
              <Line type="monotone" dataKey="profit" stroke="#82ca9d" strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <p className="text-sm text-muted-foreground">No closed trades yet</p>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// ModelHealthPanel
// ---------------------------------------------------------------------------

type ModelHealthState =
  | { status: "loading" }
  | { status: "ok"; health: ModelHealthResponse }
  | { status: "unavailable" };

function ModelHealthPanel() {
  const [state, setState] = useState<ModelHealthState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        const health = await getModelHealth();
        if (!cancelled) setState({ status: "ok", health });
      } catch {
        if (!cancelled) setState({ status: "unavailable" });
      }
    };

    load();
    const interval = setInterval(load, REFRESH_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  const collectingData = (
    <div className="flex items-center space-x-2 py-6 text-sm text-muted-foreground">
      <Gauge className="h-4 w-4" />
      <span>Collecting data</span>
    </div>
  );

  return (
    <div>
      <div className="mb-3">
        <h2 className="text-lg font-semibold">Model Health</h2>
        <p className="text-sm text-muted-foreground">
          Directional accuracy and calibration per pair
        </p>
      </div>
      {state.status === "loading" && (
        <Card>
          <CardContent>
            <p className="py-6 text-sm text-muted-foreground">Loading model health...</p>
          </CardContent>
        </Card>
      )}
      {state.status === "unavailable" && (
        <Card>
          <CardContent>{collectingData}</CardContent>
        </Card>
      )}
      {state.status === "ok" && state.health.pairs.length === 0 && (
        <Card>
          <CardContent>{collectingData}</CardContent>
        </Card>
      )}
      {state.status === "ok" && state.health.pairs.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {state.health.pairs.map((pairHealth) => {
            const calibrationData = pairHealth.calibration.map((bucket) => ({
              bucket: `${(bucket.bucket_low * 100).toFixed(0)}-${(bucket.bucket_high * 100).toFixed(0)}%`,
              predicted: Number((bucket.predicted_mean * 100).toFixed(1)),
              realized: Number((bucket.realized_hit_rate * 100).toFixed(1)),
            }));

            return (
              <Card key={pairHealth.pair}>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-medium">{pairHealth.pair}</CardTitle>
                  <CardDescription>
                    {pairHealth.n_predictions.toLocaleString()} predictions scored
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <div className="text-xs text-muted-foreground">Accuracy (7d)</div>
                      <div className="text-xl font-bold">
                        {pairHealth.directional_accuracy_7d !== null
                          ? `${(pairHealth.directional_accuracy_7d * 100).toFixed(1)}%`
                          : "—"}
                      </div>
                    </div>
                    <div>
                      <div className="text-xs text-muted-foreground">Accuracy (30d)</div>
                      <div className="text-xl font-bold">
                        {pairHealth.directional_accuracy_30d !== null
                          ? `${(pairHealth.directional_accuracy_30d * 100).toFixed(1)}%`
                          : "—"}
                      </div>
                    </div>
                  </div>

                  {calibrationData.length > 0 ? (
                    <ResponsiveContainer width="100%" height={160}>
                      <BarChart data={calibrationData}>
                        <CartesianGrid strokeDasharray="3 3" />
                        <XAxis dataKey="bucket" fontSize={11} />
                        <YAxis fontSize={11} unit="%" />
                        <Tooltip />
                        <Legend />
                        <Bar dataKey="predicted" name="Predicted" fill="#8884d8" />
                        <Bar dataKey="realized" name="Realized" fill="#82ca9d" />
                      </BarChart>
                    </ResponsiveContainer>
                  ) : (
                    <p className="text-sm text-muted-foreground">Collecting data</p>
                  )}
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// SystemStatus
// ---------------------------------------------------------------------------

type PingState = "checking" | "up" | "down";

function statusDotColor(state: PingState): string {
  if (state === "up") return "bg-green-500";
  if (state === "down") return "bg-red-500";
  return "bg-yellow-500";
}

function SystemStatus({ signals }: { signals: SignalMap }) {
  const [signalApi, setSignalApi] = useState<PingState>("checking");
  const [executionEngine, setExecutionEngine] = useState<PingState>("checking");

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      const [signalResult, freqtradeResult] = await Promise.allSettled([
        pingSignalApi(),
        pingFreqtrade(),
      ]);
      if (cancelled) return;
      setSignalApi(signalResult.status === "fulfilled" ? "up" : "down");
      setExecutionEngine(freqtradeResult.status === "fulfilled" ? "up" : "down");
    };

    load();
    const interval = setInterval(load, REFRESH_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  const signalStates = Object.values(signals);
  const resolved = signalStates.filter((s) => s.status !== "loading");
  const anyStale = signalStates.some((s) => s.status === "ok" && s.signal.stale);
  const anyFresh = signalStates.some((s) => s.status === "ok" && !s.signal.stale);

  let freshness: PingState;
  let freshnessLabel: string;
  if (resolved.length === 0) {
    freshness = "checking";
    freshnessLabel = "Checking...";
  } else if (anyStale) {
    freshness = "checking"; // amber
    freshnessLabel = "Stale signals detected";
  } else if (anyFresh) {
    freshness = "up";
    freshnessLabel = "All signals fresh";
  } else {
    freshness = "down";
    freshnessLabel = "No signal data";
  }

  const items = [
    {
      label: "Signal API",
      icon: Activity,
      state: signalApi,
      detail:
        signalApi === "up" ? "Healthy" : signalApi === "down" ? "Unreachable" : "Checking...",
    },
    {
      label: "Execution Engine",
      icon: Bot,
      state: executionEngine,
      detail:
        executionEngine === "up"
          ? "Healthy"
          : executionEngine === "down"
            ? "Offline"
            : "Checking...",
    },
    {
      label: "Data Freshness",
      icon: HeartPulse,
      state: freshness,
      detail: freshnessLabel,
    },
  ];

  return (
    <Card>
      <CardContent className="py-4">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {items.map((item) => {
            const Icon = item.icon;
            return (
              <div key={item.label} className="flex items-center space-x-3">
                <span
                  className={`h-2.5 w-2.5 shrink-0 rounded-full ${statusDotColor(item.state)}`}
                />
                <Icon className="h-4 w-4 text-muted-foreground" />
                <div>
                  <div className="text-sm font-medium">{item.label}</div>
                  <div className="text-xs text-muted-foreground">{item.detail}</div>
                </div>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Trading (main panel)
// ---------------------------------------------------------------------------

export function Trading() {
  const signals = useSignals();

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Trading</h1>
          <p className="text-muted-foreground">Trading bot signals, positions, and health</p>
        </div>
      </div>

      <PanelErrorBoundary name="System Status">
        <SystemStatus signals={signals} />
      </PanelErrorBoundary>

      <PanelErrorBoundary name="Signal Feed">
        <SignalFeed signals={signals} />
      </PanelErrorBoundary>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <PanelErrorBoundary name="Open Positions">
          <OpenPositions />
        </PanelErrorBoundary>
        <PanelErrorBoundary name="Equity">
          <EquityPanel />
        </PanelErrorBoundary>
      </div>

      <PanelErrorBoundary name="Model Health">
        <ModelHealthPanel />
      </PanelErrorBoundary>
    </div>
  );
}
