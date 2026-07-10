import { NextResponse } from "next/server";
import { isAuthenticated } from "@/lib/auth";

export const dynamic = "force-dynamic";

export async function GET() {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const url = process.env.CORTANA_BRIDGE_URL;
  const token = process.env.CORTANA_BRIDGE_TOKEN;
  if (!url || !token) {
    return NextResponse.json({ error: "Bridge is not configured" }, { status: 503 });
  }

  return NextResponse.json(
    { url, token },
    { headers: { "Cache-Control": "no-store" } },
  );
}
