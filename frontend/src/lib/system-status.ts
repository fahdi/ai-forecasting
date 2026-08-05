import type { DetailedHealth } from "./api";

/**
 * Dashboard header status.
 *
 * The header used to read "Connected" whenever the request resolved, against
 * /health, whose payload is a hardcoded "healthy". That is a liveness probe
 * for the web process, not a statement about the system, so a degraded stack
 * looked fine on the landing page. This maps the detailed payload instead and
 * names what is wrong, so the header is worth glancing at.
 */

export type SystemStatus = "healthy" | "degraded" | "unhealthy" | "checking";

export type SystemStatusView = {
  status: SystemStatus;
  label: string;
  /** Human-readable list of components that are not healthy, or null. */
  detail: string | null;
};

// Absent by configuration rather than broken; saying so would be noise.
const NOT_A_FAULT = new Set(["healthy", "not_configured"]);

function humanize(name: string): string {
  return name.replace(/_/g, " ");
}

export function systemStatusView(
  health: DetailedHealth | null,
  failed: boolean,
): SystemStatusView {
  if (failed) {
    return { status: "unhealthy", label: "Disconnected", detail: null };
  }
  if (!health) {
    return { status: "checking", label: "Checking...", detail: null };
  }

  const faults = Object.entries(health.components ?? {})
    .filter(([, component]) => !NOT_A_FAULT.has(component?.status))
    .map(([name, component]) => `${humanize(name)} ${component.status}`);

  const degraded = health.status !== "healthy" || faults.length > 0;

  return {
    status: degraded ? "degraded" : "healthy",
    label: degraded ? "Degraded" : "Connected",
    detail: faults.length > 0 ? faults.join(", ") : null,
  };
}
