import { createHash, createHmac, timingSafeEqual } from "node:crypto";
import { cookies } from "next/headers";

export const SESSION_COOKIE = "cortana_session";
const SESSION_TTL_SECONDS = 60 * 60 * 24 * 14;

type SessionPayload = {
  sub: "owner";
  iat: number;
  exp: number;
};

function sessionSecret(): string {
  const secret = process.env.CORTANA_SESSION_SECRET;
  if (!secret || secret.length < 32) {
    throw new Error("CORTANA_SESSION_SECRET must contain at least 32 characters");
  }
  return secret;
}

function sign(value: string): string {
  return createHmac("sha256", sessionSecret()).update(value).digest("base64url");
}

export function createSessionToken(): string {
  const now = Math.floor(Date.now() / 1000);
  const payload: SessionPayload = {
    sub: "owner",
    iat: now,
    exp: now + SESSION_TTL_SECONDS,
  };
  const body = Buffer.from(JSON.stringify(payload)).toString("base64url");
  return `${body}.${sign(body)}`;
}

export function verifySessionToken(token?: string): boolean {
  if (!token) return false;
  const [body, signature, extra] = token.split(".");
  if (!body || !signature || extra) return false;

  const expected = sign(body);
  const actualBuffer = Buffer.from(signature);
  const expectedBuffer = Buffer.from(expected);
  if (
    actualBuffer.length !== expectedBuffer.length ||
    !timingSafeEqual(actualBuffer, expectedBuffer)
  ) {
    return false;
  }

  try {
    const payload = JSON.parse(Buffer.from(body, "base64url").toString()) as SessionPayload;
    return payload.sub === "owner" && payload.exp > Math.floor(Date.now() / 1000);
  } catch {
    return false;
  }
}

export async function isAuthenticated(): Promise<boolean> {
  const cookieStore = await cookies();
  return verifySessionToken(cookieStore.get(SESSION_COOKIE)?.value);
}

export function verifyAccessKey(accessKey: string): boolean {
  const configuredHash = process.env.CORTANA_ACCESS_KEY_HASH;
  if (!configuredHash || configuredHash.length !== 64 || !accessKey) return false;

  const suppliedHash = createHash("sha256").update(accessKey).digest("hex");
  const supplied = Buffer.from(suppliedHash, "hex");
  const configured = Buffer.from(configuredHash, "hex");
  return supplied.length === configured.length && timingSafeEqual(supplied, configured);
}
