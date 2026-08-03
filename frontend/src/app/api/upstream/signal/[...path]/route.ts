/**
 * Server-side proxy to the platform (signal) API. The FastAPI container is
 * never exposed publicly; the browser only talks to this route, which the
 * middleware gates behind the session cookie.
 */
import { NextRequest, NextResponse } from 'next/server';

const SIGNAL_API_INTERNAL_URL = process.env.SIGNAL_API_INTERNAL_URL || 'http://localhost:8000';

async function forward(request: NextRequest, path: string[]): Promise<NextResponse> {
  const target = new URL(`${SIGNAL_API_INTERNAL_URL}/${path.join('/')}`);
  target.search = request.nextUrl.search;

  const init: RequestInit = {
    method: request.method,
    headers: {
      Accept: request.headers.get('accept') ?? 'application/json',
      ...(request.headers.get('content-type')
        ? { 'Content-Type': request.headers.get('content-type')! }
        : {}),
    },
    // Streams the incoming body through without buffering.
    body: request.method === 'GET' || request.method === 'HEAD' ? undefined : request.body,
    // @ts-expect-error duplex is required by undici when streaming a body
    duplex: 'half',
    signal: AbortSignal.timeout(30_000),
  };

  try {
    const upstream = await fetch(target, init);
    return new NextResponse(upstream.body, {
      status: upstream.status,
      headers: {
        'Content-Type': upstream.headers.get('content-type') ?? 'application/json',
      },
    });
  } catch {
    return NextResponse.json({ error: 'signal API unreachable' }, { status: 503 });
  }
}

export async function GET(request: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return forward(request, (await ctx.params).path);
}

export async function POST(request: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return forward(request, (await ctx.params).path);
}
