import { NextRequest, NextResponse } from 'next/server';
import { createSessionToken, SESSION_COOKIE, SESSION_TTL_MS } from '@/lib/session';

function constantTimeEqual(a: string, b: string): boolean {
  const enc = new TextEncoder();
  const bufA = enc.encode(a);
  const bufB = enc.encode(b);
  let diff = bufA.length ^ bufB.length;
  const len = Math.max(bufA.length, bufB.length);
  for (let i = 0; i < len; i++) {
    diff |= (bufA[i] ?? 0) ^ (bufB[i] ?? 0);
  }
  return diff === 0;
}

/**
 * Accounts come from env: DASHBOARD_USERNAME/DASHBOARD_PASSWORD (single user,
 * legacy) and/or DASHBOARD_USERS ("alice:pass1,bob:pass2").
 */
function getUsers(): Record<string, string> {
  const users: Record<string, string> = {};
  if (process.env.DASHBOARD_USERNAME && process.env.DASHBOARD_PASSWORD) {
    users[process.env.DASHBOARD_USERNAME] = process.env.DASHBOARD_PASSWORD;
  }
  for (const pair of (process.env.DASHBOARD_USERS ?? '').split(',')) {
    const idx = pair.indexOf(':');
    if (idx > 0) users[pair.slice(0, idx).trim()] = pair.slice(idx + 1).trim();
  }
  return users;
}

export async function POST(request: NextRequest) {
  const secret = process.env.AUTH_SECRET;
  const users = getUsers();
  if (!secret || Object.keys(users).length === 0) {
    return NextResponse.json({ error: 'auth not configured' }, { status: 503 });
  }

  let username = '';
  let password = '';
  try {
    const body = await request.json();
    username = String(body.username ?? '');
    password = String(body.password ?? '');
  } catch {
    return NextResponse.json({ error: 'invalid request' }, { status: 400 });
  }

  // Compare against a dummy when the username is unknown so response timing
  // doesn't reveal which usernames exist.
  const expectedPass = users[username] ?? '<no-such-user>';
  const passOk = constantTimeEqual(password, expectedPass);
  if (!(username in users) || !passOk) {
    // Slow down credential guessing; nginx adds rate limiting on top.
    await new Promise((resolve) => setTimeout(resolve, 750));
    return NextResponse.json({ error: 'invalid credentials' }, { status: 401 });
  }

  const response = NextResponse.json({ ok: true });
  response.cookies.set(SESSION_COOKIE, await createSessionToken(secret), {
    httpOnly: true,
    sameSite: 'lax',
    secure: process.env.NODE_ENV === 'production',
    path: '/',
    maxAge: SESSION_TTL_MS / 1000,
  });
  return response;
}
