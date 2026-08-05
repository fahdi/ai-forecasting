import { describe, expect, it } from "vitest";
import { systemStatusView } from "./system-status";
import type { DetailedHealth } from "./api";

/**
 * The dashboard header derived "API: Connected" from whether the request
 * resolved, against /health, which returns a hardcoded "healthy". So while
 * production sat degraded with five-day-old market data, the landing page
 * showed a green check.
 */

const health = (
  status: string,
  components: Record<string, string> = {},
): DetailedHealth => ({
  status,
  components: Object.fromEntries(
    Object.entries(components).map(([name, s]) => [name, { status: s }]),
  ),
});

describe("systemStatusView", () => {
  it("is checking before anything has loaded", () => {
    const view = systemStatusView(null, false);
    expect(view.status).toBe("checking");
    expect(view.label).toBe("Checking...");
  });

  it("is disconnected when the request failed", () => {
    const view = systemStatusView(null, true);
    expect(view.status).toBe("unhealthy");
    expect(view.label).toBe("Disconnected");
  });

  it("is healthy when every component is healthy", () => {
    const view = systemStatusView(health("healthy", { database: "healthy" }), false);
    expect(view.status).toBe("healthy");
    expect(view.label).toBe("Connected");
    expect(view.detail).toBeNull();
  });

  it("reports degraded and names the failing component", () => {
    // The live outage: everything reachable, no market data arriving.
    const view = systemStatusView(
      health("degraded", { database: "healthy", market_data: "stale" }),
      false,
    );
    expect(view.status).toBe("degraded");
    expect(view.label).toBe("Degraded");
    expect(view.detail).toBe("market data stale");
  });

  it("names every unhealthy component, not just the first", () => {
    const view = systemStatusView(
      health("degraded", { redis: "unhealthy", market_data: "stale" }),
      false,
    );
    expect(view.detail).toContain("redis unhealthy");
    expect(view.detail).toContain("market data stale");
  });

  it("does not treat not_configured as a fault", () => {
    const view = systemStatusView(
      health("healthy", { database: "healthy", backups: "not_configured" }),
      false,
    );
    expect(view.status).toBe("healthy");
    expect(view.detail).toBeNull();
  });

  it("surfaces an undeterminable component without calling it healthy", () => {
    const view = systemStatusView(
      health("healthy", { database: "healthy", market_data: "unknown" }),
      false,
    );
    expect(view.detail).toBe("market data unknown");
  });

  it("trusts an explicit degraded status even if no component looks bad", () => {
    const view = systemStatusView(health("degraded", { database: "healthy" }), false);
    expect(view.status).toBe("degraded");
  });

  it("underscores in component names are not shown to the user", () => {
    const view = systemStatusView(
      health("degraded", { model_storage: "unhealthy" }),
      false,
    );
    expect(view.detail).not.toContain("_");
  });
});
