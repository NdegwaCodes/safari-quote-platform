export const ACCESS_COOKIE = "acacia_access";
export const REFRESH_COOKIE = "acacia_refresh";

export const API_BASE = process.env.API_BASE_URL ?? "http://localhost:8000";
export const API_V1 = "/api/v1";

export const ACCESS_MAX_AGE = 60 * 15;
export const REFRESH_MAX_AGE = 60 * 60 * 24 * 7;

export const cookieOptions = (maxAge: number) => ({
  httpOnly: true,
  secure: process.env.NODE_ENV === "production",
  sameSite: "lax" as const,
  path: "/",
  maxAge,
});
