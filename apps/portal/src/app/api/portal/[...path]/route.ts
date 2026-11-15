import { NextRequest, NextResponse } from "next/server";
import {
  API_BASE,
  API_V1,
  NO_LINK,
  READABLE,
  TOKEN_COOKIE,
  errorEnvelope,
} from "@/lib/session";


async function handle(
  req: NextRequest,
  ctx: { params: Promise<{ path: string[] }> },
) {
  const { path } = await ctx.params;
  const target = path.join("/");

  if (!(READABLE as readonly string[]).includes(target)) {
    return NextResponse.json(
      errorEnvelope("NOT_FOUND", "There is nothing to read there."),
      { status: 404 },
    );
  }

  const token = req.cookies.get(TOKEN_COOKIE)?.value;
  if (!token) {
    return NextResponse.json(NO_LINK, { status: 403 });
  }

  const apiRes = await fetch(`${API_BASE}${API_V1}/portal/${target}`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });

  const text = await apiRes.text();
  const out = new NextResponse(text, {
    status: apiRes.status,
    headers: {
      "Content-Type":
        apiRes.headers.get("content-type") ?? "application/json",
      "Cache-Control": "no-store, private",
    },
  });

  if (apiRes.status === 401 || apiRes.status === 403) {
    out.cookies.delete(TOKEN_COOKIE);
  }
  return out;
}

export { handle as GET };
