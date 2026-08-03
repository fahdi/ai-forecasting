/**
 * Signed session cookie helpers, shared by the middleware (edge runtime)
 * and the auth route handlers (node). Web Crypto only — no node:crypto —
 * so both runtimes can import this module.
 *
 * Cookie format: "<expiresMs>.<base64url hmac-sha256(expiresMs, AUTH_SECRET)>"
 */

export const SESSION_COOKIE = 'aif_session';
export const SESSION_TTL_MS = 7 * 24 * 60 * 60 * 1000;

function base64url(bytes: ArrayBuffer): string {
  let binary = '';
  for (const byte of new Uint8Array(bytes)) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

async function hmac(payload: string, secret: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    'raw',
    new TextEncoder().encode(secret),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign'],
  );
  const signature = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(payload));
  return base64url(signature);
}

export async function createSessionToken(secret: string, now = Date.now()): Promise<string> {
  const expires = String(now + SESSION_TTL_MS);
  return `${expires}.${await hmac(expires, secret)}`;
}

export async function verifySessionToken(
  token: string | undefined,
  secret: string,
  now = Date.now(),
): Promise<boolean> {
  if (!token) return false;
  const [expires, signature] = token.split('.');
  if (!expires || !signature) return false;
  if (!/^\d+$/.test(expires) || Number(expires) < now) return false;
  const expected = await hmac(expires, secret);
  if (signature.length !== expected.length) return false;
  // Constant-time comparison; both strings are base64url of fixed-size MACs.
  let diff = 0;
  for (let i = 0; i < expected.length; i++) {
    diff |= signature.charCodeAt(i) ^ expected.charCodeAt(i);
  }
  return diff === 0;
}
