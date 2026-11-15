export const TOKEN_COOKIE = "acacia_trip";

export const API_BASE = process.env.API_BASE_URL ?? "http://localhost:8000";
export const API_V1 = "/api/v1";

export const TOKEN_MAX_AGE = 60 * 60 * 12;

export const cookieOptions = () => ({
  httpOnly: true,
  secure: process.env.NODE_ENV === "production",
  sameSite: "strict" as const,
  path: "/",
  maxAge: TOKEN_MAX_AGE,
});

export const READABLE = ["trip", "statement", "document.html"] as const;

export const errorEnvelope = (code: string, message: string) => ({
  error: { code, message, details: [] as unknown[] },
});

export const NO_LINK = errorEnvelope(
  "portal_no_link",
  "Open your trip using the link your consultant sent you.",
);
