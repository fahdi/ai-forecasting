/**
 * Response security headers for the dashboard.
 *
 * Served publicly at forecasts.isupercoder.com behind nginx, which already
 * supplies Strict-Transport-Security. Setting HSTS here too would emit the
 * header twice, so it is deliberately absent.
 *
 * No Content-Security-Policy yet: Next.js emits inline bootstrap scripts and
 * styles, so a useful policy needs nonce plumbing and its own testing pass
 * rather than being tacked on here.
 */

export type SecurityHeader = { key: string; value: string };

export const securityHeaders: SecurityHeader[] = [
  // The dashboard is never embedded, so framing is always an attack.
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=()",
  },
];

export function securityHeaderRules() {
  return [{ source: "/:path*", headers: securityHeaders }];
}
