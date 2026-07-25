"use client";

import { useEffect, useRef, useState } from "react";
import {
  CandlestickSeries,
  ColorType,
  LineSeries,
  LineStyle,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  UNIVERSE_PAIRS,
  getChartCandles,
  getChartPredictions,
  type ChartCandlesResponse,
  type ChartPredictionsResponse,
} from "@/lib/trading-api";

const REFRESH_MS = 60_000;

const COLOR_UP = "#22c55e";
const COLOR_DOWN = "#ef4444";
const COLOR_OUT_OF_SAMPLE = "#3b82f6";
const COLOR_IN_SAMPLE = "#9ca3af";
const COLOR_UNRESOLVED = "#a3a3a3";

export function CandleChartPanel() {
  const [pair, setPair] = useState<string>(UNIVERSE_PAIRS[0]);
  const [candles, setCandles] = useState<ChartCandlesResponse | null>(null);
  const [predictions, setPredictions] = useState<ChartPredictionsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [candleData, predictionData] = await Promise.all([
          getChartCandles(pair),
          getChartPredictions(pair),
        ]);
        if (!cancelled) {
          setCandles(candleData);
          setPredictions(predictionData);
          setError(null);
        }
      } catch {
        if (!cancelled) setError("Chart data unavailable");
      }
    }
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [pair]);

  useEffect(() => {
    if (!containerRef.current || !candles) return;

    const chart = createChart(containerRef.current, {
      autoSize: true,
      height: 420,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#737373",
        attributionLogo: true,
      },
      grid: {
        vertLines: { color: "rgba(115, 115, 115, 0.12)" },
        horzLines: { color: "rgba(115, 115, 115, 0.12)" },
      },
      timeScale: { timeVisible: true, secondsVisible: false },
      rightPriceScale: { borderVisible: false },
    });
    chartRef.current = chart;

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: COLOR_UP,
      downColor: COLOR_DOWN,
      wickUpColor: COLOR_UP,
      wickDownColor: COLOR_DOWN,
      borderVisible: false,
    });
    candleSeries.setData(
      candles.candles.map((candle) => ({
        time: candle.time as UTCTimestamp,
        open: candle.open,
        high: candle.high,
        low: candle.low,
        close: candle.close,
      })),
    );

    if (predictions && predictions.model_view.length > 0) {
      const boundarySeconds = predictions.training_window_end
        ? Date.parse(predictions.training_window_end) / 1000
        : 0;
      const inSample = predictions.model_view.filter((point) => point.time <= boundarySeconds);
      const outOfSample = predictions.model_view.filter((point) => point.time >= boundarySeconds);

      const probScaleOptions = {
        priceScaleId: "probability",
        priceLineVisible: false,
        lastValueVisible: false,
        lineWidth: 2 as const,
      };
      if (inSample.length > 0) {
        const inSampleSeries = chart.addSeries(LineSeries, {
          ...probScaleOptions,
          color: COLOR_IN_SAMPLE,
          lineStyle: LineStyle.Dashed,
        });
        inSampleSeries.setData(
          inSample.map((point) => ({ time: point.time as UTCTimestamp, value: point.prob_long })),
        );
      }
      if (outOfSample.length > 0) {
        const outSeries = chart.addSeries(LineSeries, {
          ...probScaleOptions,
          color: COLOR_OUT_OF_SAMPLE,
        });
        outSeries.setData(
          outOfSample.map((point) => ({ time: point.time as UTCTimestamp, value: point.prob_long })),
        );
        outSeries.createPriceLine({
          price: 0.5,
          color: "rgba(115, 115, 115, 0.4)",
          lineWidth: 1,
          lineStyle: LineStyle.Dotted,
          axisLabelVisible: false,
          title: "0.5",
        });
      }
      chart.priceScale("probability").applyOptions({
        scaleMargins: { top: 0.78, bottom: 0 },
        borderVisible: false,
      });
    }

    if (predictions && predictions.logged.length > 0) {
      const candleTimes = new Set(candles.candles.map((candle) => candle.time));
      const markers: SeriesMarker<Time>[] = predictions.logged
        .filter((entry) => candleTimes.has(entry.time))
        .map((entry) => ({
          time: entry.time as UTCTimestamp,
          position: entry.direction === "long" ? "belowBar" : "aboveBar",
          shape: entry.direction === "long" ? "arrowUp" : "circle",
          color:
            entry.realized === null
              ? COLOR_UNRESOLVED
              : (entry.direction === "long") === (entry.realized === 1)
                ? COLOR_UP
                : COLOR_DOWN,
          size: 1,
        }));
      createSeriesMarkers(candleSeries, markers);
    }

    chart.timeScale().fitContent();
    return () => {
      chart.remove();
      chartRef.current = null;
    };
  }, [candles, predictions]);

  const trainedThrough = predictions?.training_window_end
    ? new Date(predictions.training_window_end).toLocaleDateString()
    : null;

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <div>
          <CardTitle>Candles &amp; Model View</CardTitle>
          <CardDescription>
            Real {candles?.interval ?? "4h"} candles with the ensemble&apos;s probability of
            &quot;long&quot; and logged live signals
          </CardDescription>
        </div>
        <div className="flex gap-1">
          {UNIVERSE_PAIRS.map((universePair) => (
            <button
              key={universePair}
              onClick={() => setPair(universePair)}
              className={`rounded-md px-2 py-1 text-xs font-medium transition-colors ${
                pair === universePair
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-muted-foreground hover:bg-muted/70"
              }`}
            >
              {universePair.replace("-USDT", "")}
            </button>
          ))}
        </div>
      </CardHeader>
      <CardContent>
        {error ? (
          <p className="py-16 text-center text-sm text-muted-foreground">{error}</p>
        ) : (
          <>
            <div ref={containerRef} className="h-[420px] w-full" />
            <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
              <span className="flex items-center gap-1">
                <span className="inline-block h-0.5 w-4 bg-[#3b82f6]" /> prob(long), out-of-sample
              </span>
              <span className="flex items-center gap-1">
                <span className="inline-block h-0.5 w-4 border-t-2 border-dashed border-[#9ca3af]" />
                prob(long), in-sample{trainedThrough ? ` (trained through ${trainedThrough})` : ""}
              </span>
              <span className="flex items-center gap-1">
                <span className="text-[#22c55e]">▲</span>/<span className="text-[#ef4444]">▲</span>
                logged long signal (right/wrong once resolved)
              </span>
              <span className="flex items-center gap-1">
                <span className="text-[#a3a3a3]">▲</span> unresolved
              </span>
              {predictions?.model_version && (
                <Badge variant="outline" className="ml-auto font-mono text-[10px]">
                  {predictions.model_version}
                </Badge>
              )}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
