import { NextResponse } from "next/server";
import { createSessionToken, SESSION_COOKIE, verifyAccessKey } from "@/lib/auth";

export const runtime = "nodejs";

export async function POST(request: Request) {
  const origin = request.headers.get("origin");
  if (origin && new URL(request.url).origin !== origin) {
    return NextResponse.json({ error: "Invalid origin" }, { status: 403 });
  }

  let accessKey = "";
  try {
    const body = (await request.json()) as { accessKey?: unknown };
    accessKey = typeof body.accessKey === "string" ? body.accessKey.trim() : "";
  } catch {
    return NextResponse.json({ error: "Invalid request" }, { status: 400 });
  }

  if (!verifyAccessKey(accessKey)) {
    await new Promise((resolve) => setTimeout(resolve, 600));
    return NextResponse.json({ error: "Invalid access key" }, { status: 401 });
  }

  const response = NextResponse.json({ ok: true });
  response.cookies.set(SESSION_COOKIE, createSessionToken(), {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "strict",
    path: "/",
    maxAge: 60 * 60 * 24 * 14,
  });
  return response;
}
