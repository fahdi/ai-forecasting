/**
 * Session token logic: signing, verification, expiry, and sliding renewal.
 * This is the security boundary for the public dashboard, so it gets real
 * tests: a subtle regression here either locks users out or lets forged
 * cookies through.
 */
import { describe, expect, it } from "vitest";

import {
  createSessionToken,
  SESSION_TTL_MS,
  shouldRenewSessionToken,
  verifySessionToken,
} from "./session";

const SECRET = "test-secret-0123456789-0123456789";
const NOW = 1_754_500_000_000;

describe("verifySessionToken", () => {
  it("accepts a freshly created token", async () => {
    const token = await createSessionToken(SECRET, NOW);
    expect(await verifySessionToken(token, SECRET, NOW)).toBe(true);
  });

  it("rejects an expired token", async () => {
    const token = await createSessionToken(SECRET, NOW);
    expect(await verifySessionToken(token, SECRET, NOW + SESSION_TTL_MS + 1)).toBe(false);
  });

  it("rejects a token signed with a different secret", async () => {
    const token = await createSessionToken("other-secret-0123456789-01234", NOW);
    expect(await verifySessionToken(token, SECRET, NOW)).toBe(false);
  });

  it("rejects tampered expiry timestamps", async () => {
    const token = await createSessionToken(SECRET, NOW);
    const [, signature] = token.split(".");
    const forged = `${NOW + 10 * SESSION_TTL_MS}.${signature}`;
    expect(await verifySessionToken(forged, SECRET, NOW)).toBe(false);
  });

  it("rejects garbage and missing tokens", async () => {
    expect(await verifySessionToken(undefined, SECRET, NOW)).toBe(false);
    expect(await verifySessionToken("", SECRET, NOW)).toBe(false);
    expect(await verifySessionToken("no-dot-here", SECRET, NOW)).toBe(false);
    expect(await verifySessionToken("123.", SECRET, NOW)).toBe(false);
  });
});

describe("shouldRenewSessionToken (sliding sessions)", () => {
  it("does not renew a fresh token", async () => {
    const token = await createSessionToken(SECRET, NOW);
    expect(await shouldRenewSessionToken(token, SECRET, NOW + 1000)).toBe(false);
  });

  it("renews once more than half the TTL has elapsed", async () => {
    const token = await createSessionToken(SECRET, NOW);
    const pastHalfLife = NOW + SESSION_TTL_MS / 2 + 1000;
    expect(await shouldRenewSessionToken(token, SECRET, pastHalfLife)).toBe(true);
  });

  it("never renews an invalid or expired token", async () => {
    const token = await createSessionToken(SECRET, NOW);
    expect(await shouldRenewSessionToken(token, SECRET, NOW + SESSION_TTL_MS + 1)).toBe(false);
    expect(await shouldRenewSessionToken("garbage", SECRET, NOW)).toBe(false);
    expect(await shouldRenewSessionToken(undefined, SECRET, NOW)).toBe(false);
  });
});
