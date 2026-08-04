import { NextRequest, NextResponse } from 'next/server';
import {
  createSessionToken,
  SESSION_COOKIE,
  SESSION_TTL_MS,
  shouldRenewSessionToken,
  verifySessionToken,
} from '@/lib/session';

const PUBLIC_PATHS = new Set(['/login', '/api/auth/login']);

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  if (PUBLIC_PATHS.has(pathname)) return NextResponse.next();

  const secret = process.env.AUTH_SECRET;
  const hasUsers =
    (process.env.DASHBOARD_USERNAME && process.env.DASHBOARD_PASSWORD) ||
    (process.env.DASHBOARD_USERS ?? '').includes(':');
  if (!secret || !hasUsers) {
    // Fail closed: a public trading dashboard must never come up unauthenticated.
    return new NextResponse('Dashboard auth is not configured (AUTH_SECRET plus DASHBOARD_USERNAME/DASHBOARD_PASSWORD or DASHBOARD_USERS).', {
      status: 503,
    });
  }

  const token = request.cookies.get(SESSION_COOKIE)?.value;
  if (await verifySessionToken(token, secret)) {
    const response = NextResponse.next();
    // Sliding session: refresh the cookie for active users past half-life.
    if (await shouldRenewSessionToken(token, secret)) {
      response.cookies.set(SESSION_COOKIE, await createSessionToken(secret), {
        httpOnly: true,
        sameSite: 'lax',
        secure: process.env.NODE_ENV === 'production',
        path: '/',
        maxAge: SESSION_TTL_MS / 1000,
      });
    }
    return response;
  }

  if (pathname.startsWith('/api/')) {
    return NextResponse.json({ error: 'unauthorized' }, { status: 401 });
  }
  const loginUrl = request.nextUrl.clone();
  loginUrl.pathname = '/login';
  loginUrl.search = '';
  return NextResponse.redirect(loginUrl);
}

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
};
