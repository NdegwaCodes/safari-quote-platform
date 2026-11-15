"use client";

import { useEffect, useState } from "react";
import type { ApiError } from "@/lib/types";


export type Read<T> =
  | { state: "loading" }
  | { state: "ready"; data: T }
  | { state: "failed"; error: ApiError };

const FAILED: ApiError = {
  code: "PORTAL_UNAVAILABLE",
  message:
    "This could not be loaded just now. Please try again in a moment -- " +
    "nothing about your booking has changed.",
};

export function useRead<T>(path: string): Read<T> {
  const [result, setResult] = useState<Read<T>>({ state: "loading" });

  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const res = await fetch(`/api/portal/${path}`);
        const text = await res.text();
        const payload = text ? JSON.parse(text) : null;
        if (!live) return;
        if (res.ok && payload) {
          setResult({ state: "ready", data: payload as T });
        } else {
          setResult({
            state: "failed",
            error: (payload?.error ?? FAILED) as ApiError,
          });
        }
      } catch {
        if (live) setResult({ state: "failed", error: FAILED });
      }
    })();
    return () => {
      live = false;
    };
  }, [path]);

  return result;
}
