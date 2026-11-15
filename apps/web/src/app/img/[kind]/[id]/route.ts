import { NextRequest, NextResponse } from "next/server";


const API_BASE = process.env.API_BASE_URL ?? "http://localhost:8000";

export async function GET(
  _req: NextRequest,
  ctx: { params: Promise<{ kind: string; id: string }> },
) {
  const { kind, id } = await ctx.params;

  if (!/^[a-z]+$/.test(kind) || !/^[0-9a-fA-F-]{36}$/.test(id)) {
    return new NextResponse("Not found", { status: 404 });
  }

  const upstream = await fetch(
    `${API_BASE}/api/v1/public/images/${kind}/${id}`,
    { next: { revalidate: 604800 } },
  );
  if (!upstream.ok) {
    return new NextResponse("Not found", { status: 404 });
  }

  return new NextResponse(upstream.body, {
    status: 200,
    headers: {
      "Content-Type":
        upstream.headers.get("content-type") ?? "application/octet-stream",
      "Cache-Control": "public, max-age=604800, immutable",
    },
  });
}
