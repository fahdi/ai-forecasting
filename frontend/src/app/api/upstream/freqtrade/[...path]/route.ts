/**
 * Server-side proxy to the freqtrade REST API. Read-only by design: only a
 * whitelist of GET endpoints is forwarded, so the public dashboard can never
 * reach trade-mutating endpoints (forcebuy/forcesell/stop/...). Credentials
 * stay server-side — nothing NEXT_PUBLIC.
 */
import { NextRequest, NextResponse } from 'next/server';

const FREQTRADE_INTERNAL_URL = process.env.FREQTRADE_INTERNAL_URL || 'http://localhost:8080';
const FREQTRADE_USER = process.env.FREQTRADE_API_USERNAME || 'freqtrade';
const FREQTRADE_PASS = process.env.FREQTRADE_API_PASSWORD || 'local-dry-run';

const ALLOWED_PATHS = new Set([
  'api/v1/ping',
  'api/v1/status',
  'api/v1/profit',
  'api/v1/balance',
  'api/v1/show_config',
]);

export async function GET(request: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const path = (await ctx.params).path.join('/');
  if (!ALLOWED_PATHS.has(path)) {
    return NextResponse.json({ error: 'endpoint not allowed' }, { status: 403 });
  }

  try {
    const upstream = await fetch(`${FREQTRADE_INTERNAL_URL}/${path}`, {
      headers: {
        Accept: 'application/json',
        Authorization: `Basic ${Buffer.from(`${FREQTRADE_USER}:${FREQTRADE_PASS}`).toString('base64')}`,
      },
      signal: AbortSignal.timeout(10_000),
    });
    const body = await upstream.text();
    return new NextResponse(body, {
      status: upstream.status,
      headers: { 'Content-Type': upstream.headers.get('content-type') ?? 'application/json' },
    });
  } catch {
    return NextResponse.json({ error: 'freqtrade unreachable' }, { status: 503 });
  }
}
