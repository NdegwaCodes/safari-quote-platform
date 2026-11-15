import { NextRequest, NextResponse } from "next/server";


const API_BASE = process.env.API_BASE_URL ?? "http://localhost:8000";

export async function POST(req: NextRequest) {
  const body = await req.text();

  const forwarded = req.headers.get("x-forwarded-for");

  const upstream = await fetch(`${API_BASE}/api/v1/public/enquiries`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(forwarded ? { "X-Forwarded-For": forwarded } : {}),
    },
    body,
    cache: "no-store",
  });

  const text = await upstream.text();
  return new NextResponse(text, {
    status: upstream.status,
    headers: {
      "Content-Type":
        upstream.headers.get("content-type") ?? "application/json",
      "Cache-Control": "no-store",
    },
  });
}
