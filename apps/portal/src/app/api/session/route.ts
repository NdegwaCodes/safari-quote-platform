import { NextRequest, NextResponse } from "next/server";
import {
  API_BASE,
  API_V1,
  NO_LINK,
  TOKEN_COOKIE,
  cookieOptions,
} from "@/lib/session";


export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => null);
  const token = typeof body?.token === "string" ? body.token.trim() : "";

  if (!token) {
    return NextResponse.json(NO_LINK, { status: 403 });
  }

  const res = await fetch(`${API_BASE}${API_V1}/portal/trip`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });

  const text = await res.text();
  const data = text ? JSON.parse(text) : null;

  if (!res.ok) {
    const out = NextResponse.json(data ?? NO_LINK, { status: res.status });
    out.cookies.delete(TOKEN_COOKIE);
    return out;
  }

  const out = NextResponse.json(data);
  out.cookies.set(TOKEN_COOKIE, token, cookieOptions());
  return out;
}

export async function DELETE() {
  const out = NextResponse.json({ ok: true });
  out.cookies.delete(TOKEN_COOKIE);
  return out;
}
