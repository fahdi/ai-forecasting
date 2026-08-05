import { describe, expect, it } from "vitest";
import { securityHeaders, securityHeaderRules } from "./security-headers";

/**
 * The dashboard is a login-gated view of live trading state, served publicly
 * at forecasts.isupercoder.com. nginx supplies HSTS; everything else was
 * missing, so an authenticated session could be framed and clickjacked.
 */

const valueOf = (key: string) =>
  securityHeaders.find((h) => h.key.toLowerCase() === key.toLowerCase())?.value;

describe("securityHeaders", () => {
  it("denies framing outright", () => {
    // The dashboard is never embedded anywhere, so SAMEORIGIN would be slack.
    expect(valueOf("X-Frame-Options")).toBe("DENY");
  });

  it("stops MIME sniffing", () => {
    expect(valueOf("X-Content-Type-Options")).toBe("nosniff");
  });

  it("does not leak full URLs to third parties", () => {
    expect(valueOf("Referrer-Policy")).toBe("strict-origin-when-cross-origin");
  });

  it("turns off device APIs the dashboard never uses", () => {
    const policy = valueOf("Permissions-Policy") ?? "";
    for (const feature of ["camera", "microphone", "geolocation"]) {
      expect(policy).toContain(`${feature}=()`);
    }
  });

  it("leaves HSTS to nginx so the header is not sent twice", () => {
    expect(valueOf("Strict-Transport-Security")).toBeUndefined();
  });

  it("has no duplicate or blank entries", () => {
    const keys = securityHeaders.map((h) => h.key.toLowerCase());
    expect(new Set(keys).size).toBe(keys.length);
    for (const header of securityHeaders) {
      expect(header.key.trim()).not.toBe("");
      expect(header.value.trim()).not.toBe("");
    }
  });
});

describe("securityHeaderRules", () => {
  it("applies to every route, not just the home page", () => {
    const rules = securityHeaderRules();
    expect(rules).toHaveLength(1);
    expect(rules[0].source).toBe("/:path*");
    expect(rules[0].headers).toEqual(securityHeaders);
  });
});
